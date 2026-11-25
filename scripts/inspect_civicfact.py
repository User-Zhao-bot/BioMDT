"""Profile the released CIViC-Fact datasets and audit exact links to Phase 1 CIViC records."""

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

from download_civic import FACT_BUILD, FACT_COMMIT, ROOT
from process_civic import dump_json, dump_jsonl


def jsonl(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def predictive(row):
    return row["claim"]["content"].get("evidenceType") == "PREDICTIVE"


def resolve_links(source_name, rows, civic):
    links = []
    for row in rows:
        evidence_id = str(row["civic.id"])
        pmid = str(row["document.pmid"])
        case_id = civic.get((evidence_id, pmid))
        if case_id is not None:
            links.append(
                {
                    "fixture": source_name,
                    "civic_case_id": case_id,
                    "evidence_id": evidence_id,
                    "pmid": pmid,
                    "fact_row_id": row.get("id"),
                    "fact_partition": row.get("partition"),
                    "fact_evidence_selection_method": row.get("evidence.selection_method"),
                    "hypothesis_annotation_ids": [
                        span["meta"]["hypothesis.id"]
                        for span in row["evidence"]
                        if span["meta"].get("hypothesis.id")
                    ],
                }
            )
    return links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw/civicfact")
    parser.add_argument("--civic", type=Path, default=ROOT / "data/processed/civic/references.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/processed/civicfact")
    args = parser.parse_args()

    verification = list(jsonl(args.raw / "data.jsonl.gz"))
    retrieval = list(jsonl(args.raw / "retrieval.jsonl.gz"))
    manual = list(jsonl(args.raw / "expert_reviews_2025-03-21.jsonl"))

    chunk_rows = 0
    source_papers = {}
    for row in jsonl(args.raw / "document_chunks.jsonl.gz"):
        chunk_rows += 1
        source_papers[str(row["document.pmid"])] = row["document.content_source"]

    verification_gold = [row for row in verification if not row["generated"]]
    verification_reviews = [review for row in verification for review in row["reviews"]]
    manual_reviews = [review for row in manual for review in row["reviews"]]
    with_human_notes = sum(
        any(span["meta"].get("hypothesis.comment", "").strip() for span in row["evidence"])
        for row in retrieval
    )

    civic = {
        (item["evidence_id"], item["citation_id"]): case["case_id"]
        for case in jsonl(args.civic)
        for item in case["supporting_evidence"]
        if item["source_type"] == "PubMed"
    }
    verification_links = resolve_links("verification_original", verification_gold, civic)
    retrieval_links = resolve_links("retrieval", retrieval, civic)

    args.out.mkdir(parents=True, exist_ok=True)
    dump_jsonl(args.out / "civic_links.jsonl", verification_links + retrieval_links)
    dump_json(
        args.out / "statistics.json",
        {
            "build": FACT_BUILD,
            "commit": FACT_COMMIT,
            "verification": {
                "rows": len(verification),
                "rows_by_partition": dict(Counter(row["partition"] for row in verification)),
                "rows_by_label": dict(Counter(row["gold_label_name"] for row in verification)),
                "original_rows": len(verification_gold),
                "predictive_rows": sum(predictive(row) for row in verification),
                "predictive_rows_by_partition": dict(Counter(row["partition"] for row in verification if predictive(row))),
                "original_predictive_rows_by_partition": dict(Counter(row["partition"] for row in verification_gold if predictive(row))),
                "evidence_sources": dict(Counter(row["evidence.source"] for row in verification)),
                "review_annotations_by_username": dict(Counter(review["username"] for review in verification_reviews)),
            },
            "retrieval": {
                "rows": len(retrieval),
                "rows_by_label": dict(Counter(row["gold_label_name"] for row in retrieval)),
                "predictive_rows": sum(predictive(row) for row in retrieval),
                "annotated_spans": sum(len(row["evidence"]) for row in retrieval),
                "rows_with_hypothesis_span_comment": with_human_notes,
                "supporting_rows_with_chunked_source_paper": sum(
                    row["gold_label_name"] == "SUPPORTS" and str(row["document.pmid"]) in source_papers
                    for row in retrieval
                ),
            },
            "document_chunks": {
                "chunks": chunk_rows,
                "unique_pubmed_ids": len(source_papers),
                "unique_papers_by_source": dict(Counter(source_papers.values())),
            },
            "expert_review_archive_2025_03_21": {
                "rows": len(manual),
                "rows_with_reason": sum(any(review.get("reason") for review in row["reviews"]) for row in manual),
                "annotations": len(manual_reviews),
                "annotations_by_label": dict(Counter(review["label"] for review in manual_reviews)),
                "group_validated_annotations": sum(bool(review.get("group_review_validated")) for review in manual_reviews),
            },
            "exact_eid_pmid_links": {
                name: {
                    "rows": len(found),
                    "CIViC_case_keys": len({link["civic_case_id"] for link in found}),
                    "unique_eids": len({link["evidence_id"] for link in found}),
                    "unique_pmids": len({link["pmid"] for link in found}),
                }
                for name, found in (("verification_original", verification_links), ("retrieval", retrieval_links))
            },
        },
    )


if __name__ == "__main__":
    main()
