#
# What a test is: the caller's side of a call, and what should happen when it's
# replayed. Made from a recorded call, then edited by the user.
#

from typing import Optional

import store

MAX_TURNS = 30
MAX_CHECKS = 10


def from_call(call: dict) -> dict:
    """A new test that replays what the caller said in `call`.

    Its expectations start as what happened on the call (where it ended, what it
    collected), so the test first checks that the agent still does the same.
    Rules about what the agent says (checks) are added by the user.
    """
    turns = [e["text"].strip() for e in call.get("events", []) if e["type"] == "user" and e.get("text", "").strip()]
    if not turns:
        raise ValueError("The caller said nothing on this call, so there's nothing to replay.")
    first = turns[0]
    return {
        "id": store.new_test_id(),
        "name": first if len(first) <= 60 else first[:57].rstrip() + "…",
        "created_at": store.now(),
        "from_call": call.get("id"),
        "caller_turns": turns[:MAX_TURNS],
        "expect": {
            "final_node": call.get("final_node"),
            "collected": sorted(call.get("collected") or {}),
            "checks": [],
        },
        "last_run": None,
    }


def clean(data: dict, test: Optional[dict] = None) -> dict:
    """Apply the editable fields in `data` (name, caller_turns, expect) to `test`,
    checking each one. Raises ValueError with a readable message."""
    test = dict(test or {})
    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"].strip():
            raise ValueError("A test needs a name.")
        test["name"] = data["name"].strip()
    if "caller_turns" in data:
        turns = data["caller_turns"]
        if not isinstance(turns, list) or not all(isinstance(t, str) and t.strip() for t in turns):
            raise ValueError("Caller turns must be a list of non-empty sentences.")
        if not 1 <= len(turns) <= MAX_TURNS:
            raise ValueError(f"A test needs between 1 and {MAX_TURNS} caller turns.")
        test["caller_turns"] = [t.strip() for t in turns]
    if "expect" in data:
        expect = data["expect"]
        if not isinstance(expect, dict):
            raise ValueError("'expect' must be an object.")
        final_node = expect.get("final_node")
        if final_node is not None and (not isinstance(final_node, str) or not final_node.strip()):
            raise ValueError("The expected final node must be a node name, or none.")
        collected = expect.get("collected") or []
        if not isinstance(collected, list) or not all(isinstance(f, str) and f.strip() for f in collected):
            raise ValueError("Expected fields must be a list of field names.")
        checks = expect.get("checks") or []
        if not isinstance(checks, list) or not all(isinstance(c, str) and c.strip() for c in checks):
            raise ValueError("Checks must be a list of non-empty sentences.")
        if len(checks) > MAX_CHECKS:
            raise ValueError(f"A test can have at most {MAX_CHECKS} checks.")
        test["expect"] = {
            "final_node": final_node,
            "collected": [f.strip() for f in collected],
            "checks": [c.strip() for c in checks],
        }
    return test


def evaluate(test: dict, record: dict, grades: list[dict]) -> list[dict]:
    """Each expectation of `test`, checked against one replay's `record`.

    Routing and data are checked in code; `grades` are the grader's verdicts on
    the checks about what the agent said. Every result:
    {"kind": "final_node" | "collected" | "check", "label", "passed", "detail"}.
    """
    expect = test["expect"]
    results = []
    if expect.get("final_node"):
        ended = record.get("final_node")
        results.append({
            "kind": "final_node",
            "label": f"Ends at {expect['final_node']}",
            "passed": ended == expect["final_node"],
            "detail": f"Ended at {ended}.",
        })
    collected = record.get("collected") or {}
    for field in expect.get("collected", []):
        value = collected.get(field)
        got = value is not None and not (isinstance(value, str) and not value.strip())
        results.append({
            "kind": "collected",
            "label": f"Collects {field}",
            "passed": got,
            "detail": f"Collected {value!r}." if got else "Not collected.",
        })
    for g in grades:
        results.append({"kind": "check", "label": g["check"], "passed": g["passed"], "detail": g["evidence"]})
    return results
