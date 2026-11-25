import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from deepevidence_data import (
    evaluate_predictions,
    normalize_record,
    prepare_official_data,
)


def sample_record():
    return {
        "id": "example_1",
        "task_type": "preclinical_research",
        "question": "Which findings are supported?",
        "options": ["A. Target A is inhibited.", "B. Target B is activated."],
        "answers": ["A"],
        "gains": [2, 0],
        "rationale": "The assay directly measured the target.",
    }


def test_normalized_inputs_do_not_contain_reference_fields():
    model_input, reference = normalize_record(
        sample_record(), "moa_pathway_reasoning"
    )

    assert model_input == {
        "id": "example_1",
        "task_type": "moa_pathway_reasoning",
        "question": "Which findings are supported?",
        "options": ["A. Target A is inhibited.", "B. Target B is activated."],
    }
    assert reference["answers"] == ["A"]
    assert reference["source_task_type"] == "preclinical_research"
    assert "answers" not in model_input
    assert "rationale" not in model_input


def test_evaluator_handles_single_and_multiselect_exact_match():
    inputs = [
        {
            "id": "single",
            "task_type": "target_identification",
            "question": "Select a target.",
            "options": ["A. One", "B. Two"],
        },
        {
            "id": "multiple",
            "task_type": "moa_pathway_reasoning",
            "question": "Select mechanisms.",
            "options": ["A. One", "B. Two", "C. Three"],
        },
    ]
    references = [
        {
            "id": "single",
            "task_type": "target_identification",
            "answers": ["A"],
        },
        {
            "id": "multiple",
            "task_type": "moa_pathway_reasoning",
            "answers": ["A", "C"],
        },
    ]
    predictions = [
        {"id": "single", "prediction": ["A"]},
        {"id": "multiple", "prediction": ["C", "A"]},
    ]

    result = evaluate_predictions(inputs, references, predictions)

    assert result["overall"]["accuracy"] == 1.0
    assert result["by_task"]["target_identification"]["accuracy"] == 1.0
    assert result["by_task"]["moa_pathway_reasoning"]["accuracy"] == 1.0


def test_evaluator_scores_missing_invalid_and_multiselect_errors_as_zero():
    inputs = [
        {
            "id": "single",
            "task_type": "target_identification",
            "question": "Select a target.",
            "options": ["A. One", "B. Two"],
        },
        {
            "id": "missing_option",
            "task_type": "moa_pathway_reasoning",
            "question": "Select mechanisms.",
            "options": ["A. One", "B. Two", "C. Three"],
        },
        {
            "id": "extra_option",
            "task_type": "in_vivo_metabolic_flux_response",
            "question": "Select cohorts.",
            "options": ["A. One", "B. Two", "C. Three"],
        },
        {
            "id": "invalid_option",
            "task_type": "target_identification",
            "question": "Select a target.",
            "options": ["A. One", "B. Two"],
        },
    ]
    references = [
        {
            "id": "single",
            "task_type": "target_identification",
            "answers": ["A"],
        },
        {
            "id": "missing_option",
            "task_type": "moa_pathway_reasoning",
            "answers": ["A", "C"],
        },
        {
            "id": "extra_option",
            "task_type": "in_vivo_metabolic_flux_response",
            "answers": ["A", "C"],
        },
        {
            "id": "invalid_option",
            "task_type": "target_identification",
            "answers": ["A"],
        },
    ]
    predictions = [
        {"id": "single", "prediction": ["B"]},
        {"id": "missing_option", "prediction": ["A"]},
        {"id": "extra_option", "prediction": ["A", "B", "C"]},
        {"id": "invalid_option", "prediction": ["Z"]},
    ]

    result = evaluate_predictions(inputs, references, predictions)

    assert result["overall"]["accuracy"] == 0.0
    assert all(row["score"] == 0.0 for row in result["items"])


def test_evaluator_keeps_missing_predictions_in_the_denominator():
    inputs = [
        {
            "id": "present",
            "task_type": "target_identification",
            "question": "Select a target.",
            "options": ["A. One", "B. Two"],
        },
        {
            "id": "missing",
            "task_type": "target_identification",
            "question": "Select a target.",
            "options": ["A. One", "B. Two"],
        },
    ]
    references = [
        {
            "id": "present",
            "task_type": "target_identification",
            "answers": ["A"],
        },
        {
            "id": "missing",
            "task_type": "target_identification",
            "answers": ["B"],
        },
    ]

    result = evaluate_predictions(
        inputs,
        references,
        [
            {"id": "present", "prediction": ["A"]},
            {"id": "missing", "prediction": None},
        ],
    )

    assert result["overall"]["accuracy"] == 0.5
    assert result["overall"]["missing"] == 1


def test_evaluator_reports_abstentions_invalid_outputs_and_completed_errors_separately():
    inputs = [{"id": item_id, "task_type": "moa_pathway_reasoning", "question": "q",
               "options": ["A. One", "B. Two"]}
              for item_id in ("abstain", "invalid", "completed")]
    references = [{"id": item_id, "task_type": "moa_pathway_reasoning", "answers": ["A"]}
                  for item_id in ("abstain", "invalid", "completed")]
    predictions = [
        {"id": "abstain", "prediction": [], "prediction_status": "abstention"},
        {"id": "invalid", "prediction": [], "prediction_status": "invalid_prediction"},
        {"id": "completed", "prediction": ["B"], "prediction_status": "completed"},
    ]

    result = evaluate_predictions(inputs, references, predictions)

    assert result["overall"]["abstentions"] == 1
    assert result["overall"]["invalid_predictions"] == 1
    assert result["overall"]["completed_predictions"] == 1
    assert result["overall"]["model_errors"] == 0


def test_evaluator_separates_format_errors_and_model_failures_from_wrong_answers():
    inputs = [{"id": item_id, "task_type": "target_identification", "question": "q",
               "options": ["A. One", "B. Two"]}
              for item_id in ("format", "model_error", "wrong")]
    references = [{"id": item_id, "task_type": "target_identification", "answers": ["A"]}
                  for item_id in ("format", "model_error", "wrong")]
    predictions = [
        {"id": "format", "prediction": None, "prediction_status": "format_error"},
        {"id": "model_error", "prediction": None, "prediction_status": "model_error",
         "error": "API failed"},
        {"id": "wrong", "prediction": ["B"], "prediction_status": "completed"},
    ]

    result = evaluate_predictions(inputs, references, predictions)

    assert result["overall"]["format_errors"] == 1
    assert result["overall"]["model_errors"] == 1
    assert result["overall"]["accuracy"] == 0.0


def test_prepare_writes_disjoint_inputs_references_and_six_anomalies(tmp_path):
    raw_dir = Path("data/raw/deepevidence")
    result = prepare_official_data(raw_dir, tmp_path)
    inputs = [
        json.loads(line)
        for line in (tmp_path / "test_inputs.jsonl").read_text().splitlines()
    ]
    references = [
        json.loads(line)
        for line in (tmp_path / "references.jsonl").read_text().splitlines()
    ]

    assert result["total_records"] == 75
    assert len(inputs) == len(references) == 75
    assert not any({"answers", "gains", "rationale", "kegg_evidence"} & row.keys()
                   for row in inputs)
    assert len(json.loads((tmp_path / "label_anomalies.json").read_text())) == 6
    exposed = json.loads((tmp_path / "pilot_exposed_items.json").read_text())
    assert {row["id"] for row in exposed} == {
        "target_identification_19",
        "preclinical_research_1",
        "in_vivo_flux_response_2",
    }
