import asyncio
import copy
import json

import pytest

from prospero import LLMReply, ToolCall, run_turn
from prospero import loop

TASK = lambda text: [{"role": "developer", "content": text}]  # noqa: E731


def call(name, **args):
    return ToolCall(id=f"call_{name}_{len(json.dumps(args))}", name=name, arguments=json.dumps(args))


class ScriptedLLM:
    """Replies with the given LLMReplys in order, and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen = []

    async def __call__(self, messages, tools, on_tool_call=None):
        self.seen.append(copy.deepcopy(messages))
        if not self.replies:
            raise AssertionError("the LLM was called more times than scripted")
        return self.replies.pop(0)


def run(llm, agent=None, history=(), message="Build it."):
    async def collect():
        return [e async for e in run_turn(agent, list(history), message, llm)]

    return asyncio.run(collect())


BUILD = LLMReply(None, [
    call("updateAgent", patch={"name": "Clinic", "persona": "Be brief."}),
    call("addNode", node={"name": "greeting", "task_messages": TASK("Greet.")}),
    call("addNode", node={"name": "goodbye", "task_messages": TASK("Bye."), "end": True}),
    call("addEdge", node="greeting", edge={"function": "done", "description": "When done.", "target": "goodbye"}),
    call("setInitialNode", node="greeting"),
])
VALIDATE = LLMReply(None, [call("validate")])
FINISH = LLMReply(None, [call("finish", summary="A two-step clinic agent.", assumptions=["Opening hours unknown."])])


def test_builds_validates_and_finishes():
    llm = ScriptedLLM(BUILD, VALIDATE, FINISH)
    events = run(llm)

    assert [e["type"] for e in events] == ["op"] * 5 + ["validation", "done"]
    assert events[1]["label"] == "Added node 'greeting'"
    assert events[5] == {"type": "validation", "errors": 0, "warnings": 0}
    done = events[-1]
    assert done["summary"] == "A two-step clinic agent."
    assert done["assumptions"] == ["Opening hours unknown."]
    assert done["agent"]["initial_node"] == "greeting"
    assert [n["name"] for n in done["agent"]["nodes"]] == ["greeting", "goodbye"]
    assert done["issues"] == []


def test_a_failed_edit_is_explained_to_the_llm_and_not_streamed():
    bad = LLMReply(None, [call("addEdge", node="nope", edge={"function": "x", "description": "x", "target": "y"})])
    llm = ScriptedLLM(bad, BUILD, FINISH)
    events = run(llm)

    second_call = llm.seen[1]
    assert second_call[-1] == {"role": "tool", "tool_call_id": bad.tool_calls[0].id, "content": "ERROR: No node named 'nope'."}
    assert [e["type"] for e in events] == ["op"] * 5 + ["done"]


def test_finish_is_refused_while_errors_remain():
    llm = ScriptedLLM(FINISH, BUILD, FINISH)
    events = run(llm)

    refusal = llm.seen[1][-1]["content"]
    assert refusal.startswith("ERROR: the agent still has") and "Fix them, then call finish again." in refusal
    assert events[-1]["type"] == "done"


def test_a_text_reply_ends_the_turn_as_a_question():
    llm = ScriptedLLM(LLMReply("Which emergency number should callers use?", []))
    [event] = run(llm)
    assert event["type"] == "reply"
    assert event["text"] == "Which emergency number should callers use?"
    assert event["agent"] == {"name": "New agent", "initial_node": "", "nodes": []}


def test_text_alongside_tool_calls_is_streamed_as_a_note():
    llm = ScriptedLLM(LLMReply("Starting with the greeting.", BUILD.tool_calls), FINISH)
    events = run(llm)
    assert events[0] == {"type": "note", "text": "Starting with the greeting."}


def test_arguments_that_are_not_json_are_refused():
    llm = ScriptedLLM(LLMReply(None, [ToolCall("c1", "addNode", "{not json")]), LLMReply("Sorry.", []))
    run(llm)
    assert llm.seen[1][-1]["content"] == "ERROR: the arguments were not a JSON object."


def test_unknown_and_excluded_tools_are_refused():
    llm = ScriptedLLM(LLMReply(None, [call("replaceAgent", agent={}, reason="x")]), LLMReply("Ok.", []))
    run(llm)
    assert llm.seen[1][-1]["content"] == "ERROR: unknown tool 'replaceAgent'."


def test_stops_after_max_steps(monkeypatch):
    monkeypatch.setattr(loop, "MAX_STEPS", 3)
    llm = ScriptedLLM(VALIDATE, VALIDATE, VALIDATE)
    events = run(llm)
    assert events[-1] == {"type": "error", "message": "ProsperO stopped after 3 steps without finishing."}


def test_an_llm_failure_becomes_an_error_event():
    async def failing(messages, tools, on_tool_call=None):
        raise RuntimeError("rate limited")

    [event] = run(failing)
    assert event == {"type": "error", "message": "The LLM request failed: rate limited"}


def test_context_has_prompt_history_agent_without_positions_and_message():
    agent = {"name": "A", "initial_node": "s", "nodes": [{"name": "s", "task_messages": [], "position": {"x": 1, "y": 2}}]}
    before = copy.deepcopy(agent)
    llm = ScriptedLLM(LLMReply("Done.", []))
    run(llm, agent=agent, history=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
        message="Add a goodbye node.")

    sent = llm.seen[0]
    assert sent[0]["role"] == "system" and sent[0]["content"].startswith("You are ProsperO")
    assert sent[1:3] == [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    assert '"name": "s"' in sent[3]["content"] and '"position"' not in sent[3]["content"]
    assert sent[4] == {"role": "user", "content": "Add a goodbye node."}
    assert agent == before  # the caller's agent is never modified


@pytest.mark.parametrize("name", ["moveNodes", "replaceAgent"])
def test_layout_and_whole_agent_replacement_are_not_offered(name):
    from prospero.tools import TOOLS

    assert name not in {t["function"]["name"] for t in TOOLS}


def test_positions_are_left_to_the_editor():
    from prospero.tools import TOOLS

    assert '"position"' not in json.dumps(TOOLS)  # not offered...
    placed = LLMReply(None, [
        call("addNode", node={"name": "a", "task_messages": TASK("Hi."), "position": {"x": 9, "y": 9}}),
        call("updateNode", node="a", patch={"end": True, "position": {"x": 1, "y": 1}}),
    ])
    events = run(ScriptedLLM(placed, LLMReply("Ok.", [])))
    ops = [e["op"] for e in events if e["type"] == "op"]
    assert "position" not in ops[0]["node"] and ops[1]["patch"] == {"end": True}  # ...and ignored if sent


def test_prospero_knows_agents_are_english_only():
    from prospero.prompt import SYSTEM_PROMPT
    from prospero.tools import TOOLS

    update_agent = next(t for t in TOOLS if t["function"]["name"] == "updateAgent")
    assert "languages" not in update_agent["function"]["parameters"]["properties"]["patch"]["properties"]
    assert "Agents speak English only" in SYSTEM_PROMPT


# ---- streaming ----------------------------------------------------------------------
class StreamingLLM:
    """Reports each tool call through on_tool_call before returning, like the real
    streaming client, and notes what the consumer had received by then."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen_before_return = []
        self.received = []

    async def __call__(self, messages, tools, on_tool_call=None):
        reply = self.replies.pop(0)
        for c in reply.tool_calls:
            await on_tool_call(c)
            await asyncio.sleep(0.01)  # time passes between calls while streaming
        self.seen_before_return.append(list(self.received))
        return reply


