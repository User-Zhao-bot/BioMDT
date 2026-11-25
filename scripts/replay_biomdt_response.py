"""Replay a saved BioMDT agent response through the current graph writer."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from biomdt.entity_index import BiomedicalEntityIndex
from biomdt.graph import EvidenceGraph
from biomdt.runner import integrate_agent_response


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent", default="literature")
    args = parser.parse_args()
    run = json.loads(args.run_log.read_text(encoding="utf-8"))
    graph = EvidenceGraph()
    groups: dict[str, list[str]] = defaultdict(list)
    for claim in run["claims"]:
        graph.add_claim(claim)
        groups[claim["option"]].append(claim["claim_id"])
    for option, claim_ids in groups.items():
        graph.add_option_group(option, "AND", claim_ids)
    agent_output = next(item for item in run["agent_outputs"] if item["agent"] == args.agent)
    retrieved = run.get("agent_results", {}).get(args.agent, [])
    _, integration = integrate_agent_response(
        graph,
        BiomedicalEntityIndex(),
        agent_output["response"],
        retrieved,
        agent_output["claim_ids"],
        args.agent,
    )
    result = {
        "case_id": run["id"],
        "agent": args.agent,
        "source_run": str(args.run_log),
        "retrieval_result_count": len(retrieved),
        "response_format": integration["response_format"],
        "parsed_records": integration["parsed_records"],
        "added_records": integration["added_records"],
        "rejected_records": integration["rejected_records"],
        "graph_before": integration["before_graph"],
        "graph_after": integration["after_graph"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "case_id", "response_format", "parsed_records", "added_records", "rejected_records",
    )}, ensure_ascii=False))
