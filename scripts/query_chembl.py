"""Fetch a ChEMBL molecule, its mechanisms, and mechanism targets."""
import argparse
import json
from urllib.parse import quote, urlencode

from query_common import QUERY_DIR, fetch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("molecule_id", nargs="?", default="CHEMBL1229517")
    parser.add_argument("--activity-target", nargs="+", default=[])
    args = parser.parse_args()
    molecule_id = quote(args.molecule_id.upper(), safe="")
    base = "https://www.ebi.ac.uk/chembl/api/data"
    output = QUERY_DIR / "chembl"
    fetch(f"{base}/molecule/{molecule_id}.json", output / f"{molecule_id}.json")
    query = urlencode({"molecule_chembl_id": molecule_id, "limit": 1000})
    page = json.loads(fetch(
        f"{base}/mechanism.json?{query}", output / f"{molecule_id}-mechanisms.json"
    ))
    if page["page_meta"]["next"]:
        raise ValueError("Mechanisms exceed the page limit")
    targets = {
        row["target_chembl_id"] for row in page["mechanisms"] if row["target_chembl_id"]
    }
    activity_targets = {quote(target.upper(), safe="") for target in args.activity_target}
    for target in sorted(targets | activity_targets):
        fetch(f"{base}/target/{target}.json", output / f"{target}.json")
    for target in sorted(activity_targets):
        query = urlencode({
            "molecule_chembl_id": molecule_id, "target_chembl_id": target,
            "standard_type": "IC50", "standard_units": "nM", "limit": 10,
        })
        fetch(f"{base}/activity.json?{query}", output / f"{molecule_id}-{target}-ic50.json")
