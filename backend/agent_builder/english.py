#
# English only (AD-15).
#
# Every agent speaks English. bot.py fixes speech-to-text and the voice to
# English, and the builder adds this rule to every node, after any persona
# override, so no node can drop it.
#

ENGLISH_ONLY_RULE = (
    "Language: speak only English, whatever language the caller uses. If the caller "
    "doesn't speak English, say in English that you can only help in English. Never "
    "reply in another language."
)
