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
