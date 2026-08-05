"""Tests for ButtonWake — the ReSpeaker HAT's physical button on GPIO17.

V1's input model promised "one physical button — wake / cancel / push-to-talk"
from the start and it was never wired; hardware/gpio.py was still a mock whose
docstring read "Real Pi impl will use gpiod once hardware arrives." The
hardware arrived in June 2026. See hardware/button.py.

gpiozero is Pi-only, so it's faked here — these run on a laptop.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lumi.audio.wake_word import CompositeWakeSource
from lumi.hardware.button import ButtonWake
from lumi.runtime.barge_in import BargeInWatcher


class _FakeButton:
    """Stands in for gpiozero.Button. Records the pin/kwargs it was built with
    and lets a test fire the press callback synchronously."""

    instances: list[_FakeButton] = []

    def __init__(self, pin, pull_up=None, bounce_time=None) -> None:
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.when_pressed = None
        self.closed = False
        _FakeButton.instances.append(self)

    def press(self) -> None:
        assert self.when_pressed is not None, "no press handler registered"
        self.when_pressed()

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _fake_gpiozero(monkeypatch):
    _FakeButton.instances = []
    module = types.ModuleType("gpiozero")
    module.Button = _FakeButton  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpiozero", module)
    yield


def _trigger(wake: ButtonWake) -> _FakeButton:
    """Force lazy GPIO setup, then hand back the fake button."""
    wake._ensure_started()
    assert _FakeButton.instances, "expected a gpiozero.Button to be constructed"
    return _FakeButton.instances[-1]


def test_press_while_idle_wakes(tmp_path: Path) -> None:
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    button = _trigger(wake)
    button.press()
    # wait_for_wake() would return immediately now.
    assert wake._event.is_set()


def test_press_while_speaking_barges_in_instead_of_waking(tmp_path: Path) -> None:
    """The behaviour that makes one button enough. Waking her back up the
    instant you told her to stop talking is the one thing that would make the
    button feel broken, so the barge-in path must NOT set the wake event."""
    wake = ButtonWake(tmp_path, is_speaking=lambda: True)
    button = _trigger(wake)
    button.press()

    assert not wake._event.is_set(), "a barge-in press must not also wake her"
    trigger = tmp_path / ".barge_in.json"
    assert trigger.exists(), "expected a barge-in trigger to be written"
    assert json.loads(trigger.read_text())["source"] == "button"


def test_barge_in_uses_the_same_channel_as_the_open_palm_gesture(tmp_path: Path) -> None:
    """One consumer (BargeInWatcher), one set of stale-trigger rules — rather
    than a GPIO callback reaching into the voice loop's threads."""
    wake = ButtonWake(tmp_path, is_speaking=lambda: True)
    watcher = BargeInWatcher(tmp_path, poll_s=0.01)
    cancel = watcher.arm()
    try:
        _trigger(wake).press()
        assert cancel.wait(timeout=2.0)
        assert watcher.source == "button"
    finally:
        watcher.disarm()


def test_uses_gpio17_with_a_pull_up_and_debounce(tmp_path: Path) -> None:
    """GPIO17 active-low with a pull-up is how the HAT wires it. Debounce
    matters because a mechanical switch bounces, and without it one physical
    press would fire several times — which on the barge-in path would look
    like a button that randomly refuses to wake her."""
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    button = _trigger(wake)
    assert button.pin == 17
    assert button.pull_up is True
    assert button.bounce_time and button.bounce_time > 0


def test_missing_gpio_degrades_to_a_dead_source(monkeypatch, tmp_path: Path) -> None:
    """On a dev laptop there's no GPIO at all. That must not take down the
    voice loop — the wake word and gesture paths still work, this source just
    never fires."""
    broken = types.ModuleType("gpiozero")

    def _raise(*a, **k):
        raise RuntimeError("no GPIO on this platform")

    broken.Button = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpiozero", broken)

    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    wake._ensure_started()  # must not raise
    assert wake._unavailable is True


def test_unavailable_source_is_not_retried_every_wait(monkeypatch, tmp_path: Path) -> None:
    """The composite races this source once per turn; retrying a doomed GPIO
    open every time would spam the log forever."""
    attempts = {"n": 0}
    broken = types.ModuleType("gpiozero")

    def _raise(*a, **k):
        attempts["n"] += 1
        raise RuntimeError("nope")

    broken.Button = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpiozero", broken)

    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    for _ in range(5):
        wake._ensure_started()
    assert attempts["n"] == 1


