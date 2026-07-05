"""Tests for speak_streaming — sentence buffering and thread overlap."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

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


# ── on_sentence caption hook ─────────────────────────────────────────────


def test_on_sentence_called_with_one_sentence_at_a_time() -> None:
    """The voice loop's live-caption feature hooks this callback. It must
    receive ONE sentence at a time, not the cumulative reply so far — an
    earlier cumulative design made a multi-sentence caption grow to fill
    the whole screen instead of reading like live captions (found in real
    use, 2026-07-02; see device_display.py's publish_caption)."""
    tts = MagicMock()
    seen: list[tuple[str, bool]] = []
    speak_streaming(
        tts, _chunks("First sentence. ", "Second sentence."),
        on_sentence=lambda text, is_last: seen.append((text, is_last)),
    )
    assert seen == [("First sentence.", False), ("Second sentence.", True)]


def test_on_sentence_fires_when_spoken_not_when_parsed() -> None:
    """Regression test for a real bug found on the Pi (2026-07-05): a
    single incoming chunk can contain SEVERAL complete sentences at once
    (routine after RoutedBackend's cloud-first flip — cloud streams
    arrive in much bigger pieces than local token-by-token streaming
    did). The old code fired on_sentence the moment each sentence was
    PARSED off the chunk, all in a tight loop in the main thread — while
    the background worker thread was still speaking through them one at
    a time. Visually this looked like "only the last caption ever
    appears," even though every sentence really was queued: all the
    caption updates landed within milliseconds of each other while the
    actual audio was still seconds behind.

    Fix: on_sentence now fires from INSIDE the worker thread, right
    before tts.speak() is called for that sentence — so caption timing
    tracks audio timing. This test feeds THREE sentences in one chunk
    (worst case for the old bug) and makes tts.speak() artificially slow,
    then asserts each on_sentence call is paced by the PRECEDING speak()
    call actually finishing — not fired in a burst up front.
    """
    speak_started_at: list[float] = []
    on_sentence_at: list[float] = []

    def slow_speak(_text: str) -> None:
        speak_started_at.append(time.monotonic())
        time.sleep(0.05)

    tts = MagicMock()
    tts.speak.side_effect = slow_speak

    def record_on_sentence(_text: str, _is_last: bool) -> None:
        on_sentence_at.append(time.monotonic())

    speak_streaming(
        tts,
        _chunks("First sentence. Second sentence. Third sentence."),
        on_sentence=record_on_sentence,
    )

    assert len(on_sentence_at) == 3
    assert len(speak_started_at) == 3
    # Each on_sentence call must land at or after that SAME sentence's
    # speak() call starts (paced with real timing), not all clustered at
    # the very start before any speak() has even begun.
    for i in range(3):
        assert on_sentence_at[i] >= speak_started_at[i] - 0.01
    # The gap between the first and last caption update should reflect
    # the real speaking delay (2 * 0.05s between 3 sentences), not be
    # near-instant like a parse-time burst would produce.
    assert on_sentence_at[-1] - on_sentence_at[0] >= 0.08


def test_on_sentence_marks_final_when_stream_ends_on_boundary() -> None:
    """Edge case: if the token stream ends exactly on a sentence boundary,
    `buf` is empty afterward. The one-item-lookahead design holds the
    sentence back (undecided whether it's last) until it either sees a
    following sentence or the stream ends — here the stream ends first,
    so it fires exactly once, correctly marked final. (An earlier design
    queued it as non-final immediately, then had to re-fire the same
    text a second time to signal completion — this is the fix for that:
    one accurate call instead of two, one of them wrong.)"""
    tts = MagicMock()
    seen: list[tuple[str, bool]] = []
    speak_streaming(
        tts, _chunks("Only one sentence. "),
        on_sentence=lambda text, is_last: seen.append((text, is_last)),
    )
    assert seen == [("Only one sentence.", True)]


def test_on_sentence_not_called_when_omitted() -> None:
    """Default None — existing non-caption callers are unaffected."""
    tts = MagicMock()
    # Should not raise even though no on_sentence is passed.
    speak_streaming(tts, _chunks("Hello world."))
    tts.speak.assert_called_once_with("Hello world.")


def test_on_sentence_does_not_change_tts_behavior() -> None:
    """Regression guard: the caption hook must not alter what's actually
    spoken — tts.speak() calls stay exactly as before."""
    tts = MagicMock()
    speak_streaming(
        tts, _chunks("Hel", "lo wor", "ld. Next ", "one."),
        on_sentence=lambda _t, _f: None,
    )
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
