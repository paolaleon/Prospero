import asyncio

from pipecat.frames.frames import (
    InterimTranscriptionFrame, LLMMessagesAppendFrame, TranscriptionFrame, TTSUpdateSettingsFrame,
)
from pipecat.tests.utils import run_test

from language_guard import LanguageGuard


def said(text, language):
    return TranscriptionFrame(text=text, user_id="caller", timestamp="t", language=language)


def run_guard(allowed, frames):
    events, states = [], []

    async def on_event(action, language, text):
        events.append((action, language, text))

    guard = LanguageGuard(allowed, on_event=on_event, on_change=lambda g: states.append((g.call_language, g.blocked)))
    down, _ = asyncio.run(run_test(guard, frames_to_send=frames, expected_down_frames=None))
    return down, events, states


def texts(frames):
    return [f.text for f in frames if isinstance(f, TranscriptionFrame)]


def test_english_only_passes_english_and_blocks_other_languages():
    down, events, states = run_guard(["en"], [said("I'd like a checkup.", "eng"), said("Hola, quiero una cita.", "spa")])
    passed = texts(down)
    assert passed[0] == "I'd like a checkup."
    assert "Hola" not in passed[1] and "spoke in Spanish" in passed[1]  # the words never reach the LLM
    assert [e[:2] for e in events] == [("locked", "en"), ("blocked", "es")]
    assert states == [("en", False), ("en", True)]


def test_lock_tells_the_llm_and_switches_the_voice_before_the_words():
    down, _, _ = run_guard(["en", "es"], [said("Hola, quiero una cita.", "spa")])
    kinds = [type(f) for f in down]
    assert kinds.index(LLMMessagesAppendFrame) < kinds.index(TTSUpdateSettingsFrame) < kinds.index(TranscriptionFrame)
    message = next(f for f in down if isinstance(f, LLMMessagesAppendFrame)).messages[0]
    assert message == {"role": "system", "content": "The caller is speaking Spanish. From now on, reply only in Spanish for the rest of the call."}
    assert next(f for f in down if isinstance(f, TTSUpdateSettingsFrame)).delta.language == "es"
    assert texts(down) == ["Hola, quiero una cita."]


def test_the_language_stays_locked_after_the_first_choice():
    down, events, states = run_guard(["en", "es"], [said("I'd like to book.", "en"), said("Sí, el martes.", "es"), said("Tuesday works.", "en")])
    passed = texts(down)
    assert "continuing this call in English" in passed[1]
    assert passed[2] == "Tuesday works."
    assert states == [("en", False), ("en", True), ("en", False)]  # unblocked again in English
    assert sum(isinstance(f, LLMMessagesAppendFrame) for f in down) == 1  # locked once


def test_a_disallowed_first_utterance_doesnt_lock_the_call():
    down, events, states = run_guard(["en", "es"], [said("Bonjour.", "fra"), said("Hello.", "en")])
    assert [e[:2] for e in events] == [("blocked", "fr"), ("locked", "en")]
    assert states[0] == (None, True)


def test_undetected_language_passes_through():
    down, events, states = run_guard(["en"], [said("Mm-hmm.", None)])
    assert texts(down) == ["Mm-hmm."] and events == [] and states == [(None, False)]


def test_interim_results_in_a_blocked_language_are_dropped():
    interim = InterimTranscriptionFrame(text="Hola", user_id="caller", timestamp="t", language="spa")
    down, _, _ = run_guard(["en"], [interim])
    assert not any(isinstance(f, InterimTranscriptionFrame) for f in down)


def test_a_handled_block_is_dropped_so_the_fallback_speaks_alone():
    states = []

    async def on_event(action, language, text):
        return action == "blocked"  # the runtime moved the call to its fallback

    guard = LanguageGuard(["en"], on_event=on_event, on_change=lambda g: states.append(g.blocked))
    down, _ = asyncio.run(run_test(guard, frames_to_send=[said("Hola.", "spa")], expected_down_frames=None))
    assert texts(down) == []  # neither the words nor the note reach the LLM
    assert states == [True]


def test_locking_to_the_default_language_leaves_the_voice_alone():
    down, _, _ = run_guard(["en", "es"], [said("I'd like to book.", "en")])
    assert not any(isinstance(f, TTSUpdateSettingsFrame) for f in down)  # no reconnect
    assert any(isinstance(f, LLMMessagesAppendFrame) for f in down)
