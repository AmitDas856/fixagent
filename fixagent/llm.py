"""LLM clients.

The agent talks to the model through one small interface: ``complete(messages,
tools)`` returns an ``LLMResponse``. Two implementations are provided:

* ``OpenAICompatLLM`` calls any server that speaks the OpenAI-style
  ``/chat/completions`` API with tool calling. It uses only the standard
  library, so the project has no third-party runtime dependencies.
* ``ScriptedLLM`` replays a fixed list of steps. It is used by the tests so
  the whole agent loop can be exercised offline and deterministically.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Set when the model produced arguments that were not valid JSON.
    parse_error: str | None = None


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass


class OpenAICompatLLM:
    """Client for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        temperature: float = 0.0,
    ) -> None:
        self.model = model or os.environ.get("FIXAGENT_MODEL", "")
        self.api_key = api_key or os.environ.get("FIXAGENT_API_KEY", "")
        self.base_url = (base_url or os.environ.get("FIXAGENT_BASE_URL", "")).rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        missing = [
            name
            for name, value in (
                ("FIXAGENT_MODEL", self.model),
                ("FIXAGENT_BASE_URL", self.base_url),
            )
            if not value
        ]
        if missing:
            raise LLMError(
                "Missing LLM settings: " + ", ".join(missing) + ". See the README."
            )

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": [{"type": "function", "function": spec} for spec in tools],
            "temperature": self.temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM request failed ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        return parse_chat_completion(payload)


def parse_chat_completion(payload: dict) -> LLMResponse:
    """Convert a chat-completions JSON payload into an ``LLMResponse``."""
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected LLM response: {str(payload)[:300]}") from exc

    calls: list[ToolCall] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function", {})
        raw_args = function.get("arguments") or "{}"
        parse_error = None
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            arguments, parse_error = {}, f"invalid tool arguments: {exc}"
        calls.append(
            ToolCall(
                id=raw.get("id") or f"call_{index}",
                name=function.get("name", ""),
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return LLMResponse(text=message.get("content") or "", tool_calls=calls)


class ScriptedLLM:
    """Replays a fixed script. Each step is either text or a list of
    ``(tool_name, arguments)`` pairs."""

    def __init__(self, steps: list[str | list[tuple[str, dict]]]) -> None:
        self._steps = list(steps)
        self._index = 0
        self.seen_messages: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.seen_messages.append([dict(m) for m in messages])
        if self._index >= len(self._steps):
            return LLMResponse(text="(script exhausted)")
        step = self._steps[self._index]
        self._index += 1
        if isinstance(step, str):
            return LLMResponse(text=step)
        calls = [
            ToolCall(id=f"call_{self._index}_{i}", name=name, arguments=dict(args))
            for i, (name, args) in enumerate(step)
        ]
        return LLMResponse(tool_calls=calls)
