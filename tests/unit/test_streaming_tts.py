"""Tests for speak_streaming — sentence buffering, thread overlap, barge-in."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lumi.audio.tts import MacSayTTS, PiperTTS, speak_streaming


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


# ── Barge-in / cancellation ──────────────────────────────────────────────
#
# Until 2026-08-05 there was no way to stop Lumi mid-reply by any means:
# the wake source is stopped for the duration of a turn, the ReSpeaker
# button was never wired, and open-palm only rendered a badge. These lock
# in the cancellation contract the barge-in surfaces are built on.


def test_returns_true_when_it_speaks_the_whole_reply() -> None:
    """The return value is how callers tell a completed turn from an
    interrupted one (for captions and the audit log)."""
    tts = MagicMock()
    assert speak_streaming(tts, _chunks("One. ", "Two.")) is True


def test_returns_true_with_an_unset_cancel_event() -> None:
    tts = MagicMock()
    assert speak_streaming(tts, _chunks("One. "), cancel=threading.Event()) is True
    tts.stop.assert_not_called()


def test_cancel_already_set_speaks_nothing() -> None:
    """Barge-in that lands before the reply starts — e.g. the user waves
    off an answer they can already tell they don't want."""
    cancel = threading.Event()
    cancel.set()
    tts = MagicMock()
    assert speak_streaming(tts, _chunks("One. ", "Two."), cancel=cancel) is False
    tts.speak.assert_not_called()


def test_cancel_mid_utterance_drops_the_remaining_sentences() -> None:
    """The core barge-in case, and the open question GestureBadge.tsx
    flagged: sentences already parsed and queued but not yet played get
    DROPPED, not drained. Holding them would just replay stale speech the
    user has already interrupted.

    Synchronised on stop() rather than a sleep, which also mirrors the real
    contract: PiperTTS.speak() returns because stop() aborted the PortAudio
    stream out from under its sd.wait().
    """
    cancel = threading.Event()
    stop_called = threading.Event()
    spoken: list[str] = []

    def speak(text: str) -> None:
        spoken.append(text)
        if len(spoken) == 1:
            first_utterance.set()
            stop_called.wait(timeout=3.0)

    first_utterance = threading.Event()
    tts = MagicMock()
    tts.speak.side_effect = speak
    tts.stop.side_effect = stop_called.set

    def barge_in() -> None:
        first_utterance.wait(timeout=3.0)
        cancel.set()

    threading.Thread(target=barge_in, daemon=True).start()
    completed = speak_streaming(
        tts, _chunks("One. ", "Two. ", "Three. ", "Four."), cancel=cancel,
    )

    assert completed is False
    assert spoken == ["One."], "queued-but-unplayed sentences should be dropped"
    tts.stop.assert_called()


def test_cancel_stops_consuming_the_llm_stream() -> None:
    """A cancelled reply shouldn't keep pulling tokens into a void — on the
    cloud path that's billable, and on the local path it's CPU the rest of
    the stack wants."""
    cancel = threading.Event()
    pulled: list[int] = []

    def stream():
        for i in range(50):
            if i == 3:
                cancel.set()  # barge-in lands as the 4th chunk is produced
            pulled.append(i)
            yield f"Sentence {i}. "

    tts = MagicMock()
    assert speak_streaming(tts, stream(), cancel=cancel) is False
    # The producer checks cancel at the top of each iteration, so it stops
    # right after the chunk that set it — not after all 50.
    assert pulled == [0, 1, 2, 3]


def test_cancel_suppresses_the_final_sentence_marker() -> None:
    """No point captioning a sentence as the final one when it's never
    going to be spoken — the caller marks the turn interrupted instead."""
    cancel = threading.Event()
    cancel.set()
    seen: list[tuple[str, bool]] = []
    speak_streaming(
        MagicMock(), _chunks("One. ", "Two."),
        on_sentence=lambda t, f: seen.append((t, f)),
        cancel=cancel,
    )
    assert seen == []


def test_resets_the_backend_latch_at_the_start_of_each_reply() -> None:
    """PiperTTS is loaded once and reused for the whole process lifetime, so
    a stop() latched by a previous turn's barge-in would silence the next
    reply entirely if it weren't cleared."""
    tts = MagicMock()
    speak_streaming(tts, _chunks("Hello."))
    tts.reset.assert_called_once()


def test_works_with_a_backend_that_has_no_reset() -> None:
    """reset()/stop() are part of the TTS protocol, but a third-party or
    older backend object may not have them — that shouldn't crash a reply
    that isn't even using cancellation."""
    class Minimal:
        def __init__(self) -> None:
            self.spoken: list[str] = []

        @property
        def name(self) -> str:
            return "minimal"

        def speak(self, text: str) -> None:
            self.spoken.append(text)

    tts = Minimal()
    assert speak_streaming(tts, _chunks("Hello there.")) is True  # type: ignore[arg-type]
    assert tts.spoken == ["Hello there."]


# ── Backend stop() implementations ───────────────────────────────────────


def test_piper_stop_latches_so_a_queued_utterance_stays_silent(tmp_path: Path) -> None:
    """sd.stop() alone can't cover a barge-in that lands between sentences,
    or during the ~0.4-0.7s of synthesis before playback starts — there's no
    active stream to abort. The latch covers that window.

    Also proves the latch short-circuits before the model load: this voice
    file doesn't exist, so speak() would raise FileNotFoundError if the
    latch weren't checked first.
    """
    piper = PiperTTS("no-such-voice", tmp_path)
    piper.stop()
    piper.speak("this must not play")  # no raise == never reached the load


def test_piper_reset_clears_the_latch(tmp_path: Path) -> None:
    piper = PiperTTS("no-such-voice", tmp_path)
    piper.stop()
    piper.reset()
    # Latch cleared, so speak() now proceeds far enough to hit the missing
    # model — which is the proof it's no longer short-circuiting.
    with pytest.raises(FileNotFoundError):
        piper.speak("now it tries for real")


def test_mac_say_stop_terminates_the_in_flight_process() -> None:
    """`say` is a subprocess, not PortAudio playback, so sd.stop() has no
    effect on it — it needs its own handle."""
    if not hasattr(MacSayTTS, "stop"):  # pragma: no cover
        pytest.skip("stop() not implemented")
    tts = MacSayTTS()
    started = threading.Event()

    def run() -> None:
        started.set()
        # A long utterance so there's reliably something in flight.
        tts.speak("one two three four five six seven eight nine ten")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    started.wait(timeout=2.0)
    time.sleep(0.3)  # let Popen actually spawn
    tts.stop()
    t.join(timeout=3.0)
    assert not t.is_alive(), "stop() should have cut the utterance short"


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
