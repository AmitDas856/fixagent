"""Tests the pull request step against a local git remote and a stand-in for
the gh command, so nothing is sent to GitHub."""

import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

from fixagent import cli
from fixagent.pullrequest import (
    PullRequestError,
    fetch_issue,
    make_body,
    make_title,
    open_pull_request,
    slugify,
)

from conftest import DEMO_REPOS, SCRIPTS, needs
from test_http_client import FakeServer

pytestmark = needs("git")

FAKE_GH = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write("HTTP 401: Bad credentials")
    sys.exit(1)
if "/issues/" in sys.argv[2]:
    print(json.dumps({{"title": "median is wrong", "body": "Even-length lists give the wrong answer."}}))
else:
    print(json.dumps({{"html_url": "https://github.com/example/demo/pull/7"}}))
"""

PATCH = """\
--- a/stats.py
+++ b/stats.py
@@ -13,7 +13,7 @@
         raise ValueError("median of empty list")
     ordered = sorted(values)
     middle = len(ordered) // 2
-    return ordered[middle]
+    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


 def value_range(values):
"""


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def gh_log(tmp_path, monkeypatch):
    """Puts a fake gh first on PATH and returns a function that reads its calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(FAKE_GH)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    for key, value in {
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    return lambda: [json.loads(line) for line in log.read_text().splitlines()]


@pytest.fixture
def repo(tmp_path, gh_log):
    """A git checkout of the Python demo repo with a local bare 'origin'."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    shutil.copytree(DEMO_REPOS / "py_stats", work)
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "initial")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "-u", "origin", "main")
    return work


def test_opens_pull_request_on_a_new_branch(repo, gh_log):
    main_before = git(repo, "rev-parse", "main")
    pull = open_pull_request(repo, PATCH, "Fix: median is wrong", "the body")

    assert pull.url == "https://github.com/example/demo/pull/7"
    assert pull.base == "main" and pull.branch.startswith("fixagent/median-is-wrong-")
    # The fix is on the pushed branch only; main is untouched and checked out again.
    assert "ordered[middle - 1]" in git(repo, "show", f"origin/{pull.branch}:stats.py")
    assert git(repo, "rev-parse", "main") == main_before
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "ordered[middle - 1]" not in (repo / "stats.py").read_text()
    assert git(repo, "log", "-1", "--format=%s", pull.branch) == "Fix: median is wrong"

    (call,) = gh_log()
    assert call[:2] == ["api", "repos/{owner}/{repo}/pulls"]
    assert f"head={pull.branch}" in call and "base=main" in call
    assert "title=Fix: median is wrong" in call and "body=the body" in call


def test_works_when_the_project_is_a_subdirectory(tmp_path, gh_log):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    top = tmp_path / "mono"
    shutil.copytree(DEMO_REPOS / "py_stats", top / "services" / "stats")
    git(top, "init", "-q", "-b", "main")
    git(top, "add", "-A")
    git(top, "commit", "-q", "-m", "initial")
    git(top, "remote", "add", "origin", str(origin))

    pull = open_pull_request(top / "services" / "stats", PATCH, "Fix: median", "body")
    fixed = git(top, "show", f"origin/{pull.branch}:services/stats/stats.py")
    assert "ordered[middle - 1]" in fixed


def test_refuses_uncommitted_changes(repo, gh_log):
    (repo / "stats.py").write_text("# work in progress\n")
    with pytest.raises(PullRequestError, match="uncommitted changes"):
        open_pull_request(repo, PATCH, "Fix: x", "body")
    assert (repo / "stats.py").read_text() == "# work in progress\n"
    assert gh_log() == [] and git(repo, "branch", "--list", "fixagent/*") == ""


def test_refuses_non_git_directory_and_empty_patch(tmp_path, gh_log):
    with pytest.raises(PullRequestError, match="not a git repository"):
        open_pull_request(tmp_path, PATCH, "Fix: x", "body")
    with pytest.raises(PullRequestError, match="no patch"):
        open_pull_request(tmp_path, "", "Fix: x", "body")


def test_patch_that_does_not_apply_leaves_no_branch(repo, gh_log):
    bad = PATCH.replace("return ordered[middle]\n", "return something_else\n")
    with pytest.raises(PullRequestError, match="git apply"):
        open_pull_request(repo, bad, "Fix: x", "body")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(repo, "branch", "--list", "fixagent/*") == ""
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_github_failure_is_reported_with_the_pushed_branch(repo, gh_log, monkeypatch):
    monkeypatch.setenv("FAKE_GH_FAIL", "1")
    with pytest.raises(PullRequestError, match="was pushed, but the pull request could not be opened"):
        open_pull_request(repo, PATCH, "Fix: x", "body", branch="fixagent/manual")
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "ordered[middle - 1]" in git(repo, "show", "origin/fixagent/manual:stats.py")


def test_fetch_issue(repo, gh_log):
    text = fetch_issue(repo, 12)
    assert text == "median is wrong\n\nEven-length lists give the wrong answer."
    assert gh_log()[0] == ["api", "repos/{owner}/{repo}/issues/12"]


def test_title_body_and_slug():
    assert make_title("median() is wrong\nmore detail") == "Fix: median() is wrong"
    assert len(make_title("x" * 200)) == 65 and make_title("x" * 200).endswith("...")
    assert slugify(" Median() is WRONG!! ") == "median-is-wrong"
    assert slugify("???") == "fix"
    body = make_body("the issue", "the summary", issue_number=12)
    assert body.startswith("Fixes #12") and "the issue" in body and "the summary" in body
    assert "Fixes #" not in make_body("the issue", "")


@pytest.fixture
def model(monkeypatch):
    def start(script):
        server = FakeServer(script)
        monkeypatch.setenv("FIXAGENT_MODEL", "test-model")
        monkeypatch.setenv("FIXAGENT_BASE_URL", server.url)
        servers.append(server)
        return server

    servers = []
    yield start
    for server in servers:
        server.close()


def test_command_line_fixes_a_github_issue_and_opens_a_pull_request(
    repo, gh_log, model, tmp_path, capsys
):
    model(SCRIPTS["py_stats_median"])
    code = cli.main(
        ["--repo", str(repo), "--github-issue", "12", "--open-pr", "--out", str(tmp_path / "p")]
    )
    output = capsys.readouterr().out
    assert code == 0 and "Result:     fixed" in output
    assert "Pull request: https://github.com/example/demo/pull/7 (fixagent/median-is-wrong-" in output

    issue_call, pull_call = gh_log()
    assert issue_call[1].endswith("/issues/12")
    assert "title=Fix: median is wrong" in pull_call
    body = next(arg for arg in pull_call if arg.startswith("body="))
    assert "Fixes #12" in body and "Averaged the two middle values." in body
    branch = next(arg for arg in pull_call if arg.startswith("head=")).removeprefix("head=")
    assert "(ordered[middle - 1] + ordered[middle]) / 2" in git(repo, "show", f"origin/{branch}:stats.py")


def test_command_line_opens_no_pull_request_for_an_unverified_fix(repo, gh_log, model, tmp_path, capsys):
    model([[("finish", {"summary": "Looks fine to me."})]])
    code = cli.main(
        ["--repo", str(repo), "--issue", "median is wrong", "--open-pr", "--out", str(tmp_path / "p")]
    )
    assert code == 1
    assert "not opened, because the fix was not verified" in capsys.readouterr().out
    assert gh_log() == [] and git(repo, "branch", "-a", "--list", "*fixagent*") == ""
