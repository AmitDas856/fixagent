"""Turn a verified fix into a GitHub pull request.

The fix is committed on a new branch, never on the branch you are working on.
GitHub is reached through the ``gh`` command line tool, so you must have it
installed and signed in (``gh auth login``).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class PullRequestError(RuntimeError):
    pass


@dataclass
class PullRequest:
    url: str
    branch: str
    base: str


def _run(repo: Path, argv: list[str], stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            argv, cwd=repo, input=stdin, capture_output=True, text=True, timeout=120
        )
    except FileNotFoundError as exc:
        raise PullRequestError(f"'{argv[0]}' is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise PullRequestError(f"'{' '.join(argv[:3])}' timed out") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:400]
        raise PullRequestError(f"'{' '.join(argv[:3])}' failed: {detail}")
    return result.stdout.strip()


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return _run(repo, ["git", *args], stdin=stdin)


def _gh_api(repo: Path, path: str, fields: dict[str, str] | None = None) -> dict:
    """Call the GitHub REST API. ``{owner}/{repo}`` in the path is filled in by
    gh from the repository's remote."""
    argv = ["gh", "api", path]
    for key, value in (fields or {}).items():
        argv += ["-f", f"{key}={value}"]
    output = _run(repo, argv)
    try:
        data = json.loads(output)
    except ValueError as exc:
        raise PullRequestError(f"unexpected reply from GitHub: {output[:200]}") from exc
    if not isinstance(data, dict):
        raise PullRequestError(f"unexpected reply from GitHub: {output[:200]}")
    return data


def slugify(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].strip("-") or "fix"


def make_title(issue: str, max_length: int = 60) -> str:
    lines = issue.strip().splitlines()
    first_line = lines[0].strip() if lines else "bug"
    if len(first_line) > max_length:
        first_line = first_line[: max_length - 3].rstrip() + "..."
    return f"Fix: {first_line}"


def make_body(issue: str, summary: str, issue_number: int | None = None) -> str:
    parts = []
    if issue_number is not None:
        parts.append(f"Fixes #{issue_number}")
    parts.append(f"## Issue\n{issue.strip()}")
    if summary.strip():
        parts.append(f"## What changed\n{summary.strip()}")
    parts.append(
        "## Checks\nThe test suite failed before this change and passes with it. "
        "Test files were not modified."
    )
    parts.append("Opened by fixagent. Please review before merging.")
    return "\n\n".join(parts)


def fetch_issue(repo: Path | str, number: int) -> str:
    """Read an issue's title and description from GitHub."""
    data = _gh_api(Path(repo), f"repos/{{owner}}/{{repo}}/issues/{int(number)}")
    title = str(data.get("title") or "").strip()
    body = str(data.get("body") or "").strip()
    if not title:
        raise PullRequestError(f"issue #{number} was not found")
    return f"{title}\n\n{body}".strip()


def open_pull_request(
    repo: Path | str,
    patch: str,
    title: str,
    body: str,
    branch: str | None = None,
    remote: str = "origin",
) -> PullRequest:
    repo = Path(repo).resolve()
    if not patch.strip():
        raise PullRequestError("there is no patch to open a pull request for")

    try:
        _git(repo, "rev-parse", "--is-inside-work-tree")
    except PullRequestError as exc:
        raise PullRequestError(f"{repo} is not a git repository") from exc
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise PullRequestError("the repository has uncommitted changes. Commit or stash them first.")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if base == "HEAD":
        raise PullRequestError("the repository is not on a branch")
    _git(repo, "remote", "get-url", remote)

    if branch is None:
        digest = hashlib.sha1(patch.encode("utf-8")).hexdigest()[:7]
        branch = f"fixagent/{slugify(title.removeprefix('Fix:'))}-{digest}"

    _git(repo, "checkout", "-b", branch)
    pushed = False
    try:
        _git(repo, "apply", "--index", "-", stdin=patch)
        _git(repo, "commit", "-m", title)
        _git(repo, "push", "-u", remote, branch)
        pushed = True
        data = _gh_api(
            repo,
            "repos/{owner}/{repo}/pulls",
            {"title": title, "head": branch, "base": base, "body": body},
        )
    except PullRequestError as exc:
        _git(repo, "checkout", "-f", base)
        if pushed:
            raise PullRequestError(
                f"branch '{branch}' was pushed, but the pull request could not be opened: {exc}"
            ) from exc
        _git(repo, "branch", "-D", branch)
        raise
    _git(repo, "checkout", base)

    url = str(data.get("html_url") or "")
    if not url:
        raise PullRequestError(f"branch '{branch}' was pushed, but GitHub returned no pull request link")
    return PullRequest(url=url, branch=branch, base=base)
