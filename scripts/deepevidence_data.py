"""Prepare isolated DeepEvidence inputs and score predictions with its grader."""
from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as parquet

ROOT = Path(__file__).resolve().parents[1]
TASK_FILES = {
    "target_identification": "target_identification.parquet",
    "moa_pathway_reasoning": "moa_pathway_reasoning.parquet",
    "in_vivo_metabolic_flux_response": "in_vivo_metabolic_flux_response.parquet",
}
PILOT_EXPOSED = [
    {
        "id": "target_identification_19",
        "task_type": "target_identification",
        "reason": "Question was submitted to the Codex CLI workflow; no scored answer was produced.",
        "result_file": "results/deepevidence/target_identification_19_attempt.json",
    },
    {
        "id": "preclinical_research_1",
        "task_type": "moa_pathway_reasoning",
        "reason": "Completed development smoke run through the historical DeepEvidence workflow.",
        "result_file": "results/deepevidence/preclinical_research_1.json",
    },
    {
        "id": "in_vivo_flux_response_2",
        "task_type": "in_vivo_metabolic_flux_response",
        "reason": "Completed development smoke run through the historical DeepEvidence workflow.",
        "result_file": "results/deepevidence/in_vivo_flux_response_2.json",
    },
]
OPTION_CODE = re.compile(r"^([A-Z])\.\s")
AUTHOR_GRADER_PATH = (
    ROOT
    / "data/raw/deepevidence/BioDSA-paper/scripts/harbor_bdr_grade.py"
)


