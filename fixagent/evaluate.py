"""Run the agent over a set of tasks and report the fix rate.

A tasks file is JSON: a list of {"name", "repo", "issue"} objects, where
"repo" is a path relative to the tasks file.

    python -m fixagent.evaluate demo_repos/tasks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from .llm import LLM, LLMError, OpenAICompatLLM
from .runner import FixResult, fix_issue


def load_tasks(tasks_file: Path) -> list[dict]:
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    for task in tasks:
        task["repo"] = str((tasks_file.parent / task["repo"]).resolve())
    return tasks


def evaluate(
    tasks: list[dict],
    llm_for_task: Callable[[dict], LLM],
    max_steps: int = 30,
) -> list[dict]:
    rows = []
    for task in tasks:
        try:
            result: FixResult = fix_issue(
                task["repo"], task["issue"], llm_for_task(task), max_steps=max_steps
            )
            rows.append(
                {
                    "name": task["name"],
                    "language": result.language,
                    "fixed": result.success,
                    "status": result.status,
                    "steps": result.steps,
                    "tool_calls": result.tool_calls,
                    "seconds": round(result.seconds, 1),
                }
            )
        except LLMError as exc:
            rows.append(
                {
                    "name": task["name"],
                    "language": "?",
                    "fixed": False,
                    "status": f"error: {exc}",
                    "steps": 0,
                    "tool_calls": 0,
                    "seconds": 0.0,
                }
            )
    return rows


def format_report(rows: list[dict]) -> str:
    lines = [f"{'task':<22}{'language':<10}{'fixed':<7}{'steps':<7}{'seconds':<8}"]
    for row in rows:
        lines.append(
            f"{row['name']:<22}{row['language']:<10}{'yes' if row['fixed'] else 'no':<7}"
            f"{row['steps']:<7}{row['seconds']:<8}"
        )
    fixed = sum(1 for row in rows if row["fixed"])
    rate = 100 * fixed / len(rows) if rows else 0.0
    lines.append(f"\nFix rate: {fixed}/{len(rows)} ({rate:.0f}%)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixagent.evaluate")
    parser.add_argument("tasks", help="Path to a tasks JSON file.")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--out", default="eval_results.json")
    args = parser.parse_args(argv)

    try:
        llm = OpenAICompatLLM()
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rows = evaluate(load_tasks(Path(args.tasks)), lambda task: llm, args.max_steps)
    print(format_report(rows))
    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
