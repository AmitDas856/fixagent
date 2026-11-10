"""Web server for the dashboard.

Serves a small JSON API and the built React app from ``dashboard/dist``.

    python -m fixagent.server --tasks demo_repos/tasks.json

Runs use a real model when FIXAGENT_MODEL and FIXAGENT_BASE_URL are set.
Otherwise the server is in demo mode and replays a scripted model, which the
API and the dashboard both label clearly.

The server only runs the tasks listed in the tasks file, and listens on
127.0.0.1 by default. It has no login, so do not expose it to a network.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .demo import DEMO_SCRIPTS, scripted_llm
from .evaluate import load_tasks
from .languages import detect_language
from .llm import LLM, LLMError, OpenAICompatLLM
from .runner import fix_issue

MAX_BODY_BYTES = 64 * 1024
MAX_RUNS_KEPT = 50
DEFAULT_DIST = Path(__file__).resolve().parent.parent / "dashboard" / "dist"


class RunStore:
    """Holds runs in memory and executes each one on its own thread."""

    def __init__(self, tasks: list[dict], max_steps: int = 30) -> None:
        self.tasks = {task["name"]: task for task in tasks}
        self.max_steps = max_steps
        self._runs: dict[str, dict] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self.model = os.environ.get("FIXAGENT_MODEL", "")
        self.mode = "model" if self.model and os.environ.get("FIXAGENT_BASE_URL") else "demo"

    # ----- read side ------------------------------------------------------

    def config(self) -> dict:
        return {"mode": self.mode, "model": self.model if self.mode == "model" else None}

    def task_list(self) -> list[dict]:
        return [
            {
                "name": task["name"],
                "issue": task["issue"],
                "language": detect_language(Path(task["repo"])),
                "runnable": self.mode == "model" or task["name"] in DEMO_SCRIPTS,
            }
            for task in self.tasks.values()
        ]

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            run = self._runs.get(run_id)
            return json.loads(json.dumps(run)) if run else None

    def summaries(self) -> list[dict]:
        with self._lock:
            return [
                {key: value for key, value in self._runs[run_id].items() if key != "events"}
                | {"result": _without_bulk(self._runs[run_id]["result"])}
                for run_id in reversed(self._order)
            ]

    # ----- write side -----------------------------------------------------

    def start(self, task_name: str) -> dict:
        task = self.tasks.get(task_name)
        if task is None:
            raise KeyError(task_name)
        if self.mode == "demo" and task_name not in DEMO_SCRIPTS:
            raise ValueError(f"'{task_name}' has no demo script. Set a model to run it.")
        run = {
            "id": uuid.uuid4().hex[:12],
            "task": task_name,
            "issue": task["issue"],
            "language": detect_language(Path(task["repo"])),
            "mode": self.mode,
            "model": self.model if self.mode == "model" else None,
            "status": "running",
            "started_at": time.time(),
            "seconds": 0.0,
            "events": [],
            "result": None,
            "error": None,
        }
        with self._lock:
            self._runs[run["id"]] = run
            self._order.append(run["id"])
            while len(self._order) > MAX_RUNS_KEPT:
                self._runs.pop(self._order.pop(0), None)
        thread = threading.Thread(target=self._execute, args=(run["id"], task), daemon=True)
        thread.start()
        return self.get(run["id"])  # type: ignore[return-value]

    def _llm(self, task_name: str) -> LLM:
        return OpenAICompatLLM() if self.mode == "model" else scripted_llm(task_name)

    def _execute(self, run_id: str, task: dict) -> None:
        started = time.monotonic()

        def on_event(event: dict) -> None:
            stamped = dict(event, t=round(time.monotonic() - started, 2))
            with self._lock:
                if run_id in self._runs:
                    self._runs[run_id]["events"].append(stamped)

        try:
            result = fix_issue(
                task["repo"],
                task["issue"],
                self._llm(task["name"]),
                max_steps=self.max_steps,
                on_event=on_event,
            )
            update = {
                "status": "done",
                "result": {
                    "success": result.success,
                    "status": result.status,
                    "steps": result.steps,
                    "tool_calls": result.tool_calls,
                    "stop_reason": result.stop_reason,
                    "summary": result.summary,
                    "patch": result.patch,
                    "test_output": result.test_output[-4000:],
                },
            }
        except (LLMError, OSError, ValueError) as exc:
            update = {"status": "error", "error": str(exc)}
        update["seconds"] = round(time.monotonic() - started, 2)
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].update(update)


def _without_bulk(result: dict | None) -> dict | None:
    if result is None:
        return None
    return {key: value for key, value in result.items() if key not in ("patch", "test_output")}


def make_handler(store: RunStore, dist: Path) -> type[BaseHTTPRequestHandler]:
    dist = dist.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "fixagent"

        def log_message(self, *args) -> None:  # keep the console quiet
            pass

        def _json(self, status: int, payload) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/config":
                return self._json(200, store.config())
            if path == "/api/tasks":
                return self._json(200, store.task_list())
            if path == "/api/runs":
                return self._json(200, store.summaries())
            if path.startswith("/api/runs/"):
                run = store.get(path.removeprefix("/api/runs/"))
                if run is None:
                    return self._json(404, {"error": "run not found"})
                return self._json(200, run)
            if path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            self._static(path)

        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != "/api/runs":
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                return self._json(413, {"error": "request body too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                task_name = body["task"]
                if not isinstance(task_name, str):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                return self._json(400, {"error": 'send JSON like {"task": "<task name>"}'})
            try:
                run = store.start(task_name)
            except KeyError:
                return self._json(400, {"error": f"unknown task '{task_name}'"})
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            self._json(201, run)

        def _static(self, path: str) -> None:
            if not dist.is_dir():
                message = (
                    "The dashboard has not been built yet. "
                    "Run 'npm install' and 'npm run build' in the dashboard folder."
                )
                data = message.encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            target = (dist / path.lstrip("/")).resolve()
            inside = target == dist or dist in target.parents
            if not inside or not target.is_file():
                target = dist / "index.html"  # single-page app fallback
            data = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def create_server(
    tasks_file: Path, host: str = "127.0.0.1", port: int = 8000, dist: Path = DEFAULT_DIST
) -> tuple[ThreadingHTTPServer, RunStore]:
    store = RunStore(load_tasks(Path(tasks_file)))
    server = ThreadingHTTPServer((host, port), make_handler(store, Path(dist)))
    return server, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fixagent.server")
    parser.add_argument("--tasks", default="demo_repos/tasks.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server, store = create_server(Path(args.tasks), args.host, args.port)
    mode = f"model {store.model}" if store.mode == "model" else "demo mode (scripted model)"
    print(f"fixagent dashboard: http://{args.host}:{server.server_port}  [{mode}]")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
