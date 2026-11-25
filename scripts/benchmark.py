"""Run or summarize a frozen DeepEvidence benchmark selection."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from shutil import copyfile
import sys
from time import monotonic

from biomdt.runner import validate_model_input
from deepevidence_data import ROOT, TASK_FILES, PILOT_EXPOSED, read_jsonl

METHODS = ("direct", "deepevidence", "biomdt")
DATA = ROOT / "data/processed/deepevidence"


def select_cases(rows, mode, ids, task, limit, exposed):
    if mode == "smoke":
        ids = ["preclinical_research_1"]
    elif mode == "pilot":
        ids = sorted(exposed)
    if mode == "single-task" and not task:
        raise ValueError("single-task requires --task")
    if mode == "custom" and not (ids or task or limit):
        raise ValueError("custom requires a selection")
    if set(ids) - {row["id"] for row in rows}:
        raise ValueError("Unknown item ID")
    selected = [validate_model_input(row) for row in rows
                if (not ids or row["id"] in ids) and (not task or row["task_type"] == task)]
    if not selected:
        raise ValueError("Empty selection")
    return selected[:limit] if limit else selected


def option_scores(prediction, reference):
    selected, expected = set(prediction), set(reference)
    overlap = len(selected & expected)
    return (overlap / len(selected) if selected else 0,
            overlap / len(expected) if expected else 0,
            2 * overlap / (len(selected) + len(expected)) if selected or expected else 0)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def case_result(directory, method, item):
    return directory / "cases" / method / item / "result.json"


def run_case(directory, config, row, method):
    item = row["id"]
    output = case_result(directory, method, item)
    if output.exists():
        return
    case_dir = output.parent
    case_dir.mkdir(parents=True, exist_ok=True)
    inputs = case_dir / "input.jsonl"
    inputs.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    script = "run_deepevidence.py" if method == "deepevidence" else "run_biomdt.py"
    command = [sys.executable, str(ROOT / "scripts" / script), "--inputs", str(inputs),
               "--item-id", item, "--model", config["model"], "--output-dir", str(case_dir)]
    if method == "deepevidence":
        command.extend(["--budget-profile", config["deepevidence_profile"]])
        native_result = case_dir / f"{item}_unified.json"
    else:
        command.extend(["--method", method, "--max-collaboration-rounds", str(config["biomdt_rounds"])])
        native_result = case_dir / "runs" / f"{item}-{method}.json"
    env = os.environ.copy()
    for key, value in {
        "OPENAI_REASONING_EFFORT": config["reasoning_effort"],
        "OPENAI_TEMPERATURE": config["temperature"],
        "OPENAI_BASE_URL": config["base_url"],
        "BENCHMARK_KNOWLEDGE_SCOPE": config["knowledge_scope"],
        "BENCHMARK_TIMEOUT": config["timeout_seconds"],
        "BENCHMARK_RETRIES": config["retries"],
        "BENCHMARK_MAX_MODEL_CALLS": config["max_model_calls"],
        "BENCHMARK_MAX_TOOL_CALLS": config["max_tool_calls"],
        "BENCHMARK_MAX_TOKENS": config["max_total_tokens"],
    }.items():
        env[key] = "" if value is None else str(value)
    start = monotonic()
    completed = None
    if not native_result.exists():
        with (case_dir / "process.log").open("a") as log:
            completed = subprocess.run(command, cwd=case_dir, env=env, stdout=log, stderr=log)
    if native_result.exists():
        result = json.loads(native_result.read_text())
    else:
        result = {"id": item, "task_type": row["task_type"], "method": method,
                  "prediction": None, "prediction_status": "interface_error",
                  "error": f"Worker exited with code {completed.returncode}. See process.log."}
    result["wall_seconds"] = round(monotonic() - start, 3) if completed else None
    write_json(output, result)
    print(f"{method} {item} {result['prediction_status']}", flush=True)



def freeze_method_source(directory, resume):
    scripts = ROOT / "scripts"
    files = [*sorted((scripts / "biomdt").glob("*.py")),
             *(scripts / name for name in (
                 "run_biomdt.py", "run_deepevidence.py", "deepevidence_smoke.py", "biomedical_evidence.py"
             ))]
    for source in files:
        snapshot = directory / "method_source" / source.relative_to(scripts)
        if resume:
            if not snapshot.is_file() or snapshot.read_bytes() != source.read_bytes():
                raise ValueError(f"Cannot resume with different method source: {source.name}")
        else:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            copyfile(source, snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "score", "plot"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/benchmark.json")
    parser.add_argument("--mode", choices=["smoke", "pilot", "single-task", "full", "custom"], default="smoke")
    parser.add_argument("--method", choices=METHODS, action="append")
    parser.add_argument("--task", choices=TASK_FILES)
    parser.add_argument("--item-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--format", choices=["png", "pdf", "svg"], action="append")
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    manifest = directory / "manifest.json"
    if args.action == "run":
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be positive")
        defaults = json.loads((ROOT / "configs/benchmark.json").read_text())
        supplied = json.loads(args.config.read_text())
        if set(supplied) - set(defaults):
            parser.error("Unknown config key. Supply credentials via environment variables.")
        config = defaults | supplied
        for key in ("concurrency", "timeout_seconds", "biomdt_rounds", "max_model_calls",
                    "max_tool_calls", "max_total_tokens"):
            if type(config[key]) is not int or config[key] < 1:
                parser.error(f"{key} must be a positive integer")
        if type(config["retries"]) is not int or config["retries"] < 0:
            parser.error("retries must be a nonnegative integer")
        if config["knowledge_scope"] not in {"native", "shared-literature"}:
            parser.error("Invalid knowledge_scope")
        if config["deepevidence_profile"] not in {"author", "project"}:
            parser.error("Invalid DeepEvidence budget profile")
        for key, env in (("model", "OPENAI_MODEL"), ("reasoning_effort", "OPENAI_REASONING_EFFORT")):
            if env in os.environ:
                config[key] = os.environ[env] or None
        if os.getenv("OPENAI_TEMPERATURE"):
            config["temperature"] = float(os.environ["OPENAI_TEMPERATURE"])
        config["base_url"] = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
        config["deepevidence_source"] = subprocess.check_output(
            ["git", "-C", str(ROOT / "data/raw/deepevidence/BioDSA-paper"), "rev-parse", "HEAD"], text=True
        ).strip()
        config["dataset_revision"] = "06b349b24ee18a8d5a2db3e498884d5ad9600f76"
        exposed = {row["id"] for row in PILOT_EXPOSED}
        if args.mode in {"smoke", "pilot", "full"} and (args.item_id or args.task or args.limit):
            parser.error("Use custom mode to filter a predefined selection")
        if args.mode == "single-task" and (args.item_id or args.limit):
            parser.error("Use custom mode for part of a task")
        rows = select_cases(read_jsonl(DATA / "test_inputs.jsonl"), args.mode,
                            args.item_id, args.task, args.limit, exposed)
        methods = list(dict.fromkeys(args.method or METHODS))
        plan = {"mode": args.mode, "methods": methods, "config": config,
                "cases": rows, "exposed": sorted(exposed)}
        if manifest.exists():
            if not args.resume or plan != json.loads(manifest.read_text()):
                parser.error("Existing run requires --resume and the original configuration and selection")
        if not os.getenv("OPENAI_API_KEY") and any(
            not case_result(directory, method, row["id"]).exists() for method in methods for row in rows
        ):
            parser.error("Set OPENAI_API_KEY before starting inference")
        try:
            freeze_method_source(directory, manifest.exists())
        except ValueError as error:
            parser.error(str(error))
        if not manifest.exists():
            write_json(manifest, plan)
        jobs = [(row, method) for row in rows for method in methods]
        with ThreadPoolExecutor(max_workers=config["concurrency"]) as executor:
            list(executor.map(lambda job: run_case(directory, config, *job), jobs))
    if args.action in {"run", "score"}:
        from benchmark_metrics import summarize
        summarize(directory, json.loads(manifest.read_text()))
    if args.action in {"run", "plot"}:
        from plot_benchmark import plot
        plot(directory, args.format or ["png"])


if __name__ == "__main__":
    main()
