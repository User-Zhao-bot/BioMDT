import sys
from pathlib import Path
import json
from subprocess import CompletedProcess
from unittest.mock import patch
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from biomdt.graph import EvidenceGraph
from biomdt.backend import OUTPUT_SCHEMA
from biomdt.backend import CodexCliBackend
from biomdt.backend import OpenAICompatibleBackend
from biomdt.runner import BioMDTRunner, DirectLLMRunner, _extract_agent_evidence, filter_attempted_agent_queries, infer_entities_and_roles, integrate_agent_response, parse_final_response, refine_compound_claims, requires_atomic_refinement, select_agents_for_gaps, task_answer_instruction, validate_prediction, validate_prediction_for_question


def test_same_context_opposite_evidence_is_conflicting():
    graph = EvidenceGraph()
    graph.add_claim({
        "claim_id": "C1",
        "option": "A",
        "text": "Drug X suppresses ERK signaling.",
        "operator": "AND",
        "required_evidence_types": ["literature"],
    })
    graph.add_evidence({
        "claim_id": "C1",
        "subject": "Drug X",
        "relation": "inhibits",
        "object": "ERK signaling",
        "stance": "supports",
        "context": {"disease": "HNSCC", "intervention": "Drug X"},
        "directness": "direct",
        "source_id": "PMID:1",
        "raw_evidence": "Reduced ERK phosphorylation in HNSCC cells.",
    })
    graph.add_evidence({
        "claim_id": "C1",
        "subject": "Drug X",
        "relation": "inhibits",
        "object": "ERK signaling",
        "stance": "contradicts",
        "context": {"disease": "HNSCC", "intervention": "Drug X"},
        "directness": "direct",
        "source_id": "PMID:2",
        "raw_evidence": "No ERK change in HNSCC cells.",
    })

    assert graph.recompute()["C1"]["status"] == "Conflicting"


def test_different_context_opposite_evidence_is_not_a_conflict():
    graph = EvidenceGraph()
    graph.add_claim({
        "claim_id": "C1", "option": "A", "text": "Claim",
        "operator": "AND", "required_evidence_types": ["literature"],
    })
    for source_id, stance, disease in (
        ("PMID:1", "supports", "HNSCC"),
        ("PMID:2", "contradicts", "melanoma"),
    ):
        graph.add_evidence({
            "claim_id": "C1", "subject": "X", "relation": "changes",
            "object": "Y", "stance": stance,
            "context": {"disease": disease}, "directness": "direct",
            "source_id": source_id, "raw_evidence": source_id,
        })

    status = graph.recompute()["C1"]
    assert status["status"] == "Supported"
    assert status["context_mismatches"] == 1


def test_comparison_option_requires_evidence_with_a_comparator():
    graph = EvidenceGraph()
    graph.add_claim({"claim_id": "C1", "option": "A", "text": "Model X has a higher response than model Y.",
                     "operator": "COMPARISON", "required_evidence_types": ["literature"]})
    graph.add_option_group("A", "COMPARISON", ["C1"])
    graph.add_evidence({"claim_id": "C1", "subject": "Drug", "relation": "increases",
                        "object": "response", "stance": "supports", "context": {},
                        "directness": "direct", "source_id": "PMID:1",
                        "raw_evidence": "Drug increases response.", "comparison": "vehicle"})

    assert graph.option_states()["A"]["status"] == "Supported"


def test_graph_adds_option_nodes_for_every_option_mapping_edge():
    graph = EvidenceGraph()
    graph.add_claim({"claim_id": "C1", "option": "A", "text": "claim",
                     "operator": "AND", "children": [],
                     "required_evidence_types": ["literature"], "context": {}})
    graph.add_option_group("A", "AND", ["C1"])

    nodes = {node["id"] for node in graph.to_dict()["nodes"]}
    dangling = [edge for edge in graph.to_dict()["edges"]
                if edge["source"] not in nodes or edge["target"] not in nodes]

    assert "A" in nodes
    assert dangling == []


def test_runner_records_structured_messages_between_specialist_roles():
    backend = StubBackend()
    result = BioMDTRunner(backend, StubTools()).run({
        "id": "pilot_test", "task_type": "target_identification",
        "question": "What is the role of BRCA1 in breast cancer?",
        "options": ["A. BRCA1 is relevant.", "B. No relationship."],
    })

    message = result["collaboration_messages"][0]
    assert message["sender"] == "Coordinator"
    assert message["recipient"] == "genomics"
    assert message["claim_ids"] == ["C001"]
    assert message["evidence_gap"][0]["status"] == "Missing"


def test_duplicate_database_records_from_one_pmid_do_not_duplicate_evidence():
    graph = EvidenceGraph()
    evidence = {
        "claim_id": "C1", "subject": "X", "relation": "regulates",
        "object": "Y", "stance": "supports", "context": {},
        "directness": "indirect", "source_id": "PMID:9",
        "raw_evidence": "same paper observation",
    }
    assert graph.add_evidence(evidence) is True
    assert graph.add_evidence(evidence | {"database": "pubtator"}) is False
    assert len(graph.evidence) == 1


