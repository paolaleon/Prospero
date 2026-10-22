from agent_builder.languages import SUPPORTED_LANGUAGES, language_rule, speech_language


def test_one_language_fixes_speech_services():
    assert speech_language(["en"]) == "en"
    assert speech_language(["es"]) == "es"


def test_several_languages_let_speech_services_detect():
    assert speech_language(["en", "es"]) is None


def test_rules_name_the_languages():
    assert language_rule(["es"]).startswith("Language: speak only Spanish")
    assert "English, Spanish or French" in language_rule(["en", "es", "fr"])


def test_supported_codes_are_two_letter_iso_codes():
    assert all(len(code) == 2 and code.islower() for code in SUPPORTED_LANGUAGES)
