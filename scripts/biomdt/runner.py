from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import re
from time import monotonic
from typing import Any
from urllib.error import HTTPError

from biomdt.graph import EvidenceGraph
from biomdt.entity_index import BiomedicalEntityIndex
from biomdt.prompts import COORDINATOR_PROMPT, ROLE_PROMPTS
from biomdt.tools import BiomedicalToolExecutor


REFERENCE_FIELDS = {
    "answers", "gains", "rationale", "kegg_evidence", "reference",
    "label", "gold_answer",
}
AGENT_ORDER = ("genomics", "pathway", "drug", "literature")


def validate_model_input(row: dict[str, Any]) -> dict[str, Any]:
    leaked = REFERENCE_FIELDS.intersection(row)
    if leaked:
        raise ValueError(f"Reference fields are forbidden during inference: {sorted(leaked)}")
    required = {"id", "task_type", "question", "options"}
    missing = required.difference(row)
    if missing:
        raise ValueError(f"Model input is missing fields: {sorted(missing)}")
    return {key: row[key] for key in ("id", "task_type", "question", "options")}


def select_agents_for_gaps(gaps: list[dict[str, Any]]) -> dict[str, list[str]]:
    tasks: dict[str, list[str]] = {}
    for gap in gaps:
        status = gap["status"]
        if status == "Contradicted":
            continue
        if status == "Supported":
            if gap.get("support_level") != "indirect":
                continue
            agents = ["literature"]
        else:
            agents = ["literature"] if status == "Conflicting" else gap.get("required_evidence_types", [])
        if not agents:
            agents = ["literature"]
        for agent in agents:
            if agent not in AGENT_ORDER:
                agent = "literature"
            tasks.setdefault(agent, [])
            if gap["claim_id"] not in tasks[agent]:
                tasks[agent].append(gap["claim_id"])
    return {agent: tasks[agent] for agent in AGENT_ORDER if agent in tasks}


