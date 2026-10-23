from pipecat.turns.user_start import TranscriptionUserTurnStartStrategy, VADUserTurnStartStrategy

from bot import user_turn_strategies


def test_partial_transcripts_dont_interrupt_the_bot():
    start = user_turn_strategies().start
    assert any(isinstance(s, VADUserTurnStartStrategy) for s in start)  # real barge-in
    transcription = next(s for s in start if isinstance(s, TranscriptionUserTurnStartStrategy))
    assert transcription._use_interim is False