def test_edits_are_sent_while_the_reply_is_still_streaming():
    llm = StreamingLLM(BUILD, FINISH)

    async def collect():
        events = []
        async for e in run_turn(None, [], "Build it.", llm):
            llm.received.append(e["type"])
            events.append(e)
        return events

    events = asyncio.run(collect())
    assert llm.seen_before_return[0] == ["op"] * 5  # all five edits out before the reply ended
    assert [e["type"] for e in events] == ["op"] * 5 + ["done"]
    assert events[-1]["agent"]["initial_node"] == "greeting"


def test_streamed_calls_are_answered_once_and_in_order():
    bad = call("addEdge", node="nope", edge={"function": "x", "description": "x", "target": "y"})
    llm = StreamingLLM(LLMReply(None, [bad, *BUILD.tool_calls]), FINISH)
    recorder = ScriptedLLM()  # only used to see the second request's messages

    async def second(messages, tools, on_tool_call=None):
        recorder.seen.append(copy.deepcopy(messages))
        return await StreamingLLM.__call__(llm, messages, tools, on_tool_call)

    llm_calls = iter([llm, second])

    async def complete(messages, tools, on_tool_call=None):
        return await next(llm_calls)(messages, tools, on_tool_call=on_tool_call)

    events = run(complete)
    tool_messages = [m for m in recorder.seen[0] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == [bad.id] + [c.id for c in BUILD.tool_calls]
    assert tool_messages[0]["content"] == "ERROR: No node named 'nope'."
    assert [e["type"] for e in events] == ["op"] * 5 + ["done"]
