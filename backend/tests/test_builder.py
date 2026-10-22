import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_builder import AgentBuilder

EXAMPLE = Path(__file__).parent.parent / "example_flow.json"


def take_first_transition(builder: AgentBuilder, args: dict):
    """Run the start node's first edge handler, as Pipecat would when the LLM calls it."""
    function = builder.build_initial_node()["functions"][0]
    flow_manager = SimpleNamespace(state={})
    result, next_node = asyncio.run(function.handler(args, flow_manager))
    return result, next_node, flow_manager.state


def test_listener_gets_each_transition():
    builder = AgentBuilder.from_json(EXAMPLE)
    calls = []

    async def listener(from_node, function, to_node, args):
        calls.append((from_node, function, to_node, args))

    builder.on_transition = listener
    _, next_node, state = take_first_transition(builder, {"intent": "book"})

    assert calls == [("greeting", "choose_intent", "collect_details", {"intent": "book"})]
    assert next_node["name"] == "collect_details"
    assert state == {"intent": "book"}


def test_a_failing_listener_does_not_break_the_transition():
    builder = AgentBuilder.from_json(EXAMPLE)

    async def broken(*_):
        raise RuntimeError("listener bug")

    builder.on_transition = broken
    result, next_node, _ = take_first_transition(builder, {"intent": "cancel"})

    assert result == {"status": "success", "intent": "cancel"}
    assert next_node["name"] == "collect_details"


def test_no_listener_by_default():
    builder = AgentBuilder.from_json(EXAMPLE)
    assert builder.on_transition is None
    _, next_node, _ = take_first_transition(builder, {"intent": "book"})
    assert next_node["name"] == "collect_details"


def test_invalid_agents_are_refused():
    data = json.loads(EXAMPLE.read_text())
    data["nodes"][0]["edges"][0]["target"] = "nope"
    with pytest.raises(ValueError, match="targets unknown node 'nope'"):
        AgentBuilder.from_dict(data)


# ---- refusing transitions without the data they require -------------------------
def collect_details_builder():
    """A builder whose start node is collect_details (requires full_name and reason)."""
    data = json.loads(EXAMPLE.read_text())
    data["initial_node"] = "collect_details"
    return AgentBuilder.from_dict(data)


def test_missing_required_field_keeps_the_call_in_place():
    builder = collect_details_builder()
    moved, refused = [], []

    async def on_move(*a):
        moved.append(a)

    async def on_refuse(*a):
        refused.append(a)

    builder.on_transition, builder.on_transition_refused = on_move, on_refuse
    result, next_node, state = take_first_transition(builder, {"full_name": "Ana Ruiz"})

    assert next_node is None  # no transition
    assert result["status"] == "error"
    assert "Missing required field 'reason'." in result["error"]
    assert state == {}  # nothing saved
    assert moved == []
    assert refused == [("collect_details", "record_details", {"full_name": "Ana Ruiz"}, ["Missing required field 'reason'."])]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_required_values_count_as_missing(blank):
    builder = collect_details_builder()
    result, next_node, _ = take_first_transition(builder, {"full_name": blank, "reason": "checkup"})
    assert next_node is None
    assert "Missing required field 'full_name'." in result["error"]


def test_values_outside_the_allowed_list_are_refused():
    builder = AgentBuilder.from_json(EXAMPLE)  # choose_intent: intent in book/reschedule/cancel
    result, next_node, _ = take_first_transition(builder, {"intent": "complain"})
    assert next_node is None
    assert result["error"].startswith("Field 'intent' must be one of: book, reschedule, cancel (got 'complain').")


def test_complete_arguments_still_transition():
    builder = collect_details_builder()
    result, next_node, state = take_first_transition(builder, {"full_name": "Ana Ruiz", "reason": "checkup"})
    assert next_node["name"] == "offer_times"
    assert state == {"full_name": "Ana Ruiz", "reason": "checkup"}


def test_a_failing_refusal_listener_does_not_break_the_call():
    builder = collect_details_builder()

    async def broken(*_):
        raise RuntimeError("listener bug")

    builder.on_transition_refused = broken
    result, next_node, _ = take_first_transition(builder, {})
    assert (result["status"], next_node) == ("error", None)
