"""End-to-end tests of the agent loop, using a scripted model so they run
offline. They check the loop, the tools and the independent verification."""

import json

import pytest

from fixagent import ScriptedLLM, fix_issue
from fixagent.evaluate import evaluate, format_report, load_tasks
from fixagent.llm import LLMError, OpenAICompatLLM, parse_chat_completion

from conftest import DEMO_REPOS, MEDIAN_FIX, SCRIPTS, needs

TASKS = {task["name"]: task for task in load_tasks(DEMO_REPOS / "tasks.json")}


def run_task(name, script=None, **kwargs):
    task = TASKS[name]
    return fix_issue(task["repo"], task["issue"], ScriptedLLM(script or SCRIPTS[name]), **kwargs)


def test_fixes_python_bug():
    result = run_task("py_stats_median")
    assert result.success and result.failing_before
    assert result.language == "python"
    assert result.stop_reason == "finish"
    assert result.steps == 5 and result.tool_calls == 5
    assert "+++ b/stats.py" in result.patch
    assert "+        return (ordered[middle - 1] + ordered[middle]) / 2" in result.patch


@needs("make", "g++")
def test_fixes_cpp_bug():
    result = run_task("cpp_strutil_trim")
    assert result.success and result.language == "cpp"
    assert "+    return text.substr(first, last - first + 1);" in result.patch
    # Only the edited source file is in the patch, not the compiled program.
    assert result.patch.count("+++ ") == 1


@needs("cargo")
def test_fixes_rust_bug():
    result = run_task("rs_wordcount_spaces")
    assert result.success and result.language == "rust"
    assert "+    text.split_whitespace().count()" in result.patch
    assert "Cargo.lock" not in result.patch


def test_original_repo_is_never_modified():
    original = (DEMO_REPOS / "py_stats" / "stats.py").read_text()
    result = run_task("py_stats_median")
    assert (DEMO_REPOS / "py_stats" / "stats.py").read_text() == original
    assert (result.workdir / "stats.py").read_text() != original


def test_wrong_fix_is_not_reported_as_success():
    """The model claims success, but the tests still fail. The runner checks
    the tests itself, so the result must be a failure."""
    script = [
        [("edit_file", {"path": "stats.py", "old_text": "ordered[middle]", "new_text": "ordered[0]"})],
        [("finish", {"summary": "Fixed it!"})],
    ]
    result = run_task("py_stats_median", script)
    assert result.run.finished and result.summary == "Fixed it!"
    assert not result.success and result.status == "not fixed"


def test_finish_without_any_change_is_not_success():
    result = run_task("py_stats_median", [[("finish", {"summary": "Looks fine."})]])
    assert not result.success and result.patch == ""


def test_cannot_pass_by_editing_the_tests():
    script = [
        [("write_file", {"path": "tests/test_stats.py", "content": "def test_ok():\n    pass\n"})],
        [("finish", {"summary": "Tests pass now."})],
    ]
    result = run_task("py_stats_median", script)
    assert not result.success
    assert "read-only" in result.run.events[1]["result"]


def test_step_limit_stops_the_agent():
    script = [[("list_files", {})]] * 50
    result = run_task("py_stats_median", script, max_steps=4)
    assert result.steps == 4 and result.stop_reason == "step limit reached"
    assert not result.success


def test_model_that_only_talks_is_nudged_then_stopped():
    llm = ScriptedLLM(["I think the bug is in median."] * 5)
    task = TASKS["py_stats_median"]
    result = fix_issue(task["repo"], task["issue"], llm)
    assert result.stop_reason == "model stopped calling tools" and result.steps == 3
    assert llm.seen_messages[1][-1]["content"].startswith("Use a tool to continue")


def test_tool_errors_are_sent_back_so_the_model_can_recover():
    old, new = MEDIAN_FIX
    script = [
        [("edit_file", {"path": "stats.py", "old_text": "not in the file", "new_text": "x"})],
        [("edit_file", {"path": "stats.py", "old_text": old, "new_text": new})],
        [("finish", {"summary": "done"})],
    ]
    llm = ScriptedLLM(script)
    task = TASKS["py_stats_median"]
    result = fix_issue(task["repo"], task["issue"], llm)
    assert result.success
    tool_message = llm.seen_messages[1][-1]
    assert tool_message["role"] == "tool" and "old_text was not found" in tool_message["content"]


def test_messages_follow_the_chat_tool_calling_format():
    llm = ScriptedLLM(SCRIPTS["py_stats_median"])
    task = TASKS["py_stats_median"]
    fix_issue(task["repo"], task["issue"], llm)
    first, second = llm.seen_messages[0], llm.seen_messages[1]
    assert [m["role"] for m in first] == ["system", "user"]
    assert "median() returns the wrong value" in first[1]["content"]
    assert "stats.py" in first[1]["content"]
    assistant, tool = second[2], second[3]
    call = assistant["tool_calls"][0]
    assert call["type"] == "function" and call["function"]["name"] == "run_tests"
    assert json.loads(call["function"]["arguments"]) == {}
    assert tool["tool_call_id"] == call["id"] and tool["content"].startswith("Tests FAILED")


def test_trajectory_log_is_written(tmp_path):
    log = tmp_path / "run.jsonl"
    run_task("py_stats_median", log_path=log)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    tools = [e["name"] for e in events if e["type"] == "tool"]
    assert tools == ["run_tests", "read_file", "edit_file", "run_tests", "finish"]


@needs("make", "g++", "cargo")
def test_evaluation_reports_fix_rate():
    tasks = list(TASKS.values())
    # One task gets a model that gives up, so the rate is 2 out of 3.
    scripts = dict(SCRIPTS, cpp_strutil_trim=[[("finish", {"summary": "gave up"})]])
    rows = evaluate(tasks, lambda task: ScriptedLLM(scripts[task["name"]]))
    assert [row["fixed"] for row in rows] == [True, False, True]
    assert "Fix rate: 2/3 (67%)" in format_report(rows)


def test_parse_chat_completion():
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "abc",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                        },
                        {"id": "bad", "function": {"name": "edit_file", "arguments": "{oops"}},
                    ],
                }
            }
        ]
    }
    response = parse_chat_completion(payload)
    assert response.text == ""
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == {"path": "a.py"}
    assert response.tool_calls[1].parse_error.startswith("invalid tool arguments")
    with pytest.raises(LLMError):
        parse_chat_completion({"error": "nope"})


def test_llm_client_needs_settings(monkeypatch):
    for name in ("FIXAGENT_MODEL", "FIXAGENT_BASE_URL", "FIXAGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LLMError, match="FIXAGENT_MODEL, FIXAGENT_BASE_URL"):
        OpenAICompatLLM()
