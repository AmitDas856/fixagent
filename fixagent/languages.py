"""Language detection and default test commands for a repository."""

from __future__ import annotations

import sys
from pathlib import Path

# Directories the agent never lists, searches, diffs or copies.
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "target",
    "build",
    "node_modules",
    ".venv",
    "venv",
}


def detect_language(repo: Path) -> str:
    """Return "hack", "rust", "cpp", "python" or "unknown" for a repository."""
    if (repo / ".hhconfig").exists():
        return "hack"
    if (repo / "Cargo.toml").exists():
        return "rust"
    if (repo / "Makefile").exists() or (repo / "CMakeLists.txt").exists():
        return "cpp"
    if (repo / "pyproject.toml").exists() or any(repo.rglob("*.py")):
        return "python"
    return "unknown"


def default_test_command(repo: Path) -> list[str]:
    """Pick the command that runs the repository's tests."""
    language = detect_language(repo)
    if language == "hack":
        # Convention used here: a Hack entry point at tests/run_tests.hack.
        return ["hhvm", "tests/run_tests.hack"]
    if language == "rust":
        return ["cargo", "test", "--quiet"]
    if language == "cpp":
        if (repo / "Makefile").exists():
            return ["make", "test"]
        return ["sh", "-c", "cmake -S . -B build && cmake --build build && ctest --test-dir build"]
    if language == "python":
        return [sys.executable, "-m", "pytest", "-q"]
    raise ValueError(
        f"Could not work out how to run tests in {repo}. Pass a test command."
    )


def is_test_path(relative: Path) -> bool:
    """True for files that hold tests. The agent may read these but not edit
    them, so it cannot "fix" a bug by weakening the test that catches it."""
    parts = [p.lower() for p in relative.parts]
    if any(p in ("tests", "test") for p in parts[:-1]):
        return True
    name = relative.name.lower()
    stem = name.rsplit(".", 1)[0]
    return stem.startswith("test_") or stem.endswith("_test")