def test_gap_scheduler_assigns_only_missing_claim_roles():
    gaps = [
        {"claim_id": "C1", "status": "Missing", "required_evidence_types": ["genomics", "pathway"]},
        {"claim_id": "C2", "status": "Supported", "required_evidence_types": ["drug"]},
        {"claim_id": "C3", "status": "Conflicting", "required_evidence_types": ["drug"]},
    ]

    assert select_agents_for_gaps(gaps) == {
        "genomics": ["C1"],
        "pathway": ["C1"],
        "literature": ["C3"],
    }


def test_role_router_derives_specialists_when_coordinator_has_no_entities_or_roles():
    claims = [{"claim_id": "C1", "option": "A",
               "text": "CYH33 inhibits PI3Kalpha and reduces AKT phosphorylation.",
               "required_evidence_types": ["literature"], "context": {}}]
    entities, routed = infer_entities_and_roles(
        "In HNSCC, does CYH33 block PI3Kalpha signaling?", claims, {}
    )

    assert entities["drugs"] == ["CYH33"]
    assert "PI3Kalpha" in entities["proteins"]
    assert set(routed["C1"]) == {"genomics", "pathway", "drug", "literature"}


def test_role_router_extracts_named_entities_from_question_and_option_text():
    question = "In HNSCC, evaluate CYH33 effects on PI3Kα, AKT phosphorylation, and SHP2."
    claims = [{"claim_id": "C1", "option": "A", "text": "CYH33 inhibits PI3Kα.",
               "required_evidence_types": [], "context": {}}]
    entities, roles = infer_entities_and_roles(question, claims, {})

    assert entities["drugs"] == ["CYH33"]
    assert "PI3Kα" in entities["proteins"]
    assert "SHP2" in entities["genes"]
    assert roles["C1"] == ["genomics", "pathway", "drug", "literature"]


def test_role_router_does_not_assign_pathway_agent_for_generic_gene_relevance():
    claims = [{"claim_id": "C1", "option": "A", "text": "BRCA1 is relevant to the mechanism.",
               "required_evidence_types": [], "context": {}}]
    _, routed = infer_entities_and_roles("What is the role of BRCA1?", claims, {})

    assert routed["C1"] == ["genomics", "literature"]


def test_gap_router_can_assign_a_second_specialist_after_first_role_has_run():
    pending = select_agents_for_gaps([{
        "claim_id": "C1", "status": "Missing",
        "required_evidence_types": ["genomics", "pathway", "drug", "literature"],
    }])
    remaining = {
        role: [claim_id for claim_id in ids if (role, claim_id) != ("genomics", "C1")]
        for role, ids in pending.items()
    }

    assert remaining["pathway"] == ["C1"]
    assert remaining["drug"] == ["C1"]


def test_agent_query_signature_changes_when_entity_query_changes():
    from biomdt.runner import agent_query_signature

    claim = {"claim_id": "C1", "text": "BRCA1 function", "required_evidence_types": ["genomics"]}
    first = agent_query_signature("genomics", claim, {"genes": ["BRCA1"]})
    same = agent_query_signature("genomics", claim, {"genes": ["BRCA1"]})
    refined = agent_query_signature("genomics", claim, {"uniprot_ids": ["P38398"]})

    assert first == same
    assert first != refined


def test_query_filter_allows_same_agent_when_retrieval_parameters_change():
    from biomdt.runner import agent_query_signature

    claim = {"claim_id": "C1", "text": "BRCA1 function"}
    previous = agent_query_signature("genomics", claim, {"genes": ["BRCA1"]})
    assert filter_attempted_agent_queries(
        {"genomics": ["C1"]}, {"C1": claim},
        {"uniprot_ids": ["P38398"]}, {previous},
    ) == {"genomics": ["C1"]}


def test_gap_scheduler_can_revisit_role_when_query_condition_changes():
    gaps = [{"claim_id": "C1", "status": "Missing",
             "required_evidence_types": ["genomics", "literature"]}]
    available = select_agents_for_gaps(gaps)
    attempted = {("genomics", "C1", "BRCA1"), ("literature", "C1", "breast cancer")}
    query_candidates = {"genomics": {"C1": "P38398"},
                       "literature": {"C1": "BRCA1 response colorectal cancer"}}

    remaining = {
        role: [claim_id for claim_id in claim_ids
               if (role, claim_id, query_candidates[role].get(claim_id)) not in attempted]
        for role, claim_ids in available.items()
    }

    assert remaining == available


def test_followup_merger_ignores_non_mapping_entity_updates_and_keeps_query_terms():
    from biomdt.runner import merge_followup_entities

    entities = {"genes": ["PIK3CA"], "proteins": [], "diseases": [],
                "drugs": ["CYH33"], "uniprot_ids": [], "keywords": ["CYH33"]}
    merged = merge_followup_entities(entities, {
        "entity_updates": [{"type": "genes", "value": "PTEN"}],
        "query_terms": ["HNSCC feedback"],
    })

    assert merged["genes"] == ["PIK3CA"]
    assert "HNSCC feedback" in merged["keywords"]


def test_followup_merger_extracts_query_terms_without_stringifying_plan_objects():
    from biomdt.runner import merge_followup_entities

    entities = {"genes": [], "proteins": [], "diseases": [], "drugs": [],
                "uniprot_ids": [], "keywords": []}
    merged = merge_followup_entities(entities, {
        "query_terms": [{"claim_id": "C1", "role": "literature", "terms": ["BRCA1 TNBC"]}],
    })

    assert merged["keywords"] == ["BRCA1 TNBC"]


