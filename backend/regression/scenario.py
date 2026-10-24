#
# What a test is: the caller's side of a call, and what should happen when it's
# replayed. Made from a recorded call, then edited by the user.
#

from typing import Optional

import store

MAX_TURNS = 30
MAX_CHECKS = 10

# Spoken replies should be one or two short sentences: long ones are hard to
# follow on the phone, and speech is most of a call's cost (D-19).
DEFAULT_MAX_REPLY_WORDS = 40
# A replay may take a few more turns than the call it came from (an extra
# question, a retry) before that counts as going in circles.
TURN_MARGIN = 2


def _turns(events: list) -> int:
    return sum(1 for e in events if e["type"] in ("user", "agent"))


def _words(text: str) -> int:
    return len(text.split())


def from_call(call: dict) -> dict:
    """A new test that replays what the caller said in `call`.

    Its expectations start as what happened on the call (where it ended, what it
    collected, about how many turns it took), so the test first checks that the
    agent still does the same. It also expects no fallback and short replies.
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
            "no_fallback": True,
            "max_reply_words": DEFAULT_MAX_REPLY_WORDS,
            "max_turns": _turns(call.get("events", [])) + TURN_MARGIN,
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
        no_fallback = expect.get("no_fallback", True)
        if not isinstance(no_fallback, bool):
            raise ValueError("'no_fallback' must be true or false.")
        limits = {}
        for key, default, label in (
            ("max_reply_words", DEFAULT_MAX_REPLY_WORDS, "The longest reply"),
            ("max_turns", None, "The number of turns"),
        ):
            value = expect.get(key, default)  # null: not checked
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 500):
                raise ValueError(f"{label} must be a whole number from 1 to 500, or none.")
            limits[key] = value
        test["expect"] = {
            "final_node": final_node,
            "collected": [f.strip() for f in collected],
            "checks": [c.strip() for c in checks],
            "no_fallback": no_fallback,
            **limits,
        }
    return test


def evaluate(test: dict, record: dict, grades: list[dict]) -> list[dict]:
    """Each expectation of `test`, checked against one replay's `record`.

    Routing and data are checked in code; `grades` are the grader's verdicts on
    the checks about what the agent said. Every result:
    {"kind": "final_node" | "collected" | "no_fallback" | "reply_length" | "turns" | "check",
     "label", "passed", "detail"}.
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
    events = record.get("events", [])
    # Tests saved before these expectations existed get their defaults.
    if expect.get("no_fallback", True):
        fallback = next((e for e in events if e["type"] == "fallback"), None)
        results.append({
            "kind": "no_fallback",
            "label": "Never falls back",
            "passed": fallback is None,
            "detail": f"Got stuck in {fallback['from_node']} and fell back." if fallback else "No fallback.",
        })
    max_words = expect.get("max_reply_words", DEFAULT_MAX_REPLY_WORDS)
    if max_words:
        replies = [e["text"] for e in events if e["type"] == "agent"]
        longest = max(replies, key=_words, default="")
        results.append({
            "kind": "reply_length",
            "label": f"Replies of at most {max_words} words",
            "passed": _words(longest) <= max_words,
            "detail": f"Longest reply: {_words(longest)} words." + (f' "{longest}"' if _words(longest) > max_words else ""),
        })
    if expect.get("max_turns"):
        turns = _turns(events)
        results.append({
            "kind": "turns",
            "label": f"Done within {expect['max_turns']} turns",
            "passed": turns <= expect["max_turns"],
            "detail": f"Took {turns} turns.",
        })
    for g in grades:
        results.append({"kind": "check", "label": g["check"], "passed": g["passed"], "detail": g["evidence"]})
    return results
