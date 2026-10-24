#
# Usage — what a call consumed, as reported by the services (D-19).
#
# Pipecat reports usage as MetricsFrames when metrics are on: tokens per LLM
# call and characters per TTS request. UsageMeter sits in the pipeline after
# the TTS, sees both, and adds them up. Speech-to-text is billed by streamed
# audio time, so it's the call's duration (set when the record is finished).
#
# Records keep usage, not money: prices change and depend on the plan, so the
# cost is worked out when a record is read (pricing.py).
#
#   {"llm": {"calls", "input_tokens", "cached_tokens", "output_tokens"},
#    "tts": {"requests", "characters"},
#    "stt": {"seconds"}}
#

from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def empty_llm() -> dict:
    return {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}


def add_llm(llm: dict, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> None:
    """Add one LLM call. `input_tokens` includes the cached ones, as OpenAI reports it."""
    llm["calls"] += 1
    llm["input_tokens"] += input_tokens or 0
    llm["cached_tokens"] += cached_tokens or 0
    llm["output_tokens"] += output_tokens or 0


class UsageMeter(FrameProcessor):
    """Adds up the usage the services report as the frames go past."""

    def __init__(self, tts: bool = True):
        super().__init__()
        self.usage: dict = {"llm": empty_llm()}
        if tts:
            self.usage["tts"] = {"requests": 0, "characters": 0}

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            self.count(frame)
        await self.push_frame(frame, direction)

    def count(self, frame: MetricsFrame) -> None:
        for data in frame.data:
            if isinstance(data, LLMUsageMetricsData):
                t = data.value
                add_llm(self.usage["llm"], t.prompt_tokens, t.completion_tokens, t.cache_read_input_tokens or 0)
            elif isinstance(data, TTSUsageMetricsData) and "tts" in self.usage:
                self.usage["tts"]["requests"] += 1
                self.usage["tts"]["characters"] += data.value
