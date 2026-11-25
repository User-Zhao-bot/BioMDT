"""Fetch the pinned public dataset and historical grader, then prepare inputs."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from deepevidence_data import ROOT, TASK_FILES, prepare_official_data

DATASET_REVISION = "06b349b24ee18a8d5a2db3e498884d5ad9600f76"
BIODSA_COMMIT = "b12439eba3c77a9bab652015b17467c1f5bcf9ce"


def setup(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    source = raw_dir / "BioDSA-paper"
    if not source.exists():
        with TemporaryDirectory(dir=raw_dir) as scratch:
            checkout = Path(scratch) / "BioDSA-paper"
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run([
                "git", "-C", str(checkout), "fetch", "--depth=1",
                "https://github.com/RyanWangZf/BioDSA.git", BIODSA_COMMIT,
            ], check=True)
            subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"], check=True)
            checkout.rename(source)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != BIODSA_COMMIT:
        raise SystemExit(f"Expected BioDSA at {BIODSA_COMMIT}, found {revision}")

    dataset_url = f"https://huggingface.co/datasets/zifeng-ai/DeepEvidence/resolve/{DATASET_REVISION}"
    for filename in TASK_FILES.values():
        path = raw_dir / filename
        if not path.exists():
            temporary = path.with_suffix(".part")
            subprocess.run([
                "curl", "--fail", "--location", "--silent", "--show-error", "--retry", "2",
                "--output", str(temporary), f"{dataset_url}/{filename}",
            ], check=True)
            temporary.replace(path)

    stats = prepare_official_data(raw_dir)
    print(f"Prepared {stats['total_records']} questions and recorded {stats['anomaly_count']} label anomalies.")


if __name__ == "__main__":
    setup(ROOT / "data/raw/deepevidence")
