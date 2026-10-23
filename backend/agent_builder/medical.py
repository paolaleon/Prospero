#
# Medical safety (AD-17).
#
# Every agent is a medical voice agent (AD-11), so the builder adds this rule to
# every node, after the persona or any per-node persona override. It doesn't
# depend on who wrote the persona: an agent made by hand, or edited, can't end
# up without it.
#

NO_MEDICAL_ADVICE_RULE = (
    "Medical safety: never diagnose, interpret symptoms, or suggest treatments, remedies, "
    "home care or medications (including over-the-counter ones and doses), even if the caller "
    "insists. If asked, say you can't give medical advice, and offer to book an appointment or "
    "pass the question to the clinic's staff. If the caller describes something urgent or "
    "life-threatening, tell them to hang up and call emergency services now."
)