def test_plan_normalizer_skips_non_mapping_claim_items():
    from biomdt.runner import _normalize_plan

    claims, operators = _normalize_plan({"claims": [["malformed"]]}, ["A. Candidate"])

    assert claims[0]["option"] == "A"
    assert claims[0]["text"] == "Candidate"
    assert operators == {"A": "AND"}


def test_prediction_validation_distinguishes_abstention_from_invalid_output():
    assert validate_prediction([], ["A", "B"]) == ([], "abstention")
    assert validate_prediction(["A", "Z"], ["A", "B"]) == ([], "invalid_prediction")
    assert validate_prediction(["A", "A"], ["A", "B"]) == ([], "invalid_prediction")
    assert validate_prediction(["A"], ["A", "B"]) == (["A"], "completed")
    assert validate_prediction_for_question(["A", "B"], ["A", "B"],
                                             "Select one gene.") == ([], "invalid_prediction")


def test_answer_cardinality_instruction_uses_only_question_text():
    assert "exactly two" in task_answer_instruction("Select two most promising genes.")
    assert "no fixed number" in task_answer_instruction("Which mechanisms are supported?")
    assert "answers" not in task_answer_instruction("Select one gene.").lower()


def test_final_answer_parser_distinguishes_abstention_format_and_model_errors():
    assert parse_final_response('<BIOMED_FINAL>{"selected_options":[]}</BIOMED_FINAL>', ["A", "B"]) == ([], "abstention", None)
    assert parse_final_response('no tag', ["A", "B"])[1] == "format_error"
    assert parse_final_response('<BIOMED_FINAL>{"selected_options":["Z"]}</BIOMED_FINAL>', ["A", "B"])[1] == "invalid_prediction"
    assert parse_final_response('<BIOMED_FINAL>{"selected_options":["A"]}</BIOMED_FINAL>', ["A", "B"]) == (["A"], "completed", None)


def test_agent_evidence_normalizer_keeps_nested_records_without_mutating_response():
    from biomdt.runner import _extract_agent_evidence

    response = {"claim_evidence": [{
        "claim_id": "C1", "assessment": "supported", "evidence": [{
            "subject": "CYH33", "relation": "inhibits", "object": "PI3Kalpha",
            "source_id": "PMID:40533463", "raw_evidence": "Reported in HNSCC cells.",
        }],
    }]}

    evidence = _extract_agent_evidence(response)

    assert len(evidence) == 1
    assert evidence[0]["claim_id"] == "C1"
    assert evidence[0]["source_id"] == "PMID:40533463"
    assert len(response["claim_evidence"]) == 1


def test_agent_evidence_normalizer_expands_top_level_source_ids():
    from biomdt.runner import _extract_agent_evidence

    evidence = _extract_agent_evidence({"evidence": [{
        "claim_id": "C1", "subject": "SHMT2", "relation": "affects",
        "object": "tracer labeling", "source_ids": ["PMID:43078003", "PMID:43060637"],
        "observation": "The studies report different models.",
    }]})

    assert [row["source_id"] for row in evidence] == [
        "PMID:43078003", "PMID:43060637"
    ]


def test_agent_evidence_normalizer_accepts_logged_fact_interpretation_contract():
    from biomdt.runner import _extract_agent_evidence

    response = {"evidence": [{
        "claim_id": "C1", "subject": "ERBB2", "subject_type": "Gene",
        "relation": "encodes", "object": "ERBB2 protein", "object_type": "Protein",
        "source_id": "P04626", "evidence_status": "fact", "supports_claim": True,
        "interpretation": "UniProt identifies ERBB2 as encoding this protein.",
        "context": {"disease": "", "mismatch": ""},
    }]}

    evidence = _extract_agent_evidence(response)[0]

    assert evidence["raw_evidence"].startswith("UniProt identifies")
    assert evidence["stance"] == "supports"


def test_agent_evidence_normalizer_accepts_evidence_string_from_real_agent_output():
    from biomdt.runner import _extract_agent_evidence

    evidence = _extract_agent_evidence({"evidence": [{
        "claim_id": "C1", "subject": "ERBB2", "relation": "encodes",
        "object": "ERBB2 protein", "source_id": "P04626",
        "fact_or_inference": "fact", "evidence": "UniProt describes ERBB2.",
    }]})[0]

    assert evidence["raw_evidence"] == "UniProt describes ERBB2."


def test_agent_evidence_normalizer_keeps_limitation_note_for_insufficient_database_fact():
    from biomdt.runner import _extract_agent_evidence

    evidence = _extract_agent_evidence({"evidence": [{
        "claim_id": "C1", "subject": "SHMT2", "relation": "is_identified_as",
        "object": "protein", "source_id": "hsa:6472", "supports_claim": False,
        "evidence_type": "fact", "note": "The record identifies the gene only.",
    }]})[0]

    assert evidence["raw_evidence"] == "The record identifies the gene only."
    assert evidence["stance"] == "insufficient"


