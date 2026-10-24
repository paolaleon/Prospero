import pytest
from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData

import pricing
import store
from call_record import CallRecorder
from usage import UsageMeter

AGENT = {"name": "A", "model": "gpt-4o", "initial_node": "a", "nodes": [{"name": "a", "end": True}]}


def test_the_meter_adds_up_llm_and_tts_usage():
    meter = UsageMeter()
    for _ in range(2):
        meter.count(MetricsFrame(data=[
            LLMUsageMetricsData(processor="llm", value=LLMTokenUsage(
                prompt_tokens=1000, completion_tokens=50, total_tokens=1050, cache_read_input_tokens=800)),
            TTSUsageMetricsData(processor="tts", value=120),
        ]))
    assert meter.usage["llm"] == {"calls": 2, "input_tokens": 2000, "cached_tokens": 1600, "output_tokens": 100}
    assert meter.usage["tts"] == {"requests": 2, "characters": 240}


def test_replays_dont_count_speech():
    meter = UsageMeter(tts=False)
    meter.count(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", value=120)]))
    assert "tts" not in meter.usage


def test_voice_calls_pay_for_speech_to_text_by_duration():
    recorder = CallRecorder(AGENT, "a", 1, source="test")
    recorder.record["started_at"] = "2026-10-24T10:00:00+00:00"
    recorder.usage, recorder.speech = {"llm": {"calls": 0}}, True
    store_now = store.now
    try:
        store.now = lambda: "2026-10-24T10:01:30+00:00"
        record = recorder.finish()
    finally:
        store.now = store_now
    assert record["usage"]["stt"] == {"seconds": 90.0}


def test_cost_is_worked_out_from_usage_and_prices():
    usage = {
        "llm": {"calls": 4, "input_tokens": 1_000_000, "cached_tokens": 400_000, "output_tokens": 100_000},
        "tts": {"requests": 4, "characters": 2000},
        "stt": {"seconds": 3600},
    }
    c = pricing.cost(usage, "gpt-4o")
    # 600k fresh x $2.50/M + 400k cached x $1.25/M + 100k out x $10/M
    assert c["llm"] == pytest.approx(1.5 + 0.5 + 1.0)
    assert c["tts"] == pytest.approx(0.08)
    assert c["stt"] == pytest.approx(0.39)
    assert c["total"] == pytest.approx(3.47) and c["complete"]


def test_a_model_without_a_price_makes_the_cost_incomplete():
    c = pricing.cost({"llm": {"calls": 1, "input_tokens": 10, "cached_tokens": 0, "output_tokens": 1},
                      "tts": {"requests": 1, "characters": 1000}}, "some-new-model")
    assert c["llm"] is None and c["complete"] is False
    assert c["total"] == pytest.approx(0.04)


def test_calls_without_usage_have_no_cost():
    assert pricing.cost(None, "gpt-4o") is None


# ---- how a call ended (D-20) ------------------------------------------------------------
@pytest.mark.parametrize("events, final_node, outcome", [
    ([{"type": "ended", "from_node": "a", "reason": "caller_done"}], "built_in_end", "completed"),
    ([{"type": "ended", "from_node": "a", "reason": "cannot_help"}], "built_in_end", "could_not_help"),
    ([{"type": "fallback", "from_node": "a", "reason": "x", "to_node": "built_in_fallback"}], "built_in_fallback", "stuck"),
    ([], "a", "completed"),  # "a" is an end node
    ([], "b", "caller_hung_up"),
])
def test_every_call_says_how_it_ended(events, final_node, outcome):
    agent = {**AGENT, "nodes": [{"name": "a", "end": True}, {"name": "b"}]}
    assert store.call_outcome({"agent": agent, "final_node": final_node, "events": events}) == outcome


def test_the_agent_ending_a_call_is_recorded():
    recorder = CallRecorder(AGENT, "a", 1, source="test")
    recorder.ended("a", "cannot_help")
    record = recorder.finish()
    assert record["final_node"] == "built_in_end" and record["ended_by"] == "agent"
    assert record["outcome"] == "could_not_help"
