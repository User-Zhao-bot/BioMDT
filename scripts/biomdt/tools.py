from __future__ import annotations

import os
import re
from typing import Any

from biomedical_evidence import BioKnowledgeTools


def _unique(values: list[Any], limit: int) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) == limit:
            break
    return result


def _compact_record(record: dict[str, Any], database: str) -> dict[str, Any]:
    if database == "uniprot":
        return {key: record.get(key) for key in ("id", "gene", "protein_name", "function", "organism", "entry_type")}
    if database == "open_targets":
        return {key: record.get(key) for key in ("id", "name", "approvedSymbol", "approvedName", "description", "functionDescriptions", "proteinIds", "pathways") if key in record}
    if database == "reactome":
        return {key: record.get(key) for key in ("stId", "stIdVersion", "displayName", "speciesName") if key in record}
    if database == "kegg":
        return {key: record.get(key) for key in ("id", "symbol", "aliases", "name", "organism", "pathways") if key in record}
    if database == "chembl":
        keys = (
            "molecule_chembl_id", "pref_name", "molecule_name", "mechanism_of_action",
            "action_type", "target_chembl_id", "target_name", "target_components",
            "standard_type", "standard_value", "standard_units", "assay_description",
        )
        compact = {key: record.get(key) for key in keys if key in record}
        if "target_components" in compact:
            compact["target_components"] = [
                {key: component.get(key) for key in ("accession", "component_type") if key in component}
                for component in compact["target_components"]
            ]
        return compact
    if database == "pubmed":
        return {key: (str(record.get(key, ""))[:1800] if key == "abstract" else record.get(key))
                for key in ("id", "title", "abstract", "doi") if key in record}
    if database == "pubtator":
        fields = ("pmid", "pmcid", "id", "title", "entities", "relations", "annotations")
        compact = {key: record.get(key) for key in fields if key in record}
        if not compact.get("pmcid"):
            pmcid = next((p["infons"]["article-id_pmc"] for p in record.get("passages", [])
                          if p.get("infons", {}).get("article-id_pmc")), None)
            if pmcid:
                compact["pmcid"] = pmcid
        annotations = [a for passage in record.get("passages", []) for a in passage.get("annotations", [])]
        if annotations:
            compact["annotations"] = [{"text": a.get("text"), "type": a.get("infons", {}).get("type"),
                                       "identifier": a.get("infons", {}).get("identifier")} for a in annotations[:20]]
        return compact
    return record


def _literature_terms(entities: dict[str, list[str]], claims: list[dict[str, Any]]) -> list[str]:
    anchors = entities.get("drugs", []) or entities.get("genes", [])
    diseases = entities.get("diseases", [])
    if anchors and diseases:
        anchor = anchors[0].replace('"', '')
        disease = diseases[0].replace('"', '')
        focused = f'"{anchor}"[All Fields] AND "{disease}"[All Fields]'
        if not entities.get("drugs") and len(anchors) > 1:
            second = anchors[1].replace('"', '')
            return [focused, f'"{second}"[All Fields] AND "{disease}"[All Fields]', anchor]
        return [focused, anchor]
    terms = _unique(entities.get("keywords", []), 2)
    if terms:
        return terms
    terms = _unique(entities.get("drugs", []) + entities.get("genes", [])
                    + entities.get("proteins", []), 2)
    if terms:
        return terms
    for claim in claims:
        abbreviations = re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", claim["text"])
        terms.extend(_unique(abbreviations, 2))
    if terms:
        return _unique(terms, 2)
    return _unique([claim["text"] for claim in claims], 1)


