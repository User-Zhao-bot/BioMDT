"""Collect method run logs into the prediction JSONL expected by the grader."""
import argparse
import json
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("biomdt", "direct", "deepevidence"), required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.runs_dir.glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        if "id" not in result and result.get("item_id"):
            result["id"] = result["item_id"]
        if result.get("method") not in {None, args.method}:
            continue
        rows.append({key: result.get(key) for key in (
            "id", "prediction", "prediction_status", "error"
        )})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({"method": args.method, "rows": len(rows), "output": str(args.output)}))
