"""Run the historical DeepEvidence agent on one normalized model input."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from deepevidence_smoke import CodexDeepEvidence
from biomdt.backend import OpenAICompatibleBackend
from biomdt.runner import task_answer_instruction, validate_prediction_for_question
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool


def budget_profile(name: str) -> dict[str, int]:
    profiles = {
        "author": {
            "main_search_rounds_budget": 5,
            "main_action_rounds_budget": 20,
            "subagent_action_rounds_budget": 5,
        },
        "project": {
            "main_search_rounds_budget": 1,
            "main_action_rounds_budget": 5,
            "subagent_action_rounds_budget": 3,
        },
    }
    try:
        return profiles[name]
    except KeyError as error:
        raise ValueError(f"Unknown DeepEvidence budget profile: {name}") from error


class OpenAIDeepEvidence(CodexDeepEvidence):
    def __init__(self, *args, api_backend, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_backend = api_backend
        self.retrieval_log = []

    def _record_tools(self, state, outcomes):
        databases = {
            "search_papers": "pubtator", "fetch_paper_content": "pubmed",
            "find_entities": "pubtator", "find_related_entities": "pubtator",
            "fetch_paper_annotations": "pubtator", "get_paper_references": "pubmed",
        }
        calls = {call["id"]: call for call in state.messages[-1].tool_calls}
        for message in outcomes["messages"]:
            call = calls[message.tool_call_id]
            if call["name"] not in databases:
                continue
            output = str(message.content)
            body = output.partition("### Output:")[2].strip() or output.strip()
            body = body.removeprefix("```").lstrip()
            failed = (body.startswith(("Error", "Failed", "Traceback"))
                      or "Code exited with non-zero status" in output)
            self.retrieval_log.append({
                "tool": call["name"], "tool_call_id": call["id"], "inputs": call["args"],
                "database": databases[call["name"]], "output": output,
                "error": body if failed else None,
            })
        return outcomes

    def _tool_node(self, state, config):
        return self._record_tools(state, super()._tool_node(state, config))

    def _tool_node_for_bfs_agent(self, state, config):
        return self._record_tools(state, super()._tool_node_for_bfs_agent(state, config))

    def _tool_node_for_dfs_agent(self, state, config):
        return self._record_tools(state, super()._tool_node_for_dfs_agent(state, config))

    def _call_model(self, model_name, messages, tools=None, **kwargs):
        available_tools = {
            tool.name: tool for tool in (tools or []) if tool.name != "code_execution"
        }
        system_prompt = str(messages[0].content).lower() if messages else ""
        if "breadth-first exploration" in system_prompt:
            stage = "BFRS"
        elif "depth-first exploration" in system_prompt:
            stage = "DFRS"
        else:
            stage = "orchestrator"
        role_map = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
        api_messages = []
        for message in messages:
            serialized = message.model_dump(mode="json")
            role = role_map.get(serialized.get("type"), serialized.get("role", "user"))
            row = {"role": role, "content": serialized.get("content", "")}
            if role == "tool" and serialized.get("tool_call_id"):
                row["tool_call_id"] = serialized["tool_call_id"]
            if role == "assistant" and serialized.get("tool_calls"):
                row["tool_calls"] = [{
                    "id": call.get("id") or f"api_{uuid4().hex}",
                    "type": "function",
                    "function": {"name": call["name"],
                                 "arguments": json.dumps(call.get("args", {}), ensure_ascii=False)},
                } for call in serialized["tool_calls"]]
            if serialized.get("name") and role == "tool":
                row["name"] = serialized["name"]
            api_messages.append(row)
        response = self.api_backend.complete_with_tools(
            stage, api_messages,
            [convert_to_openai_tool(tool) for tool in available_tools.values()],
        )
        limit = int(os.getenv("BENCHMARK_MAX_TOOL_CALLS", "0"))
        if limit and response["tool_calls"] and sum(bool(call["tool_name"]) for call in self.cli_calls) >= limit:
            raise RuntimeError("Tool call budget exhausted")
        tool_calls = []
        for model_call in response["tool_calls"]:
            tool_name = model_call["name"]
            if tool_name not in available_tools:
                raise ValueError(f"Unknown BioDSA tool {tool_name}")
            tool_calls.append({"name": tool_name, "args": model_call["args"],
                               "id": model_call["id"] or f"api_{uuid4().hex}"})
        usage = self.api_backend.calls[-1]
        self.cli_calls.append({"stage": stage,
                               "tool_name": tool_calls[0]["name"] if tool_calls else "",
                               "usage": {key: usage[key] for key in
                                         ("input_tokens", "output_tokens", "total_tokens")},
                               "model": usage["model"], "provider": usage["provider"], "gateway_retries": usage["gateway_retries"],
                               "requests": tool_calls})
        return AIMessage(content=response.get("text", ""), tool_calls=tool_calls,
                         usage_metadata={
                             "input_tokens": usage["input_tokens"],
                             "output_tokens": usage["output_tokens"],
                             "total_tokens": usage["total_tokens"],
                         })


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--inputs", type=Path, default=ROOT / "data/processed/deepevidence/test_inputs.jsonl")
    parser.add_argument("--codex", type=Path, default=Path.home() / ".local/bin/codex")
    parser.add_argument("--model", default="codex-default")
    parser.add_argument("--backend", choices=("openai-compatible", "codex-cli"), default="openai-compatible")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results/deepevidence")
    parser.add_argument("--budget-profile", choices=("author", "project"), default="author")
    args = parser.parse_args()
    row = next((item for item in read_jsonl(args.inputs) if item["id"] == args.item_id), None)
    if row is None:
        parser.error(f"Unknown item ID: {args.item_id}")

    query = row["question"] + "\n\n" + "\n".join(row["options"]) + (
        "\n\nUse available public biomedical tools to investigate the case. "
        "Delegate at least one focused query to a BFRS or DFRS subagent before answering. "
        "Explain with citations. " + task_answer_instruction(row["question"]) + " End with exactly one "
        '<BIOMED_FINAL>{"selected_options":["A"]}</BIOMED_FINAL> tag; A is a format example.'
    )
    previous_cwd = Path.cwd()
    execution_error = None
    with TemporaryDirectory(prefix="deepevidence-unified-") as directory:
        run_dir = Path(directory)
        cli_dir = run_dir / "cli"
        cli_dir.mkdir()
        schema = run_dir / "turn.schema.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {"text": {"type": "string"}, "tool_name": {"type": "string"},
                           "tool_arguments_json": {"type": "string"}},
            "required": ["text", "tool_name", "tool_arguments_json"],
            "additionalProperties": False,
        }), encoding="utf-8")
        api_backend = OpenAICompatibleBackend(model=None if args.model == "codex-default" else args.model) \
            if args.backend == "openai-compatible" else None
        agent_class = OpenAIDeepEvidence if api_backend else CodexDeepEvidence
        agent_kwargs = {"api_backend": api_backend} if api_backend else {}
        agent = agent_class(
            model_name=args.model, api_type="codex-cli", api_key=None,
            evidence_graph_cache_dir=str(run_dir / "graph"),
            **budget_profile(args.budget_profile), light_mode=False, **agent_kwargs,
        )
        agent.cli, agent.schema, agent.cli_dir, agent.cli_calls = args.codex, schema, cli_dir, []
        os.chdir(run_dir)
        try:
            execution = agent.go(query, knowledge_bases=["pubmed_papers"], verbose=False)
        except Exception as error:
            execution_error = str(error)
        finally:
            os.chdir(previous_cwd)
    if execution_error:
        calls = api_backend.calls if api_backend else agent.cli_calls
        input_tokens = sum(call.get("input_tokens", call.get("usage", {}).get("input_tokens", 0)) for call in calls)
        output_tokens = sum(call.get("output_tokens", call.get("usage", {}).get("output_tokens", 0)) for call in calls)
        result = {
            "id": row["id"], "task_type": row["task_type"], "prediction": None,
            "prediction_status": "model_error", "method": "deepevidence",
            "budget_profile": args.budget_profile, "error": execution_error,
            "tool_calls": agent.cli_calls,
            "http_failures": api_backend.http_failures if api_backend else None,
            **({"retrieval_log": agent.retrieval_log} if api_backend else {}),
            "runtime": {"model": args.model, "provider": args.backend,
                        "llm_call_count": len(calls), "input_tokens": input_tokens,
                        "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
                        "tool_call_count": sum(bool(call.get("tool_name")) for call in agent.cli_calls)},
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / f"{row['id']}_unified.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        prediction_path = args.output_dir / "unified_predictions.jsonl"
        existing = [item for item in read_jsonl(prediction_path) if item["id"] != row["id"]] if prediction_path.exists() else []
        existing.append({"id": row["id"], "prediction": None,
                         "prediction_status": "model_error", "error": execution_error})
        prediction_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing), encoding="utf-8")
        print(json.dumps({"id": row["id"], "error": execution_error,
                          "runtime": result["runtime"], "log": str(output_path)}, ensure_ascii=False))
        return
    final_response = execution.final_response
    match = re.findall(r"<BIOMED_FINAL>\s*(\{.*?\})\s*</BIOMED_FINAL>", final_response, re.DOTALL)
    try:
        prediction = json.loads(match[-1]).get("selected_options") if match else None
    except (json.JSONDecodeError, AttributeError):
        prediction = None
    if prediction is None:
        prediction_status = "format_error"
    else:
        valid_options = [re.match(r"^([A-Z])\.\s", option).group(1) for option in row["options"]]
        prediction, prediction_status = validate_prediction_for_question(
            prediction, valid_options, row["question"]
        )
    raw_execution = execution.to_json()
    result = {
        "id": row["id"], "task_type": row["task_type"], "prediction": prediction,
        "prediction_status": prediction_status,
        "final_response": final_response, "official_execution": raw_execution,
        "tool_calls": agent.cli_calls,
        "http_failures": api_backend.http_failures if api_backend else None,
        **({"retrieval_log": agent.retrieval_log} if api_backend else {}),
        "runtime": {
            "model": (agent.cli_calls[0].get("model", args.model) if agent.cli_calls else args.model),
            "backend": args.backend,
            "cli_version": agent.cli_calls[0].get("cli_version") if agent.cli_calls else None,
            "llm_call_count": len(agent.cli_calls),
            "input_tokens": raw_execution.get("total_input_tokens", 0),
            "output_tokens": raw_execution.get("total_output_tokens", 0),
            "total_tokens": raw_execution.get("total_input_tokens", 0) + raw_execution.get("total_output_tokens", 0),
            "tool_call_count": sum(bool(call.get("tool_name")) for call in agent.cli_calls),
        },
        "method": "deepevidence",
        "budget_profile": args.budget_profile,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{row['id']}_unified.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    prediction_path = args.output_dir / "unified_predictions.jsonl"
    existing = [item for item in read_jsonl(prediction_path) if item["id"] != row["id"]] if prediction_path.exists() else []
    existing.append({"id": row["id"], "prediction": prediction,
                     "prediction_status": prediction_status})
    prediction_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing), encoding="utf-8")
    print(json.dumps({"id": row["id"], "prediction": prediction,
                      "runtime": result["runtime"], "log": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