class BiomedicalToolExecutor:
    def __init__(self, tools: BioKnowledgeTools | None = None, max_entities: int = 2,
                 max_records: int = 4):
        self.tools = tools or BioKnowledgeTools()
        self.max_entities = max_entities
        self.max_records = max_records
        self.calls: list[dict[str, Any]] = []

    def _query(self, role: str, database: str, operation: str,
               params: dict[str, Any], *, focus: str = "") -> dict[str, Any]:
        limit = int(os.getenv("BENCHMARK_MAX_TOOL_CALLS", "0"))
        if limit and len(self.calls) >= limit:
            raise RuntimeError("Tool call budget exhausted")
        try:
            envelope = self.tools.query(database, operation, **params)
            records = envelope.get("records", [])
            if database == "kegg" and operation == "find_gene":
                records = sorted(records, key=lambda row: not str(row.get("id", "")).startswith("hsa:"))
                records = [row for row in records if str(row.get("id", "")).startswith("hsa:")]
            if operation == "full_text":
                keywords = {word for word in re.findall(r"[a-z0-9-]{3,}", focus.casefold())
                            if word not in {"the", "and", "with", "from", "for", "that", "was", "were", "does"}}
                records = sorted(records, key=lambda row: len(keywords.intersection(
                    re.findall(r"[a-z0-9-]{3,}", row["text"].casefold()))), reverse=True)
                compact = [{**row, "text": row["text"][:1800]} for row in records[:3]]
            else:
                compact = [_compact_record(row, database) for row in records[:self.max_records]]
            call = {
                "agent": role,
                "database": database,
                "operation": operation,
                "query_params": params,
                "retrieved_at": envelope.get("retrieved_at"),
                "database_version": envelope.get("database_version"),
                "query_params": params,
                "source_ids": [
                    f"PMID:{value}" if database == "pubmed" else str(value)
                    for value in envelope.get("source_ids", [])[:self.max_records]
                ],
                "records": compact,
                "status": envelope.get("request", {}).get("status"),
                "cached": envelope.get("cache_hit", False),
            }
        except Exception as error:
            call = {"agent": role, "database": database, "operation": operation,
                    "query_params": params, "error": str(error), "records": [],
                    "source_ids": [], "cached": False}
        self.calls.append(call)
        return call

    def retrieve(self, role: str, entities: dict[str, list[str]],
                 claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if os.getenv("BENCHMARK_KNOWLEDGE_SCOPE") == "shared-literature" and role != "literature":
            return []
        results = []
        genes = _unique(entities.get("genes", []) + entities.get("proteins", []), self.max_entities)
        diseases = _unique(entities.get("diseases", []), 1)
        drugs = _unique(entities.get("drugs", []), self.max_entities)
        accessions = _unique(entities.get("uniprot_ids", []), self.max_entities)
        aliases = {"pi3kα": "PIK3CA", "pi3kalpha": "PIK3CA", "shp2": "PTPN11"}
        genes = _unique([aliases.get(gene.casefold(), gene) for gene in genes], self.max_entities)
        if role == "genomics":
            for gene in genes:
                results.append(self._query(role, "uniprot", "search_gene", {"gene": gene, "limit": 3}))
                results.append(self._query(role, "open_targets", "search_target", {"query": gene, "limit": 3}))
            for disease in diseases:
                results.append(self._query(role, "open_targets", "search_disease", {"query": disease, "limit": 3}))
        elif role == "pathway":
            for gene in genes:
                hit = self._query(role, "kegg", "find_gene", {"query": gene})
                results.append(hit)
                exact = next((record["id"] for record in hit["records"]
                              if gene.upper() in record.get("name", "").split(";")[0].upper().split(", ")), None)
                if exact:
                    results.append(self._query(role, "kegg", "gene", {"identifier": exact}))
            for accession in accessions:
                results.append(self._query(role, "reactome", "pathways_by_uniprot", {"accession": accession}))
            if not accessions and genes:
                results.append(self._query(role, "reactome", "search_pathways", {"query": genes[0]}))
        elif role == "drug":
            for drug in drugs:
                result = self._query(role, "chembl", "search_molecule", {"query": drug, "limit": 3})
                results.append(result)
                molecule_ids = _unique(
                    [row.get("molecule_chembl_id") for row in result.get("records", [])], 1
                )
                for molecule_id in molecule_ids:
                    results.append(self._query(role, "chembl", "mechanisms", {"molecule_id": molecule_id, "limit": 5}))
        elif role == "literature":
            candidates = entities.get("target_candidates", []) if diseases else []
            if candidates:
                disease = diseases[0].replace('"', '')
                terms = [f'"{symbol}"[All Fields] AND "{disease}"[All Fields]'
                         for symbol in candidates]
            else:
                terms = _literature_terms(entities, claims)
            pmids = []
            for term in terms:
                query_term = f"{term}[All Fields]" if re.fullmatch(r"[A-Za-z0-9-]+", term) else term
                params = {"term": query_term, "limit": 3}
                if candidates:
                    params.update(limit=1, sort="relevance")
                result = self._query(role, "pubmed", "search", params)
                results.append(result)
                pmids.extend(value.removeprefix("PMID:") for value in result.get("source_ids", [])[:1 if candidates else 2])
            pmids = _unique(pmids, len(candidates) if candidates else 4)
            if pmids:
                for start in range(0, len(pmids), self.max_records):
                    results.append(self._query(role, "pubmed", "fetch",
                                               {"pmids": pmids[start:start + self.max_records]}))
                annotations = self._query(role, "pubtator", "annotations", {"pmids": pmids[:2]})
                results.append(annotations)
                first = next((record for record in annotations["records"]
                              if str(record.get("pmid")) == pmids[0] and record.get("pmcid")), None)
                if first and entities.get("drugs") and entities.get("diseases"):
                    results.append(self._query(role, "pubmed", "full_text", {
                        "pmid": pmids[0], "pmcid": first["pmcid"],
                    }, focus=" ".join(claim["text"] for claim in claims)))
        return results
