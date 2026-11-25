"""Unified public biomedical API queries with a local SQLite response cache."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from ssl import SSLEOFError
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data/processed/biomedical_evidence.sqlite3"
USER_AGENT = "BioMDT-course-project/1.0"


class SQLiteEvidenceCache:
    """Store complete API payloads and compact records under their query parameters."""

    def __init__(self, path: Path = DEFAULT_CACHE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS responses (
                    database_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    PRIMARY KEY (database_name, operation, params_json)
                )
                """
            )

    @staticmethod
    def params_key(params: dict[str, Any]) -> str:
        return json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def get(
        self, database: str, operation: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT envelope_json FROM responses
                WHERE database_name = ? AND operation = ? AND params_json = ?
                """,
                (database, operation, self.params_key(params)),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, envelope: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO responses
                    (database_name, operation, params_json, envelope_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    envelope["database"],
                    envelope["operation"],
                    self.params_key(envelope["query_params"]),
                    json.dumps(envelope, ensure_ascii=False),
                ),
            )

    def export(self, output: Path) -> int:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT envelope_json FROM responses
                ORDER BY database_name, operation, params_json
                """
            ).fetchall()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(row[0] + "\n" for row in rows), encoding="utf-8"
        )
        return len(rows)


def _default_transport(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/plain"}
    body = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    for attempt in range(2):
        try:
            with urlopen(request, timeout=40) as response:
                content = response.read()
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    parsed = json.loads(content)
                else:
                    parsed = content.decode("utf-8", errors="replace")
                return {
                    "body": parsed,
                    "status": response.status,
                    "url": response.url,
                    "headers": {key.lower(): value for key, value in response.headers.items()},
                }
        except (URLError, SSLEOFError) as error:
            reason = error.reason if isinstance(error, URLError) else error
            if attempt or method != "GET" or not isinstance(reason, SSLEOFError):
                raise


class BioKnowledgeTools:
    """Small task-oriented interface over the APIs used by DeepEvidence."""

    def __init__(
        self,
        cache: SQLiteEvidenceCache | None = None,
        transport: Callable[..., dict[str, Any]] = _default_transport,
    ):
        self.cache = cache or SQLiteEvidenceCache()
        self.transport = transport

    def query(self, database: str, operation: str, **params: Any) -> dict[str, Any]:
        cached = self.cache.get(database, operation, params)
        if cached is not None:
            records, source_ids = self._records(
                database, operation, cached["raw_result"], params
            )
            cached["records"] = records
            cached["source_ids"] = source_ids
            cached["cache_hit"] = True
            self.cache.put(cached)
            return cached

        method, url, request_params, json_body = self._request(
            database, operation, params
        )
        response = self.transport(method, url, request_params, json_body)
        raw = response["body"]
        records, source_ids = self._records(database, operation, raw, params)
        if database == "open_targets" and operation.startswith("search_"):
            records = records[: params.get("limit", 10)]
            source_ids = [record["id"] for record in records if record.get("id")]
        headers = response.get("headers", {})
        database_version = (
            headers.get("x-uniprot-release")
            or headers.get("x-chembl-version")
            or headers.get("x-reactome-release")
            or headers.get("x-api-deployment-date")
        )
        envelope = {
            "database": database,
            "operation": operation,
            "query_params": params,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "database_version": database_version,
            "cache_hit": False,
            "source_ids": source_ids,
            "request": {
                "method": method,
                "url": response.get("url", url),
                "query_params": request_params,
                "status": response.get("status", 200),
                "content_type": headers.get("content-type"),
            },
            "raw_result": raw,
            "records": records,
        }
        self.cache.put(envelope)
        return envelope

    @staticmethod
    def _request(
        database: str, operation: str, params: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
        p = {key: value for key, value in params.items() if value is not None}
        if database == "uniprot":
            base = "https://rest.uniprot.org"
            if operation == "entry":
                return "GET", f"{base}/uniprotkb/{quote(p['accession'], safe='')}.json", None, None
            if operation == "search_gene":
                return "GET", f"{base}/uniprotkb/search", {
                    "query": f"gene_exact:{p['gene']} AND organism_id:9606",
                    "format": "json", "size": p.get("limit", 10),
                }, None
        elif database == "open_targets":
            url = "https://api.platform.opentargets.org/api/v4/graphql"
            if operation in {"search_target", "search_disease"}:
                entity = "target" if operation == "search_target" else "disease"
                query = (
                    "query Search($queryString: String!) { "
                    f"search(queryString: $queryString, entityNames: [\"{entity}\"]) "
                    "{ hits { id name description entity } } }"
                )
                return "POST", url, None, {"query": query, "variables": {"queryString": p["query"]}}
            if operation == "target_details":
                query = (
                    "query Target($ensemblId: String!) { target(ensemblId: $ensemblId) "
                    "{ id approvedName approvedSymbol biotype functionDescriptions "
                    "proteinIds { id source } pathways { pathwayId pathway } } }"
                )
                return "POST", url, None, {"query": query, "variables": {"ensemblId": p["ensembl_id"]}}
        elif database == "reactome":
            base = "https://reactome.org/ContentService"
            if operation == "search_pathways":
                return "GET", f"{base}/search/query", {
                    "query": p["query"], "types": "Pathway", "cluster": "true",
                }, None
            if operation == "pathways_by_uniprot":
                accession = quote(p["accession"], safe="")
                return "GET", f"{base}/data/mapping/UniProt/{accession}/pathways", None, None
            if operation == "pathway":
                stable_id = quote(p["stable_id"], safe="")
                return "GET", f"{base}/data/query/{stable_id}", None, None
        elif database == "kegg":
            base = "https://rest.kegg.jp"
            if operation == "find_gene":
                return "GET", f"{base}/find/genes/{quote(p['query'], safe='')}", None, None
            if operation in {"gene", "pathway"}:
                return "GET", f"{base}/get/{quote(p['identifier'], safe='')}", None, None
        elif database == "chembl":
            base = "https://www.ebi.ac.uk/chembl/api/data"
            if operation == "search_molecule":
                return "GET", f"{base}/molecule/search.json", {
                    "q": p["query"], "limit": p.get("limit", 10),
                }, None
            if operation == "mechanisms":
                return "GET", f"{base}/mechanism.json", {
                    "molecule_chembl_id": p["molecule_id"], "limit": p.get("limit", 100),
                }, None
            if operation == "target_details":
                target_id = quote(p["target_id"], safe="")
                return "GET", f"{base}/target/{target_id}.json", None, None
            if operation == "activities":
                activity_params = {
                    "molecule_chembl_id": p.get("molecule_id"),
                    "target_chembl_id": p.get("target_id"),
                    "limit": p.get("limit", 10),
                }
                return "GET", f"{base}/activity.json", activity_params, None
        elif database == "pubmed":
            if operation == "full_text":
                pmcid = quote(p["pmcid"], safe="")
                url = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
                return "GET", f"{url}/BioC_xml/{pmcid}/ascii", None, None
            base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
            if operation == "search":
                return "GET", f"{base}/esearch.fcgi", {
                    "db": "pubmed", "term": p["term"], "retmode": "json",
                    "retmax": p.get("limit", 10),
                    **({"sort": p["sort"]} if p.get("sort") else {}),
                }, None
            if operation == "fetch":
                pmids = p["pmids"]
                if isinstance(pmids, str):
                    pmids = [pmids]
                return "GET", f"{base}/efetch.fcgi", {
                    "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
                }, None
        elif database == "pubtator":
            base = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
            if operation == "search":
                return "GET", f"{base}/search/", {
                    "text": p["query"], "page": p.get("page", 1),
                    "size": p.get("limit", 10),
                }, None
            if operation == "annotations":
                pmids = p["pmids"]
                if isinstance(pmids, str):
                    pmids = [pmids]
                return "GET", f"{base}/publications/export/biocjson", {
                    "pmids": ",".join(pmids),
                }, None
            if operation == "relations":
                return "GET", f"{base}/relations", {
                    "e1": p["entity1"], "type": p["relation"].lower(),
                    "e2": p["entity2"],
                }, None
        raise ValueError(f"Unsupported biomedical API operation: {database}.{operation}")

    @staticmethod
    def _records(
        database: str, operation: str, raw: Any, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        identifiers: list[str] = []
        if database == "uniprot":
            results = raw.get("results", []) if isinstance(raw, dict) else []
            if operation == "entry" and isinstance(raw, dict):
                results = [raw]
            for item in results:
                accession = item.get("primaryAccession")
                if accession:
                    identifiers.append(accession)
                records.append({
                    "id": accession,
                    "gene": next((g.get("geneName", {}).get("value") for g in item.get("genes", [])
                                  if g.get("geneName")), None),
                    "protein_name": item.get("proteinDescription", {}).get("recommendedName", {})
                                    .get("fullName", {}).get("value"),
                    "function": next((" ".join(text.get("value", "") for text in comment.get("texts", []))
                                       for comment in item.get("comments", [])
                                       if comment.get("commentType") == "FUNCTION"), None),
                    "organism": item.get("organism", {}).get("scientificName"),
                    "entry_type": item.get("entryType"),
                })
        elif database == "open_targets":
            data = raw.get("data", {}) if isinstance(raw, dict) else {}
            if "search" in data:
                results = data.get("search", {}).get("hits", [])
            else:
                results = [value for value in data.values() if isinstance(value, dict) and value]
            for item in results:
                identifier = item.get("id")
                if identifier:
                    identifiers.append(identifier)
                records.append({key: item.get(key) for key in (
                    "id", "name", "approvedSymbol", "approvedName", "entity",
                    "description", "functionDescriptions", "biotype", "proteinIds", "pathways",
                ) if key in item})
        elif database == "reactome":
            results = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
            if operation == "search_pathways" and isinstance(raw, dict):
                results = [dict(entry, displayName=re.sub("<[^>]+>", "", entry.get("name", "")),
                                speciesName=", ".join(entry.get("species", [])))
                           for group in raw.get("results", []) for entry in group.get("entries", [])]
            for item in results:
                identifier = item.get("stId") or item.get("stIdVersion")
                if identifier:
                    identifiers.append(identifier)
                records.append({key: item.get(key) for key in (
                    "stId", "stIdVersion", "displayName", "speciesName", "dbId",
                    "releaseDate",
                ) if key in item})
        elif database == "kegg":
            if isinstance(raw, str):
                if operation in {"gene", "pathway"}:
                    fields: dict[str, list[str]] = {}
                    current_field = None
                    for line in raw.splitlines():
                        field = line[:12].strip()
                        value = line[12:].strip()
                        if field:
                            current_field = field
                            fields.setdefault(field, []).append(value)
                        elif current_field and value:
                            fields[current_field].append(value)
                    requested_id = (params or {}).get("identifier")
                    entry_text = " ".join(fields.get("ENTRY", []))
                    identifier = requested_id or (entry_text.split()[0] if entry_text else None)
                    if identifier:
                        identifiers.append(identifier)
                    record: dict[str, Any] = {"id": identifier}
                    for field, key in (("SYMBOL", "symbol"), ("NAME", "name"),
                                       ("ORGANISM", "organism")):
                        if field in fields:
                            value = " ".join(fields[field])
                            if field == "SYMBOL":
                                symbols = [symbol.strip() for symbol in value.split(",")]
                                record[key] = symbols[0]
                                if len(symbols) > 1:
                                    record["aliases"] = symbols[1:]
                            else:
                                record[key] = value
                    pathway_rows = []
                    for value in fields.get("PATHWAY", []):
                        pathway_id, separator, pathway_name = value.partition("  ")
                        if separator:
                            pathway_rows.append({"id": pathway_id, "name": pathway_name.strip()})
                    if pathway_rows:
                        record["pathways"] = pathway_rows
                    records.append(record)
                else:
                    for line in raw.splitlines():
                        identifier, separator, name = line.partition("\t")
                        if separator and identifier:
                            identifiers.append(identifier)
                            records.append({"id": identifier, "name": name.strip()})
            elif isinstance(raw, dict):
                results = raw.get("results", [])
                for item in results:
                    identifier = item.get("entry")
                    if identifier:
                        identifiers.append(identifier)
                    records.append({"id": identifier, "name": item.get("name")})
        elif database == "chembl":
            if operation == "target_details" and isinstance(raw, dict):
                identifier = raw.get("target_chembl_id")
                if identifier:
                    identifiers.append(identifier)
                records.append({
                    key: raw.get(key)
                    for key in ("target_chembl_id", "pref_name", "target_type", "organism", "target_components")
                    if key in raw
                })
                return records, identifiers
            payload_key = {
                "search_molecule": "molecules",
                "mechanisms": "mechanisms",
                "activities": "activities",
            }.get(operation)
            results = raw.get(payload_key, []) if isinstance(raw, dict) and payload_key else []
            for item in results:
                identifier = (
                    item.get("molecule_chembl_id")
                    or item.get("target_chembl_id")
                    or item.get("activity_id")
                    or item.get("mec_id")
                )
                if identifier is not None:
                    identifiers.append(str(identifier))
                target_id = item.get("target_chembl_id")
                if target_id:
                    identifiers.append(target_id)
                records.append(item)
        elif database == "pubmed":
            if operation == "search" and isinstance(raw, dict):
                ids = raw.get("esearchresult", {}).get("idlist", [])
                identifiers.extend(map(str, ids))
                records = [{"id": str(identifier)} for identifier in ids]
            elif operation == "full_text" and isinstance(raw, str):
                pmid = (params or {})["pmid"]
                for passage in ET.fromstring(raw).findall(".//passage"):
                    metadata = {item.get("key"): item.text for item in passage.findall("infon")}
                    passage_text = passage.findtext("text", "")
                    if metadata.get("section_type") == "RESULTS" and metadata.get("type") == "paragraph" and passage_text:
                        records.append({"id": pmid, "text": passage_text, "offset": passage.findtext("offset")})
                if records:
                    identifiers.append(pmid)
            elif operation == "fetch" and isinstance(raw, str):
                root = ET.fromstring(raw)
                for article in root.findall(".//PubmedArticle"):
                    pmid = article.findtext("./MedlineCitation/PMID")
                    title_node = article.find(".//ArticleTitle")
                    title = (
                        "".join(title_node.itertext()).strip()
                        if title_node is not None else ""
                    )
                    abstract = " ".join(
                        "".join(node.itertext()) for node in article.findall(".//Abstract/AbstractText")
                    )
                    doi = next(
                        (node.text for node in article.findall(".//ArticleId")
                         if node.get("IdType") == "doi" and node.text),
                        None,
                    )
                    if pmid:
                        identifiers.append(pmid)
                    records.append({"id": pmid, "title": title, "abstract": abstract, "doi": doi})
        elif database == "pubtator":
            if isinstance(raw, dict):
                results = raw.get("results", raw.get("PubTator3", []))
                if isinstance(results, list):
                    for item in results:
                        identifier = item.get("pmid") or item.get("id")
                        if identifier:
                            identifiers.append(str(identifier))
                        records.append(item)
                elif "documents" in raw:
                    records = list(raw["documents"])
            elif isinstance(raw, list):
                for item in raw:
                    identifier = item.get("pmid") or item.get("id")
                    if identifier:
                        identifiers.append(str(identifier))
                    records.append(item)
        return records, list(dict.fromkeys(identifiers))


def query_to_file(
    tools: BioKnowledgeTools,
    database: str,
    operation: str,
    params: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Run or read a cached query and save its provenance envelope as JSON."""
    result = tools.query(database, operation, **params)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{database}-{operation}-{len(list(output_dir.glob('*.json'))) + 1:03d}.json"
    path = output_dir / filename
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
