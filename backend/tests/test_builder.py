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



# ---- English only (AD-15) ----------------------------------------------------------
def role_message(builder, data, node_index=0):
    return builder._make_node(builder._nodes_by_name[data["nodes"][node_index]["name"]])["role_message"]


def test_every_node_gets_the_english_only_rule():
    data = json.loads(EXAMPLE.read_text())
    message = role_message(AgentBuilder.from_dict(data), data)
    assert message.startswith(data["persona"])
    assert "Language: speak only English" in message


def test_a_persona_override_keeps_the_english_rule():
    data = json.loads(EXAMPLE.read_text())
    data["nodes"][1]["role_message"] = "Be extra brief."
    message = role_message(AgentBuilder.from_dict(data), data, 1)
    assert message.startswith("Be extra brief.") and "speak only English" in message


def test_old_agents_with_a_languages_list_still_load():
    data = json.loads(EXAMPLE.read_text())
    data["languages"] = ["en", "es"]  # ignored: agents are English only
    assert "speak only English" in role_message(AgentBuilder.from_dict(data), data)


# ---- recovering from a stuck node (AD-16) ----------------------------------------
from agent_builder.builder import BUILT_IN_FALLBACK


def stuck_builder(**overrides):
    """collect_details first (requires full_name and reason), with a fallback listener."""
    data = json.loads(EXAMPLE.read_text())
    data["initial_node"] = "collect_details"
    data.update(overrides)
    builder = AgentBuilder.from_dict(data)
    fallbacks = []

    async def on_fallback(*a):
        fallbacks.append(a)

    builder.on_fallback = on_fallback
    handler = builder.build_initial_node()["functions"][0].handler
    attempt = lambda args: asyncio.run(handler(args, SimpleNamespace(state={})))  # noqa: E731
    return builder, attempt, fallbacks


def test_two_refusals_in_a_row_move_the_call_to_a_polite_ending():
    builder, attempt, fallbacks = stuck_builder()
    _, first = attempt({"full_name": "Ana"})
    assert first is None  # asked again
    result, second = attempt({"full_name": "Ana"})
    assert second["name"] == BUILT_IN_FALLBACK
    assert second["functions"] == [] and second["post_actions"] == [{"type": "end_conversation"}]
    assert "staff can help directly" in second["task_messages"][0]["content"]
    assert "moves on to wrap up" in result["error"]
    assert fallbacks == [("collect_details", "missing information", BUILT_IN_FALLBACK)]


def test_the_agents_own_fallback_node_is_used_when_set():
    builder, attempt, fallbacks = stuck_builder(fallback_node="confirm")
    attempt({})
    _, second = attempt({})
    assert second["name"] == "confirm"
    assert fallbacks == [("collect_details", "missing information", "confirm")]


def test_progress_resets_the_count():
    builder, attempt, _ = stuck_builder()
    attempt({"full_name": "Ana"})  # one miss
    _, moved = attempt({"full_name": "Ana", "reason": "checkup"})
    assert moved["name"] == "offer_times"
    assert builder.current_node == "offer_times" and builder._refusals == 0


def test_a_call_never_falls_back_from_its_fallback():
    builder, attempt, fallbacks = stuck_builder(fallback_node="offer_times")
    attempt({})
    _, fallback = attempt({})  # stuck: moved to offer_times, the fallback
    assert fallback["name"] == "offer_times" and builder.current_node == "offer_times"

    # Refusals inside the fallback keep asking instead of falling back again.
    in_fallback = fallback["functions"][0].handler
    for _ in range(3):
        _, next_node = asyncio.run(in_fallback({}, SimpleNamespace(state={})))
        assert next_node is None
    assert len(fallbacks) == 1


def test_the_built_in_ending_speaks_english():
    builder, _, _ = stuck_builder()
    assert "speak only English" in builder.fallback_node_config()["role_message"]



# ---- medical safety (AD-17) -----------------------------------------------------------
from agent_builder.medical import NO_MEDICAL_ADVICE_RULE


def test_every_node_gets_the_no_medical_advice_rule_whatever_the_persona():
    data = json.loads(EXAMPLE.read_text())
    data["persona"] = "You are a friendly voice assistant."  # says nothing about advice
    data["nodes"][1]["role_message"] = "Be extra brief."  # a per-node override
    builder = AgentBuilder.from_dict(data)
    for node in builder.config.nodes:
        assert NO_MEDICAL_ADVICE_RULE in builder._make_node(node)["role_message"]
    assert NO_MEDICAL_ADVICE_RULE in builder.fallback_node_config()["role_message"]


def test_the_rule_comes_after_the_persona():
    data = json.loads(EXAMPLE.read_text())
    message = AgentBuilder.from_dict(data).build_initial_node()["role_message"]
    assert message.index(data["persona"]) < message.index("Medical safety:") < message.index("Language:")
