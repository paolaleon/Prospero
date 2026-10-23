from agent_builder.languages import (
    SUPPORTED_LANGUAGES, blocked_note, without_notes, language_rule, lock_message, names, normalize, refusal,
)


def test_detected_codes_are_normalised():
    assert normalize("eng") == "en"
    assert normalize("spa") == "es"
    assert normalize("en-US") == "en"
    assert normalize("EN") == "en"
    assert normalize("cmn") == "zh"
    assert normalize(None) is None and normalize("") is None
    assert normalize("swa") == "swa"  # unsupported: kept, so it never matches an allowed language


def test_english_only_rule():
    assert language_rule(["en"], None).startswith("Language: speak only English.")


def test_several_languages_before_and_after_the_lock():
    before = language_rule(["en", "es", "fr"], None)
    assert "start the call in English" in before and "can also speak Spanish or French" in before
    assert language_rule(["en", "es"], "es").startswith("Language: speak only Spanish.")


def test_blocked_note_tells_the_llm_what_to_say_without_the_words():
    note = blocked_note("es", ["en"], None)
    assert "spoke in Spanish" in note and "I can only help in English." in note
    assert "Don't call any function" in note
    after_lock = blocked_note("es", ["en", "es"], "en")
    assert "we're continuing this call in English" in after_lock


def test_wording_helpers():
    assert names(["en", "es", "fr"]) == "English, Spanish or French"
    assert lock_message("es") == "The caller is speaking Spanish. From now on, reply only in Spanish for the rest of the call."
    assert refusal(None, ["en"]) == "The caller isn't speaking English, so no action can be taken."
    assert all(len(c) == 2 and c.islower() for c in SUPPORTED_LANGUAGES)


def test_notes_are_removed_from_caller_turns():
    note = blocked_note("es", ["en"], None)
    assert without_notes(f"{note} {note} All favor.") == "All favor."
    assert without_notes(note) == ""
    assert without_notes("I'd like a checkup.") == "I'd like a checkup."
