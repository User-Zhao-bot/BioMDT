"""Query a DeepEvidence-compatible public API and persist its provenance envelope."""
import argparse
import json
from pathlib import Path

from biomedical_evidence import (
    BioKnowledgeTools,
    DEFAULT_CACHE,
    ROOT,
    SQLiteEvidenceCache,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        choices=("uniprot", "open_targets", "reactome", "kegg", "chembl", "pubmed", "pubtator"),
    )
    parser.add_argument("operation")
    parser.add_argument("--params-json", required=True)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data/raw/biomedical_queries"
    )
    args = parser.parse_args()

    params = json.loads(args.params_json)
    if not isinstance(params, dict):
        parser.error("--params-json must decode to a JSON object")
    tools = BioKnowledgeTools(cache=SQLiteEvidenceCache(args.cache))
    result = tools.query(args.database, args.operation, **params)
    output = args.output_dir / "cache_export.jsonl"
    exported_count = tools.cache.export(output)
    print(json.dumps({
        "cache_export": str(output),
        "database": args.database,
        "operation": args.operation,
        "cached_source_ids": result["source_ids"],
        "database_version": result["database_version"],
        "record_count": len(result["records"]),
        "exported_query_count": exported_count,
    }, ensure_ascii=False))
