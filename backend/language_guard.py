#
# LanguageGuard — keeps a call in its language (AD-15).
#
# Sits between speech-to-text and the LLM. Speech-to-text detects the language of
# every utterance; the guard then:
#   - locks the call to the first allowed language the caller speaks, tells the
#     LLM to reply in it from now on, and switches the voice to it;
#   - passes utterances in the call's language through unchanged;
#   - replaces anything else (another language, or an allowed one after the lock)
#     with a note saying what to reply, so the words never reach the LLM and no
#     action can be taken on them. Transitions are refused meanwhile (builder).
# Utterances with no detected language pass through: the guard only acts on a
# positive detection.
#

from typing import Awaitable, Callable, Optional

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    LLMMessagesAppendFrame,
    TranscriptionFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from agent_builder import languages

# (action, language, text): called when the call locks to a language
# ("locked") and when an utterance is blocked ("blocked"). bot.py records them.
# Returning True for a blocked utterance means it was handled (the call moved
# to its fallback, AD-16), so the guard drops it instead of passing the note on.
LanguageEvent = Callable[[str, Optional[str], str], Awaitable[Optional[bool]]]
# Called after every final utterance with the guard, so the builder can follow
# its state (call_language, blocked).
StateChange = Callable[["LanguageGuard"], None]


class LanguageGuard(FrameProcessor):
    def __init__(
        self,
        allowed: list[str],
        on_event: Optional[LanguageEvent] = None,
        on_change: Optional[StateChange] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._on_change = on_change
        self.allowed = list(allowed)
        self.call_language: Optional[str] = None
        self.blocked = False  # whether the caller's last utterance was blocked
        self._on_event = on_event

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame):
            # Partial results only feed live captions; drop any we'd block.
            if self._decide(languages.normalize(frame.language)) == "block":
                return
        elif isinstance(frame, TranscriptionFrame):
            spoken = languages.normalize(frame.language)
            decision = self._decide(spoken)
            if decision == "lock":
                self.call_language = spoken
                await self._emit("locked", spoken, frame.text)
                # Before the caller's words, so the LLM replies in the new language.
                await self.push_frame(
                    LLMMessagesAppendFrame([{"role": "system", "content": languages.lock_message(spoken)}], run_llm=False),
                    direction,
                )
                # The voice starts in the default language; only switch it if the
                # call locked to another one (a switch reconnects the voice).
                if spoken != self.allowed[0]:
                    await self.push_frame(
                        TTSUpdateSettingsFrame(settings={}, delta=ElevenLabsTTSService.Settings(language=spoken)),
                        direction,
                    )
            if decision == "block":
                self.blocked = True
                if await self._emit("blocked", spoken, frame.text):
                    if self._on_change:
                        self._on_change(self)
                    return  # handled: the fallback speaks instead
                frame = TranscriptionFrame(
                    text=languages.blocked_note(spoken, self.allowed, self.call_language),
                    user_id=frame.user_id,
                    timestamp=frame.timestamp,
                    language=frame.language,
                )
            else:
                self.blocked = False
            if self._on_change:
                self._on_change(self)

        await self.push_frame(frame, direction)

    def _decide(self, spoken: Optional[str]) -> str:
        """'pass', 'lock' or 'block' for an utterance in language `spoken`."""
        if spoken is None:
            return "pass"  # nothing detected: don't guess
        if self.call_language is None:
            return "lock" if spoken in self.allowed else "block"
        return "pass" if spoken == self.call_language else "block"

    async def _emit(self, action: str, spoken: Optional[str], text: str) -> bool:
        return bool(self._on_event and await self._on_event(action, spoken, text))
