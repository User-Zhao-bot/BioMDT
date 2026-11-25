import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark import select_cases, option_scores


def test_smoke_uses_only_the_exposed_cyh33_item():
    rows = [{"id": "other", "task_type": "target_identification"},
            {"id": "preclinical_research_1", "task_type": "moa_pathway_reasoning"}]
    for row in rows:
        row.update(question="Question?", options=["A. Answer"])

    assert select_cases(rows, "smoke", [], None, None, set()) == rows[1:]


def test_partial_multiselect_and_zero_prediction():
    assert option_scores(["A"], ["A", "B"]) == (1, 0.5, 2 / 3)
    assert option_scores([], ["A"]) == (0, 0, 0)


def test_batch_selection_counts_use_official_inputs():
    from benchmark import DATA
    from deepevidence_data import read_jsonl
    rows = read_jsonl(DATA / "test_inputs.jsonl")
    assert len(select_cases(rows, "full", [], None, None, set())) == 75
    assert len(select_cases(rows, "single-task", [], "target_identification", None, set())) == 25


def test_resume_skips_saved_failure_without_model_call(tmp_path, monkeypatch):
    from benchmark import case_result, run_case, write_json

    row = {"id": "exposed_pilot"}
    output = case_result(tmp_path, "biomdt", row["id"])
    write_json(output, {"prediction_status": "model_error"})

    def fail(*args, **kwargs):
        raise AssertionError("Saved outcome must not trigger another API call")

    monkeypatch.setattr("benchmark.subprocess.run", fail)
    run_case(tmp_path, {}, row, "biomdt")
    assert "model_error" in output.read_text()


def test_audit_distinguishes_actual_record_from_citation_string():
    from benchmark_metrics import evidence_metrics

    run = {"method": "deepevidence", "prediction_status": "completed",
           "final_response": "Supporting evidence (PMID:12345678).",
           "retrieval_log": []}
    assert evidence_metrics(run, {})["traceability"] == 0
    assert evidence_metrics(run, {})["support_rate"] is None
    run["retrieval_log"].append({"database": "pubmed", "tool": "fetch_paper_content",
                                 "tool_call_id": "call_1", "output": "Article PMID:12345678"})
    assert evidence_metrics(run, {})["traceability"] == 1
    assert evidence_metrics(run, {})["support_rate"] is None


def test_unattempted_cases_remain_in_scheduled_denominator():
    from benchmark_metrics import aggregate

    rows = [
        {"status": "correct", "exact_match": 1, "precision": 1, "recall": 1, "f1": 1, "evidence": {}},
        {"status": "not_run", "exact_match": 0, "precision": 0, "recall": 0, "f1": 0, "evidence": {}},
    ]
    report = aggregate(rows)
    assert report["expected"] == 2
    assert report["attempted"] == 1
    assert report["exact_match"] == report["coverage"] == report["f1"] == 0.5
    assert report["runtime_median"] is None


def test_citation_in_echoed_deepevidence_python_is_not_retrieved_evidence():
    from benchmark_metrics import evidence_metrics

    run = {"method": "deepevidence", "prediction_status": "completed",
           "final_response": "Supports the claim (PMID:12345678).",
           "retrieval_log": [{"database": "pubmed", "tool": "fetch_paper_content",
                              "tool_call_id": "call_1",
                              "output": "### Executed Code:\nfetch('PMID:12345678')\n"
                                        "### Output:\nNo records returned."}]}
    assert evidence_metrics(run, {})["traceability"] == 0
