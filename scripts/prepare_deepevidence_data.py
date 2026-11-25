"""Create model-only inputs and isolated references from the pinned parquet files."""
import argparse
import json
from pathlib import Path

from deepevidence_data import ROOT, prepare_official_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/deepevidence")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data/processed/deepevidence"
    )
    args = parser.parse_args()
    result = prepare_official_data(args.raw_dir, args.output_dir)
    print(json.dumps({
        "total_records": result["total_records"],
        "anomaly_count": result["anomaly_count"],
        "by_task": {
            task: {
                "sample_count": summary["sample_count"],
                "answer_cardinality": summary["answer_cardinality"],
                "option_count": summary["option_count"],
            }
            for task, summary in result["by_task"].items()
        },
    }, ensure_ascii=False))
