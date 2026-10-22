import asyncio
import copy
import json
from pathlib import Path

import pytest

import store
from call_guard import StartValidationMiddleware

EXAMPLE = json.loads((Path(__file__).parent.parent / "example_flow.json").read_text())


class FakeRunner:
    """Stands in for the Pipecat runner: records the body it was given, answers 200."""

    def __init__(self):
        self.body = None

    async def __call__(self, scope, receive, send):
        chunks, more = [], True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        self.body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"sessionId": "s1"}'})


def call(body: bytes, path="/start", method="POST", chunk_size=None):
    """Send one request through the middleware; return (status, json, runner)."""
    runner = FakeRunner()
    guard = StartValidationMiddleware(runner)
    pieces = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)] if chunk_size else [body]
    messages = [{"type": "http.request", "body": p, "more_body": i < len(pieces) - 1} for i, p in enumerate(pieces)]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": []}
    asyncio.run(guard(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(payload), runner


def start_body(**body) -> bytes:
    return json.dumps({"body": body}).encode()


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AGENTS_DIR", tmp_path / "agents")
    store.save_version("saved", copy.deepcopy(EXAMPLE))


def broken_agent():
    agent = copy.deepcopy(EXAMPLE)
    agent["nodes"][0]["edges"][0]["target"] = "nope"
    return agent


def test_refuses_an_inline_agent_with_errors():
    status, payload, runner = call(start_body(agent=broken_agent()))
    assert status == 422
    assert payload["detail"] == "Agent has errors."
    assert {"severity": "error", "message": "Transition 'choose_intent' targets unknown node 'nope'.",
            "node": "greeting", "edge": 0} in payload["issues"]
    assert runner.body is None  # the runner never saw it


def test_refuses_an_unknown_agent_or_version():
    status, payload, runner = call(start_body(agent_id="missing"))
    assert (status, runner.body) == (404, None)
    assert "not found" in payload["detail"]

    status, payload, _ = call(start_body(agent_id="saved", version=9))
    assert status == 404
    assert "no version 9" in payload["detail"]


def test_passes_valid_requests_through_unchanged():
    for body in [start_body(agent=EXAMPLE), start_body(agent_id="saved", version=1), b"{}"]:
        status, payload, runner = call(body)
        assert (status, payload) == (200, {"sessionId": "s1"})
        assert runner.body == body


def test_reassembles_a_body_sent_in_chunks():
    body = start_body(agent=EXAMPLE)
    status, _, runner = call(body, chunk_size=64)
    assert status == 200
    assert runner.body == body

    status, _, runner = call(start_body(agent=broken_agent()), chunk_size=64)
    assert (status, runner.body) == (422, None)


@pytest.mark.parametrize("body", [b"{not json", b"[1, 2]"])
def test_leaves_malformed_requests_to_the_runner(body):
    status, _, runner = call(body)
    assert status == 200
    assert runner.body == body


def test_ignores_other_routes():
    body = start_body(agent=broken_agent())
    for path, method in [("/api/validate", "POST"), ("/start", "GET")]:
        status, _, runner = call(body, path=path, method=method)
        assert status == 200
        assert runner.body == body
