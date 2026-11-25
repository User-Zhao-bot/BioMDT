"""Score predictions against isolated DeepEvidence references."""
import argparse
import json
from pathlib import Path

from deepevidence_data import ROOT, evaluate_predictions, read_jsonl


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path, default=ROOT / "data/processed/deepevidence/test_inputs.jsonl"
    )
    parser.add_argument(
        "--references", type=Path,
        default=ROOT / "data/processed/deepevidence/references.jsonl",
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--item-id", help="Score only one development or pilot case")
    args = parser.parse_args()
    inputs = read_jsonl(args.inputs)
    references = read_jsonl(args.references)
    predictions = read_jsonl(args.predictions)
    if args.item_id:
        inputs = [row for row in inputs if row["id"] == args.item_id]
        references = [row for row in references if row["id"] == args.item_id]
        predictions = [row for row in predictions if row["id"] == args.item_id]
        if not inputs:
            parser.error(f"Unknown item ID: {args.item_id}")
    result = evaluate_predictions(
        inputs,
        references,
        predictions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["overall"], ensure_ascii=False))
