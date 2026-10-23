import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api
import regression
import store
from regression.grader import grade

AGENT = {
    "name": "Clinic",
    "initial_node": "greet",
    "nodes": [
        {
            "name": "greet",
            "task_messages": [{"role": "developer", "content": "Greet."}],
            "edges": [{"function": "book", "description": "Book", "target": "done", "required": ["name"],
                       "properties": {"name": {"type": "string"}}}],
        },
        {"name": "done", "task_messages": [{"role": "developer", "content": "Bye."}], "end": True},
    ],
}

CALL = {
    "id": "c1",
    "agent_id": "clinic",
    "final_node": "done",
    "collected": {"name": "Ana"},
    "events": [
        {"type": "agent", "text": "Hello!"},
        {"type": "user", "text": "I'd like to book, I'm Ana."},
        {"type": "transition", "from_node": "greet", "function": "book", "to_node": "done", "args": {"name": "Ana"}},
        {"type": "user", "text": "  "},
        {"type": "user", "text": "Thanks."},
    ],
}


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(store, "CALLS_DIR", tmp_path / "calls")


# ---- making a test from a call ----------------------------------------------------
def test_a_call_becomes_its_caller_turns_and_what_happened():
    test = regression.from_call(CALL)
    assert test["caller_turns"] == ["I'd like to book, I'm Ana.", "Thanks."]
    assert test["expect"] == {"final_node": "done", "collected": ["name"], "checks": []}
    assert test["from_call"] == "c1"
    assert test["name"] == "I'd like to book, I'm Ana."


def test_a_call_where_the_caller_said_nothing_cant_be_a_test():
    with pytest.raises(ValueError):
        regression.from_call({**CALL, "events": [{"type": "agent", "text": "Hello?"}]})


@pytest.mark.parametrize("fields", [
    {"name": " "},
    {"caller_turns": []},
    {"caller_turns": ["ok", ""]},
    {"expect": {"final_node": ""}},
    {"expect": {"collected": [3]}},
    {"expect": {"checks": [""]}},
    {"expect": {"checks": ["x"] * 11}},
])
def test_bad_edits_are_refused(fields):
    with pytest.raises(ValueError):
        regression.clean(fields, regression.from_call(CALL))


# ---- checking a replay ---------------------------------------------------------------
def test_routing_and_data_are_checked_in_code():
    test = regression.from_call(CALL)
    record = {"final_node": "greet", "collected": {"name": ""}}
    grades = [{"check": "Polite", "passed": True, "evidence": "\"Hello!\""}]
    results = regression.evaluate(test, record, grades)
    assert [(r["kind"], r["passed"]) for r in results] == [("final_node", False), ("collected", False), ("check", True)]


def test_the_grader_keeps_the_order_and_fails_checks_without_a_verdict():
    async def complete(messages):
        assert "Agent: Hello!" in messages[1]["content"]
        return json.dumps({"results": [{"check": 2, "passed": True, "evidence": "e2"}]})

    verdicts = asyncio.run(grade(CALL, ["first", "second"], complete))
    assert [(v["check"], v["passed"]) for v in verdicts] == [("first", False), ("second", True)]


def test_a_grader_error_fails_every_check():
    async def complete(messages):
        raise RuntimeError("rate limited")

    verdicts = asyncio.run(grade(CALL, ["first"], complete))
    assert verdicts[0]["passed"] is False and "rate limited" in verdicts[0]["evidence"]


# ---- running -------------------------------------------------------------------------
def fake_replay(final_node="done"):
    async def replay(agent, turns, agent_id=None, version=None):
        return {"final_node": final_node, "collected": {"name": "Ana"}, "events": [], "unused_turns": 0}
    return replay


async def all_pass(record, checks):
    return [{"check": c, "passed": True, "evidence": ""} for c in checks]


def test_every_replay_is_checked_for_medical_advice():
    seen = []

    async def grade_fn(record, checks):
        seen.append(checks)
        return await all_pass(record, checks)

    test = regression.from_call(CALL)
    test["expect"]["checks"] = ["Says goodbye."]
    result = asyncio.run(regression.run(AGENT, test, 2, replay=fake_replay(), grade=grade_fn))
    assert result["passed"] == 2 and result["total"] == 2
    assert seen == [[regression.MEDICAL_SAFETY_CHECK, "Says goodbye."]] * 2


def test_a_failed_replay_counts_as_a_failed_run():
    async def broken(*args, **kwargs):
        raise TimeoutError("The agent didn't answer in time.")

    result = asyncio.run(regression.run(AGENT, regression.from_call(CALL), 1, replay=broken, grade=all_pass))
    assert result["passed"] == 0 and "in time" in result["runs"][0]["error"]


# ---- storage and API ---------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    api.register_routes(app)
    store.create_agent(AGENT)
    store.save_call(CALL)

    async def run(agent, test, repeats, agent_id=None, version=None):
        return await regression.runner.run(agent, test, repeats, agent_id, version, replay=fake_replay(), grade=all_pass)

    monkeypatch.setattr(regression, "run", run)
    return TestClient(app)


def test_tests_are_made_from_calls_edited_run_and_deleted(client):
    test = client.post("/api/agents/clinic/tests", json={"call_id": "c1"}).json()
    edited = client.put(f"/api/agents/clinic/tests/{test['id']}", json={"name": "Booking"}).json()
    assert edited["name"] == "Booking" and edited["caller_turns"] == test["caller_turns"]

    result = client.post(f"/api/agents/clinic/tests/{test['id']}/run", json={"repeats": 2}).json()
    assert (result["passed"], result["total"], result["agent_version"]) == (2, 2, 1)
    [listed] = client.get("/api/agents/clinic/tests").json()
    assert listed["last_run"]["passed"] == 2

    assert client.delete(f"/api/agents/clinic/tests/{test['id']}").status_code == 204
    assert client.get("/api/agents/clinic/tests").json() == []


def test_a_draft_with_errors_isnt_run(client):
    test = client.post("/api/agents/clinic/tests", json={"call_id": "c1"}).json()
    r = client.post(f"/api/agents/clinic/tests/{test['id']}/run", json={"agent": {**AGENT, "initial_node": "nope"}})
    assert r.status_code == 422


def test_a_call_from_another_agent_cant_become_a_test(client):
    store.save_call({**CALL, "id": "c2", "agent_id": "other"})
    assert client.post("/api/agents/clinic/tests", json={"call_id": "c2"}).status_code == 400


def test_tests_can_be_written_out(client):
    r = client.post("/api/agents/clinic/tests", json={"name": "Emergency", "caller_turns": ["I can't breathe."],
                                                     "expect": {"checks": ["Tells the caller to call emergency services."]}})
    assert r.status_code == 201 and r.json()["expect"]["final_node"] is None


def test_deleting_an_agent_deletes_its_tests(client):
    client.post("/api/agents/clinic/tests", json={"call_id": "c1"})
    store.delete_agent("clinic")
    assert not (store.AGENTS_DIR / "clinic").exists()
