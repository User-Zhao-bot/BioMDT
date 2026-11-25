"""Download the official CIViC and CIViC-Fact snapshot files used in Phase 1."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copyfileobj
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CIVIC_RELEASE = "01-Nov-2026"
CIVIC_TABLES = (
    "ClinicalEvidenceSummaries",
    "FeatureSummaries",
    "MolecularProfileSummaries",
    "VariantSummaries",
)
FACT_COMMIT = "1e7d58550fedf88eaf8884028cc7dbc703256037"
FACT_BUILD = "civicfact-2026.06.09"


def download(directory, filename, url):
    destination = ROOT / "data" / "raw" / directory / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_suffix(destination.suffix + ".part")
    with urlopen(url, timeout=120) as response, pending.open("wb") as output:
        copyfileobj(response, output)
    pending.replace(destination)
    print(f"{destination.relative_to(ROOT)}: {destination.stat().st_size} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=["civic", "civicfact", "all"], default="all", nargs="?")
    args = parser.parse_args()
    jobs = []
    if args.dataset in ("civic", "all"):
        base = f"https://civicdb.org/downloads/{CIVIC_RELEASE}"
        for table in CIVIC_TABLES:
            filename = f"{CIVIC_RELEASE}-{table}.tsv"
            jobs.append(("civic", filename, f"{base}/{filename}"))
        jobs.append(("civic", "PMID20453058-SupplementaryTableS1.xls", "https://ndownloader.figshare.com/files/39893154"))
    if args.dataset in ("civicfact", "all"):
        base = f"https://raw.githubusercontent.com/creisle/civicfact/{FACT_COMMIT}"
        for table in ("data", "retrieval", "document_chunks"):
            filename = f"{table}.jsonl.gz"
            jobs.append(("civicfact", filename, f"{base}/data_builder/builds/{FACT_BUILD}/{filename}"))
        review_path = "manual_reviews/data/doccano/2025.03.21_additional_explanations_2024.03.21/reviews.jsonl"
        jobs.append(("civicfact", "expert_reviews_2025-03-21.jsonl", f"{base}/{review_path}"))
    with ThreadPoolExecutor(max_workers=4) as executor:
        for future in [executor.submit(download, *job) for job in jobs]:
            future.result()


if __name__ == "__main__":
    main()
