"""Write a public API response and its source metadata."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

QUERY_DIR = Path(__file__).resolve().parents[1] / "data/raw/queries"


def fetch(url, output, kind="json"):
    request = Request(url, headers={
        "Accept": f"application/{kind}",
        "User-Agent": "BioMDT-course-project/1.0",
    })
    with urlopen(request, timeout=45) as response:
        body = response.read()
        metadata = {
            "url": response.url,
            "status": response.status,
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "headers": {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in {"date", "content-type", "etag", "last-modified"}
                or key.lower().startswith("x-uniprot-")
            },
        }
    if kind == "json":
        json.loads(body)
    else:
        from xml.etree import ElementTree
        ElementTree.fromstring(body)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    output.with_suffix(output.suffix + ".source.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(output)
    return body
