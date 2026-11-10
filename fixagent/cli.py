"""Command line: fix one issue in one repository."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .llm import LLMError, OpenAICompatLLM
from .runner import fix_issue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fixagent",
        description="AI agent that fixes a bug in a Python, C++ or Rust repository.",
    )
    parser.add_argument("--repo", required=True, help="Path to the repository.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue", help="The bug report, as text.")
    source.add_argument("--issue-file", help="File containing the bug report.")
    parser.add_argument("--test-cmd", help="Test command. Detected automatically if omitted.")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--out", default="fix.patch", help="Where to write the patch.")
    parser.add_argument("--log", help="Write the step-by-step trajectory here (JSON lines).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    issue = args.issue or Path(args.issue_file).read_text(encoding="utf-8")
    try:
        llm = OpenAICompatLLM()
        result = fix_issue(
            args.repo,
            issue,
            llm,
            test_command=shlex.split(args.test_cmd) if args.test_cmd else None,
            max_steps=args.max_steps,
            log_path=Path(args.log) if args.log else None,
        )
    except (LLMError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Language:   {result.language}")
    print(f"Result:     {result.status}")
    print(f"Steps:      {result.steps} ({result.tool_calls} tool calls, {result.seconds:.1f}s)")
    print(f"Stopped:    {result.stop_reason}")
    if result.summary:
        print(f"Summary:    {result.summary}")
    if result.patch:
        Path(args.out).write_text(result.patch, encoding="utf-8")
        print(f"Patch:      {args.out}")
    print(f"Working copy: {result.workdir}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
