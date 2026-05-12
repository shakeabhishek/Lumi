"""GPIO mocks. Real Pi impl will use `gpiod` (libgpiod) once hardware arrives."""

from __future__ import annotations

from ..log import get_logger

log = get_logger(__name__)


class NullGPIO:
    """No-op GPIO. Logs every call so dev still sees what would happen on hardware."""

    def set(self, pin: int, value: bool) -> None:
        log.debug("gpio.set", pin=pin, value=value)

    def get(self, pin: int) -> bool:
        log.debug("gpio.get", pin=pin)
        return False
