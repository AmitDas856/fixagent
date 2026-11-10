import sys

import pytest

from fixagent.languages import default_test_command, detect_language, is_test_path
from fixagent.tools import Toolbox, find_codesearch, truncate
from pathlib import Path

from conftest import DEMO_REPOS


@pytest.fixture
def box(py_repo):
    # codesearch_bin=None plus this flag forces the pure-Python search path.
    toolbox = Toolbox(py_repo, [sys.executable, "-m", "pytest", "-q"])
    toolbox.codesearch_bin = None
    return toolbox


def test_list_files(box):
    assert box.list_files().splitlines() == ["stats.py", "tests/test_stats.py"]


def test_read_file_has_line_numbers(box):
    output = box.read_file("stats.py", start_line=10, end_line=11)
    assert "   10 | def median(values):" in output
    assert "showing lines 10-11" in output


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "tests/../../x"])
def test_paths_outside_repo_are_rejected(box, path):
    assert "outside the repository" in box.call("read_file", {"path": path})
    assert "outside the repository" in box.call("write_file", {"path": path, "content": "x"})


def test_symlink_escape_is_rejected(box, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (box.root / "link.txt").symlink_to(secret)
    assert "outside the repository" in box.call("read_file", {"path": "link.txt"})


def test_edit_file_replaces_unique_text(box):
    result = box.call(
        "edit_file",
        {"path": "stats.py", "old_text": "return ordered[middle]", "new_text": "return 0"},
    )
    assert result == "Edited stats.py."
    assert "return 0" in (box.root / "stats.py").read_text()
    assert box.edited_files == {"stats.py"}


def test_edit_file_rejects_missing_and_ambiguous_text(box):
    missing = box.call("edit_file", {"path": "stats.py", "old_text": "nope", "new_text": "x"})
    assert "not found" in missing
    ambiguous = box.call(
        "edit_file", {"path": "stats.py", "old_text": "if not values:", "new_text": "x"}
    )
    assert "matches 3 places" in ambiguous
    assert box.edited_files == set()


def test_test_files_are_read_only(box):
    before = (box.root / "tests/test_stats.py").read_text()
    edit = box.call(
        "edit_file",
        {"path": "tests/test_stats.py", "old_text": "== 2.5", "new_text": "== 3"},
    )
    write = box.call("write_file", {"path": "tests/test_stats.py", "content": ""})
    assert "read-only" in edit and "read-only" in write
    assert (box.root / "tests/test_stats.py").read_text() == before
    assert "import pytest" in box.read_file("tests/test_stats.py")


def test_run_tests_reports_failure(box):
    output = box.run_tests()
    assert output.startswith("Tests FAILED")
    assert "test_median_even_length" in output


@pytest.mark.parametrize("command", ["rm -rf .", "curl http://example.com", "/bin/sh -c ls", "sh x"])
def test_disallowed_commands_are_blocked(box, command):
    assert "is not allowed" in box.call("run_command", {"command": command})


def test_allowed_command_runs_without_shell(box):
    # '&&' is passed as a plain argument, not interpreted by a shell.
    output = box.call("run_command", {"command": "python3 -c \"print('hi')\" && echo no"})
    assert "exit code 0" in output and "hi" in output and "no" not in output.split("hi")[1]


def test_command_timeout(py_repo):
    box = Toolbox(py_repo, [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    passed, output = box.tests_pass()
    assert not passed and "timed out" in output


def test_unknown_tool_and_bad_arguments(box):
    assert "unknown tool" in box.call("delete_everything", {})
    assert "bad arguments" in box.call("read_file", {"nope": 1})


def test_search_code_python(box):
    output = box.search_code("def median")
    assert output == "stats.py:10:def median(values):"
    assert "No matches" in box.search_code("zzz_not_there")


def test_rust_search_matches_python_search(py_repo):
    binary = find_codesearch()
    if binary is None:
        pytest.skip("Rust codesearch binary not built")
    fast = Toolbox(py_repo, ["true"], codesearch_bin=binary)
    slow = Toolbox(py_repo, ["true"])
    slow.codesearch_bin = None
    for pattern in ["median", "import", "values) ==", "zzz_not_there"]:
        assert fast.search_code(pattern) == slow.search_code(pattern)


def test_truncate_keeps_both_ends():
    text = "A" * 5000 + "B" * 5000
    short = truncate(text, limit=100)
    assert short.startswith("A" * 50) and short.endswith("B" * 50)
    assert "characters omitted" in short


def test_language_detection():
    assert detect_language(DEMO_REPOS / "py_stats") == "python"
    assert detect_language(DEMO_REPOS / "cpp_strutil") == "cpp"
    assert detect_language(DEMO_REPOS / "rs_wordcount") == "rust"
    assert default_test_command(DEMO_REPOS / "rs_wordcount")[:2] == ["cargo", "test"]
    assert default_test_command(DEMO_REPOS / "cpp_strutil") == ["make", "test"]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tests/test_stats.py", True),
        ("tests/wordcount.rs", True),
        ("src/parser_test.cpp", True),
        ("test_utils.py", True),
        ("src/lib.rs", False),
        ("stats.py", False),
        ("src/contest.py", False),
        ("latest/report.py", False),
    ],
)
def test_is_test_path(path, expected):
    assert is_test_path(Path(path)) is expected
