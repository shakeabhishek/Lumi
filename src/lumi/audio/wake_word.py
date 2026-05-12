"""Wake-word detection.

V1 ships with a curated palette of pre-trained names — see CLAUDE.md. Until we
wire OpenWakeWord (Pi) or Porcupine, dev uses push-to-talk: press Enter to wake.

The interface (`WakeSource.wait_for_wake`) is what the runtime depends on, so
swapping push-to-talk for real wake-word detection later is a one-class change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..log import get_logger

log = get_logger(__name__)


class WakeSource(ABC):
    @abstractmethod
    def wait_for_wake(self) -> None:
        """Block until Lumi should wake up and start listening."""


class PushToTalkWake(WakeSource):
    """Enter key = wake. Trivial, reliable, perfect for laptop dev."""

    def __init__(self, prompt: str = "[press Enter to talk to Lumi, Ctrl-C to quit] ") -> None:
        self._prompt = prompt

    def wait_for_wake(self) -> None:
        try:
            input(self._prompt)
        except EOFError:
            raise KeyboardInterrupt from None


class OpenWakeWordWake(WakeSource):
    """TODO: implement when we move to the Pi. Listens to a streaming mic feed and
    fires when the configured wake word is detected."""

    def __init__(self, model: str) -> None:
        self._model = model

    def wait_for_wake(self) -> None:
        raise NotImplementedError("OpenWakeWord wake source — implement on Pi")
