"""Run BioMDT or Direct LLM on development-exposed DeepEvidence inputs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from biomdt.backend import CodexCliBackend, OpenAICompatibleBackend
from biomdt.runner import BioMDTRunner, DirectLLMRunner


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("biomdt", "direct"), default="biomdt")
    parser.add_argument("--inputs", type=Path, default=ROOT / "data/processed/deepevidence/test_inputs.jsonl")
    parser.add_argument("--item-id")
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--model")
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--backend", choices=("openai-compatible", "codex-cli"), default="openai-compatible")
    parser.add_argument("--max-collaboration-rounds", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/biomdt/phase2_1")
    args = parser.parse_args()
    rows = read_jsonl(args.inputs)
    if args.item_id:
        rows = [row for row in rows if row["id"] == args.item_id]
        if not rows:
            parser.error(f"Unknown item ID: {args.item_id}")
    elif args.pilot_only:
        exposed_path = ROOT / "data/processed/deepevidence/pilot_exposed_items.json"
        exposed_ids = {row["id"] for row in json.loads(exposed_path.read_text(encoding="utf-8"))}
        rows = [row for row in rows if row["id"] in exposed_ids][:args.limit]
    else:
        parser.error("Specify --item-id or --pilot-only. Full benchmark runs are not enabled here.")

    output_rows = []
    for row in rows:
        backend = (
            OpenAICompatibleBackend(model=args.model)
            if args.backend == "openai-compatible"
            else CodexCliBackend(executable=args.codex, model=args.model)
        )
        try:
            runner = BioMDTRunner(backend, max_collaboration_rounds=args.max_collaboration_rounds)
            result = runner.run(row) if args.method == "biomdt" else DirectLLMRunner(backend).run(row)
        except Exception as error:
            result = {"id": row["id"], "task_type": row["task_type"], "prediction": None,
                      "prediction_status": "model_error",
                      "error": str(error), "runtime": {"model": args.model or "codex-default",
                      "cli_version": getattr(backend, "cli_version", None), "llm_calls": backend.calls}}
        finally:
            backend.close()
        result["http_failures"] = getattr(backend, "http_failures", None)
        result["method"] = args.method
        output_rows.append(result)
        log_path = args.output_dir / "runs" / f"{row['id']}-{args.method}.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"id": row["id"], "method": args.method,
                          "prediction": result.get("prediction"),
                          "runtime": result.get("runtime"), "log": str(log_path)},
                         ensure_ascii=False))
    write_jsonl(args.output_dir / f"{args.method}_predictions.jsonl", [
        {key: result.get(key) for key in ("id", "prediction", "prediction_status", "error")}
        for result in output_rows
    ])


if __name__ == "__main__":
    main()
