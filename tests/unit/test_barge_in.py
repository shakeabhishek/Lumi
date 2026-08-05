"""Tests for BargeInWatcher — the consumer side of "stop talking".

Context for why this exists at all: until 2026-08-05 nothing could interrupt
Lumi mid-reply. The wake source is stopped for the duration of a turn, the
ReSpeaker button was never wired past MockGPIO, and open palm / thumbs-down
were classified, badged, and dropped. See runtime/barge_in.py.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lumi.runtime.barge_in import BargeInWatcher, request_barge_in

_FAST_POLL = 0.01


def _write_trigger(data_dir: Path, source: str = "gesture:open_palm", age_s: float = 0.0) -> None:
    ts = datetime.now(UTC) - timedelta(seconds=age_s)
    (data_dir / ".barge_in.json").write_text(
        json.dumps({"source": source, "ts": ts.isoformat()}), encoding="utf-8",
    )


def _await_event(event: threading.Event, timeout: float = 2.0) -> bool:
    return event.wait(timeout=timeout)


def test_fires_on_a_fresh_trigger(tmp_path: Path) -> None:
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        _write_trigger(tmp_path)
        assert _await_event(cancel), "a fresh open-palm trigger should cancel the reply"
        assert w.source == "gesture:open_palm"
    finally:
        w.disarm()


def test_ignores_a_stale_trigger(tmp_path: Path) -> None:
    """A palm from a couple of seconds ago was aimed at a sentence that has
    already finished playing — much tighter window than the 5s the wake path
    allows, because wake and interrupt aren't judged on the same timescale."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        _write_trigger(tmp_path, age_s=30.0)
        assert not _await_event(cancel, timeout=0.3)
        assert w.source is None
    finally:
        w.disarm()


def test_arm_discards_a_trigger_written_before_the_reply_started(tmp_path: Path) -> None:
    """The regression this guards: an open palm during the THINK phase, before
    Lumi opens her mouth. If arm() didn't clear it, the trigger would fire the
    instant she started speaking — reading as "she refuses to talk" rather
    than "I interrupted her"."""
    _write_trigger(tmp_path)  # trigger lands BEFORE arming
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        assert not _await_event(cancel, timeout=0.3)
        assert not (tmp_path / ".barge_in.json").exists()
    finally:
        w.disarm()


def test_consumes_the_trigger_file(tmp_path: Path) -> None:
    """One trigger interrupts one reply — a leftover file would cancel the
    next one too."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        _write_trigger(tmp_path)
        assert _await_event(cancel)
        assert not (tmp_path / ".barge_in.json").exists()
    finally:
        w.disarm()


def test_no_trigger_means_no_cancel(tmp_path: Path) -> None:
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        assert not _await_event(cancel, timeout=0.2)
    finally:
        w.disarm()


def test_disarm_stops_watching(tmp_path: Path) -> None:
    """While disarmed (i.e. Lumi is idle, not speaking) a trigger must not be
    latched — "interrupt" is meaningless with nothing to interrupt."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    w.disarm()
    _write_trigger(tmp_path)
    assert not _await_event(cancel, timeout=0.3)


def test_rearms_after_disarm(tmp_path: Path) -> None:
    """One watcher serves the whole voice loop, so arm/disarm cycles once per
    reply, forever. Same rebuild-on-next-use idiom as FileTriggerWake.stop()."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    w.arm()
    w.disarm()

    cancel = w.arm()
    try:
        _write_trigger(tmp_path)
        assert _await_event(cancel), "watcher should work again after a disarm/arm cycle"
    finally:
        w.disarm()


def test_arm_returns_a_cleared_event_each_time(tmp_path: Path) -> None:
    """A previous turn's interrupt must not leak into this turn's reply."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    _write_trigger(tmp_path)
    assert _await_event(cancel)
    w.disarm()

    cancel2 = w.arm()
    try:
        assert not cancel2.is_set()
        assert w.source is None
    finally:
        w.disarm()


def test_corrupt_trigger_does_not_crash_the_loop(tmp_path: Path) -> None:
    """Same tolerance as FileTriggerWake and the audit log's get_recent(): a
    half-written or hand-mangled file is dropped, and the next one self-heals.
    A bad file must never take down the voice loop."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        (tmp_path / ".barge_in.json").write_text("{not json at all", encoding="utf-8")
        assert not _await_event(cancel, timeout=0.2)
        # And a good trigger right after still works.
        _write_trigger(tmp_path)
        assert _await_event(cancel)
    finally:
        w.disarm()


def test_missing_timestamp_is_treated_as_corrupt(tmp_path: Path) -> None:
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        (tmp_path / ".barge_in.json").write_text(
            json.dumps({"source": "button"}), encoding="utf-8",
        )
        assert not _await_event(cancel, timeout=0.2)
    finally:
        w.disarm()


def test_records_the_source_for_the_audit_log(tmp_path: Path) -> None:
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        _write_trigger(tmp_path, source="button")
        assert _await_event(cancel)
        assert w.source == "button"
    finally:
        w.disarm()


# ── request_barge_in (in-process producer, e.g. the ReSpeaker button) ─────


def test_request_barge_in_round_trips(tmp_path: Path) -> None:
    """The button handler writes through this rather than reaching into the
    voice loop's threads; the watcher is the single consumer either way."""
    w = BargeInWatcher(tmp_path, poll_s=_FAST_POLL)
    cancel = w.arm()
    try:
        request_barge_in(tmp_path, source="button")
        assert _await_event(cancel)
        assert w.source == "button"
    finally:
        w.disarm()


def test_request_barge_in_writes_the_shape_the_worker_writes(tmp_path: Path) -> None:
    """The vision-worker can't import this package (MediaPipe needs protobuf
    4.x, chromadb needs 7.x) so it has its own copy of this writer. If the
    payload shape drifts, gesture barge-in breaks silently — this pins it."""
    request_barge_in(tmp_path, source="button")
    payload = json.loads((tmp_path / ".barge_in.json").read_text(encoding="utf-8"))
    assert set(payload) == {"source", "ts"}
    assert payload["source"] == "button"
    datetime.fromisoformat(payload["ts"])  # parses, and is tz-aware
    assert datetime.fromisoformat(payload["ts"]).tzinfo is not None


def test_request_barge_in_leaves_no_temp_files(tmp_path: Path) -> None:
    request_barge_in(tmp_path, source="button")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