def test_integration_accepts_real_retrieved_record_identifier_and_context_mismatch():
    from biomdt.runner import integrate_agent_response
    from biomdt.graph import EvidenceGraph
    from biomdt.entity_index import BiomedicalEntityIndex

    response = {"evidence": [{
        "claim_id": "C1", "subject": "ERBB2", "subject_type": "Gene",
        "relation": "encodes", "object": "ERBB2 protein", "object_type": "Protein",
        "source_id": "P04626", "evidence_status": "fact", "supports_claim": True,
        "interpretation": "UniProt identifies ERBB2 as encoding this protein.",
        "context": {"disease": "", "mismatch": "Not specific to TNBC."},
    }]}
    graph = EvidenceGraph()
    _, report = integrate_agent_response(
        graph, BiomedicalEntityIndex(), response,
        [{"database": "uniprot", "source_ids": ["P04626"]}], ["C1"], "genomics",
    )

    assert report["added_records"] == 1
    assert report["after_graph"]["evidence"][0]["source_id"] == "P04626"


def test_graph_integration_reports_retrieval_failure_separately_from_unlinked_evidence():
    from biomdt.runner import integrate_agent_response
    from biomdt.graph import EvidenceGraph
    from biomdt.entity_index import BiomedicalEntityIndex

    graph = EvidenceGraph()
    index = BiomedicalEntityIndex()
    response = {"claim_evidence": [{
        "claim_id": "C1", "assessment": "supported", "evidence": [{
            "subject": "CYH33", "relation": "inhibits", "object": "PI3Kalpha",
            "source_id": "PMID:40533463", "raw_evidence": "Reported in HNSCC cells.",
        }],
    }]}
    no_retrieval = integrate_agent_response(
        graph, index, response, [], ["C1"], "literature"
    )[1]

    mismatched_source = integrate_agent_response(
        graph, index, response,
        [{"source_ids": ["PMID:40533463"], "error": "PubMed request failed"}],
        ["C1"], "literature",
    )[1]

    assert no_retrieval["added_records"] == 0
    assert no_retrieval["rejected_records"] == {"source_not_retrieved": 1}
    assert mismatched_source["added_records"] == 1


def test_run_entrypoint_uses_phase_specific_default_output_directory():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("scripts/run_biomdt.py").read_text(encoding="utf-8"))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and getattr(node.func, "attr", None) == "add_argument"
                   and node.args and isinstance(node.args[0], ast.Constant)
                   and node.args[0].value == "--output-dir"]

    assert assignments
    default = next(keyword.value for keyword in assignments[0].keywords if keyword.arg == "default")
    assert "phase2_1" in ast.unparse(default)


def test_deepevidence_budget_profiles_distinguish_author_default_and_project_cap():
    from run_deepevidence import budget_profile

    assert budget_profile("author") == {
        "main_search_rounds_budget": 5,
        "main_action_rounds_budget": 20,
        "subagent_action_rounds_budget": 5,
    }
    assert budget_profile("project") == {
        "main_search_rounds_budget": 1,
        "main_action_rounds_budget": 5,
        "subagent_action_rounds_budget": 3,
    }


def test_cli_output_schema_is_strict_and_covers_claim_and_evidence_fields():
    assert OUTPUT_SCHEMA["additionalProperties"] is False
    assert "claims" in OUTPUT_SCHEMA["required"]
    assert "claim_id" in OUTPUT_SCHEMA["properties"]["claims"]["items"]["properties"]
    assert "source_id" in OUTPUT_SCHEMA["properties"]["evidence"]["items"]["properties"]


def test_backend_stops_before_model_call_when_cli_is_not_logged_in(tmp_path):
    backend = object.__new__(CodexCliBackend)
    backend.executable = "/opt/codex"
    backend.model = None
    backend.reasoning_effort = "low"
    backend.timeout = 10
    backend.cwd = tmp_path
    backend.schema_path = tmp_path / "schema.json"
    backend.calls = []
    backend.session_ids = {}
    with patch("biomdt.backend.subprocess.run", return_value=CompletedProcess(
        args=["codex", "login", "status"], returncode=0, stdout="Not logged in\n", stderr=""
    )) as run:
        try:
            backend.complete("direct", "answer", {"question": "q"})
        except RuntimeError as error:
            assert "not logged in" in str(error).lower()
        else:
            raise AssertionError("An unauthenticated CLI must not start an inference request")
    assert run.call_args.args[0] == ["/opt/codex", "login", "status"]


