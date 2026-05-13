"""Tests for speak_streaming — sentence buffering and thread overlap."""

from __future__ import annotations

from unittest.mock import MagicMock, call

from lumi.audio.tts import speak_streaming


def _chunks(*parts: str):
    yield from parts


def test_single_sentence_spoken() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks("Hello world."))
    tts.speak.assert_called_once_with("Hello world.")


def test_splits_on_period_space() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks("First sentence. ", "Second sentence."))
    calls = [c.args[0] for c in tts.speak.call_args_list]
    assert "First sentence." in calls
    assert "Second sentence." in calls


def test_splits_on_question_mark() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks("How are you? ", "I am fine."))
    calls = [c.args[0] for c in tts.speak.call_args_list]
    assert any("How are you?" in c for c in calls)
    assert any("I am fine." in c for c in calls)


def test_empty_stream_no_speak() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks())
    tts.speak.assert_not_called()


def test_whitespace_only_not_spoken() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks("   "))
    tts.speak.assert_not_called()


def test_no_punctuation_spoken_as_one() -> None:
    tts = MagicMock()
    speak_streaming(tts, _chunks("no punctuation here at all"))
    tts.speak.assert_called_once_with("no punctuation here at all")


def test_multiple_chunks_assembled() -> None:
    tts = MagicMock()
    # Chunks don't align with sentence boundaries
    speak_streaming(tts, _chunks("Hel", "lo wor", "ld. Next ", "one."))
    calls = [c.args[0] for c in tts.speak.call_args_list]
    full = " ".join(calls)
    assert "Hello world." in full
    assert "Next one." in full


def test_router_handle_streaming_yields_chunks() -> None:
    """handle_streaming LLM path yields individual chunks."""
    from unittest.mock import MagicMock

    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    conv.stream_chat.return_value = iter(["chunk1 ", "chunk2."])
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts)
    chunks = list(router.handle_streaming("tell me something"))
    assert chunks == ["chunk1 ", "chunk2."]


def test_router_handle_streaming_native_yields_full_text() -> None:
    from lumi.skills.router import SkillRouter

    conv = MagicMock()
    tts = MagicMock()
    router = SkillRouter(conversation=conv, tts=tts)
    # TimerSkill triggers on "timer" but needs a duration — test with volume
    chunks = list(router.handle_streaming("volume up"))
    assert len(chunks) == 1  # single chunk from native skill
