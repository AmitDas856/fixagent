"""The tools the agent can call.

Every tool is confined to one repository directory. Paths that escape it are
rejected, test files are read-only, and commands run without a shell from an
allowlist with a timeout.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable

from .languages import IGNORED_DIRS, is_test_path

MAX_OUTPUT_CHARS = 6000
MAX_SEARCH_RESULTS = 50
MAX_FILE_LINES = 400

ALLOWED_COMMANDS = {
    "pytest",
    "python",
    "python3",
    "make",
    "cmake",
    "ctest",
    "cargo",
    "g++",
    "gcc",
    "clang++",
    "rustc",
}


class ToolError(Exception):
    """Raised for mistakes the model can recover from. The message is sent
    back to the model as the tool result."""


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - 2 * half
    return f"{text[:half]}\n... [{dropped} characters omitted] ...\n{text[-half:]}"


class Toolbox:
    def __init__(
        self,
        root: Path,
        test_command: list[str],
        timeout: float = 180.0,
        codesearch_bin: Path | None = None,
        protect_tests: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.test_command = list(test_command)
        self.timeout = timeout
        self.codesearch_bin = codesearch_bin if codesearch_bin else find_codesearch()
        self.protect_tests = protect_tests
        self.edited_files: set[str] = set()
        self._handlers: dict[str, Callable[..., str]] = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "search_code": self.search_code,
            "edit_file": self.edit_file,
            "write_file": self.write_file,
            "run_tests": self.run_tests,
            "run_command": self.run_command,
        }

    # ----- dispatch -------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"ERROR: unknown tool '{name}'. Available: {', '.join(self._handlers)}, finish"
        try:
            return truncate(handler(**arguments))
        except ToolError as exc:
            return f"ERROR: {exc}"
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"

    # ----- path handling --------------------------------------------------

    def _resolve(self, path: str) -> Path:
        if not isinstance(path, str) or not path:
            raise ToolError("path must be a non-empty string")
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"path '{path}' is outside the repository")
        return candidate

    def _relative(self, path: Path) -> Path:
        return path.relative_to(self.root)

    def _check_writable(self, path: Path) -> None:
        relative = self._relative(path)
        if any(part in IGNORED_DIRS for part in relative.parts):
            raise ToolError(f"'{relative}' is in a build or system directory")
        if self.protect_tests and is_test_path(relative):
            raise ToolError(
                f"'{relative}' is a test file and is read-only. Fix the source code instead."
            )

    def _walk(self, start: Path):
        for directory, subdirs, files in os.walk(start):
            subdirs[:] = sorted(d for d in subdirs if d not in IGNORED_DIRS)
            for name in sorted(files):
                yield Path(directory) / name

    # ----- tools ----------------------------------------------------------

    def list_files(self, path: str = ".") -> str:
        start = self._resolve(path)
        if not start.is_dir():
            raise ToolError(f"'{path}' is not a directory")
        files = [str(self._relative(f)) for f in self._walk(start)]
        if not files:
            return "(no files)"
        return "\n".join(files[:500])

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"'{path}' is not a file")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ToolError(f"'{path}' is not a text file") from exc
        start = max(1, int(start_line))
        end = min(len(lines), int(end_line) if end_line else start + MAX_FILE_LINES - 1)
        numbered = [f"{n:>5} | {lines[n - 1]}" for n in range(start, end + 1)]
        footer = f"\n[showing lines {start}-{end} of {len(lines)}]" if lines else "(empty file)"
        return "\n".join(numbered) + footer

    def search_code(self, pattern: str, path: str = ".") -> str:
        """Literal, case-sensitive text search. Returns path:line:text."""
        if not pattern:
            raise ToolError("pattern must not be empty")
        start = self._resolve(path)
        if self.codesearch_bin:
            hits = self._search_with_binary(pattern, start)
        else:
            hits = self._search_python(pattern, start)
        if not hits:
            return f"No matches for '{pattern}'."
        shown = hits[:MAX_SEARCH_RESULTS]
        extra = len(hits) - len(shown)
        return "\n".join(shown) + (f"\n[{extra} more matches not shown]" if extra > 0 else "")

    def _search_python(self, pattern: str, start: Path) -> list[str]:
        hits: list[str] = []
        files = [start] if start.is_file() else self._walk(start)
        for file in files:
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    hits.append(f"{self._relative(file)}:{number}:{line.strip()}")
        return hits

    def _search_with_binary(self, pattern: str, start: Path) -> list[str]:
        try:
            result = subprocess.run(
                [str(self.codesearch_bin), pattern, str(start)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.root,
            )
        except (OSError, subprocess.TimeoutExpired):
            return self._search_python(pattern, start)
        if result.returncode not in (0, 1):
            return self._search_python(pattern, start)
        hits = []
        prefix = str(self.root) + os.sep
        for line in result.stdout.splitlines():
            hits.append(line[len(prefix):] if line.startswith(prefix) else line)
        return hits

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"'{path}' is not a file")
        self._check_writable(target)
        content = target.read_text(encoding="utf-8")
        count = content.count(old_text) if old_text else 0
        if count == 0:
            raise ToolError("old_text was not found. Read the file and copy the text exactly.")
        if count > 1:
            raise ToolError(
                f"old_text matches {count} places. Include more surrounding lines so it is unique."
            )
        target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        self.edited_files.add(str(self._relative(target)))
        return f"Edited {self._relative(target)}."

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        if target.is_dir():
            raise ToolError(f"'{path}' is a directory")
        self._check_writable(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.edited_files.add(str(self._relative(target)))
        return f"Wrote {self._relative(target)} ({len(content.splitlines())} lines)."

    def run_tests(self) -> str:
        code, output = self._run(self.test_command)
        status = "PASSED" if code == 0 else f"FAILED (exit code {code})"
        return f"Tests {status}\n{output}"

    def tests_pass(self) -> tuple[bool, str]:
        """Used by the runner to check the result independently of the model."""
        code, output = self._run(self.test_command)
        return code == 0, output

    def run_command(self, command: str) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ToolError(f"could not parse command: {exc}") from exc
        if not argv:
            raise ToolError("command is empty")
        if os.path.basename(argv[0]) not in ALLOWED_COMMANDS or os.sep in argv[0]:
            raise ToolError(
                f"'{argv[0]}' is not allowed. Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
            )
        code, output = self._run(argv)
        return f"exit code {code}\n{output}"

    def _run(self, argv: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                argv,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            return 127, f"command not found: {argv[0]}"
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {self.timeout:.0f} seconds"
        return result.returncode, (result.stdout + result.stderr).strip()

    # ----- schemas sent to the model --------------------------------------

    def specs(self) -> list[dict]:
        def spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
            return {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }

        string = {"type": "string"}
        return [
            spec(
                "list_files",
                "List files in the repository, or in one directory of it.",
                {"path": {**string, "description": "Directory, relative to the repo root."}},
                [],
            ),
            spec(
                "read_file",
                "Read a text file with line numbers.",
                {
                    "path": string,
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                ["path"],
            ),
            spec(
                "search_code",
                "Search for an exact piece of text across the repository. "
                "Returns matching lines as path:line:text.",
                {"pattern": string, "path": string},
                ["pattern"],
            ),
            spec(
                "edit_file",
                "Replace one exact piece of text in a file. old_text must appear "
                "exactly once. Test files cannot be edited.",
                {"path": string, "old_text": string, "new_text": string},
                ["path", "old_text", "new_text"],
            ),
            spec(
                "write_file",
                "Create a file or overwrite it completely.",
                {"path": string, "content": string},
                ["path", "content"],
            ),
            spec(
                "run_tests",
                "Build the project and run its test suite: " + shlex.join(self.test_command),
                {},
                [],
            ),
            spec(
                "run_command",
                "Run one build or test command (no shell features). Allowed: "
                + ", ".join(sorted(ALLOWED_COMMANDS)),
                {"command": string},
                ["command"],
            ),
            spec(
                "finish",
                "Call this once the tests pass, or when you cannot make progress.",
                {"summary": {**string, "description": "What was wrong and what you changed."}},
                ["summary"],
            ),
        ]


def find_codesearch() -> Path | None:
    """Locate the optional Rust search tool. Falls back to pure Python if absent."""
    override = os.environ.get("FIXAGENT_CODESEARCH")
    if override:
        return Path(override) if Path(override).is_file() else None
    project_root = Path(__file__).resolve().parent.parent
    for profile in ("release", "debug"):
        candidate = project_root / "tools" / "codesearch" / "target" / profile / "codesearch"
        if candidate.is_file():
            return candidate
    return None
