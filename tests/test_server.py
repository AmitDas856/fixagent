"""Tests the dashboard's API server over real HTTP on a local port."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from fixagent.languages import default_test_command, detect_language
from fixagent.server import create_server

from conftest import DEMO_REPOS, needs
from test_agent import run_task  # noqa: F401  (shared helper)


@pytest.fixture
def api(tmp_path, monkeypatch):
    for name in ("FIXAGENT_MODEL", "FIXAGENT_BASE_URL", "FIXAGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>fixagent</title>")
    (dist / "assets" / "app.js").write_text("console.log('app')")

    server, _ = create_server(DEMO_REPOS / "tasks.json", port=0, dist=dist)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=data)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                content = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            content, status = error.read(), error.code
        return status, (content.decode() if raw else json.loads(content))

    yield call
    server.shutdown()
    server.server_close()


def wait_for(api, run_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, run = api(f"/api/runs/{run_id}")
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish in time")


def test_config_reports_demo_mode_without_a_model(api):
    assert api("/api/config") == (200, {"mode": "demo", "model": None})


def test_tasks_are_listed_with_languages(api):
    status, tasks = api("/api/tasks")
    assert status == 200
    assert [(t["name"], t["language"]) for t in tasks] == [
        ("py_stats_median", "python"),
        ("cpp_strutil_trim", "cpp"),
        ("rs_wordcount_spaces", "rust"),
    ]
    assert all(t["runnable"] and t["issue"] for t in tasks)


def test_run_reports_steps_patch_and_verdict(api):
    status, started = api("/api/runs", {"task": "py_stats_median"})
    assert status == 201 and started["status"] == "running" and started["mode"] == "demo"

    run = wait_for(api, started["id"])
    assert run["status"] == "done" and run["error"] is None
    assert run["result"]["success"] is True and run["result"]["status"] == "fixed"
    assert "+++ b/stats.py" in run["result"]["patch"]
    tools = [event["name"] for event in run["events"] if event["type"] == "tool"]
    assert tools == ["run_tests", "read_file", "edit_file", "run_tests", "finish"]
    assert all("t" in event for event in run["events"])

    _, summaries = api("/api/runs")
    assert summaries[0]["id"] == run["id"] and "events" not in summaries[0]
    assert summaries[0]["result"]["success"] is True and "patch" not in summaries[0]["result"]


@pytest.mark.parametrize(
    "body, expected",
    [({"task": "nope"}, "unknown task"), ({}, "send JSON"), ({"task": 5}, "send JSON")],
)
def test_bad_run_requests_are_rejected(api, body, expected):
    status, reply = api("/api/runs", body)
    assert status == 400 and expected in reply["error"]
    assert api("/api/runs")[1] == []


def test_unknown_run_and_route_return_404(api):
    assert api("/api/runs/doesnotexist")[0] == 404
    assert api("/api/other")[0] == 404


def test_static_files_and_single_page_fallback(api):
    assert "<title>fixagent</title>" in api("/", raw=True)[1]
    assert api("/assets/app.js", raw=True)[1] == "console.log('app')"
    # Unknown paths and attempts to leave the folder both get the app page.
    assert "<title>fixagent</title>" in api("/runs/abc", raw=True)[1]
    assert "<title>fixagent</title>" in api("/../../etc/passwd", raw=True)[1]


def test_hack_project_is_detected():
    repo = DEMO_REPOS / "hack_cart"
    assert detect_language(repo) == "hack"
    assert default_test_command(repo) == ["hhvm", "tests/run_tests.hack"]


@needs("hhvm")
def test_fixes_hack_bug():
    from fixagent import fix_issue
    from fixagent.demo import scripted_llm
    from fixagent.evaluate import load_tasks

    (task,) = load_tasks(DEMO_REPOS / "tasks_hack.json")
    result = fix_issue(task["repo"], task["issue"], scripted_llm(task["name"]))
    assert result.success and result.language == "hack"
    assert "+    $total += $item[0] * $item[1];" in result.patch