def test_openai_compatible_backend_sends_schema_prompt_and_records_usage():
    backend = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    backend.api_key = "test-key"
    backend.base_url = "https://api.example.test"
    backend.model = "test-model"
    backend.timeout = 30
    backend.reasoning_effort = "low"
    backend.calls = []

    response = {
        "choices": [{"message": {"content": '{"selected_options":["A"]}'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132},
    }
    with patch("biomdt.backend.urlopen") as urlopen:
        from io import BytesIO
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps(response).encode()
        urlopen.return_value = Response()
        result = backend.complete("direct", "system instructions", {"question": "q"})

    request = urlopen.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.example.test/v1/chat/completions"
    assert body["model"] == "test-model"
    assert body["reasoning_effort"] == "low"
    assert body["response_format"] == {"type": "json_object"}
    assert result["selected_options"] == ["A"]
    assert backend.calls[0]["input_tokens"] == 120
    assert backend.calls[0]["output_tokens"] == 12
    assert request.get_header("Authorization") == "Bearer test-key"
    assert request.get_header("User-agent") == "OpenAI/Python BioMDT/1.0"


def test_openai_compatible_backend_uses_strict_json_schema_when_requested():
    backend = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    backend.api_key = "test-key"
    backend.base_url = "https://api.example.test"
    backend.model = "test-model"
    backend.timeout = 30
    backend.reasoning_effort = "low"
    backend.calls = []
    response = {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {}}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    with patch("biomdt.backend.urlopen") as urlopen:
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode()
        urlopen.return_value = Response()
        result = backend.complete("test", "Return JSON", {}, output_schema=schema)

    body = json.loads(urlopen.call_args.args[0].data)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert result["ok"] is True


def test_openai_compatible_backend_parses_native_tool_calls():
    backend = OpenAICompatibleBackend.__new__(OpenAICompatibleBackend)
    backend.api_key = "test-key"
    backend.base_url = "https://api.example.test"
    backend.model = "test-model"
    backend.timeout = 30
    backend.reasoning_effort = "low"
    backend.calls = []
    response = {
        "model": "test-model",
        "choices": [{"message": {"content": "", "tool_calls": [{
            "id": "call_1", "type": "function", "function": {
                "name": "search_papers", "arguments": '{"query":"CYH33"}',
            },
        }]}}],
        "usage": {"prompt_tokens": 55, "completion_tokens": 8, "total_tokens": 63},
    }
    with patch("biomdt.backend.urlopen") as urlopen:
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode()
        urlopen.return_value = Response()
        result = backend.complete_with_tools(
            "DFRS", [{"role": "user", "content": "Find CYH33 papers"}],
            [{"type": "function", "function": {"name": "search_papers",
              "description": "Search PubMed", "parameters": {"type": "object",
              "properties": {"query": {"type": "string"}}, "required": ["query"],
              "additionalProperties": False}}}],
        )

    body = json.loads(urlopen.call_args.args[0].data)
    assert body["tools"][0]["function"]["name"] == "search_papers"
    assert result["tool_calls"][0]["args"] == {"query": "CYH33"}
    assert backend.calls[0]["input_tokens"] == 55


def test_runner_accepts_only_model_input_fields():
    from biomdt.runner import validate_model_input

    row = {
        "id": "pilot_1",
        "task_type": "moa_pathway_reasoning",
        "question": "Which mechanism is correct?",
        "options": ["A. One", "B. Two"],
    }
    assert validate_model_input(row) == row
    try:
        validate_model_input(row | {"answers": ["A"]})
    except ValueError as error:
        assert "reference" in str(error).lower()
    else:
        raise AssertionError("Reference fields must be rejected before inference")


class StubBackend:
    model = "stub-model"
    cli_version = "test"

    def __init__(self):
        self.calls = []

    def complete(self, role, instructions, payload, reuse_session=False):
        self.calls.append({"role": role, "reuse_session": reuse_session})
        if role == "coordinator" and payload.get("stage") == "select_follow_up":
            return {"follow_up_roles": ["literature"]}
        if role == "coordinator":
            return {
                "claims": [{
                    "option": "A", "text": "BRCA1 is relevant to the mechanism.",
                    "operator": "AND", "required_evidence_types": ["genomics"],
                    "context": {"disease": "breast cancer"},
                }],
                "entities": {"genes": ["BRCA1"], "diseases": ["breast cancer"]},
            }
        if role == "genomics":
            return {"evidence": [{
        "claim_id": "C001", "subject": "BRCA1", "subject_type": "Gene",
        "relation": "has_function", "object": "DNA repair",
        "object_type": "BiologicalProcess", "stance": "supports", "context": {},
                "directness": "indirect", "source_id": "ENSG00000012048",
                "raw_evidence": "BRCA1 has a DNA repair function.",
            }]}
        if role == "literature":
            return {"evidence": [{
        "claim_id": "C001", "subject": "BRCA1", "subject_type": "Gene",
        "relation": "supports", "object": "mechanistic relevance",
        "object_type": "BiomedicalEntity", "stance": "supports",
                "context": {"disease": "breast cancer"}, "directness": "direct",
                "source_id": "PMID:12345", "raw_evidence": "Study reports the mechanism.",
            }]}
        if role == "decision":
            return {"selected_options": ["A"], "explanation": "Supported by E0002.",
                    "biology": "BRCA1 is involved in DNA repair."}
        if role == "direct":
            return {"selected_options": ["A"], "explanation": "Direct baseline."}
        raise AssertionError(role)


class StubTools:
    def __init__(self):
        self.calls = []

    def retrieve(self, role, entities, claims):
        source_id = "ENSG00000012048" if role == "genomics" else "PMID:12345"
        result = {"agent": role, "records": [{"summary": "evidence"}],
                  "source_ids": [source_id], "status": 200}
        self.calls.append({"agent": role, "source_ids": [source_id]})
        return [result]


def test_runner_dispatches_literature_for_an_indirect_evidence_gap():
    backend = StubBackend()
    tools = StubTools()
    result = BioMDTRunner(backend, tools).run({
        "id": "pilot_test", "task_type": "target_identification",
        "question": "What is the role of BRCA1 in breast cancer?",
        "options": ["A. BRCA1 is relevant.", "B. No relationship."],
    })

    assert result["prediction"] == ["A"]
    assert result["option_states"]["A"]["status"] == "Supported"
    assert [call["agent"] for call in tools.calls] == ["genomics", "literature"]
    assert any(event["event"] == "gap_driven_follow_up" for event in result["events"])
    assert len(result["evidence_graph"]["edges"]) >= 5
    assert "Gene:BRCA1" in {node["id"] for node in result["evidence_graph"]["nodes"]}
    assert "answers" not in result


def test_runner_saves_graph_state_before_and_after_evidence_writes():
    backend = StubBackend()
    result = BioMDTRunner(backend, StubTools(), max_collaboration_rounds=1).run({
        "id": "pilot_test", "task_type": "target_identification",
        "question": "What is the role of BRCA1 in breast cancer?",
        "options": ["A. BRCA1 is relevant.", "B. No relationship."],
    })

    snapshots = result["graph_snapshots"]
    assert snapshots[0]["stage"] == "before_evidence"
    assert snapshots[0]["graph"]["evidence"] == []
    assert snapshots[-1]["stage"] == "after_evidence"
    assert snapshots[-1]["graph"]["evidence"]
    assert result["prediction_status"] == "completed"


def test_agent_response_integration_reports_retrieval_parse_source_and_graph_states():
    graph = EvidenceGraph()
    graph.add_claim({"claim_id": "C001", "option": "A", "text": "Drug targets protein",
                     "operator": "AND", "required_evidence_types": ["literature"]})
    entities = __import__("biomdt.entity_index", fromlist=["BiomedicalEntityIndex"]).BiomedicalEntityIndex()
    response = {"claim_evidence": [{
        "claim_id": "C001", "subject": "Drug X", "subject_type": "Drug",
        "predicate": "targets", "object": "Protein Y", "object_type": "Protein",
        "observation": "Study observed target binding.", "evidence_type": "Direct experiment",
        "source_id": "PMID:123", "evidence_status": "supported",
    }, {
        "claim_id": "C001", "subject": "Drug X", "predicate": "activates",
        "object": "Protein Y", "observation": "Unsupported source observation.",
        "source_id": "PMID:999",
    }]}
    retrieved = [{"database": "pubmed", "operation": "fetch",
                  "source_ids": ["PMID:123"], "records": [{"id": "123"}]}]

    before, result = integrate_agent_response(graph, entities, response, retrieved,
                                              ["C001"], "literature")

    assert before["evidence"] == []
    assert result["parsed_records"] == 2
    assert result["added_records"] == 1
    assert result["rejected_records"] == {"source_not_retrieved": 1}
    assert result["after_graph"]["evidence"][0]["source_id"] == "PMID:123"
    assert any(edge["type"] == "derived_from" for edge in result["after_graph"]["edges"])


def test_runner_builds_provenance_edges_from_claim_evidence_response_format():
    class Backend:
        model = "stub-model"
        cli_version = "test"

        def __init__(self):
            self.calls = []

        def complete(self, role, instructions, payload, reuse_session=False):
            self.calls.append({"role": role, "input_tokens": 1, "output_tokens": 1,
                               "total_tokens": 2})
            if role == "coordinator":
                return {"claims": [{"claim_id": "orig1", "option": "A",
                                     "text": "CYH33 inhibits PI3K alpha",
                                     "required_evidence_types": ["literature"],
                                     "context": {}}],
                        "entities": {}}
            if role in {"drug", "literature"}:
                return {"claim_evidence": [{
                    "claim_id": "C001", "subject": "CYH33", "subject_type": "Drug",
                    "predicate": "inhibits", "object": "PI3K alpha", "object_type": "Protein",
                    "observation": "A PubMed review identifies CYH33 as a PI3Kalpha inhibitor.",
                    "evidence_type": "Review statement", "relevance": "Directly supports the target relation.",
                    "source_id": "PMID:42939506",
                }]}
            if role == "decision":
                return {"selected_options": ["A"], "explanation": "Supported by E0001.",
                        "biology": "CYH33 is a PI3Kalpha inhibitor."}
            raise AssertionError(role)

    class Tools:
        calls = []

        def retrieve(self, role, entities, claims):
            return [{"agent": role, "records": [{"id": "PMID:42939506"}],
                     "source_ids": ["PMID:42939506"], "status": 200}]

    result = BioMDTRunner(Backend(), Tools(), max_collaboration_rounds=1).run({
        "id": "schema_test", "task_type": "moa_pathway_reasoning",
        "question": "Which mechanism is supported?",
        "options": ["A. CYH33 inhibits PI3K alpha.", "B. No mechanism."],
    })

    assert result["prediction"] == ["A"]
    assert len(result["evidence_graph"]["evidence"]) == 1
    assert any(edge["type"] == "derived_from" for edge in result["evidence_graph"]["edges"])
    assert any(edge["type"] == "supports" for edge in result["evidence_graph"]["edges"])


def test_direct_runner_does_not_receive_external_tool_results():
    backend = StubBackend()
    result = DirectLLMRunner(backend).run({
        "id": "direct_test", "task_type": "target_identification",
        "question": "Choose an answer.", "options": ["A. Yes", "B. No"],
    })

    assert result["prediction"] == ["A"]
    assert backend.calls == [{"role": "direct", "reuse_session": False}]
    assert result["runtime"]["tool_call_count"] == 0


def test_agent_nested_claim_evidence_is_normalized_into_graph_records():
    response = {"claims": [{
        "claim_id": "C001", "relationship_to_claim": "partial_support",
        "source_id": "PMID:42939506", "subject": "CYH33", "subject_type": "Drug",
        "predicate": "inhibits", "object": "PI3K alpha", "object_type": "Protein",
        "observation": "Review describes selective inhibition.",
        "evidence_type": "Review statement; indirect evidence",
        "disease_tissue_model": "Tumor treatment context",
        "readout": "Target inhibition", "direction": "inhibition",
        "comparator": "Not reported",
    }]}
    evidence = _extract_agent_evidence(response)

    assert evidence[0]["stance"] == "insufficient"
    assert evidence[0]["relation"] == "inhibits"
    assert evidence[0]["raw_evidence"] == "Review describes selective inhibition."
    assert evidence[0]["directness"] == "indirect"
    assert evidence[0]["source_id"] == "PMID:42939506"


def test_insufficient_evidence_is_recorded_without_counting_as_refutation():
    evidence = _extract_agent_evidence({"results": [{
        "claim_id": "C001", "evidence_status": "insufficient_evidence",
        "source_id": "PMID:42939506", "subject": "CYH33", "subject_type": "Drug",
        "predicate": "does_not_report", "object": "AKT phosphorylation",
        "object_type": "ExperimentalObservation",
        "observation": "The supplied abstract does not report the measurement.",
        "direct_observation": False,
    }]})

    assert evidence[0]["stance"] == "insufficient"
    assert evidence[0]["directness"] == "indirect"


def test_claims_with_conjunctive_or_causal_statements_get_atomicity_review():
    assert requires_atomic_refinement([
        {"text": "Drug blocks ERK phosphorylation and involves SHP2."},
    ])
    assert requires_atomic_refinement([
        {"text": "Drug inhibits PI3K, leading to reduced AKT phosphorylation."},
    ])
    assert not requires_atomic_refinement([
        {"text": "Drug inhibits PI3K alpha."},
    ])


def test_compound_claims_split_into_option_preserving_atomic_claims():
    claims = refine_compound_claims([
        {"claim_id": "C1", "option": "C", "text": "CYH33 blocks ERK phosphorylation, and SHP2 is involved in the mechanism", "operator": "AND"},
        {"claim_id": "C2", "option": "A", "text": "CYH33 inhibits PI3Kα, leading to reduced AKT phosphorylation.", "operator": "AND"},
    ])

    assert [claim["text"] for claim in claims[:2]] == [
        "CYH33 blocks ERK phosphorylation",
        "SHP2 is involved in the mechanism",
    ]
    assert all(claim["option"] == "C" for claim in claims[:2])
    assert claims[0]["claim_id"] != claims[1]["claim_id"]


def test_partial_or_context_mismatched_observation_is_not_full_claim_support():
    partial = _extract_agent_evidence({"claims": [{
        "claim_id": "C1", "assessment": "Partial support for the target, but the full claim is not established.",
        "subject": "Drug", "predicate": "inhibits", "object": "Target",
        "experimental_observation": "The target effect is described.", "source_id": "PMID:1",
    }]})
    mismatched = _extract_agent_evidence({"claims": [{
        "claim_id": "C2", "assessment": "Evidence is from a different disease/model and intervention.",
        "subject": "Drug", "predicate": "increases", "object": "CD8 cells",
        "experimental_observation": "Combination in another cancer.", "source_id": "PMID:2",
    }]})

    assert partial[0]["stance"] == "insufficient"
    assert mismatched[0]["stance"] == "insufficient"
    assert mismatched[0]["context_match"] is False


def test_context_match_explanation_is_normalized_to_boolean():
    evidence = _extract_agent_evidence({"claims": [{
        "claim_id": "C1", "assessment": "mismatched evidence",
        "subject": "Drug", "predicate": "increases", "object": "CD8 cells",
        "experimental_observation": "Combination result.", "source_id": "PMID:2",
        "context_match": "Mismatched: ovarian model, not HNSCC.",
    }]})

    assert evidence[0]["context_match"] is False


def test_reported_non_target_disease_context_is_nonapplicable():
    evidence = _extract_agent_evidence({"claims": [{
        "claim_id": "C1", "evidence_status": "supported",
        "subject": "CYH33", "predicate": "increases", "object": "CD8 cells",
        "experimental_observation": "Combination result.", "source_id": "PMID:2",
        "disease_tissue_model": "ID8 ovarian cancer, not HNSCC.",
    }]})

    assert evidence[0]["context_match"] is False


def test_claim_evidence_response_uses_relevance_to_assess_context_and_partial_support():
    evidence = _extract_agent_evidence({"claim_evidence": [{
        "claim_id": "C1", "subject": "CYH33", "predicate": "selectively inhibits",
        "object": "PI3K alpha", "observation": "Review describes target selectivity.",
        "evidence_type": "Literature description",
        "relevance": "Supports the target mechanism generally, but does not establish the observation in HNSCC.",
        "disease_tissue_model": "Ovarian cancer, not HNSCC.", "source_id": "PMID:1",
    }]})

    assert evidence[0]["stance"] == "insufficient"
    assert evidence[0]["context_match"] is False


def test_context_mismatch_is_kept_as_nonapplicable_evidence():
    graph = EvidenceGraph()
    graph.add_claim({"claim_id": "C1", "option": "A", "text": "Claim",
                     "operator": "AND", "required_evidence_types": ["literature"],
                     "context": {"disease": "HNSCC"}})
    graph.add_evidence({
        "claim_id": "C1", "subject": "CYH33", "relation": "enhances",
        "object": "CD8 infiltration", "stance": "insufficient", "context_match": False,
        "context": {"reported_context": "ID8 ovarian cancer, combination treatment"},
        "directness": "direct", "source_id": "PMID:42",
        "raw_evidence": "Combination result in ovarian cancer.",
    })

    state = graph.recompute()["C1"]
    assert state["status"] == "Missing"
    assert state["context_mismatches"] == 1


def test_extract_agent_evidence_expands_source_ids_and_preserves_partial_support():
    evidence = _extract_agent_evidence({"claims": [{
        "claim_id": "C001", "option": "A", "assessment": "partial_support",
        "subject": "CYH33", "subject_type": "Drug", "predicate": "inhibits",
        "object": "PI3K alpha", "object_type": "Protein",
        "experimental_observation": "Review calls CYH33 a PI3Kalpha inhibitor.",
        "evidence_type": "Review; indirect", "source_ids": ["PMID:1", "PMID:2"],
    }]})

    assert [row["source_id"] for row in evidence] == ["PMID:1", "PMID:2"]
    assert all(row["stance"] == "insufficient" for row in evidence)
    assert all(row["raw_evidence"] == "Review calls CYH33 a PI3Kalpha inhibitor." for row in evidence)


def test_only_explicit_experimental_refutation_becomes_contradicting_evidence():
    evidence = _extract_agent_evidence({"claims": [{
        "claim_id": "C001", "assessment": "explicitly_contradicted",
        "subject": "CYH33", "predicate": "increases", "object": "MHC-I",
        "experimental_observation": "The assay measured no increase versus vehicle.",
        "source_id": "PMID:8", "evidence_type": "Direct observation",
    }]})

    assert evidence[0]["stance"] == "contradicts"


def test_atomicity_audit_gateway_timeout_keeps_first_plan():
    from urllib.error import HTTPError

    class GatewayTimeoutBackend(StubBackend):
        def complete(self, role, instructions, payload, reuse_session=False):
            if "claims_to_audit" in payload:
                raise HTTPError("https://api.example.test", 524, "gateway timeout", {}, None)
            return super().complete(role, instructions, payload, reuse_session)

    result = BioMDTRunner(GatewayTimeoutBackend(), StubTools()).run({
        "id": "audit_timeout",
        "task_type": "target_identification",
        "question": "Which option is supported?",
        "options": ["A. BRCA1 and DNA repair are related."],
    })

    assert result["prediction"] == ["A"]
    assert any(event["event"] == "coordinator_atomicity_audit_unavailable"
               for event in result["events"])
    assert result["evidence_graph"]["evidence"]


def test_graph_uses_typed_context_before_duplicate_flat_fields():
    graph = EvidenceGraph()
    graph.add_claim({"claim_id": "C1", "option": "A", "text": "Inhibits a target",
                     "context": {"disease": "head and neck squamous cell carcinoma (HNSCC)"}})
    graph.add_evidence({"claim_id": "C1", "source_id": "PMID:1", "stance": "supports",
                        "disease": "HNSCC",
                        "context": {"disease": "head and neck squamous cell carcinoma (HNSCC)"}})
    assert graph.recompute()["C1"]["status"] == "Supported"


def test_context_matches_equivalent_readouts_and_control_descriptions():
    from biomdt.graph import contexts_match

    expected = {"disease": "head and neck squamous cell carcinoma (HNSCC)",
                "readout": "AKT phosphorylation", "comparison": "reduced versus control or baseline"}
    assert contexts_match(expected, {"disease": "HNSCC", "readout": "phosphorylated Akt",
                                     "comparison": "reduced versus control"})
    assert not contexts_match(expected, {"disease": "HNSCC", "readout": "ERK phosphorylation"})
    assert not contexts_match(expected, {"disease": "HNSCC", "readout": "AKT phosphorylation",
                                         "comparison": "versus another drug"})


def test_answer_cardinality_recognizes_an_interrogative_with_two_requested_cohorts():
    question = "In this experiment, which two mouse cohorts show the strongest response?"
    assert "exactly two" in task_answer_instruction(question)
    assert validate_prediction_for_question(["D"], ["A", "D"], question) == ([], "invalid_prediction")
    assert validate_prediction_for_question(["A", "D"], ["A", "D"], question) == (["A", "D"], "completed")


def test_openai_completion_retries_gateway_524_once(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from unittest.mock import Mock

    backend = OpenAICompatibleBackend(api_key="test", base_url="https://api.example.test",
                                      model="test-model")
    response = BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
    urlopen = Mock(side_effect=[
        HTTPError("https://api.example.test", 524, "gateway timeout", {}, None),
        response,
    ])
    monkeypatch.setattr("biomdt.backend.urlopen", urlopen)
    assert backend.complete("literature", "Extract evidence.", {}) == {}
    assert urlopen.call_count == 2
