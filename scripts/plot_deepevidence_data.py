"""Render task composition and answer-shape charts from processed statistics."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from biomedical_evidence import ROOT

TASKS = (
    ("target_identification", "Target identification"),
    ("moa_pathway_reasoning", "MoA and pathway reasoning"),
    ("in_vivo_metabolic_flux_response", "In vivo flux response"),
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--statistics",
        type=Path,
        default=ROOT / "data/processed/deepevidence/statistics.json",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "results/data/deepevidence"
    )
    args = parser.parse_args()
    statistics = json.loads(args.statistics.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 14,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "#f7f8fa",
        "axes.facecolor": "#f7f8fa",
        "savefig.facecolor": "#f7f8fa",
    })
    names = [label for _, label in TASKS]
    rows = [statistics["by_task"][task] for task, _ in TASKS]

    fig, ax = plt.subplots(figsize=(10, 5.6), constrained_layout=True)
    y = np.arange(len(TASKS))
    single = [row["answer_cardinality"].get("1", 0) for row in rows]
    multiple = [row["sample_count"] - count for row, count in zip(rows, single)]
    ax.barh(y, single, color="#168c83", height=0.56, label="Single-select")
    ax.barh(y, multiple, left=single, color="#e3a34b", height=0.56, label="Multi-select")
    for index, (one, many) in enumerate(zip(single, multiple)):
        ax.text(one / 2, index, str(one), ha="center", va="center", color="white", weight="bold")
        ax.text(one + many / 2, index, str(many), ha="center", va="center", color="#29323a", weight="bold")
        ax.text(one + many + 0.55, index, f"n={one + many}", ha="left", va="center", color="#59636e")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlim(0, 31)
    ax.set_xlabel("Official test questions")
    ax.set_title("DeepEvidence task format")
    ax.grid(axis="x", color="#dfe3e8", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", ncols=2)
    fig.savefig(args.output_dir / "task_answer_format.png", dpi=220)
    plt.close(fig)

    option_sizes = [5, 6, 7, 8, 10]
    matrix = np.array([
        [row["option_count"].get(str(size), 0) for size in option_sizes]
        for row in rows
    ])
    fig, ax = plt.subplots(figsize=(8.8, 4.9), constrained_layout=True)
    image = ax.imshow(matrix, cmap="YlGnBu", aspect="auto", vmin=0, vmax=25)
    ax.set_xticks(range(len(option_sizes)), [str(size) for size in option_sizes])
    ax.set_yticks(range(len(TASKS)), names)
    ax.set_xlabel("Candidate options per question")
    ax.set_title("Candidate-option count by task")
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]
            color = "white" if value >= 14 else "#27313a"
            ax.text(column_index, row_index, str(value), ha="center", va="center", color=color, weight="bold")
    colorbar = fig.colorbar(image, ax=ax, shrink=0.85)
    colorbar.set_label("Question count")
    fig.savefig(args.output_dir / "candidate_option_distribution.png", dpi=220)
    plt.close(fig)
    print(args.output_dir)
