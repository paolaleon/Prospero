#
# ProsperO's tool loop: one user message in, a stream of events out.
#
# Each turn is stateless: the caller sends the agent as it currently stands, the
# chat so far and the new message. ProsperO edits a working copy with the same
# operations the editor uses (apply_op), checks it with the same validator
# (validate_agent), and can't finish while errors remain. Every successful edit
# is streamed as it happens, so the editor can draw it.
#
# Events (plain dicts):
#   {"type": "op", "op": {...}, "label": "..."}          an edit was applied
#   {"type": "note", "text": "..."}                       text the LLM wrote while working
#   {"type": "validation", "errors": n, "warnings": n}    validate was called
#   {"type": "done", "summary", "assumptions", "agent", "issues"}   finished
#   {"type": "reply", "text", "agent", "issues"}          answered without finishing (e.g. a question)
#   {"type": "error", "message": "..."}                   the turn failed
#

import asyncio
import copy
import json
import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Optional

from loguru import logger

from agent_builder import validate_agent
from agent_builder.operations import OperationError, apply_op, describe_op

from .prompt import SYSTEM_PROMPT
from .tools import EDIT_TOOL_NAMES, TOOLS

DEFAULT_MODEL = "gpt-5.5"
MAX_STEPS = 40  # LLM calls per turn; a build usually needs far fewer


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON, as the LLM wrote it


@dataclass
class LLMReply:
    content: Optional[str]
    tool_calls: list = field(default_factory=list)  # list[ToolCall]


# Called with each tool call as soon as it's complete, while the reply is still
# being generated, so its edit can be applied and drawn straight away.
OnToolCall = Callable[[ToolCall], Awaitable[None]]

# Given the messages and tools, return the LLM's next reply. Called as
# complete(messages, tools, on_tool_call=...): a streaming implementation calls
# on_tool_call for each finished call along the way; one that doesn't stream
# (like the test fakes) ignores it, and run_turn handles the calls afterwards.
Complete = Callable[..., Awaitable[LLMReply]]


