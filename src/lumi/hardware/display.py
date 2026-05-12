"""Display implementations.

- `PygameDisplay`: opens a window the size of the real SPI panel and blits frames.
  Used for laptop dev.
- `SPIDisplay`: TODO when hardware arrives. Will write frames to the Waveshare
  3.5" panel over the SPI bus.
"""

from __future__ import annotations

import os

from .base import Display, Frame

# Defer pygame import until instantiation — keeps headless test runs cheap and
# avoids pulling SDL when we only need types from this module.


class PygameDisplay(Display):
    def __init__(self, width: int, height: int, title: str = "Lumi") -> None:
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        import pygame  # noqa: PLC0415 — lazy import by design

        pygame.init()
        pygame.display.set_caption(title)
        self._pygame = pygame
        self._size = (width, height)
        self._surface = pygame.display.set_mode(self._size)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def show(self, frame: Frame) -> None:
        # frame.pixels is HxWx3 uint8; pygame wants WxH surfarray order
        arr = frame.pixels.swapaxes(0, 1)
        surf = self._pygame.surfarray.make_surface(arr)
        self._surface.blit(surf, (0, 0))
        self._pygame.display.flip()
        # Drain the event queue so the OS doesn't think the window is hung.
        for event in self._pygame.event.get():
            if event.type == self._pygame.QUIT:
                raise KeyboardInterrupt

    def close(self) -> None:
        self._pygame.quit()


def make_display(width: int, height: int) -> Display:
    """Factory — returns the right Display for the current platform.

    For now always Pygame. When the Pi build lands, dispatch on platform/env.
    """
    return PygameDisplay(width, height)
