from __future__ import annotations

import re
from typing import Any


CONTEXT_FIELDS = (
    "disease", "tissue", "model", "species", "intervention",
    "readout", "comparison", "timepoint",
)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def contexts_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for key in CONTEXT_FIELDS:
        a = _normalize(left.get(key))
        b = _normalize(right.get(key))
        if not a or not b or a == b:
            continue
        if key == "disease":
            # Accept a short form when the other field supplies its expansion.
            if a.endswith(f" ({b})") or b.endswith(f" ({a})"):
                continue
        elif key == "readout":
            a, b = (re.sub(r"\bphosphorylated ([\w-]+)\b", r"\1 phosphorylation", value)
                    for value in (a, b))
            if set(a.split(" and ")) & set(b.split(" and ")):
                continue
        elif key == "comparison":
            a, b = (re.sub(r"^.*?\bversus ", "", value) for value in (a, b))
            if set(a.split(" or ")) & set(b.split(" or ")):
                continue
        return False
    return True


def _evidence_context(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row["context"].get(key) or row.get(key) for key in CONTEXT_FIELDS}


class EvidenceGraph:
    def __init__(self):
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self.claims: dict[str, dict[str, Any]] = {}
        self.evidence: list[dict[str, Any]] = []
        self._evidence_sources: set[tuple[str, str]] = set()
        self._conflict_groups: dict[str, str] = {}

    def add_claim(self, claim: dict[str, Any]) -> None:
        claim_id = str(claim["claim_id"])
        normalized = {
            "claim_id": claim_id,
            "option": str(claim["option"]),
            "text": str(claim["text"]),
            "operator": str(claim.get("operator", "AND")).upper(),
            "children": list(claim.get("children", [])),
            "required_evidence_types": list(dict.fromkeys(
                claim.get("required_evidence_types", ["literature"])
            )),
            "context": dict(claim.get("context", {})),
        }
        self.claims[claim_id] = normalized
        self.nodes[claim_id] = {"id": claim_id, "type": "Claim", **normalized}
        self.edges.append({"source": claim_id, "target": normalized["option"], "type": "maps_to_option"})
        for child_id in normalized["children"]:
            self.edges.append({"source": claim_id, "target": child_id, "type": "requires"})

    def add_option_group(self, option: str, operator: str, claim_ids: list[str]) -> None:
        group_id = f"OPTION:{option}"
        self.nodes.setdefault(option, {"id": option, "type": "Option", "label": option})
        group = {"id": group_id, "type": "CompositeClaim", "option": option,
                 "operator": operator, "children": list(claim_ids)}
        self.nodes[group_id] = group
        for claim_id in claim_ids:
            self.edges.append({"source": group_id, "target": claim_id, "type": "requires"})
        self.edges.append({"source": group_id, "target": option, "type": "maps_to_option"})

    def add_entities(self, entities: list[dict[str, Any]], edges: list[dict[str, str]]) -> None:
        for entity in entities:
            self.nodes.setdefault(entity["id"], entity)
        known_edges = {(edge["source"], edge["target"], edge["type"]) for edge in self.edges}
        for edge in edges:
            edge_key = (edge["source"], edge["target"], edge["type"])
            if edge_key not in known_edges:
                self.edges.append(edge)
                known_edges.add(edge_key)

    def add_evidence(self, evidence: dict[str, Any]) -> bool:
        claim_id = str(evidence["claim_id"])
        source_id = str(evidence.get("source_id") or "").strip()
        source_key = (claim_id, source_id) if source_id else (
            claim_id, _normalize(evidence.get("raw_evidence"))
        )
        if source_key in self._evidence_sources:
            return False
        self._evidence_sources.add(source_key)
        evidence_id = f"E{len(self.evidence) + 1:04d}"
        row = {
            "evidence_id": evidence_id,
            "claim_id": claim_id,
            "subject": evidence.get("subject", ""),
            "subject_id": evidence.get("subject_id"),
            "subject_type": evidence.get("subject_type", "BiomedicalEntity"),
            "relation": evidence.get("relation", ""),
            "object": evidence.get("object", ""),
            "object_id": evidence.get("object_id"),
            "object_type": evidence.get("object_type", "BiomedicalEntity"),
            "stance": str(evidence.get("stance", "supports")).lower(),
            "context_match": evidence.get("context_match"),
            "context": dict(evidence.get("context", {})),
            "intervention": evidence.get("intervention"),
            "disease": evidence.get("disease"),
            "tissue": evidence.get("tissue"),
            "model": evidence.get("model"),
            "readout": evidence.get("readout"),
            "effect_direction": evidence.get("effect_direction"),
            "comparison": evidence.get("comparison"),
            "directness": str(evidence.get("directness", "indirect")).lower(),
            "evidence_kind": str(evidence.get("evidence_kind", "fact")).lower(),
            "source_id": source_id,
            "source_type": evidence.get("source_type", "database"),
            "database": evidence.get("database"),
            "raw_evidence": str(evidence.get("raw_evidence", "")),
            "agent": evidence.get("agent"),
            "derived_from": list(evidence.get("derived_from", [])),
        }
        self.evidence.append(row)
        self.nodes[evidence_id] = {"id": evidence_id, "type": "Evidence", **row}
        self.edges.append({"source": evidence_id, "target": claim_id, "type": row["stance"]})
        if source_id:
            self.nodes.setdefault(source_id, {"id": source_id, "type": "Literature" if source_id.startswith("PMID:") else "Source"})
            self.edges.append({"source": evidence_id, "target": source_id, "type": "derived_from"})
        for entity, prefix in ((row["subject"], "subject"), (row["object"], "object")):
            if entity:
                entity_id = row.get(f"{prefix}_id") or _normalize(entity)
                resolved_type = row.get(f"{prefix}_type") or "BiomedicalEntity"
                self.nodes.setdefault(entity_id, {"id": entity_id, "type": resolved_type,
                                                   "label": entity, "identifiers": []})
                self.edges.append({"source": entity_id, "target": evidence_id, "type": "participates_in"})
        return True

    def recompute(self) -> dict[str, dict[str, Any]]:
        states = {}
        for claim_id, claim in self.claims.items():
            rows = [row for row in self.evidence if row["claim_id"] == claim_id]
            applicable = []
            mismatches = 0
            for row in rows:
                context = _evidence_context(row)
                if row.get("context_match") is False:
                    mismatches += 1
                elif contexts_match(context, claim["context"]):
                    applicable.append(row)
                else:
                    mismatches += 1
            supports = [row for row in applicable if row["stance"] == "supports"]
            contradicts = [row for row in applicable if row["stance"] == "contradicts"]
            aligned_conflict = any(
                contexts_match(
                    _evidence_context(left),
                    _evidence_context(right),
                )
                for left in supports for right in contradicts
            )
            if aligned_conflict:
                self._conflict_groups[claim_id] = f"CONFLICT:{claim_id}"
            if supports and contradicts and aligned_conflict:
                status = "Conflicting"
            elif supports:
                status = "Supported"
            elif contradicts:
                status = "Contradicted"
            else:
                status = "Missing"
            states[claim_id] = {
                "claim_id": claim_id,
                "status": status,
                "support_level": (
                    "direct" if any(row["directness"] == "direct" for row in supports)
                    else "indirect" if supports else None
                ),
                "supporting_evidence_ids": [row["evidence_id"] for row in supports],
                "contradicting_evidence_ids": [row["evidence_id"] for row in contradicts],
                "context_mismatches": mismatches + (
                    len(contradicts) if supports and contradicts and not aligned_conflict else 0
                ),
                "conflict_group": self._conflict_groups.get(claim_id),
                "required_evidence_types": claim["required_evidence_types"],
            }
        return states

    def option_states(self) -> dict[str, dict[str, Any]]:
        atom_states = self.recompute()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in self.claims.values():
            grouped.setdefault(claim["option"], []).append({
                **claim, "status": atom_states[claim["claim_id"]]["status"]
            })
        results = {}
        for option, claims in grouped.items():
            statuses = [claim["status"] for claim in claims]
            operator = claims[0]["operator"]
            if operator == "NOT" and len(statuses) == 1:
                status = {"Supported": "Contradicted", "Contradicted": "Supported"}.get(statuses[0], statuses[0])
            elif operator == "OR":
                status = (
                    "Supported" if "Supported" in statuses else
                    "Conflicting" if "Conflicting" in statuses else
                    "Contradicted" if all(value == "Contradicted" for value in statuses) else
                    "Missing"
                )
            elif operator == "COMPARISON":
                comparison_observations = [
                    row for claim_id in [claim["claim_id"] for claim in claims]
                    for row in self.evidence if row["claim_id"] == claim_id
                    and row.get("comparison") and row.get("context_match") is not False
                ]
                status = (
                    "Conflicting" if "Conflicting" in statuses else
                    "Contradicted" if "Contradicted" in statuses else
                    "Supported" if statuses and all(value == "Supported" for value in statuses)
                    and comparison_observations else
                    "Missing"
                )
            else:
                status = (
                    "Contradicted" if "Contradicted" in statuses else
                    "Conflicting" if "Conflicting" in statuses else
                    "Supported" if statuses and all(value == "Supported" for value in statuses) else
                    "Missing"
                )
            results[option] = {"option": option, "operator": operator, "status": status,
                               "claim_ids": [claim["claim_id"] for claim in claims]}
        return results

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "claims": list(self.claims.values()),
            "evidence": self.evidence,
            "claim_states": self.recompute(),
            "option_states": self.option_states(),
        }