def test_gpio_is_opened_only_once_across_turns(tmp_path: Path) -> None:
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    for _ in range(4):
        wake._ensure_started()
    assert len(_FakeButton.instances) == 1


def test_stop_keeps_the_button_live_for_barge_in(tmp_path: Path) -> None:
    """Unlike OpenWakeWordWake.stop(), which must free the exclusive ALSA
    device, this deliberately holds the GPIO line. stop() is called at the
    START of a turn — exactly the window where Lumi is speaking and the user
    wants to interrupt. Releasing it there would disable barge-in precisely
    when it's needed."""
    speaking = {"v": False}
    wake = ButtonWake(tmp_path, is_speaking=lambda: speaking["v"])
    button = _trigger(wake)

    wake.stop()
    assert not button.closed, "stop() must not release the GPIO line"

    speaking["v"] = True
    button.press()
    assert (tmp_path / ".barge_in.json").exists(), (
        "barge-in must still work after stop()"
    )


def test_stop_clears_a_stale_wake_press(tmp_path: Path) -> None:
    """A press that arrived while the loop was already mid-turn shouldn't make
    the NEXT wait_for_wake() return instantly."""
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    _trigger(wake).press()
    assert wake._event.is_set()
    wake.stop()
    assert not wake._event.is_set()


def test_close_releases_the_line(tmp_path: Path) -> None:
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    button = _trigger(wake)
    wake.close()
    assert button.closed is True


def test_close_is_safe_when_never_started(tmp_path: Path) -> None:
    ButtonWake(tmp_path, is_speaking=lambda: False).close()  # must not raise


def test_unwritable_data_dir_does_not_crash_the_gpio_callback(tmp_path: Path) -> None:
    """A GPIO callback runs on gpiozero's own thread; an exception escaping it
    is both invisible and potentially fatal to that thread, so a failed
    trigger write has to be swallowed and logged."""
    wake = ButtonWake(tmp_path / "does-not-exist", is_speaking=lambda: True)
    _trigger(wake).press()  # must not raise


def test_respects_a_custom_pin(tmp_path: Path) -> None:
    wake = ButtonWake(tmp_path, is_speaking=lambda: False, pin=27)
    assert _trigger(wake).pin == 27


def test_is_speaking_is_consulted_per_press_not_cached(tmp_path: Path) -> None:
    """One long-lived button spans every turn, so the same physical button has
    to mean different things at different moments."""
    speaking = {"v": False}
    wake = ButtonWake(tmp_path, is_speaking=lambda: speaking["v"])
    button = _trigger(wake)

    button.press()  # idle -> wake
    assert wake._event.is_set()
    wake.stop()

    speaking["v"] = True
    button.press()  # speaking -> barge in
    assert not wake._event.is_set()
    assert (tmp_path / ".barge_in.json").exists()

    speaking["v"] = False
    (tmp_path / ".barge_in.json").unlink()
    button.press()  # idle again -> wake
    assert wake._event.is_set()
    assert not (tmp_path / ".barge_in.json").exists()


def test_wait_for_wake_returns_after_a_press(tmp_path: Path) -> None:
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    button = _trigger(wake)
    returned = threading.Event()

    def waiter() -> None:
        wake.wait_for_wake()
        returned.set()

    threading.Thread(target=waiter, daemon=True).start()
    # Give the waiter a moment to block, then press.
    assert not returned.wait(timeout=0.1)
    button.press()
    assert returned.wait(timeout=2.0), "wait_for_wake() should return on a press"


def test_composes_into_the_wake_race(tmp_path: Path) -> None:
    """ButtonWake is a WakeSource specifically so it drops into the existing
    CompositeWakeSource race with no new plumbing in the voice loop."""
    wake = ButtonWake(tmp_path, is_speaking=lambda: False)
    never = MagicMock()
    never.wait_for_wake = lambda: threading.Event().wait()
    composite = CompositeWakeSource([never, wake])

    button = _trigger(wake)
    done = threading.Event()
    threading.Thread(
        target=lambda: (composite.wait_for_wake(), done.set()), daemon=True,
    ).start()
    time.sleep(0.1)
    button.press()
    assert done.wait(timeout=2.0)
