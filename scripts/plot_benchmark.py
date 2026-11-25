"""Render observed benchmark metrics as publication-ready figures."""
from collections import Counter
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from deepevidence_data import TASK_FILES

LABELS = {"direct": "Direct LLM", "deepevidence": "DeepEvidence (Adapted)", "biomdt": "BioMDT"}
COLORS = {"direct": "#496b92", "deepevidence": "#bb6351", "biomdt": "#278277"}
TASK_LABELS = dict(zip(TASK_FILES, ["Target ID", "MoA", "Metabolic flux"]))


def plot(directory, formats):
    report = json.loads((directory / "summary.json").read_text())
    methods = list(report["methods"])
    rows = report["cases"]
    blocks = {method: report["methods"][method]["all_selected"] for method in methods}
    overall = {method: types["overall"] for method, types in blocks.items()}
    by_method = {method: [row for row in rows if row["method"] == method] for method in methods}
    graphs = [row["evidence"] for row in rows if row["method"] == "biomdt" and row["evidence"]]
    folder = directory / "figures"
    folder.mkdir(exist_ok=True)
    skipped = {}
    for extension in formats:
        for stale in folder.glob(f"[0-9][0-9]_*.{extension}"):
            stale.unlink()
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none", "pdf.fonttype": 42,
                         "axes.axisbelow": True})
    prefix = "Development smoke test" if report["mode"] == "smoke" else f"{report['mode']} selection"

    def save(name, fig, ax, title):
        ax.set_title(title, loc="left", weight="bold", pad=14)
        fig.text(0.015, 0.012, prefix, color="#48576b", fontsize=9)
        fig.tight_layout(rect=(0, .05, 1, 1))
        for extension in formats:
            fig.savefig(folder / f"{name}.{extension}", dpi=320, bbox_inches="tight")
        plt.close(fig)

    def bars(name, title, names, values, ylabel, fraction=False):
        if not any(value is not None for values_ in values.values() for value in values_):
            skipped[name] = "No observed values"
            return
        fig, ax = plt.subplots(figsize=(max(6, len(names) * 1.45), 4))
        width = 0.76 / len(values)
        x = np.arange(len(names))
        for j, (method, vector) in enumerate(values.items()):
            positioned = [(i, v) for i, v in enumerate(vector) if v is not None]
            ax.bar([x[i] - .38 + (j + .5) * width for i, _ in positioned],
                   [v for _, v in positioned], width, label=LABELS.get(method, method),
                   color=COLORS.get(method))
            if fraction:
                for i, value in enumerate(vector):
                    x_label = x[i] - .38 + (j + .5) * width
                    if value is not None:
                        ax.text(x_label, value + .025, f"{value:.0%}", ha="center", fontsize=8)
                    elif name == "04_evidence_quality":
                        ax.text(x_label, .025, "N/A", color="#687584", ha="center", fontsize=8)
        ax.set_xticks(x, names, rotation=15 if len(names) > 4 else 0, ha="center")
        ax.set_ylabel(ylabel)
        if fraction:
            from matplotlib.ticker import PercentFormatter
            ax.yaxis.set_major_formatter(PercentFormatter(1))
            ax.set_ylim(0, 1.16)
        if len(values) > 1:
            ax.legend(frameon=False, fontsize=8)
        save(name, fig, ax, title)

    bars("01_task_accuracy", "Exact match by task", list(TASK_LABELS.values()),
         {m: [blocks[m][t]["exact_match"] if blocks[m][t]["attempted"] else None for t in TASK_FILES]
          for m in methods}, "Accuracy", True)
    bars("02_overall_accuracy", "Overall exact match", ["Scheduled questions"],
         {m: [overall[m]["exact_match"] if overall[m]["attempted"] else None] for m in methods}, "Accuracy", True)
    bars("03_f1_coverage", "Option inference and completion", ["Option F1", "Coverage"],
         {m: [overall[m][key] if overall[m]["attempted"] else None for key in ("f1", "coverage")]
          for m in methods}, "Macro F1 / coverage", True)
    bars("04_evidence_quality", "Evidence integration audit", ["Traceability", "Support rate", "Cross-source"],
         {m: [overall[m][key] for key in ("traceability", "support_rate", "cross_source_integration")]
          for m in methods if m != "direct"}, "Observed fraction", True) if set(methods) - {"direct"} else skipped.update(
              {"04_evidence_quality": "No evidence-producing method"})

    for name, key, title, unit in (("05_tokens", "total_tokens", "Token consumption", "Tokens per case"),
                                    ("06_runtime", "wall_seconds", "Execution time", "Seconds per case")):
        samples = {m: [r[key] for r in by_method[m] if r.get(key) is not None] for m in methods}
        groups = [m for m in methods if len(samples[m]) >= 2]
        if not groups:
            skipped[name] = "Need at least two observed cases per displayed method"
            continue
        fig, ax = plt.subplots(figsize=(6.5, 4))
        boxes = ax.boxplot([samples[m] for m in groups], tick_labels=[LABELS[m] for m in groups], patch_artist=True)
        for box, m in zip(boxes["boxes"], groups):
            box.set_facecolor(COLORS[m])
        ax.set_ylabel(unit)
        save(name, fig, ax, title)

    efficiency_points = [m for m in methods if any(
        r.get("total_tokens") is not None for r in by_method[m]) and overall[m]["attempted"]]
    if efficiency_points:
        fig, ax = plt.subplots(figsize=(6.5, 4))
        for method in efficiency_points:
            ax.scatter(overall[method]["total_tokens"], overall[method]["exact_match"], s=75,
                       color=COLORS[method], label=LABELS[method])
        ax.set(xlabel="Mean observed tokens per case", ylabel="Exact match", ylim=(-.05, 1.12))
        ax.legend(frameon=False, fontsize=8)
        save("07_accuracy_resources", fig, ax, "Accuracy and resource use")
    else:
        skipped["07_accuracy_resources"] = "No matched accuracy and resource measurements"

    activations, links, transitions = Counter(), Counter(), Counter()
    for graph in graphs:
        activations.update(graph["agent_activations"])
        links.update(graph["collaborations"])
        transitions.update(f"{t['before']} → {t['after']}" for t in graph["state_transitions"])
    bars("08_agent_activation", "BioMDT specialist activation", list(activations),
         {"biomdt": list(activations.values())}, "Activations")
    if links:
        pairs = {tuple(key.split(" → ")): value for key, value in links.items()}
        agents = sorted({agent for pair in pairs for agent in pair})
        matrix = [[pairs.get((sender, recipient), 0) for recipient in agents] for sender in agents]
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        ax.imshow(matrix, cmap="GnBu")
        ax.set_xticks(range(len(agents)), agents, rotation=20)
        ax.set_yticks(range(len(agents)), agents)
        ax.set(xlabel="Recipient", ylabel="Sender")
        for i, row in enumerate(matrix):
            for j, value in enumerate(row):
                ax.text(j, i, value, ha="center", va="center",
                        color="white" if value and value >= max(links.values()) * .65 else "#202b38")
        save("09_agent_collaboration", fig, ax, "Evidence handoffs")
    else:
        skipped["09_agent_collaboration"] = "No observed cross-agent handoffs"

    source_counts = {m: Counter(database for r in by_method[m] for database in r["evidence"].get("cited_databases", []))
                     for m in methods if m != "direct"}
    databases = sorted({name for c in source_counts.values() for name in c})
    bars("10_evidence_sources", "Cited evidence by database", databases,
         {m: [c[name] for name in databases] for m, c in source_counts.items()}, "Cases with citations")
    bars("11_claim_transitions", "Claim evidence-state transitions", list(transitions),
         {"biomdt": list(transitions.values())}, "Observed transitions")
    status = dict.fromkeys(["correct", "wrong", "abstention", "invalid_prediction",
                            "format_error", "model_error", "interface_error", "not_run"])
    counts = {m: Counter(overall[m]["status_counts"]) for m in methods}
    for method in methods:
        counts[method]["database_error*"] = sum((row.get("database_errors") or 0) > 0 for row in by_method[method])
    status["database_error*"] = None
    labels = [k for k in status if any(c[k] for c in counts.values())]
    bars("12_outcomes", "Prediction outcomes (* database errors can overlap)", labels,
         {m: [counts[m][label] for label in labels] for m in methods}, "Cases")
    (folder / "skipped.json").write_text(json.dumps(skipped, indent=2) + "\n")
