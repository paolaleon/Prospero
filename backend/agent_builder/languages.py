#
# Languages an agent may speak (AD-15).
#
# An agent lists its languages, default first; without the field it's English
# only. The builder turns the list into a rule added to every node, and bot.py
# fixes speech-to-text and text-to-speech to the language when there's only one.
#

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


def _names(codes: list[str]) -> str:
    names = [SUPPORTED_LANGUAGES.get(c, c) for c in codes]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def language_rule(codes: list[str]) -> str:
    """The instruction added to every node so the agent keeps to its languages."""
    default = SUPPORTED_LANGUAGES.get(codes[0], codes[0])
    allowed = _names(codes)
    # Callers in other languages aren't left stranded: staff can call them back.
    fallback = (
        f"If the caller speaks any other language, say in {default} that you can only help in {allowed}, "
        "and offer to take their name and phone number so the clinic's staff can call them back."
    )
    if len(codes) == 1:
        return f"Language: speak only {default}, whatever language the caller uses. {fallback}"
    return (
        f"Languages: start the call in {default}, and at the start offer the caller a choice of {allowed}. "
        f"Once they choose, use that language for the rest of the call. Never use any other language. {fallback}"
    )


def speech_language(codes: list[str]) -> str | None:
    """The language to fix speech-to-text and text-to-speech to, or None to let
    them detect it (when the agent speaks several languages)."""
    return codes[0] if len(codes) == 1 else None
