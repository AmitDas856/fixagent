"""Run the agent on one issue and judge the result independently.

The repository is copied first, so the original is never touched. Success is
decided by running the tests here after the agent stops, not by what the model
says about its own work.
"""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .agent import Agent, AgentRun
from .languages import IGNORED_DIRS, default_test_command, detect_language
from .llm import LLM
from .tools import Toolbox


@dataclass
class FixResult:
    success: bool
    language: str
    failing_before: bool
    patch: str
    summary: str
    steps: int
    tool_calls: int
    stop_reason: str
    seconds: float
    test_output: str
    workdir: Path
    run: AgentRun

    @property
    def status(self) -> str:
        if not self.failing_before:
            return "tests already passed before the agent ran"
        return "fixed" if self.success else "not fixed"


def fix_issue(
    repo: Path | str,
    issue: str,
    llm: LLM,
    test_command: list[str] | None = None,
    max_steps: int = 30,
    workdir: Path | None = None,
    log_path: Path | None = None,
    timeout: float = 180.0,
    on_event: Callable[[dict], None] | None = None,
) -> FixResult:
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise FileNotFoundError(f"repository not found: {repo}")

    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="fixagent-")) / repo.name
    workdir = Path(workdir).resolve()
    shutil.copytree(repo, workdir, ignore=shutil.ignore_patterns(*IGNORED_DIRS))

    command = test_command or default_test_command(workdir)
    toolbox = Toolbox(workdir, command, timeout=timeout)

    started = time.monotonic()
    passed_before, _ = toolbox.tests_pass()
    run = Agent(
        llm, toolbox, max_steps=max_steps, log_path=log_path, on_event=on_event
    ).run(issue)
    passed_after, output = toolbox.tests_pass()
    # Only files the agent wrote go in the patch, so build by-products such as
    # lock files and compiled programs never end up in it.
    patch = make_patch(repo, workdir, only=toolbox.edited_files)

    return FixResult(
        # A fix needs a real code change that turns failing tests green.
        success=passed_after and not passed_before and bool(patch),
        language=detect_language(repo),
        failing_before=not passed_before,
        patch=patch,
        summary=run.summary,
        steps=run.steps,
        tool_calls=run.tool_calls,
        stop_reason=run.stop_reason,
        seconds=time.monotonic() - started,
        test_output=output,
        workdir=workdir,
        run=run,
    )


def _text_files(root: Path) -> dict[str, list[str]]:
    files: dict[str, list[str]] = {}
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in IGNORED_DIRS]
        for name in names:
            path = Path(directory) / name
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binaries such as compiled test programs
            files[path.relative_to(root).as_posix()] = text.splitlines(keepends=True)
    return files


def make_patch(original: Path, modified: Path, only: set[str] | None = None) -> str:
    """Unified diff of the text files that differ between two directories.
    If ``only`` is given, just those relative paths are compared."""
    before, after = _text_files(original), _text_files(modified)
    names = set(before) | set(after)
    if only is not None:
        names &= {Path(name).as_posix() for name in only}
    chunks: list[str] = []
    for name in sorted(names):
        old, new = before.get(name, []), after.get(name, [])
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{name}" if name in before else "/dev/null",
                tofile=f"b/{name}" if name in after else "/dev/null",
            )
        )
    patch = "".join(line if line.endswith("\n") else line + "\n" for line in chunks)
    return patch
