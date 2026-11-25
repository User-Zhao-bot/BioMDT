"""Fetch a UniProtKB entry by primary accession."""
import argparse
from urllib.parse import quote

from query_common import QUERY_DIR, fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accession", nargs="?", default="P15056")
    args = parser.parse_args()
    accession = quote(args.accession.upper(), safe="")
    fetch(
        f"https://rest.uniprot.org/uniprotkb/{accession}.json",
        QUERY_DIR / "uniprot" / f"{accession}.json",
    )
