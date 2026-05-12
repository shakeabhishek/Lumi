"""USB composite gadget mocks.

Real Pi impl uses `libcomposite` via /sys/kernel/config/usb_gadget/ to expose
HID + Mass Storage + CDC to the host PC. That's a Week 4 / hardware-phase task.
"""

from __future__ import annotations

from ..log import get_logger

log = get_logger(__name__)


class NullUSBGadget:
    def setup(self) -> None:
        log.debug("usb_gadget.setup (no-op on laptop)")

    def teardown(self) -> None:
        log.debug("usb_gadget.teardown")

    def send_text(self, text: str) -> None:
        log.debug("usb_gadget.send_text", text=text)
