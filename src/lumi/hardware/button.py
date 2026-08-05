"""The ReSpeaker HAT's physical button — GPIO17.

V1's input model has promised "one physical button — wake / cancel /
push-to-talk" since the start, and it was never wired: `hardware/gpio.py` was
still a mock whose docstring read "Real Pi impl will use gpiod once hardware
arrives." The hardware arrived in June 2026.

**One button, context-dependent**, rather than two behaviours the user has to
remember:

  - while Lumi is **speaking** -> barge in. This is the surface that works
    when the user's hands are busy and a gesture is awkward, and unlike the
    open-palm path it needs no camera, so it keeps working with
    `camera_enabled` off.
  - otherwise -> **wake**, exactly like the wake word.

Modelled as a `WakeSource` so it drops into the existing `CompositeWakeSource`
race alongside `OpenWakeWordWake` and `FileTriggerWake` — no new plumbing in
the voice loop, and pressing the button is simply another way to wake. The
barge-in half deliberately does NOT set the wake event: waking Lumi back up
the instant you told her to stop talking is the one behaviour that would make
the button feel broken.

Pi 5 note: gpiozero must use the **lgpio** backend. RPi.GPIO does not work on
the Pi 5 at all (different SoC, RP1 southbridge), which is why the `pi` extra
pins lgpio rather than RPi.GPIO. Imports are lazy so the module stays
importable on the Mac, where neither exists.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from ..audio.wake_word import WakeSource
from ..log import get_logger
from ..runtime.barge_in import request_barge_in

log = get_logger(__name__)

# GPIO17 (BCM) on the ReSpeaker 2-Mics Pi HAT. Verified readable on the
# device via gpiozero before this was written.
DEFAULT_BUTTON_PIN = 17

# The HAT's button is wired active-low with a pull-up.
_PULL_UP = True

# Mechanical switches bounce. gpiozero debounces in software when given a
# bounce time; 80 ms is comfortably longer than contact chatter and far
# shorter than a deliberate second press.
_BOUNCE_S = 0.08


class ButtonWake(WakeSource):
    """Physical button as a wake source, with barge-in while speaking.

    `is_speaking` is injected rather than read off a state machine directly so
    this stays testable without one, and so the button doesn't need to know
    what a LumiState is.
    """

    def __init__(
        self,
        data_dir: Path,
        is_speaking: Callable[[], bool],
        pin: int = DEFAULT_BUTTON_PIN,
    ) -> None:
        self._data_dir = data_dir
        self._is_speaking = is_speaking
        self._pin = pin
        self._event = threading.Event()
        self._button: object | None = None
        self._unavailable = False

    def wait_for_wake(self) -> None:
        self._ensure_started()
        self._event.wait()
        self._event.clear()

    def stop(self) -> None:
        """Deliberately keeps the gpiozero Button alive, unlike
        OpenWakeWordWake.stop() which must free the ALSA device.

        A GPIO line isn't exclusive the way the mic is, and the button has to
        stay live *precisely* during the part of the turn when the wake source
        is stopped — that's when Lumi is speaking and the user wants to
        interrupt her. Releasing it here would disable barge-in exactly when
        it's needed.
        """
        self._event.clear()

    def close(self) -> None:
        """Release the GPIO line. For shutdown and tests, not per-turn."""
        button = self._button
        self._button = None
        if button is not None:
            try:
                button.close()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                log.debug("button.close_error", error=str(exc))

    # ── internals ────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        if self._button is not None or self._unavailable:
            return
        try:
            from gpiozero import Button  # noqa: PLC0415

            button = Button(self._pin, pull_up=_PULL_UP, bounce_time=_BOUNCE_S)
        except Exception as exc:  # noqa: BLE001
            # No GPIO (dev laptop), or the pin is already claimed. Degrade to
            # "this wake source never fires" rather than taking down the voice
            # loop — the wake word and gesture paths still work.
            self._unavailable = True
            log.info("button.unavailable", pin=self._pin, error=str(exc))
            return
        button.when_pressed = self._on_press
        self._button = button
        log.info("button.ready", pin=self._pin)

    def _on_press(self) -> None:
        if self._is_speaking():
            # Routed through the same file-drop channel the open-palm gesture
            # uses, so there's one consumer (BargeInWatcher) and one set of
            # stale-trigger rules — rather than this reaching into the voice
            # loop's threads from a GPIO callback.
            log.info("button.pressed", action="barge_in")
            try:
                request_barge_in(self._data_dir, source="button")
            except OSError as exc:
                log.warning("button.barge_in_write_failed", error=str(exc))
            return
        log.info("button.pressed", action="wake")
        self._event.set()
