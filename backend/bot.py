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
# Which agent a call runs is decided per call by the `/start` request body:
#   {"agent": {...}}     an inline (possibly unsaved) agent — what the editor sends
#   {"agent_id": "..."}  a saved agent from backend/agents/
#   {}                   AGENT_FLOW below
#
# During a call, every node change is pushed to the client as an RTVI server
# message, so the editor can highlight where the conversation is in the graph.
#
# Run:  python bot.py   (editor API on http://localhost:7860/api, test client at /client)
#

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
from agent_builder import AgentBuilder

# Load .env next to this file, so the bot runs the same from the repo root or backend/.
load_dotenv(Path(__file__).parent / ".env", override=True)


# The agent a call runs when its request names none. Point this at any agent JSON
# (the Phase 2 Composer would generate one and drop it here).
AGENT_FLOW = Path(__file__).parent / "example_flow.json"


transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(
    transport: BaseTransport, runner_args: RunnerArguments, builder: AgentBuilder
) -> None:
    config = builder.config
    logger.info(f"Starting '{config.name}' with {len(config.nodes)} nodes")

    stt = ElevenLabsRealtimeSTTService(api_key=os.environ["ELEVENLABS_API_KEY"])
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=config.voice_id),
    )
    llm = OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=config.model)

    async def notify_node(node: str, **extra) -> None:
        await worker.rtvi.send_server_message({"type": "flow.node", "node": node, **extra})

    async def on_transition(from_node: str, function: str, to_node: str, args: dict) -> None:
        await notify_node(to_node, from_node=from_node, function=function, args=args)

    builder.on_transition = on_transition

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

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
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
    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Entry point invoked by the Pipecat dev runner (and Pipecat Cloud)."""
    builder = _builder_for(runner_args.body or {})
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args, builder)


def _builder_for(body: dict) -> AgentBuilder:
    """Pick the agent for this call from the /start request body."""
    if isinstance(body.get("agent"), dict):
        return AgentBuilder.from_dict(body["agent"])
    if body.get("agent_id"):
        return AgentBuilder.from_dict(api.load_agent(body["agent_id"]))
    return AgentBuilder.from_json(AGENT_FLOW)


if __name__ == "__main__":
    from pipecat.runner.run import app, main

    # Must be registered before main() adds the runner's own routes.
    api.register_routes(app)
    main()
