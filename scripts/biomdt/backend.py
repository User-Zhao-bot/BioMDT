from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in (
        "disease", "tissue", "model", "species", "intervention",
        "readout", "comparison", "timepoint",
    )},
    "required": ["disease", "tissue", "model", "species", "intervention",
                 "readout", "comparison", "timepoint"],
    "additionalProperties": False,
}
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"}, "option": {"type": "string"},
        "text": {"type": "string"}, "operator": {"type": "string"},
        "children": {"type": "array", "items": {"type": "string"}},
        "required_evidence_types": {"type": "array", "items": {"type": "string"}},
        "context": CONTEXT_SCHEMA,
    },
    "required": ["claim_id", "option", "text", "operator", "children",
                 "required_evidence_types", "context"],
    "additionalProperties": False,
}
EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"}, "subject": {"type": "string"},
        "subject_type": {"type": "string"}, "relation": {"type": "string"},
        "object": {"type": "string"}, "object_type": {"type": "string"},
        "stance": {"type": "string"}, "context": CONTEXT_SCHEMA,
        "intervention": {"type": "string"}, "disease": {"type": "string"},
        "tissue": {"type": "string"}, "model": {"type": "string"},
        "readout": {"type": "string"}, "effect_direction": {"type": "string"},
        "comparison": {"type": "string"}, "directness": {"type": "string"},
        "evidence_kind": {"type": "string"}, "source_id": {"type": "string"},
        "source_type": {"type": "string"}, "database": {"type": "string"},
        "raw_evidence": {"type": "string"},
        "derived_from": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "claim_id", "subject", "subject_type", "relation", "object", "object_type", "stance", "context",
        "intervention", "disease", "tissue", "model", "readout", "effect_direction",
        "comparison", "directness", "evidence_kind", "source_id", "source_type",
        "database", "raw_evidence", "derived_from",
    ],
    "additionalProperties": False,
}
ENTITY_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "array", "items": {"type": "string"}} for key in (
        "genes", "proteins", "diseases", "drugs", "uniprot_ids", "keywords",
    )},
    "required": ["genes", "proteins", "diseases", "drugs", "uniprot_ids", "keywords"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": CLAIM_SCHEMA},
        "entities": ENTITY_SCHEMA,
        "selected_options": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
        "biology": {"type": "string"},
        "key_paths": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "evidence": {"type": "array", "items": EVIDENCE_SCHEMA},
        "follow_up_roles": {"type": "array", "items": {"type": "string"}},
        "unresolved_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "claims", "entities", "selected_options", "explanation", "biology",
        "key_paths", "evidence", "follow_up_roles", "unresolved_gaps",
    ],
    "additionalProperties": False,
}


def _decode_json(text: str) -> dict[str, Any]:
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Codex CLI returned no JSON object")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Codex CLI response must be a JSON object")
    return result


class CodexCliBackend:
    def __init__(self, executable: Path | str | None = None, model: str | None = None,
                 reasoning_effort: str = "low", timeout: int = 180):
        default = Path.home() / ".local/bin/codex"
        self.executable = str(executable or (default if default.exists() else shutil.which("codex") or "codex"))
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self._scratch = TemporaryDirectory(prefix="biomdt-cli-")
        self.cwd = Path(self._scratch.name)
        self.schema_path = self.cwd / "response.schema.json"
        self.schema_path.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
        version = subprocess.run(
            [self.executable, "--version"], capture_output=True, text=True,
            timeout=20, check=False,
        )
        self.cli_version = version.stdout.strip() or "unavailable"
        self.calls: list[dict[str, Any]] = []
        self.session_ids: dict[str, str] = {}
        self._auth_checked = False

    def complete(self, role: str, instructions: str, payload: dict[str, Any],
                 reuse_session: bool = False) -> dict[str, Any]:
        if not getattr(self, "_auth_checked", False):
            status = subprocess.run(
                [self.executable, "login", "status"], capture_output=True,
                text=True, timeout=20, check=False,
            )
            self._auth_checked = True
            if status.returncode or "not logged in" in (status.stdout + status.stderr).lower():
                raise RuntimeError("Codex CLI is not logged in. Authenticate with the existing Codex account, then retry.")
        prompt = instructions + "\n\nReturn one JSON object following the required output schema.\nINPUT:\n" + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )
        session_id = self.session_ids.get(role) if reuse_session else None
        if session_id:
            prompt = "Continue as the same " + role + " agent. Return only the requested JSON object.\n" + prompt
            command = [self.executable, "exec", "resume", session_id, "-", "--json"]
        else:
            command = [
                self.executable, "exec", "--ignore-user-config", "--skip-git-repo-check",
                "--sandbox", "read-only", "--json", "--output-schema", str(self.schema_path),
                "-c", f'model_reasoning_effort="{self.reasoning_effort}"', "-",
            ]
            if role != "coordinator":
                command.insert(3, "--ephemeral")
            if self.model:
                command[2:2] = ["-m", self.model]
        completed = subprocess.run(
            command, input=prompt, capture_output=True, text=True,
            timeout=self.timeout, check=False, cwd=self.cwd,
        )
        events = [
            json.loads(line) for line in completed.stdout.splitlines()
            if line.startswith("{")
        ]
        messages = [
            event.get("item", {}).get("text", "") for event in events
            if event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "agent_message"
        ]
        turns = [event for event in events if event.get("type") == "turn.completed"]
        if completed.returncode or not messages or not turns:
            error = completed.stderr[-1200:] or completed.stdout[-1200:]
            raise RuntimeError(f"Codex CLI call failed for {role}: {error}")
        turn = turns[-1]
        usage = turn.get("usage", {})
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        thread_event = next((event for event in events if event.get("type") == "thread.started"), {})
        if thread_event.get("thread_id") and role == "coordinator":
            self.session_ids[role] = thread_event["thread_id"]
        result = _decode_json(messages[-1])
        self.calls.append({
            "role": role,
            "session_reused": bool(session_id),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "duration_seconds": turn.get("duration_seconds"),
            "model": self.model or "codex-default",
            "cli_version": self.cli_version,
        })
        return result

    def close(self) -> None:
        self._scratch.cleanup()