def openai_complete(model: Optional[str] = None, reasoning: Optional[str] = None) -> Complete:
    """The real LLM: OpenAI chat completions with tools, streamed.

    Building an agent is mostly writing out edits (~1,000 tokens per reply), so
    streaming lets the first edit appear seconds into a reply instead of at its
    end. Reasoning is off by default: it roughly halved the first reply's time
    in testing without hurting the result (PROSPERO_REASONING to change it).
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = model or os.environ.get("PROSPERO_MODEL", DEFAULT_MODEL)
    reasoning = reasoning if reasoning is not None else os.environ.get("PROSPERO_REASONING", "none")
    # Only reasoning models accept the setting.
    extra = {"reasoning_effort": reasoning} if reasoning and model.startswith(("gpt-5", "o")) else {}

    async def complete(messages: list, tools: list, on_tool_call: Optional[OnToolCall] = None) -> LLMReply:
        stream = await client.chat.completions.create(
            model=model, messages=messages, tools=tools, stream=True, **extra
        )
        content: list[str] = []
        calls: dict[int, dict] = {}  # by index, as the deltas arrive
        reported = 0

        async def report_up_to(index: int):
            # Calls are generated in order: when call N starts, call N-1 is complete.
            nonlocal reported
            while reported < index:
                call = calls.get(reported)
                if call and on_tool_call:
                    await on_tool_call(ToolCall(call["id"], call["name"], call["arguments"]))
                reported += 1

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content.append(delta.content)
            for piece in delta.tool_calls or []:
                await report_up_to(piece.index)
                call = calls.setdefault(piece.index, {"id": "", "name": "", "arguments": ""})
                if piece.id:
                    call["id"] = piece.id
                if piece.function and piece.function.name:
                    call["name"] += piece.function.name
                if piece.function and piece.function.arguments:
                    call["arguments"] += piece.function.arguments
        await report_up_to(len(calls))

        ordered = [calls[i] for i in sorted(calls)]
        return LLMReply(
            "".join(content) or None,
            [ToolCall(c["id"], c["name"], c["arguments"]) for c in ordered],
        )

    return complete


def blank_agent() -> dict:
    return {"name": "New agent", "initial_node": "", "nodes": []}


def _issues(agent: dict) -> list[dict]:
    return [i.to_dict() for i in validate_agent(agent)]


def _without_positions(agent: dict) -> dict:
    # Canvas positions mean nothing to the LLM and only cost tokens (AD-1).
    stripped = copy.deepcopy(agent)
    for node in stripped.get("nodes", []):
        node.pop("position", None)
    return stripped


def _context(agent: dict, history: list, message: str) -> list:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({
        "role": "system",
        "content": "The agent as it currently stands (positions omitted):\n```json\n"
        + json.dumps(_without_positions(agent), indent=1)
        + "\n```",
    })
    messages.append({"role": "user", "content": message})
    return messages


async def run_turn(
    agent: Optional[dict], history: list, message: str, complete: Complete
) -> AsyncIterator[dict]:
    """Run one turn of ProsperO and yield its events (see the top of this file)."""
    agent = copy.deepcopy(agent) if agent else blank_agent()
    messages = _context(agent, history, message)

    for _ in range(MAX_STEPS):
        # Tool calls that finish while the reply streams are handled right away;
        # their events go through a queue so they're sent as they happen.
        handled: dict[str, tuple[str, Optional[dict]]] = {}  # call id -> (result, done)
        queue: asyncio.Queue = asyncio.Queue()

        async def on_tool_call(call: ToolCall) -> None:
            nonlocal agent
            result, events, agent, done = _handle(call, agent)
            handled[call.id] = (result, done)
            for event in events:
                queue.put_nowait(event)

        request = asyncio.ensure_future(complete(messages, TOOLS, on_tool_call=on_tool_call))
        while not request.done() or not queue.empty():
            if not queue.empty():
                yield queue.get_nowait()
                continue
            waiter = asyncio.ensure_future(queue.get())
            await asyncio.wait({request, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if waiter.done():
                yield waiter.result()
            else:
                waiter.cancel()
        try:
            reply = request.result()
        except Exception as e:
            logger.exception("ProsperO's LLM call failed")
            yield {"type": "error", "message": f"The LLM request failed: {e}"}
            return

        assistant = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in reply.tool_calls
            ]
        messages.append(assistant)

        if not reply.tool_calls:
            # No tools: ProsperO is talking to the user (usually a question).
            yield {"type": "reply", "text": reply.content or "", "agent": agent, "issues": _issues(agent)}
            return
        if reply.content:
            yield {"type": "note", "text": reply.content}

        finished = None
        for call in reply.tool_calls:
            if call.id in handled:
                result, done = handled[call.id]  # already applied while streaming
            else:
                result, events, agent, done = _handle(call, agent)
                for event in events:
                    yield event
            # Every tool call gets an answer, as the API requires.
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            finished = finished or done
        if finished:
            yield finished
            return

    yield {"type": "error", "message": f"ProsperO stopped after {MAX_STEPS} steps without finishing."}


def _strip_positions(op: dict) -> dict:
    # Even if the model sets positions anyway, layout stays the editor's job.
    if isinstance(op.get("node"), dict):
        op["node"].pop("position", None)
    if isinstance(op.get("patch"), dict):
        op["patch"].pop("position", None)
    return op


def _handle(call: ToolCall, agent: dict) -> tuple[str, list, dict, Optional[dict]]:
    """Run one tool call. Returns (result for the LLM, events, agent, done event or None)."""
    try:
        args = json.loads(call.arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        return "ERROR: the arguments were not a JSON object.", [], agent, None

    if call.name in EDIT_TOOL_NAMES:
        op = _strip_positions({"type": call.name, **args})
        try:
            agent = apply_op(agent, op)
        except OperationError as e:
            # The LLM gets the exact reason and can correct itself.
            return f"ERROR: {e}", [], agent, None
        label = describe_op(op)
        return f"OK: {label}.", [{"type": "op", "op": op, "label": label}], agent, None

    if call.name == "validate":
        issues = _issues(agent)
        errors = sum(i["severity"] == "error" for i in issues)
        event = {"type": "validation", "errors": errors, "warnings": len(issues) - errors}
        return (json.dumps(issues) if issues else "No issues."), [event], agent, None

    if call.name == "finish":
        issues = _issues(agent)
        errors = [i for i in issues if i["severity"] == "error"]
        if errors:
            return (
                f"ERROR: the agent still has {len(errors)} error(s): {json.dumps(errors)}. "
                "Fix them, then call finish again."
            ), [], agent, None
        done = {
            "type": "done",
            "summary": str(args.get("summary", "")),
            "assumptions": [str(a) for a in args.get("assumptions", [])],
            "agent": agent,
            "issues": issues,
        }
        return "OK: handed to the user for review.", [], agent, done

    return f"ERROR: unknown tool '{call.name}'.", [], agent, None
