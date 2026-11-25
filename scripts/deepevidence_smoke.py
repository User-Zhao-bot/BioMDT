"""Run one official DeepEvidence choice case through legacy BioDSA and Codex CLI."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

import pyarrow.parquet as pq
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/deepevidence"
SOURCE = RAW / "BioDSA-paper"
sys.path.insert(0, str(SOURCE))
from biodsa.agents.deepevidence.agent import DeepEvidenceAgent

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "tool_name": {"type": "string"},
        "tool_arguments_json": {"type": "string"},
    },
    "required": ["text", "tool_name", "tool_arguments_json"],
    "additionalProperties": False,
}
SUBSETS = ("target_identification", "moa_pathway_reasoning", "in_vivo_metabolic_flux_response")


class CodexDeepEvidence(DeepEvidenceAgent):
    def _get_model(self, **kwargs):
        # BaseAgent initializes a provider eagerly. Model calls use _call_model below.
        return None

    def _call_model(self, model_name, messages, tools=None, **kwargs):
        tools = {tool.name: tool for tool in (tools or []) if tool.name != "code_execution"}
        system_prompt = str(messages[0].content).lower() if messages else ""
        if "breadth-first exploration" in system_prompt:
            stage = "BFRS"
        elif "depth-first exploration" in system_prompt:
            stage = "DFRS"
        else:
            stage = "orchestrator"
        task = {
            "messages": [message.model_dump(mode="json") for message in messages],
            "available_biodsa_tools": [convert_to_openai_tool(tool) for tool in tools.values()],
        }
        prompt = (
            "Act as the DeepEvidence role specified in the provided messages. "
            "Use only the listed BioDSA tools via the structured response; never run your own tools. "
            "For a tool action, set tool_name and serialize a single argument object in "
            "tool_arguments_json, with optional text. For a final response set tool_name "
            "to an empty string and tool_arguments_json to '{}'. Keep intermediate text concise. "
            "For the orchestrator's final response preserve the user's BIOMED_FINAL format.\n"
            + json.dumps(task, ensure_ascii=False)
        )
        model_flags = [] if model_name == "codex-default" else ["-m", model_name]
        completed = subprocess.run(
            [str(self.cli), "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
             "--sandbox", "read-only", "--json", "--output-schema", str(self.schema),
             *model_flags, "-c", 'model_reasoning_effort="low"', "-"],
            input=prompt, text=True, capture_output=True, check=False, timeout=100, cwd=self.cli_dir,
        )
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
        agent_messages = [e["item"]["text"] for e in events if e.get("type") == "item.completed"
                          and e.get("item", {}).get("type") == "agent_message"]
        turns = [e for e in events if e.get("type") == "turn.completed"]
        if completed.returncode or not agent_messages or not turns:
            error = [e for e in events if e.get("type") in {"error", "turn.failed"}]
            raise RuntimeError(f"Codex CLI model call failed: {error or completed.stderr[-500:]}")
        result = json.loads(agent_messages[-1])
        call = []
        if result["tool_name"]:
            tool_name = result["tool_name"]
            if tool_name not in tools:
                raise ValueError(f"Unknown BioDSA tool {tool_name}")
            call.append({"name": tool_name, "args": json.loads(result["tool_arguments_json"]),
                         "id": f"codex_{uuid4().hex}"})
        usage = turns[-1]["usage"]
        metadata = {key: usage.get(key, 0) for key in ("input_tokens", "output_tokens")}
        metadata["total_tokens"] = sum(metadata.values())
        self.cli_calls.append({"stage": stage, "tool_name": result["tool_name"],
                               "usage": metadata})
        return AIMessage(content=result["text"], tool_calls=call, usage_metadata=metadata)


def grade(subset, item, response):
    spec = importlib.util.spec_from_file_location(
        "bdr_grade", SOURCE / "scripts/harbor_bdr_grade.py"
    )
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    identifier = item["id"]
    reference = {
        "subset": subset, "source_split": "paper-smoke",
        "task_type": "single_choice" if len(item["answers"]) == 1 else "multi_select",
        "valid_options": [re.match(r"^([A-Z])\.\s", option).group(1)
                          for option in item["options"]],
        "label": {"selected_options": item["answers"]},
    }
    rows, _ = grader.grade(
        {identifier: reference}, [identifier],
        {identifier: {"status": "completed", "final_answer": response}},
    )
    return {"reference": reference["label"]["selected_options"], "grade": rows[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subset", choices=SUBSETS)
    parser.add_argument("item_id")
    parser.add_argument("--codex", type=Path, default=Path.home() / ".local/bin/codex")
    parser.add_argument("--model", default="codex-default")
    args = parser.parse_args()
    item = next(row for row in pq.read_table(RAW / f"{args.subset}.parquet").to_pylist()
                if row["id"] == args.item_id)
    query = item["question"] + "\n\n" + "\n".join(item["options"]) + (
        "\n\nUse available public biomedical tools to investigate the case. "
        "Delegate at least one focused query to a BFRS or DFRS subagent before answering. "
        "Explain with citations. End with exactly one "
        '<BIOMED_FINAL>{"selected_options":["A"]}</BIOMED_FINAL> tag; A is a format example.'
    )
    with TemporaryDirectory(prefix="deepevidence-smoke-") as scratch:
        run_dir = Path(scratch)
        os.chdir(run_dir)
        cli_dir = run_dir / "cli"
        cli_dir.mkdir()
        schema = run_dir / "turn.schema.json"
        schema.write_text(json.dumps(SCHEMA))
        agent = CodexDeepEvidence(
            model_name=args.model, api_type="codex-cli", api_key=None,
            evidence_graph_cache_dir=str(run_dir / "graph"),
            main_search_rounds_budget=1, main_action_rounds_budget=5,
            subagent_action_rounds_budget=3, light_mode=False,
        )
        agent.cli, agent.schema, agent.cli_dir, agent.cli_calls = args.codex, schema, cli_dir, []
        try:
            run = agent.go(query, knowledge_bases=["pubmed_papers"], verbose=False)
        except Exception:
            print(json.dumps(agent.cli_calls, ensure_ascii=False), file=sys.stderr)
            raise
        result = run.to_json()
        if isinstance(result, str):
            result = json.loads(result)
        response = run.final_response
        output = {
            "item_id": args.item_id, "subset": args.subset, "model": args.model,
            "cli_calls": agent.cli_calls, "official_execution": result,
            **grade(args.subset, item, response),
        }
        path = ROOT / "results/deepevidence" / f"{args.item_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n")
        print(path)


if __name__ == "__main__":
    main()