class OpenAICompatibleBackend:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int = 180):
        import os

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "")
        self.reasoning_effort = os.environ.get("OPENAI_REASONING_EFFORT")
        self.timeout = float(os.getenv("BENCHMARK_TIMEOUT", str(timeout)))
        self.http_failures: list[int] = []
        self.calls: list[dict[str, Any]] = []
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not self.model:
            raise ValueError("OPENAI_MODEL is required")

    def _request_completion(self, request: Request) -> tuple[dict[str, Any], int]:
        max_calls = int(os.getenv("BENCHMARK_MAX_MODEL_CALLS", "0"))
        max_tokens = int(os.getenv("BENCHMARK_MAX_TOKENS", "0"))
        if max_calls and len(self.calls) >= max_calls:
            raise RuntimeError("Model call budget exhausted")
        if max_tokens and sum(call["total_tokens"] for call in self.calls) >= max_tokens:
            raise RuntimeError("Token budget exhausted")
        retries = int(os.getenv("BENCHMARK_RETRIES", "1"))
        for attempt in range(retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8")), attempt
            except HTTPError as error:
                if hasattr(self, "http_failures"):
                    self.http_failures.append(error.code)
                if attempt >= retries or error.code not in {429, 502, 503, 504, 524}:
                    raise
                error.close()

    def complete(self, role: str, instructions: str, payload: dict[str, Any],
                 reuse_session: bool = False,
                 output_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if output_schema is None and role in {"genomics", "pathway", "drug", "literature"}:
            output_schema = {"type": "object", "properties": {"evidence": {
                "type": "array", "items": EVIDENCE_SCHEMA
            }}, "required": ["evidence"], "additionalProperties": False}
            instructions += (" Use only assigned claim_id values and retrieved source_id values. "
                             "Use stance supports, contradicts or insufficient. Supply the record excerpt "
                             "in raw_evidence. A sourced background fact may inform a mechanism while "
                             "remaining insufficient for the full claim.")
        user_content = "Return one JSON object following the required output schema.\nINPUT:\n" + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_content},
            ],
            "response_format": (
                {"type": "json_schema", "json_schema": {
                    "name": f"{role}_response", "strict": True, "schema": output_schema,
                }}
                if output_schema else {"type": "json_object"}
            ),
        }
        if self.reasoning_effort:
            request_body["reasoning_effort"] = self.reasoning_effort
        if os.getenv("OPENAI_TEMPERATURE"):
            request_body["temperature"] = float(os.environ["OPENAI_TEMPERATURE"])
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "OpenAI/Python BioMDT/1.0",
            },
            method="POST",
        )
        result, gateway_retries = self._request_completion(request)
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(f"OpenAI-compatible API returned no choices for {role}")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"OpenAI-compatible API returned no text content for {role}")
        usage = result.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        self.calls.append({
            "role": role,
            "session_reused": False,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens)),
            "model": result.get("model", self.model),
            "provider": "openai-compatible", "requested_reasoning_effort": self.reasoning_effort,
            "gateway_retries": gateway_retries,
        })
        return _decode_json(content)

    def complete_with_tools(self, role: str, messages: list[dict[str, Any]],
                            tools: list[dict[str, Any]]) -> dict[str, Any]:
        request_body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        if self.reasoning_effort:
            request_body["reasoning_effort"] = self.reasoning_effort
        if os.getenv("OPENAI_TEMPERATURE"):
            request_body["temperature"] = float(os.environ["OPENAI_TEMPERATURE"])
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "OpenAI/Python BioMDT/1.0",
            },
            method="POST",
        )
        result, gateway_retries = self._request_completion(request)
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError(f"OpenAI-compatible API returned no choices for {role}")
        message = choices[0].get("message", {})
        parsed_calls = []
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {})
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            parsed_calls.append({
                "id": call.get("id", ""), "name": function.get("name", ""),
                "args": arguments,
            })
        usage = result.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        self.calls.append({
            "role": role, "session_reused": False,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens)),
            "model": result.get("model", self.model), "provider": "openai-compatible", "requested_reasoning_effort": self.reasoning_effort,
            "gateway_retries": gateway_retries,
        })
        return {"text": message.get("content") or "", "tool_calls": parsed_calls}

    def close(self) -> None:
        return None
