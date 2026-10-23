#
# Languages an agent may speak (AD-15).
#
# An agent lists its allowed languages, default first; without the field it's
# English only. The runtime, not the agent's nodes, manages the language of a
# call: every utterance's language is detected, the first allowed language the
# caller speaks is locked in for the rest of the call, and speech in any other
# language gets no action (bot.py's LanguageGuard). This module holds the codes
# and the wording; the guard and the builder use it.
#

import re
from typing import Optional

# ISO 639-1 codes supported by ElevenLabs speech-to-text and text-to-speech.
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "tl": "Tagalog",
}

DEFAULT_LANGUAGES = ["en"]

# Speech-to-text may report ISO 639-3 codes; map the supported ones to 639-1.
_ISO3 = {
    "eng": "en", "spa": "es", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "ita": "it",
    "por": "pt", "nld": "nl", "dut": "nl", "pol": "pl", "rus": "ru", "ara": "ar", "hin": "hi",
    "zho": "zh", "chi": "zh", "cmn": "zh", "jpn": "ja", "kor": "ko", "vie": "vi", "tgl": "tl", "fil": "tl",
}


def name(code: str) -> str:
    return SUPPORTED_LANGUAGES.get(code, code)


def names(codes: list[str]) -> str:
    """'English', 'English or Spanish', 'English, Spanish or French'."""
    parts = [name(c) for c in codes]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " or " + parts[-1]


def normalize(language) -> Optional[str]:
    """A detected language as an ISO 639-1 code (e.g. 'eng' or 'en-US' -> 'en').
    None when nothing was detected. Unknown languages keep their own code, so
    they never match an allowed one."""
    if language is None:
        return None
    code = str(getattr(language, "value", language)).strip().lower().replace("_", "-")
    if not code:
        return None
    base = code.split("-")[0]
    return _ISO3.get(base, base)


def language_rule(allowed: list[str], call_language: Optional[str]) -> str:
    """The instruction added to every node's role message."""
    current = call_language or (allowed[0] if len(allowed) == 1 else None)
    if current:
        return (
            f"Language: speak only {name(current)}. If a caller's message says they spoke another "
            f"language, reply only with what it tells you to say, in {name(current)}, and don't call any function."
        )
    others = [c for c in allowed[1:]]
    return (
        f"Languages: start the call in {name(allowed[0])}; in your first reply, mention briefly that the caller "
        f"can also speak {names(others)}. Reply in the language of the caller's messages; you'll be told which "
        "language the call continues in. If a caller's message says they spoke another language, reply only "
        "with what it tells you to say, and don't call any function."
    )


def lock_message(language: str) -> str:
    """Added to the LLM's context when the call's language is locked in."""
    return f"The caller is speaking {name(language)}. From now on, reply only in {name(language)} for the rest of the call."


def blocked_note(spoken: Optional[str], allowed: list[str], call_language: Optional[str]) -> str:
    """What the LLM receives instead of words in a language the call doesn't use.
    The words themselves aren't passed on, so there's nothing to act on."""
    reply_in = call_language or allowed[0]
    heard = name(spoken) if spoken else "another language"
    if call_language and spoken in allowed:
        say = f"I'm sorry, we're continuing this call in {name(call_language)}."
    else:
        say = f"I'm sorry, I can only help in {names(allowed)}."
    return (
        f"[The caller spoke in {heard}, which this call doesn't use. Their words were not passed on. "
        f"Reply only, in {name(reply_in)}: \"{say}\" Don't call any function.]"
    )


_NOTE = re.compile(r"\[The caller spoke in [^\]]*\]\s*")


def without_notes(text: str) -> str:
    """A caller turn without the guard's notes (the record keeps those as separate
    language events). Empty if the turn was only notes."""
    return _NOTE.sub("", text).strip()


def refusal(call_language: Optional[str], allowed: list[str]) -> str:
    """Why a transition is refused while the caller isn't speaking the call's language."""
    return f"The caller isn't speaking {names([call_language] if call_language else allowed)}, so no action can be taken."
