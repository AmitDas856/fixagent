import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEMO_REPOS = PROJECT_ROOT / "demo_repos"

# The scripted "model" for each demo task: the tool calls a real model would be
# expected to make. These let the full loop run offline.
MEDIAN_FIX = (
    "    middle = len(ordered) // 2\n    return ordered[middle]",
    "    middle = len(ordered) // 2\n"
    "    if len(ordered) % 2 == 0:\n"
    "        return (ordered[middle - 1] + ordered[middle]) / 2\n"
    "    return ordered[middle]",
)
TRIM_FIX = ("last - first);", "last - first + 1);")
WORDCOUNT_FIX = ("text.split(' ').count()", "text.split_whitespace().count()")


def script_for(file: str, old: str, new: str, summary: str) -> list:
    return [
        [("run_tests", {})],
        [("read_file", {"path": file})],
        [("edit_file", {"path": file, "old_text": old, "new_text": new})],
        [("run_tests", {})],
        [("finish", {"summary": summary})],
    ]


SCRIPTS = {
    "py_stats_median": script_for("stats.py", *MEDIAN_FIX, "Averaged the two middle values."),
    "cpp_strutil_trim": script_for("strutil.cpp", *TRIM_FIX, "Fixed off-by-one in substr length."),
    "rs_wordcount_spaces": script_for(
        "src/lib.rs", *WORDCOUNT_FIX, "Split on any whitespace."
    ),
}


@pytest.fixture
def py_repo(tmp_path):
    """A private copy of the Python demo repo."""
    target = tmp_path / "py_stats"
    shutil.copytree(DEMO_REPOS / "py_stats", target)
    return target


def needs(*programs):
    missing = [p for p in programs if shutil.which(p) is None]
    return pytest.mark.skipif(bool(missing), reason=f"missing: {', '.join(missing)}")
