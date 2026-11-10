"""Tests the real HTTP client and the command line against a local stand-in
for an OpenAI-compatible server, so no network or API key is needed."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from fixagent import cli
from fixagent.llm import LLMError, OpenAICompatLLM

from conftest import DEMO_REPOS, SCRIPTS


class FakeServer:
    """Serves one scripted step per request and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                outer.requests.append(
                    {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
                )
                if not outer.script:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"script exhausted")
                    return
                calls = [
                    {
                        "id": f"call_{len(outer.requests)}_{i}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                    for i, (name, args) in enumerate(outer.script.pop(0))
                ]
                payload = {"choices": [{"message": {"content": None, "tool_calls": calls}}]}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server():
    fake = FakeServer(SCRIPTS["py_stats_median"])
    yield fake
    fake.close()


def test_client_sends_a_well_formed_request(server):
    llm = OpenAICompatLLM(model="test-model", api_key="test-key", base_url=server.url + "/")
    tools = [{"name": "run_tests", "description": "d", "parameters": {"type": "object"}}]
    response = llm.complete([{"role": "user", "content": "hi"}], tools)

    assert response.tool_calls[0].name == "run_tests"
    sent = server.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["auth"] == "Bearer test-key"
    assert sent["body"]["model"] == "test-model"
    assert sent["body"]["tools"] == [{"type": "function", "function": tools[0]}]


def test_client_reports_server_errors(server):
    server.script.clear()
    llm = OpenAICompatLLM(model="m", base_url=server.url)
    with pytest.raises(LLMError, match="500"):
        llm.complete([], [])


def test_command_line_end_to_end(server, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FIXAGENT_MODEL", "test-model")
    monkeypatch.setenv("FIXAGENT_BASE_URL", server.url)
    monkeypatch.setenv("FIXAGENT_API_KEY", "test-key")
    patch = tmp_path / "fix.patch"

    code = cli.main(
        [
            "--repo", str(DEMO_REPOS / "py_stats"),
            "--issue", "median() is wrong for even-length lists",
            "--out", str(patch),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Result:     fixed" in output and "Language:   python" in output
    assert "+++ b/stats.py" in patch.read_text()
    # Each request carries the growing conversation, ending with a tool result.
    assert len(server.requests) == 5
    assert server.requests[-1]["body"]["messages"][-1]["role"] == "tool"


def test_command_line_without_settings_exits_cleanly(monkeypatch, capsys):
    for name in ("FIXAGENT_MODEL", "FIXAGENT_BASE_URL", "FIXAGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    code = cli.main(["--repo", str(DEMO_REPOS / "py_stats"), "--issue", "x"])
    assert code == 2
    assert "Missing LLM settings" in capsys.readouterr().err