def infer_entities_and_roles(question: str, claims: list[dict[str, Any]],
                             proposed: dict[str, Any] | None = None
                             ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    proposed = proposed or {}
    text = " ".join([question, *(str(claim.get("text", "")) for claim in claims)])
    entity_values = _clean_entities(proposed)
    entity_patterns = {
        "genes": r"\b(?:BRCA1|BRCA2|BRAF|PIK3CA|TP53|EGFR|ERBB2|KRAS|NRAS|AKT[1-3]|SHP2|GLUD1|SHMT2|SLC2A1|MAPK1|MAPK3)\b",
        "drugs": r"\b(?:CYH33|vemurafenib|olaparib|alpelisib|PI-103|dapagliflozin|anti-PD-1)\b",
        "diseases": r"\b(?:HNSCC|head and neck squamous cell carcinoma|triple-negative breast cancer|ovarian clear cell carcinoma|ovarian cancer|breast cancer|pancreatic cancer|glioblastoma|melanoma|colorectal cancer|lung cancer|type 2 diabetes|ulcerative colitis)\b",
    }
    for entity_type, pattern in entity_patterns.items():
        found = re.findall(pattern, text, flags=re.IGNORECASE)
        entity_values[entity_type] = list(dict.fromkeys(entity_values[entity_type] + found))[:8]
    entity_values["proteins"] = list(dict.fromkeys(
        entity_values["proteins"] + re.findall(r"\b(?:PI3Kalpha|PI3Kα|ERK|AKT|SHP2|GLUT1|GLUD1|SHMT2)\b", text, re.IGNORECASE)
    ))[:8]
    entity_values["keywords"] = list(dict.fromkeys(
        entity_values["keywords"] + entity_values["drugs"] + entity_values["genes"] + entity_values["proteins"]
    ))[:8]

    routed: dict[str, list[str]] = {}
    for claim in claims:
        claim_id = claim["claim_id"]
        claim_text = str(claim.get("text", ""))
        lower = claim_text.casefold()
        roles = set(claim.get("required_evidence_types", []))
        named_gene = any(re.search(rf"\b{re.escape(name)}\b", claim_text, re.IGNORECASE)
                         for name in entity_values["genes"])
        named_protein = any(name.casefold() in claim_text.casefold() for name in entity_values["proteins"])
        if named_gene or named_protein or re.search(r"\b(gene|protein|target|receptor|kinase|enzyme|SHP2|ERK|AKT)\b", claim_text, re.IGNORECASE):
            roles.add("genomics")
        if (re.search(r"(pathway|signaling|phosphorylat|TCA|metabolic|flux|anapleros|downstream|upstream|cascade)", lower)
                or (named_protein and re.search(r"(inhibit|block|activate|regulate|increase|decrease|reduce|phosphorylat)", lower))):
            roles.add("pathway")
        named_drug = any(re.search(rf"\b{re.escape(name)}\b", claim_text, re.IGNORECASE)
                         for name in entity_values["drugs"])
        if named_drug and re.search(r"(inhibit|block|activate|bind|target|drug|treatment|combination|response)", lower):
            roles.add("drug")
        roles.add("literature")
        routed[claim_id] = [role for role in AGENT_ORDER if role in roles]
    return entity_values, routed


def validate_prediction(prediction: Any, valid_options: list[str]) -> tuple[list[str], str]:
    if prediction is None or prediction == []:
        return [], "abstention"
    if not isinstance(prediction, list) or any(not isinstance(code, str) for code in prediction):
        return [], "invalid_prediction"
    if len(prediction) != len(set(prediction)) or any(code not in valid_options for code in prediction):
        return [], "invalid_prediction"
    return prediction, "completed"


def validate_prediction_for_question(prediction: Any, valid_options: list[str],
                                     question: str) -> tuple[list[str], str]:
    parsed, status = validate_prediction(prediction, valid_options)
    if status != "completed":
        return parsed, status
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    match = re.search(
        r"\b(?:select|choose|identify|name|which)\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b",
        question, re.IGNORECASE,
    )
    if match:
        token = match.group(1).casefold()
        expected = number_words.get(token, int(token) if token.isdigit() else None)
        if expected is not None and len(parsed) != expected:
            return [], "invalid_prediction"
    return parsed, status


def agent_query_signature(role: str, claim: dict[str, Any],
                          entities: dict[str, list[str]]) -> str:
    role_entity_fields = {
        "genomics": ("genes", "proteins", "diseases", "uniprot_ids"),
        "pathway": ("genes", "proteins", "uniprot_ids"),
        "drug": ("drugs", "genes", "proteins"),
        "literature": ("keywords", "genes", "proteins", "drugs", "diseases"),
    }.get(role, tuple(sorted(entities)))
    payload = {
        "role": role,
        "claim_id": claim["claim_id"],
        "claim_text": claim["text"],
        "query_entities": {field: entities.get(field, []) for field in role_entity_fields},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def filter_attempted_agent_queries(candidates: dict[str, list[str]],
                                   claim_by_id: dict[str, dict[str, Any]],
                                   entities: dict[str, list[str]],
                                   attempted: set[str]) -> dict[str, list[str]]:
    filtered = {}
    for role, claim_ids in candidates.items():
        remaining = [claim_id for claim_id in claim_ids
                     if agent_query_signature(role, claim_by_id[claim_id], entities) not in attempted]
        if remaining:
            filtered[role] = remaining
    return filtered


def merge_followup_entities(entities: dict[str, list[str]],
                            followup: dict[str, Any]) -> dict[str, list[str]]:
    updates = followup.get("entity_updates")
    if not isinstance(updates, dict):
        updates = {}
    for entity_type, values in updates.items():
        if entity_type in entities and isinstance(values, list):
            entities[entity_type] = list(dict.fromkeys(
                entities[entity_type] + [str(value) for value in values]
            ))[:8]
    query_terms = followup.get("query_terms", [])
    normalized_terms = []
    if isinstance(query_terms, list):
        for term in query_terms:
            if isinstance(term, str):
                normalized_terms.append(term)
            elif isinstance(term, dict) and isinstance(term.get("terms"), list):
                normalized_terms.extend(value for value in term["terms"]
                                        if isinstance(value, str))
    if normalized_terms:
        entities["keywords"] = list(dict.fromkeys(
            normalized_terms + entities["keywords"]
        ))[:8]
    return entities


def parse_final_response(response: str, valid_options: list[str]) -> tuple[list[str], str, str | None]:
    matches = re.findall(r"<BIOMED_FINAL>\s*(\{.*?\})\s*</BIOMED_FINAL>",
                         str(response or ""), flags=re.DOTALL)
    if len(matches) != 1:
        return [], "format_error", "expected exactly one BIOMED_FINAL JSON block"
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as error:
        return [], "format_error", f"invalid BIOMED_FINAL JSON: {error.msg}"
    if set(payload) != {"selected_options"} or not isinstance(payload["selected_options"], list):
        return [], "format_error", "BIOMED_FINAL must contain only a selected_options array"
    prediction, status = validate_prediction(payload["selected_options"], valid_options)
    return prediction, status, None


def task_answer_instruction(question: str) -> str:
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    match = re.search(
        r"\b(?:select|choose|identify|name|which)\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b",
        question, re.IGNORECASE,
    )
    if match:
        token = match.group(1).casefold()
        amount = token if token in number_words else int(token)
        noun = "option" if amount in {"one", "1", 1} else "options"
        return (f"Select exactly {amount} {noun}, as explicitly requested by the question. "
                "Return every selected option once.")
    return ("Select all and only options supported by the question's criteria. There is no fixed number of options stated. "
            "Return every selected option once and abstain if the supplied evidence cannot distinguish a defensible selection.")


def _option_codes(options: list[str]) -> list[str]:
    return [option.split(".", 1)[0].strip() for option in options if "." in option]


def requires_atomic_refinement(claims: list[dict[str, Any]], options: list[str] | None = None) -> bool:
    compound_pattern = re.compile(
        r"\b(?:and|or|while|whereas|leading to|resulting in|by reducing|by increasing)\b",
        re.IGNORECASE,
    )
    statements = [str(claim.get("text", "")) for claim in claims]
    statements.extend(options or [])
    return any(compound_pattern.search(statement) for statement in statements)


def refine_compound_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = (
        re.compile(r"^(.+?),\s+leading to\s+(.+)$", re.IGNORECASE),
        re.compile(r"^(.+?),\s+and\s+(.+)$", re.IGNORECASE),
        re.compile(r"^(.+?)\s+through\s+(.+)$", re.IGNORECASE),
        re.compile(r"^(.+?)\s+by\s+(reducing|increasing|inhibiting|blocking|activating)\s+(.+)$", re.IGNORECASE),
    )
    refined = []
    for claim in claims:
        text = str(claim.get("text", "")).strip()
        split = None
        for pattern in patterns:
            match = pattern.match(text)
            if match:
                if len(match.groups()) == 3:
                    first, action, target = match.groups()
                    second = f"{action.capitalize()} {target}"
                else:
                    first, second = match.groups()
                split = (first.rstrip(" .;"), second.rstrip(" .;"))
                break
        if not split:
            refined.append(claim)
            continue
        for index, atom in enumerate(split, start=1):
            if not atom:
                continue
            child = dict(claim)
            child["claim_id"] = f"{claim.get('claim_id', 'C')}.{index}"
            child["text"] = atom
            child["operator"] = "AND"
            child["children"] = []
            refined.append(child)
    for index, claim in enumerate(refined, start=1):
        claim["claim_id"] = f"C{index:03d}"
    return refined


def _clean_entities(raw: dict[str, Any]) -> dict[str, list[str]]:
    return {
        key: list(dict.fromkeys(str(value).strip() for value in raw.get(key, [])
                               if str(value).strip()))[:8]
        for key in ("genes", "proteins", "diseases", "drugs", "uniprot_ids", "keywords")
    }


def _extract_agent_evidence(response: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = []
    rows = list(response.get("evidence", []))
    result_groups = (response.get("results", []) or response.get("claims", [])
                     or response.get("claim_evidence", []))
    for result in result_groups:
        claim_status = str(result.get("assessment", result.get("relationship_to_claim", result.get("evidence_status", result.get("status", result.get("relevance", "")))))).lower()
        is_context_mismatch = any(term in claim_status for term in (
            "context mismatch", "context_mismatch", "context-mismatched", "different disease", "different model",
            "different intervention", "not the question context",
        ))
        is_partial_or_unestablished = any(term in claim_status for term in (
            "partial", "not established", "not establish", "not supported",
            "insufficient", "not addressed", "no matching observation",
        ))
        stance = (
            "contradicts" if claim_status in {"contradicted", "refuted", "explicitly_contradicted", "refuted_by_evidence"}
            else "insufficient" if (is_context_mismatch or is_partial_or_unestablished or claim_status in {"insufficient_evidence", "not_addressed", "unknown", "context_mismatch", "context_mismatched_observation", "context_mismatched_evidence", "partial_support", "partially_supported", "not_supported_by_supplied_records", "not_established", "insufficient"})
            else "supports"
        )
        result_evidence = result.get("evidence", [])
        if not result_evidence and (result.get("source_id") or result.get("source_ids")):
            result_evidence = [result]
        for evidence in result_evidence:
            source_ids = evidence.get("source_ids") or [evidence.get("source_id")]
            source_ids = [source_id for source_id in source_ids if source_id]
            for source_id in source_ids or [None]:
                row = dict(evidence)
                row["source_id"] = source_id
                row.pop("source_ids", None)
                row.setdefault("claim_id", result.get("claim_id"))
                row.setdefault("stance", stance)
                relationship = str(result.get("relationship_to_claim", "")).lower()
                if (relationship in {"context_mismatch", "context_mismatched_observation"}
                        or is_context_mismatch):
                    row["context_match"] = False
                rows.append(row)
    for evidence in rows:
        directness_text = str(evidence.get("directness", evidence.get("evidence_type", ""))).lower()
        context = evidence.get("context", {})
        if not isinstance(context, dict):
            context = {}
        for key, source_key in (("disease", "disease"), ("tissue", "tissue"),
                                ("model", "model"), ("readout", "readout"),
                                ("comparison", "comparison"), ("intervention", "intervention"),
                                ("effect_direction", "effect_direction"), ("timepoint", "timepoint")):
            value = evidence.get(source_key)
            if value is None and key == "disease":
                value = evidence.get("disease")
            if value is None and key == "comparison":
                value = evidence.get("comparator")
            if value is None and key == "effect_direction":
                value = evidence.get("direction")
            context.setdefault(key, str(value or ""))
        if evidence.get("disease_tissue_model"):
            context["reported_context"] = str(evidence["disease_tissue_model"])
        reported_context = str(context.get("reported_context", "")).casefold()
        direct_observation = evidence.get("direct_observation")
        directness = (
            "direct" if direct_observation is True else
            "indirect" if direct_observation is False else
            "direct" if "direct" in directness_text and "indirect" not in directness_text else "indirect"
        )
        context_match = evidence.get("context_match")
        if context_match is None and any(term in reported_context for term in (
            "not hnscc", "no hnscc", "different disease", "different model",
            "not the question context",
        )):
            context_match = False
        if isinstance(context_match, str):
            normalized_match = context_match.casefold()
            if any(term in normalized_match for term in (
                "mismatch", "not hnscc", "not the question context", "not established for",
                "different disease", "different model", "different intervention", "partial:",
            )):
                context_match = False
            elif any(term in normalized_match for term in ("matched", "context aligned", "applicable")):
                context_match = True
            else:
                context_match = None
        source_ids = evidence.get("source_ids") or [evidence.get("source_id")]
        for source_id in source_ids:
            normalized.append({
                **evidence,
                "source_id": source_id,
                "relation": evidence.get("relation") or evidence.get("predicate", ""),
                "raw_evidence": (evidence.get("raw_evidence") or evidence.get("observation")
                                 or evidence.get("experimental_observation")
                                 or evidence.get("interpretation") or evidence.get("limitation")
                                 or evidence.get("evidence") or evidence.get("note", "")),
                "evidence_kind": (evidence.get("evidence_kind") or evidence.get("evidence_type")
                                  or evidence.get("fact_or_inference", "fact")),
                "stance": str(evidence.get("stance") or (
                    "supports" if evidence.get("supports_claim") is True
                    or str(evidence.get("evidence_status", "")).lower() in {"supported", "supports"}
                    else "insufficient"
                )).lower(),
                "context_match": context_match if context_match is not None else context.get("context_match"),
                "directness": directness,
                "context": context,
            })
    return normalized


def integrate_agent_response(graph: EvidenceGraph, entity_index: BiomedicalEntityIndex,
                             response: dict[str, Any], retrieved: list[dict[str, Any]],
                             claim_ids: list[str], role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    before_graph = deepcopy(graph.to_dict())
    retrieved_source_ids = {
        source_id for query in retrieved for source_id in query.get("source_ids", [])
    }
    extracted = _extract_agent_evidence(response)
    rejected: dict[str, int] = defaultdict(int)
    added = 0
    retrieval_failures = [query for query in retrieved if query.get("error")]
    supported_entity_types = {
        "Gene", "Protein", "Disease", "Drug", "Pathway", "Metabolite",
        "BiologicalProcess", "ExperimentalObservation", "Literature", "BiomedicalEntity",
    }
    for evidence in extracted:
        if evidence.get("claim_id") not in claim_ids:
            rejected["unknown_claim"] += 1
            continue
        if not evidence.get("source_id") or evidence["source_id"] not in retrieved_source_ids:
            rejected["source_not_retrieved"] += 1
            continue
        if evidence.get("stance") not in {"supports", "contradicts", "insufficient"}:
            rejected["unsupported_stance"] += 1
            continue
        if not all(evidence.get(field) for field in ("subject", "relation", "object", "raw_evidence")):
            rejected["missing_evidence_fields"] += 1
            continue
        subject_type = evidence.get("subject_type")
        object_type = evidence.get("object_type")
        if subject_type not in supported_entity_types:
            subject_type = "BiomedicalEntity"
        if object_type not in supported_entity_types:
            object_type = "BiomedicalEntity"
        subject = entity_index.resolve(evidence["subject"], subject_type)
        object_ = entity_index.resolve(evidence["object"], object_type)
        evidence["subject_id"] = subject["id"]
        evidence["subject_type"] = subject["type"]
        evidence["object_id"] = object_["id"]
        evidence["object_type"] = object_["type"]
        evidence["agent"] = role
        evidence.setdefault("source_type", "literature" if role == "literature" else "database")
        evidence.setdefault("directness", "indirect")
        evidence.setdefault("evidence_kind", "fact")
        added += int(graph.add_evidence(evidence))
    indexed_entities, indexed_edges = entity_index.to_graph()
    graph.add_entities(indexed_entities, indexed_edges)
    after_graph = deepcopy(graph.to_dict())
    return before_graph, {
        "response_format": next((key for key in ("evidence", "claims", "results", "claim_evidence") if key in response), "unsupported"),
        "parsed_records": len(extracted),
        "added_records": added,
        "rejected_records": dict(rejected),
        "retrieval_failures": [{
            "database": query.get("database"),
            "operation": query.get("operation"),
            "error": query.get("error"),
        } for query in retrieval_failures],
        "before_graph": before_graph,
        "after_graph": after_graph,
    }


def _normalize_plan(raw: dict[str, Any], options: list[str]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    valid_options = set(_option_codes(options))
    claims = []
    groups: dict[str, list[str]] = defaultdict(list)
    claim_id_map = {}
    for item in raw.get("claims", []):
        if not isinstance(item, dict):
            continue
        option = str(item.get("option", "")).strip().upper()
        text = str(item.get("text", "")).strip()
        if option not in valid_options or not text:
            continue
        claim_id = f"C{len(claims) + 1:03d}"
        if item.get("claim_id"):
            claim_id_map[str(item["claim_id"])] = claim_id
        required = [role for role in item.get("required_evidence_types", []) if role in AGENT_ORDER]
        if not required:
            required = ["literature"]
        operator = str(item.get("operator", "AND")).upper()
        if operator not in {"AND", "OR", "NOT", "COMPARISON"}:
            operator = "AND"
        claim = {
            "claim_id": claim_id,
            "option": option,
            "text": text,
            "operator": operator,
            "children": list(item.get("children", [])),
            "required_evidence_types": list(dict.fromkeys(required)),
            "context": item.get("context", {}) if isinstance(item.get("context"), dict) else {},
        }
        claims.append(claim)
        groups[option].append(claim_id)
    for claim in claims:
        claim["children"] = [claim_id_map[child] for child in claim["children"]
                             if child in claim_id_map]
    if not claims:
        for option in options:
            code, statement = option.split(".", 1)
            claim_id = f"C{len(claims) + 1:03d}"
            claims.append({
                "claim_id": claim_id, "option": code.strip(), "text": statement.strip(),
                "operator": "AND", "children": [], "required_evidence_types": ["literature"],
                "context": {},
            })
            groups[code.strip()].append(claim_id)
    operators = {}
    for claim in claims:
        operators.setdefault(claim["option"], claim["operator"])
    return claims, {option: operators.get(option, "AND") for option in groups}


class BioMDTRunner:
    def __init__(self, backend: Any, tool_executor: BiomedicalToolExecutor | None = None,
                 max_collaboration_rounds: int = 4):
        self.backend = backend
        self.tool_executor = tool_executor or BiomedicalToolExecutor()
        self.max_collaboration_rounds = max_collaboration_rounds

    def run(self, row: dict[str, Any]) -> dict[str, Any]:
        started = monotonic()
        model_input = validate_model_input(row)
        input_payload = {"question": model_input["question"], "options": model_input["options"]}
        input_payload["answer_instruction"] = task_answer_instruction(model_input["question"])
        events = [{"event": "coordinator_decompose", "round": 0}]
        plan = self.backend.complete("coordinator", COORDINATOR_PROMPT, input_payload)
        if requires_atomic_refinement(plan.get("claims", []), model_input["options"]):
            try:
                plan = self.backend.complete("coordinator", COORDINATOR_PROMPT +
                    "\nPerform an atomicity audit now. Split every conjunctive or causal statement into separate independently verifiable claims. Keep the same option letter for all component claims and set the option logic to AND or OR. Return the complete refined claim list, including unchanged atomic claims.", {
                        **input_payload,
                        "claims_to_audit": [{key: claim.get(key) for key in ("claim_id", "option", "text")}
                                            for claim in plan.get("claims", []) if isinstance(claim, dict)],
                    }, reuse_session=True)
                events.append({"event": "coordinator_atomicity_refinement", "round": 0})
            except (HTTPError, TimeoutError) as error:
                if isinstance(error, HTTPError) and error.code not in {408, 502, 503, 504, 524}:
                    raise
                events.append({"event": "coordinator_atomicity_audit_unavailable", "error": str(error)})
        claims, option_operators = _normalize_plan(plan, model_input["options"])
        claims = refine_compound_claims(claims)
        entities, inferred_roles = infer_entities_and_roles(
            model_input["question"], claims, plan.get("entities", {})
        )
        if model_input["task_type"] == "target_identification":
            candidates = [match.group(1) for option in model_input["options"]
                          if (match := re.search(r"\(([A-Z][A-Z0-9/-]{1,11})\)", option))]
            if candidates:
                entities["target_candidates"] = list(dict.fromkeys(candidates))
            entities["genes"] = list(dict.fromkeys(candidates + entities["genes"]))[:8]
            entities["diseases"] = sorted(entities["diseases"], key=lambda name: name.casefold() not in model_input["question"].casefold()
                                      or any(name.casefold() in other.casefold() and len(other) > len(name)
                                             for other in entities["diseases"]))
        for claim in claims:
            claim["required_evidence_types"] = inferred_roles[claim["claim_id"]]
        claim_by_id = {claim["claim_id"]: claim for claim in claims}
        graph = EvidenceGraph()
        entity_index = BiomedicalEntityIndex()
        for claim in claims:
            graph.add_claim(claim)
        groups: dict[str, list[str]] = defaultdict(list)
        for claim in claims:
            groups[claim["option"]].append(claim["claim_id"])
        for option, claim_ids in groups.items():
            graph.add_option_group(option, option_operators[option], claim_ids)
        graph_snapshots = [{"stage": "before_evidence", "round": 0, "graph": deepcopy(graph.to_dict())}]

        used_roles: set[str] = set()
        attempted_agent_queries: set[str] = set()
        agent_results: dict[str, list[dict[str, Any]]] = {}
        agent_outputs: list[dict[str, Any]] = []
        collaboration_messages: list[dict[str, Any]] = []
        round_index = 0
        active_tasks = select_agents_for_gaps([
            {**claim, "status": "Missing"} for claim in claims
        ])
        if active_tasks:
            first_role = next(iter(active_tasks))
            active_tasks = {first_role: active_tasks[first_role]}
        while active_tasks and round_index < self.max_collaboration_rounds:
            round_index += 1
            for role, claim_ids in active_tasks.items():
                selected_claims = [claim for claim in claims if claim["claim_id"] in claim_ids]
                events.append({"event": "agent_dispatched", "round": round_index,
                               "agent": role, "claim_ids": claim_ids})
                query_signatures = {
                    claim["claim_id"]: agent_query_signature(role, claim, entities)
                    for claim in selected_claims
                }
                attempted_agent_queries.update(query_signatures.values())
                existing_evidence = [row for row in graph.evidence if row["claim_id"] in claim_ids]
                prior_agents = list(dict.fromkeys(row["agent"] for row in existing_evidence if row.get("agent")))
                message = {
                    "sender": prior_agents[-1] if prior_agents else "Coordinator",
                    "recipient": role,
                    "claim_ids": claim_ids,
                    "existing_evidence_ids": [row["evidence_id"] for row in existing_evidence],
                    "evidence_gap": [
                        {"claim_id": claim_id, "status": graph.recompute().get(claim_id, {}).get("status", "Missing")}
                        for claim_id in claim_ids
                    ],
                    "query_requirements": selected_claims,
                    "remaining_rounds": max(self.max_collaboration_rounds - round_index, 0),
                }
                collaboration_messages.append(message)
                events.append({"event": "collaboration_message", **message})
                retrieved = self.tool_executor.retrieve(role, entities, selected_claims)
                agent_results.setdefault(role, []).extend(retrieved)
                graph_snapshots.append({"stage": "after_retrieval_before_evidence", "round": round_index,
                                        "agent": role, "graph": deepcopy(graph.to_dict())})
                for retrieval in retrieved:
                    entity_index.add_retrieval(retrieval)
                indexed_entities, indexed_edges = entity_index.to_graph()
                graph.add_entities(indexed_entities, indexed_edges)
                source_ids = {
                    source_id for result in retrieved for source_id in result.get("source_ids", [])
                }
                specialist_prompt = ROLE_PROMPTS[role]
                specialist_input = {
                    "question": model_input["question"],
                    "options": model_input["options"],
                    "collaboration_message": message,
                    "claims": selected_claims,
                    "retrievals": retrieved,
                    "source_ids": sorted(source_ids),
                }
                if role == "literature" and entities.get("target_candidates"):
                    articles = [
                        {"source_id": f"PMID:{article['id']}", "title": article.get("title", ""),
                         "abstract": (article.get("abstract") or "")[:1200]}
                        for result in retrieved if result.get("operation") == "fetch"
                        for article in result["records"] if article.get("id")
                    ]
                    specialist_input = {
                        "question": model_input["question"],
                        "claims": selected_claims,
                        "articles": articles,
                        "source_ids": [article["source_id"] for article in articles],
                    }
                    specialist_prompt += (" For this target comparison, record at most one decisive "
                                          "observation per candidate option using the supplied articles. "
                                          "Omit entries that only restate a lack of evidence.")
                response = self.backend.complete(
                    role, specialist_prompt, specialist_input, reuse_session=role in used_roles
                )
                used_roles.add(role)
                agent_outputs.append({"round": round_index, "agent": role, "claim_ids": claim_ids,
                                      "response": response})
                _, integration = integrate_agent_response(
                    graph, entity_index, response, retrieved, claim_ids, role
                )
                added = integration["added_records"]
                events.append({"event": "evidence_added", "round": round_index,
                               "agent": role, "count": added,
                               "response_format": integration["response_format"],
                               "parsed_records": integration["parsed_records"],
                               "rejected_records": integration["rejected_records"]})
                graph_snapshots.append({"stage": "after_evidence", "round": round_index,
                                        "agent": role, "added": added,
                                        "rejected_records": integration["rejected_records"],
                                        "graph": integration["after_graph"]})

            states = graph.recompute()
            gaps = [
                {**claim, **states[claim["claim_id"]]}
                for claim in claims
                if states[claim["claim_id"]]["status"] in {"Missing", "Conflicting"}
                or states[claim["claim_id"]]["support_level"] == "indirect"
            ]
            candidates = select_agents_for_gaps(gaps)
            candidates = filter_attempted_agent_queries(
                candidates, claim_by_id, entities, attempted_agent_queries
            )
            if round_index >= self.max_collaboration_rounds or not candidates:
                active_tasks = {}
                break
            followup = self.backend.complete("coordinator", COORDINATOR_PROMPT, {
                "stage": "select_follow_up",
                "question": model_input["question"],
                "unresolved_claims": gaps,
                "latest_evidence": [{
                    "id": evidence["evidence_id"], "subject": evidence["subject"],
                    "relation": evidence["relation"], "object": evidence["object"],
                    "source": evidence["source_id"],
                } for evidence in graph.evidence if evidence["agent"] == role],
                "available_follow_up_roles": list(candidates),
                "previously_attempted_queries": sorted(attempted_agent_queries),
                "remaining_rounds": self.max_collaboration_rounds - round_index,
            }, reuse_session=True)
            entities = merge_followup_entities(entities, followup)
            viable = filter_attempted_agent_queries(candidates, claim_by_id, entities,
                                                     attempted_agent_queries)
            chosen = [role for role in followup.get("follow_up_roles", []) if role in viable]
            chosen_role = chosen[0] if chosen else (next(iter(viable)) if viable else None)
            if chosen_role is None:
                active_tasks = {}
                break
            active_tasks = {chosen_role: viable[chosen_role]}
            events.append({"event": "gap_driven_follow_up", "round": round_index + 1,
                           "agent": chosen_role, "claim_ids": candidates[chosen_role]})

        atom_states = graph.recompute()
        option_states = graph.option_states()
        evidence_for_decision = [{
            "evidence_id": row["evidence_id"], "claim_id": row["claim_id"],
            "subject": row["subject"], "relation": row["relation"], "object": row["object"],
            "subject_id": row["subject_id"], "subject_type": row["subject_type"],
            "object_id": row["object_id"], "object_type": row["object_type"],
            "stance": row["stance"], "context": row["context"],
            "directness": row["directness"], "evidence_kind": row["evidence_kind"],
            "source_id": row["source_id"], "raw_evidence": row["raw_evidence"][:1200],
        } for row in graph.evidence]
        decision = self.backend.complete("decision", ROLE_PROMPTS["decision"], {
            **input_payload,
            "task_type": model_input["task_type"],
            "option_states": option_states,
            "claim_states": atom_states,
            "claims": claims,
            "evidence": evidence_for_decision,
        })
        valid_options = set(_option_codes(model_input["options"]))
        predictions, prediction_status = validate_prediction_for_question(
            decision.get("selected_options"), sorted(valid_options), model_input["question"]
        )
        if prediction_status != "completed":
            events.append({"event": "invalid_or_empty_prediction"})
        events.append({"event": "decision", "selected_options": predictions})
        calls = list(getattr(self.backend, "calls", []))
        tool_calls = list(self.tool_executor.calls)
        return {
            "id": model_input["id"],
            "task_type": model_input["task_type"],
            "prediction": predictions,
            "prediction_status": prediction_status,
            "explanation": decision.get("explanation", ""),
            "biological_interpretation": decision.get("biology", ""),
            "key_paths": decision.get("key_paths", []),
            "claims": claims,
            "entities": entities,
            "claim_states": atom_states,
            "option_states": option_states,
            "evidence_graph": graph.to_dict(),
            "graph_snapshots": graph_snapshots,
            "evidence_gaps": [state for state in atom_states.values() if state["status"] in {"Missing", "Conflicting"}],
            "unresolved_gaps": decision.get("unresolved_gaps", []),
            "agent_results": agent_results,
            "agent_outputs": agent_outputs,
            "collaboration_messages": collaboration_messages,
            "events": events,
            "tool_calls": tool_calls,
            "runtime": {
                "model": getattr(self.backend, "model", "codex-default"),
                "backend": "openai-compatible" if hasattr(self.backend, "base_url") else "codex-cli",
                "cli_version": getattr(self.backend, "cli_version", None),
                "llm_call_count": len(calls),
                "input_tokens": sum(call.get("input_tokens", 0) for call in calls),
                "output_tokens": sum(call.get("output_tokens", 0) for call in calls),
                "total_tokens": sum(call.get("total_tokens", 0) for call in calls),
                "tool_call_count": len(tool_calls),
                "duration_seconds": round(monotonic() - started, 3),
                "llm_calls": calls,
            },
            "diagnostics": {
                "retrieval_failures": [call for call in tool_calls if call.get("error")],
                "evidence_write_failures": [event for event in events
                                             if event.get("event") == "evidence_added"
                                             and event.get("rejected_records")],
            },
        }


class DirectLLMRunner:
    def __init__(self, backend: Any):
        self.backend = backend

    def run(self, row: dict[str, Any]) -> dict[str, Any]:
        model_input = validate_model_input(row)
        response = self.backend.complete("direct", ROLE_PROMPTS["direct"], {
            "question": model_input["question"], "options": model_input["options"],
            "answer_instruction": task_answer_instruction(model_input["question"]),
        })
        valid_options = set(_option_codes(model_input["options"]))
        predictions, prediction_status = validate_prediction_for_question(
            response.get("selected_options"), sorted(valid_options), model_input["question"]
        )
        calls = list(getattr(self.backend, "calls", []))
        return {
            "id": model_input["id"], "task_type": model_input["task_type"],
            "prediction": predictions, "explanation": response.get("explanation", ""),
            "prediction_status": prediction_status,
            "unresolved_gaps": response.get("unresolved_gaps", []),
            "runtime": {
                "model": getattr(self.backend, "model", "codex-default"),
                "backend": "openai-compatible" if hasattr(self.backend, "base_url") else "codex-cli",
                "cli_version": getattr(self.backend, "cli_version", None),
                "llm_call_count": len(calls),
                "input_tokens": sum(call.get("input_tokens", 0) for call in calls),
                "output_tokens": sum(call.get("output_tokens", 0) for call in calls),
                "total_tokens": sum(call.get("total_tokens", 0) for call in calls),
                "tool_call_count": 0,
            },
        }
