#
# Replay — runs an agent on a scripted caller, as text.
#
# The same agent graph, Flows runtime and LLM as a voice call (bot.py), without
# speech: each caller turn goes into the context as text, and the agent's reply
# is read back from it. What this doesn't test is the voice layer (speech
# recognition errors, interruptions, timing).
#
# A caller turn is sent once the agent has finished answering the previous one,
# including any transition and the next node's reply.
#

import asyncio
import os
import time
from typing import Optional

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.workers.runner import WorkerRunner
from pipecat_flows import FlowManager

from agent_builder import AgentBuilder
from call_record import CallRecorder
from usage import UsageMeter

# The agent has finished answering when nothing is running and nothing has
# happened for this long (a transition starts the next node's reply quickly).
QUIET_SECS = 0.8
TURN_TIMEOUT_SECS = 45


class _Activity(FrameProcessor):
    """Watches the LLM's output to tell when the agent has finished answering."""

    def __init__(self):
        super().__init__()
        self.running = 0  # replies and function calls in progress
        self.finished = 0  # replies and function calls finished since the last reset
        self.last = time.monotonic()

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (LLMFullResponseStartFrame, FunctionCallInProgressFrame)):
            self.running += 1
        elif isinstance(frame, (LLMFullResponseEndFrame, FunctionCallResultFrame)):
            self.running = max(0, self.running - 1)
            self.finished += 1
        self.last = time.monotonic()
        await self.push_frame(frame, direction)

    async def answered(self, ended: asyncio.Event) -> None:
        start = time.monotonic()
        while not ended.is_set():
            now = time.monotonic()
            if self.running == 0 and self.finished and now - self.last >= QUIET_SECS:
                return
            if now - start > TURN_TIMEOUT_SECS:
                raise TimeoutError("The agent didn't answer in time.")
            await asyncio.sleep(0.05)


async def replay(
    agent: dict,
    caller_turns: list[str],
    agent_id: Optional[str] = None,
    version: Optional[int] = None,
) -> dict:
    """Replay `caller_turns` against `agent`; returns the call record (not saved).

    If the call ends before every turn is used (an end node), the rest are
    skipped and counted in the record's "unused_turns".
    """
    builder = AgentBuilder.from_dict(agent)
    recorder = CallRecorder(agent, agent_id, version, source="replay")

    async def on_transition(from_node, function, to_node, args):
        recorder.transition(from_node, function, to_node, args)

    async def on_refused(node, function, args, problems):
        recorder.refusal(node, function, args, problems)

    async def on_fallback(from_node, reason, to_node):
        recorder.fallback(from_node, reason, to_node)

    builder.on_transition = on_transition
    builder.on_transition_refused = on_refused
    builder.on_fallback = on_fallback

    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=builder.config.model)
    context_aggregator = LLMContextAggregatorPair(LLMContext())
    activity = _Activity()
    meter = UsageMeter(tts=False)  # text only: no speech to pay for
    recorder.usage = meter.usage
    worker = PipelineWorker(
        Pipeline([context_aggregator.user(), llm, activity, meter, context_aggregator.assistant()]),
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    )
    flow_manager = FlowManager(llm=llm, context_aggregator=context_aggregator, worker=worker)

    started, ended = asyncio.Event(), asyncio.Event()

    @worker.event_handler("on_pipeline_started")
    async def on_started(worker, frame):
        started.set()

    @worker.event_handler("on_pipeline_finished")
    async def on_finished(worker, frame):
        ended.set()

    @context_aggregator.assistant().event_handler("on_assistant_turn_stopped")
    async def on_agent_turn(aggregator, message):
        if message.content:
            recorder.add("agent", text=message.content, interrupted=False)

    async def converse():
        await started.wait()
        await flow_manager.initialize(builder.build_initial_node())
        await activity.answered(ended)
        unused = len(caller_turns)
        for text in caller_turns:
            if ended.is_set():
                break
            recorder.add("user", text=text)
            unused -= 1
            activity.finished = 0
            await worker.queue_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=True))
            await activity.answered(ended)
        recorder.record["unused_turns"] = unused

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    try:
        await converse()
    finally:
        if not ended.is_set():
            await worker.queue_frame(EndFrame())
        try:
            await asyncio.wait_for(run, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Replay didn't stop in time; cancelling it")
            await runner.cancel()
    return recorder.finish()
