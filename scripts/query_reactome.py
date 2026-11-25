"""Fetch a Reactome stable ID and optionally map a UniProt accession to pathways."""
import argparse
from urllib.parse import quote

from query_common import QUERY_DIR, fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stable_ids", nargs="*", default=["R-HSA-6802948"])
    parser.add_argument("--uniprot")
    args = parser.parse_args()
    base = "https://reactome.org/ContentService/data"
    output = QUERY_DIR / "reactome"
    for item in args.stable_ids:
        stable_id = quote(item, safe="")
        fetch(f"{base}/query/{stable_id}", output / f"{stable_id}.json")
    if args.uniprot:
        accession = quote(args.uniprot.upper(), safe="")
        fetch(
            f"{base}/mapping/UniProt/{accession}/pathways",
            output / f"uniprot-{accession}-pathways.json",
        )
