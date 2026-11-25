from __future__ import annotations

import re
from typing import Any


def _key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


class BiomedicalEntityIndex:
    def __init__(self):
        self.entities: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []
        self.aliases: dict[tuple[str, str], str] = {}

    def add(self, entity_id: str, entity_type: str, label: str,
            identifier: str | None = None, aliases: list[str] | None = None) -> None:
        if not entity_id or not label:
            return
        entity = self.entities.setdefault(entity_id, {
            "id": entity_id, "type": entity_type, "label": label, "identifiers": [],
        })
        if identifier and identifier not in entity["identifiers"]:
            entity["identifiers"].append(identifier)
        for alias in [label, *(aliases or [])]:
            alias_key = (entity_type, _key(alias))
            if alias_key[1]:
                existing = self.aliases.get(alias_key)
                if existing is None or existing == entity_id:
                    self.aliases[alias_key] = entity_id

    def add_retrieval(self, result: dict[str, Any]) -> None:
        database = result.get("database")
        for record in result.get("records", []):
            if database == "uniprot":
                accession = record.get("id")
                gene = record.get("gene")
                if gene:
                    self.add(f"Gene:{gene.upper()}", "Gene", gene)
                self.add(f"UniProt:{accession}", "Protein", record.get("protein_name") or accession,
                         accession, [accession] if accession else [])
                if gene and accession:
                    self.edges.append({"source": f"Gene:{gene.upper()}",
                                       "target": f"UniProt:{accession}", "type": "encodes"})
            elif database == "open_targets":
                symbol = record.get("approvedSymbol")
                ensembl_id = record.get("id")
                if symbol:
                    self.add(f"Gene:{symbol.upper()}", "Gene", symbol, ensembl_id,
                             [record.get("approvedName", "")])
                for protein in record.get("proteinIds", []) or []:
                    protein_id = protein.get("id") if isinstance(protein, dict) else protein
                    if protein_id:
                        self.add(f"UniProt:{protein_id}", "Protein", protein_id, protein_id)
                        if symbol:
                            self.edges.append({"source": f"Gene:{symbol.upper()}",
                                               "target": f"UniProt:{protein_id}", "type": "encodes"})
                for pathway in record.get("pathways", []) or []:
                    if isinstance(pathway, dict):
                        pathway_id = pathway.get("pathwayId") or pathway.get("id")
                        pathway_name = pathway.get("pathway") or pathway.get("name")
                        if pathway_id:
                            self.add(f"OpenTargets:{pathway_id}", "Pathway", pathway_name or pathway_id,
                                     pathway_id)
            elif database == "kegg":
                symbol = record.get("symbol")
                gene_id = record.get("id")
                if symbol:
                    self.add(f"Gene:{symbol.upper()}", "Gene", symbol, gene_id, record.get("aliases", []))
                for pathway in record.get("pathways", []) or []:
                    self.add(f"KEGG:{pathway['id']}", "Pathway", pathway.get("name") or pathway["id"],
                             pathway["id"])
                    if symbol:
                        self.edges.append({"source": f"Gene:{symbol.upper()}",
                                           "target": f"KEGG:{pathway['id']}", "type": "member_of"})
            elif database == "reactome":
                pathway_id = record.get("stId")
                if pathway_id:
                    self.add(f"Reactome:{pathway_id}", "Pathway", record.get("displayName") or pathway_id,
                             pathway_id)
                    for accession in result.get("query_params", {}).get("accession", []):
                        self.add(f"UniProt:{accession}", "Protein", accession, accession)
                        self.edges.append({"source": f"UniProt:{accession}",
                                           "target": f"Reactome:{pathway_id}", "type": "participates_in"})
            elif database == "chembl":
                molecule_id = record.get("molecule_chembl_id")
                molecule_name = record.get("pref_name") or record.get("molecule_name")
                if molecule_id:
                    self.add(f"ChEMBL:{molecule_id}", "Drug", molecule_name or molecule_id,
                             molecule_id)
                target_id = record.get("target_chembl_id")
                if target_id:
                    self.add(f"ChEMBL:{target_id}", "Protein", record.get("target_name") or target_id,
                             target_id)
                for component in record.get("target_components", []) or []:
                    accession = component.get("accession")
                    if accession:
                        self.add(f"UniProt:{accession}", "Protein", accession, accession)
                        if target_id:
                            self.edges.append({"source": f"ChEMBL:{target_id}",
                                               "target": f"UniProt:{accession}", "type": "same_protein_as"})
            elif database == "pubmed":
                pmid = record.get("id")
                if pmid:
                    self.add(f"PMID:{pmid}", "Literature", record.get("title") or f"PMID {pmid}", pmid)

    def resolve(self, label: str, entity_type: str) -> dict[str, Any]:
        entity_id = self.aliases.get((entity_type, _key(label)))
        if entity_id:
            return self.entities[entity_id]
        normalized_label = str(label).strip().upper() if entity_type == "Gene" else _key(label)
        fallback_id = f"{entity_type}:{normalized_label}"
        self.add(fallback_id, entity_type, label)
        return self.entities[fallback_id]

    def to_graph(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        return list(self.entities.values()), self.edges
