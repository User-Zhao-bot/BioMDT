"""Search PubMed or fetch PubMed records by PMID."""
import argparse
from pathlib import Path
from urllib.parse import urlencode

from query_common import fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--term")
    inputs.add_argument("--pmid", nargs="+", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True, help="Raw response path")
    args = parser.parse_args()
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    if args.term:
        query = urlencode({
            "db": "pubmed", "term": args.term, "retmode": "json",
            "retmax": args.limit, "tool": "BioMDT",
        })
        fetch(f"{base}/esearch.fcgi?{query}", args.output)
    else:
        query = urlencode({
            "db": "pubmed", "id": ",".join(map(str, args.pmid)),
            "retmode": "xml", "tool": "BioMDT",
        })
        fetch(f"{base}/efetch.fcgi?{query}", args.output, "xml")
