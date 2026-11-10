"""The agent loop: ask the model, run the tools it picks, repeat."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .llm import LLM, LLMResponse
from .tools import Toolbox

SYSTEM_PROMPT = """\
You are a software engineer fixing a bug in a code repository. The repository
may be written in Python, C++, Rust or Hack.

Work in this order:
1. Explore: list the files, then read the code and tests related to the issue.
2. Reproduce: run the tests and read the failure carefully.
3. Fix: make the smallest change to the source code that fixes the root cause.
4. Verify: run the tests again. If the build or tests fail, read the error and
   try again.
5. Call finish with a short summary once the tests pass.

Rules:
- Use the tools for everything. Do not guess what a file contains.
- Never edit test files. The tests define the correct behaviour.
- Do not hard-code values to satisfy a test. Fix the real logic.
- If you cannot fix the bug, call finish and say what you found.
"""


@dataclass
class AgentRun:
    finished: bool = False
    summary: str = ""
    steps: int = 0
    tool_calls: int = 0
    stop_reason: str = ""
    events: list[dict] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        llm: LLM,
        toolbox: Toolbox,
        max_steps: int = 30,
        log_path: Path | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.llm = llm
        self.toolbox = toolbox
        self.max_steps = max_steps
        self.log_path = log_path
        self.on_event = on_event

    def run(self, issue: str) -> AgentRun:
        run = AgentRun()
        tools = self.toolbox.specs()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._task_message(issue)},
        ]
        idle_turns = 0

        for step in range(1, self.max_steps + 1):
            run.steps = step
            response = self.llm.complete(messages, tools)
            messages.append(self._assistant_message(response))
            self._record(run, {"step": step, "type": "model", "text": response.text})

            if not response.tool_calls:
                idle_turns += 1
                if idle_turns >= 3:
                    run.stop_reason = "model stopped calling tools"
                    return run
                messages.append(
                    {
                        "role": "user",
                        "content": "Use a tool to continue, or call finish if you are done.",
                    }
                )
                continue
            idle_turns = 0

            finish_summary = None
            for call in response.tool_calls:
                run.tool_calls += 1
                if call.parse_error:
                    result = f"ERROR: {call.parse_error}"
                elif call.name == "finish":
                    finish_summary = str(call.arguments.get("summary", ""))
                    result = "Finished."
                else:
                    result = self.toolbox.call(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                self._record(
                    run,
                    {
                        "step": step,
                        "type": "tool",
                        "name": call.name,
                        "arguments": call.arguments,
                        "result": result,
                    },
                )

            if finish_summary is not None:
                run.finished = True
                run.summary = finish_summary
                run.stop_reason = "finish"
                return run

        run.stop_reason = "step limit reached"
        return run

    def _task_message(self, issue: str) -> str:
        return (
            f"Issue to fix:\n{issue.strip()}\n\n"
            f"Files in the repository:\n{self.toolbox.list_files()}\n\n"
            "The run_tests tool builds the project and runs its tests."
        )

    @staticmethod
    def _assistant_message(response: LLMResponse) -> dict:
        message: dict = {"role": "assistant", "content": response.text or ""}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in response.tool_calls
            ]
        return message

    def _record(self, run: AgentRun, event: dict) -> None:
        run.events.append(event)
        if self.on_event:
            self.on_event(event)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
