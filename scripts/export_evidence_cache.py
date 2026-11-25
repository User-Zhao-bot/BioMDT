"""Export cached API requests, raw responses, and compact records as JSONL."""
import argparse
from pathlib import Path

from biomedical_evidence import DEFAULT_CACHE, SQLiteEvidenceCache


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/biomedical_queries/cache_export.jsonl"),
    )
    args = parser.parse_args()
    count = SQLiteEvidenceCache(args.cache).export(args.output)
    print(f"Exported {count} cached API responses to {args.output}")