def _load_author_grader():
    spec = importlib.util.spec_from_file_location(
        "deepevidence_author_grader", AUTHOR_GRADER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load official grader at {AUTHOR_GRADER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def normalize_record(
    row: dict[str, Any], task_type: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    model_input = {
        "id": str(row["id"]),
        "task_type": task_type,
        "question": row["question"],
        "options": list(row["options"]),
    }
    reference = {
        "id": str(row["id"]),
        "task_type": task_type,
        "source_task_type": row["task_type"],
        "answers": list(row["answers"]),
        "gains": list(row["gains"]),
        "rationale": row["rationale"],
    }
    if "kegg_evidence" in row:
        reference["kegg_evidence"] = row["kegg_evidence"]
    if "disease" in row:
        reference["disease"] = row["disease"]
    return model_input, reference


def _option_codes(options: list[str]) -> list[str]:
    codes = []
    for option in options:
        match = OPTION_CODE.match(option)
        if match is None:
            raise ValueError(f"Option lacks an alphabetical label: {option!r}")
        codes.append(match.group(1))
    if len(codes) != len(set(codes)):
        raise ValueError("Option labels must be unique within an item")
    return codes


def label_anomalies(
    model_inputs: list[dict[str, Any]], references: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    input_by_id = {row["id"]: row for row in model_inputs}
    anomalies = []
    for reference in references:
        model_input = input_by_id[reference["id"]]
        codes = _option_codes(model_input["options"])
        gains = reference["gains"]
        answer = reference["answers"]
        if len(gains) != len(codes):
            anomalies.append({
                "id": reference["id"],
                "task_type": reference["task_type"],
                "kind": "gain_count_mismatch",
                "answers": answer,
                "gain_2_options": None,
                "gains": gains,
            })
            continue
        gain_2 = [code for code, gain in zip(codes, gains) if gain == 2]
        if set(gain_2) != set(answer):
            anomalies.append({
                "id": reference["id"],
                "task_type": reference["task_type"],
                "kind": "answers_vs_gain_2",
                "answers": answer,
                "gain_2_options": gain_2,
            })
    return anomalies


def dataset_statistics(
    model_inputs: list[dict[str, Any]], references: list[dict[str, Any]]
) -> dict[str, Any]:
    reference_by_id = {row["id"]: row for row in references}
    by_task = {}
    for task_type in TASK_FILES:
        task_inputs = [row for row in model_inputs if row["task_type"] == task_type]
        task_references = [reference_by_id[row["id"]] for row in task_inputs]
        options = Counter(len(row["options"]) for row in task_inputs)
        answers = Counter(len(row["answers"]) for row in task_references)
        diseases = Counter(
            str(row.get("disease")).strip()
            for row in task_references
            if row.get("disease")
        )
        target_gene_ids = Counter()
        pathways = Counter()
        biological_processes = Counter()
        for reference in task_references:
            evidence = reference.get("kegg_evidence")
            if not isinstance(evidence, dict):
                continue
            target_gene_ids.update(evidence.get("target_gene_ids", []))
            pathways.update(evidence.get("pathways", []))
            biological_processes.update(evidence.get("biological_processes", []))
        source_task_types = Counter(row["source_task_type"] for row in task_references)
        by_task[task_type] = {
            "sample_count": len(task_inputs),
            "source_task_type_counts": dict(sorted(source_task_types.items())),
            "answer_cardinality": dict(sorted(answers.items())),
            "option_count": dict(sorted(options.items())),
            "disease_field_counts": dict(sorted(diseases.items())),
            "disease_field_unique_casefolded": len({name.casefold() for name in diseases}),
            "kegg_target_gene_id_counts": dict(sorted(target_gene_ids.items())),
            "kegg_target_gene_id_unique": len(target_gene_ids),
            "kegg_pathway_counts": dict(sorted(pathways.items())),
            "kegg_pathway_unique": len(pathways),
            "kegg_biological_process_counts": dict(sorted(biological_processes.items())),
            "kegg_biological_process_unique": len(biological_processes),
        }
    return {
        "total_records": len(model_inputs),
        "task_count": len(by_task),
        "by_task": by_task,
    }


def prepare_official_data(
    raw_dir: Path = ROOT / "data/raw/deepevidence",
    output_dir: Path = ROOT / "data/processed/deepevidence",
) -> dict[str, Any]:
    model_inputs = []
    references = []
    for task_type, filename in TASK_FILES.items():
        rows = parquet.read_table(raw_dir / filename).to_pylist()
        for row in rows:
            model_input, reference = normalize_record(row, task_type)
            model_inputs.append(model_input)
            references.append(reference)

    anomalies = label_anomalies(model_inputs, references)
    stats = dataset_statistics(model_inputs, references)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "test_inputs.jsonl", model_inputs)
    write_jsonl(output_dir / "references.jsonl", references)
    (output_dir / "label_anomalies.json").write_text(
        json.dumps(anomalies, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "pilot_exposed_items.json").write_text(
        json.dumps(PILOT_EXPOSED, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return stats | {"anomaly_count": len(anomalies)}


def evaluate_predictions(
    model_inputs: list[dict[str, Any]],
    references: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    input_by_id = {row["id"]: row for row in model_inputs}
    reference_by_id = {row["id"]: row for row in references}
    if set(input_by_id) != set(reference_by_id):
        raise ValueError("Input and reference IDs must match exactly")

    parsed_predictions = {}
    duplicate_ids = []
    prediction_status_by_id = {}
    model_error_ids = []
    for row in predictions:
        item_id = row["id"]
        if item_id in parsed_predictions:
            duplicate_ids.append(item_id)
            continue
        status = row.get("prediction_status")
        if row.get("error"):
            status = "model_error"
            model_error_ids.append(item_id)
        prediction_status_by_id[item_id] = status or (
            "completed" if row.get("prediction") else "abstention"
        )
        value = row.get("prediction")
        if value is None or status in {
            "abstention", "invalid_prediction", "format_error", "model_error", "interface_error"
        }:
            continue
        selected = value if isinstance(value, list) else [value]
        parsed_predictions[item_id] = {
            "status": "completed",
            "final_answer": (
                "<BIOMED_FINAL>"
                + json.dumps({"selected_options": selected})
                + "</BIOMED_FINAL>"
            ),
        }

    grader = _load_author_grader()
    grader_references = {}
    for item_id, reference in reference_by_id.items():
        options = input_by_id[item_id]["options"]
        answer = reference["answers"]
        task_kind = "single_choice" if len(answer) == 1 else "multi_select"
        grader_references[item_id] = {
            "subset": reference["task_type"],
            "source_split": "test",
            "task_type": task_kind,
            "valid_options": _option_codes(options),
            "label": {"selected_options": answer},
        }

    rows, summary = grader.grade(
        grader_references,
        list(grader_references),
        parsed_predictions,
        duplicates=duplicate_ids,
    )
    results = []
    for row in rows:
        if row["item_id"] == "<predictions>":
            continue
        row["task_type"] = row["subset"]
        results.append(row)
    by_task = {}
    for task_type in TASK_FILES:
        task_rows = [row for row in results if row["task_type"] == task_type]
        expected = len(task_rows)
        by_task[task_type] = {
            "expected": expected,
            "missing": sum(row["status"] == "missing" for row in task_rows),
            "accuracy": (
                sum(row["score"] or 0.0 for row in task_rows) / expected
                if expected else None
            ),
        }
    return {
        "overall": {
            "expected": len(results),
            "missing": sum(row["status"] == "missing" for row in results),
            "accuracy": summary["accuracy"],
            "grading_errors": summary["grading_error"],
            "duplicate_prediction_ids": duplicate_ids,
            "abstentions": sum(value == "abstention" for value in prediction_status_by_id.values()),
            "invalid_predictions": sum(value == "invalid_prediction" for value in prediction_status_by_id.values()),
            "format_errors": sum(value == "format_error" for value in prediction_status_by_id.values()),
            "interface_errors": sum(value == "interface_error" for value in prediction_status_by_id.values()),
            "model_errors": len(model_error_ids) + sum(value == "model_error" for value in prediction_status_by_id.values() if value != "model_error"),
            "completed_predictions": sum(value == "completed" for value in prediction_status_by_id.values()),
            "unsubmitted_predictions": len(input_by_id) - len(prediction_status_by_id),
        },
        "by_task": by_task,
        "items": results,
    }
