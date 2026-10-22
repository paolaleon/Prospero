#
# Voice pipeline — Prosper Product Engineer Challenge
#
# The runnable voice agent: WebRTC transport + ElevenLabs STT/TTS + OpenAI LLM,
# driven by a Pipecat Flows node graph. This file is generic — it loads an agent
# definition (JSON) via AgentBuilder and runs it. Swapping the agent is a data
# change (edit/replace the JSON), not a code change.
#
#   agent JSON  ->  AgentBuilder  ->  Pipecat Flows graph  ->  FlowManager
#
# Which agent a call runs is decided per call by the `/start` request body
# (see store.resolve_call_agent):
#   {"agent": {...}, "agent_id": "..."}     an unsaved draft — what the editor sends
#   {"agent_id": "...", "version": n}       a saved version (the latest if omitted)
#   {}                                      AGENT_FLOW below
#
# During a call, every node change and every recorded event (turns, transitions)
# is pushed to the client as an RTVI server message, so the editor can show the
# live transcript and highlight where the conversation is in the graph.
# When the call ends, it is recorded (transcript, node path, collected data and
# the agent it ran) in backend/calls/, as material for iterating on the agent.
#
# Run:  python bot.py   (editor API on http://localhost:7860/api, test client at /client)
#

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner
from pipecat_flows import FlowManager

import api
import store
from agent_builder import AgentBuilder

# Load .env next to this file, so the bot runs the same from the repo root or backend/.
load_dotenv(Path(__file__).parent / ".env", override=True)


# The agent a call runs when its request names none.
AGENT_FLOW = Path(__file__).parent / "example_flow.json"


transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


class CallRecorder:
    """Collects one call's timeline and writes it to the store when the call ends."""

    def __init__(self, agent: dict, agent_id, version, source: str):
        self.record = {
            "id": store.new_call_id(),
            "source": source,
            "agent_id": agent_id,
            "agent_version": version,
            "agent": agent,
            "started_at": store.now(),
            "ended_at": None,
            "ended_by": None,
            "final_node": agent["initial_node"],
            "collected": {},
            "events": [],
        }

    @property
    def call_id(self) -> str:
        return self.record["id"]

    def add(self, type: str, **fields) -> dict:
        event = {"t": store.now(), "type": type, **fields}
        self.record["events"].append(event)
        return event

    def transition(self, from_node: str, function: str, to_node: str, args: dict) -> dict:
        self.record["final_node"] = to_node
        self.record["collected"].update(args)
        return self.add("transition", from_node=from_node, function=function, to_node=to_node, args=args)

    def refusal(self, node: str, function: str, args: dict, problems: list) -> dict:
        # A transition the LLM tried without the data it requires. Repeated
        # refusals in one node are a sign its instructions need work.
        return self.add("refused", node=node, function=function, args=args, problems=problems)

    def save(self) -> None:
        end_nodes = {n["name"] for n in self.record["agent"]["nodes"] if n.get("end")}
        self.record["ended_at"] = store.now()
        self.record["ended_by"] = "agent" if self.record["final_node"] in end_nodes else "caller"
        store.save_call(self.record)
        logger.info(f"Recorded call {self.call_id} ({len(self.record['events'])} events)")


async def run_bot(
    transport: BaseTransport,
    runner_args: RunnerArguments,
    builder: AgentBuilder,
    recorder: CallRecorder,
) -> None:
    config = builder.config
    logger.info(f"Starting '{config.name}' with {len(config.nodes)} nodes (call {recorder.call_id})")

    stt = ElevenLabsRealtimeSTTService(api_key=os.environ["ELEVENLABS_API_KEY"])
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=config.voice_id),
    )
    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=config.model)

    async def notify_node(node: str, **extra) -> None:
        await worker.rtvi.send_server_message({"type": "flow.node", "node": node, **extra})

    async def notify_event(event: dict) -> None:
        # The live transcript is the call record as it's written, so what the
        # editor shows during a call is exactly what gets saved.
        await worker.rtvi.send_server_message({"type": "call.event", "event": event})

    async def on_transition(from_node: str, function: str, to_node: str, args: dict) -> None:
        await notify_event(recorder.transition(from_node, function, to_node, args))
        await notify_node(to_node, from_node=from_node, function=function, args=args)

    async def on_transition_refused(node: str, function: str, args: dict, problems: list) -> None:
        await notify_event(recorder.refusal(node, function, args, problems))

    builder.on_transition = on_transition
    builder.on_transition_refused = on_transition_refused

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
    )

    @context_aggregator.user().event_handler("on_user_turn_message_added")
    async def on_user_message(aggregator, message):
        if message.content:
            await notify_event(recorder.add("user", text=message.content))

    @context_aggregator.assistant().event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn(aggregator, message):
        if message.content:
            await notify_event(recorder.add("agent", text=message.content, interrupted=message.interrupted))

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        await worker.rtvi.send_server_message({"type": "call.started", "call_id": recorder.call_id})
        await notify_node(config.initial_node)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — starting flow at initial node")
        await flow_manager.initialize(builder.build_initial_node())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        recorder.save()


async def bot(runner_args: RunnerArguments):
    """Entry point invoked by the Pipecat dev runner (and Pipecat Cloud)."""
    body = runner_args.body or {}
    agent, agent_id, version = store.resolve_call_agent(body)
    if agent is None:
        agent = json.loads(AGENT_FLOW.read_text())
    builder = AgentBuilder.from_dict(agent)
    recorder = CallRecorder(agent, agent_id, version, source=body.get("source", "test"))
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args, builder, recorder)


if __name__ == "__main__":
    from pipecat.runner.run import app, main

    # Must be registered before main() adds the runner's own routes.
    api.register_routes(app)
    main()
