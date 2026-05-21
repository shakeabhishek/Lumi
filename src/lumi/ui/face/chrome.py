"""Screen chrome — clock + weather strip + status band wrapping any face.

The face renderer still owns the middle of the display. This composer:
  - Draws a thin top strip (always): HH:MM left, weather glyph + °C right.
  - Draws a thin bottom band when a status string is set (else hides).
  - Delegates the middle area to the face renderer.

Same Frame interface, so the compositor is a transparent wrapper. Works
identically in the laptop pygame window and on the Pi's SPI display.

Weather is fetched lazily on first need and cached for `_WEATHER_TTL_S`
seconds. If no OpenWeatherMap key is in the keychain, the weather slot
is omitted (clock still shown).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import httpx
import numpy as np

from ...hardware.base import Frame
from ...log import get_logger
from ...runtime import secrets
from ...runtime.state_machine import LumiState

log = get_logger(__name__)

_TOP_H = 16          # px of top strip
_BOTTOM_H = 18       # px of bottom band (only when status set)
_BG = (26, 26, 26)
_FG = (220, 220, 220)
_FG_DIM = (140, 140, 140)
_ACCENT = (255, 122, 201)

_WEATHER_TTL_S = 30 * 60       # refresh every 30 min
_WEATHER_TIMEOUT_S = 8.0


class ScreenCompositor:
    """Wraps a face renderer with a status overlay (Option A layout)."""

    def __init__(
        self,
        face_renderer: object,
        width: int,
        height: int,
        location: str = "San Francisco",
    ) -> None:
        self._face = face_renderer
        self._w = width
        self._h = height
        self._location = location
        self._status: str = ""
        self._weather: dict[str, Any] | None = None
        self._weather_fetched_at: float = 0.0

    # ── public surface ─────────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        """Show `text` in the bottom band, or hide the band entirely if empty."""
        self._status = (text or "").strip()

    def set_location(self, location: str) -> None:
        """Change the city used for the weather chip; next render refetches."""
        self._location = (location or "").strip() or self._location
        self._weather_fetched_at = 0.0

    def render(self, state: LumiState, tick: int) -> Frame:
        """Compose chrome + face into one Frame at the full screen size."""
        import pygame  # noqa: PLC0415

        # Lazy refresh the weather (won't block the render — uses a short timeout
        # and falls back to "no weather" on failure).
        self._maybe_refresh_weather()

        # Ask the face for a frame at the FACE area's size (excluding chrome).
        face_h = self._h - _TOP_H - (_BOTTOM_H if self._status else 0)
        try:
            self._face.set_target_size(self._w, face_h)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        face_frame = self._face.render(state, tick)

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)

        # blit the face under the chrome
        face_arr = face_frame.pixels  # H x W x 3
        face_surface = pygame.surfarray.make_surface(np.transpose(face_arr, (1, 0, 2)))
        # Scale to fit the face area if the face renderer's actual output
        # doesn't match (some renderers ignore set_target_size).
        if face_surface.get_width() != self._w or face_surface.get_height() != face_h:
            face_surface = pygame.transform.smoothscale(face_surface, (self._w, face_h))
        surface.blit(face_surface, (0, _TOP_H))

        # top strip
        self._draw_top_strip(surface)
        # bottom band — only when status set
        if self._status:
            self._draw_bottom_band(surface)

        pixels = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
        return Frame(pixels=pixels)

    # ── drawing helpers ────────────────────────────────────────────────────

    def _draw_top_strip(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        font = pygame.font.SysFont("Menlo,monospace", 12, bold=True)
        # clock — left
        clock_text = datetime.now().strftime("%H:%M")
        clock_img = font.render(clock_text, True, _FG)
        surface.blit(clock_img, (8, (_TOP_H - clock_img.get_height()) // 2))
        # weather — right
        if self._weather:
            t = self._weather.get("temperature_c")
            cond = self._weather.get("conditions", "")
            glyph = self._weather_glyph(cond)
            wx = f"{glyph} {round(t)}°C" if t is not None else f"{glyph} —"
            wx_img = font.render(wx, True, _FG)
            surface.blit(wx_img, (self._w - wx_img.get_width() - 8,
                                  (_TOP_H - wx_img.get_height()) // 2))
        # subtle separator
        pygame.draw.line(surface, (60, 60, 60), (0, _TOP_H - 1), (self._w, _TOP_H - 1))

    def _draw_bottom_band(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        y0 = self._h - _BOTTOM_H
        pygame.draw.line(surface, (60, 60, 60), (0, y0), (self._w, y0))
        font = pygame.font.SysFont("Menlo,monospace", 12, bold=True)
        # Pink accent dot, then status text
        pygame.draw.circle(surface, _ACCENT, (10, y0 + _BOTTOM_H // 2), 3)
        text_img = font.render(self._status, True, _FG)
        surface.blit(text_img, (20, y0 + (_BOTTOM_H - text_img.get_height()) // 2))

    @staticmethod
    def _weather_glyph(condition: str) -> str:
        c = (condition or "").lower()
        if "thunder" in c: return "⛈"
        if "snow" in c: return "❄"
        if "rain" in c or "drizzle" in c: return "☂"
        if "cloud" in c: return "☁"
        if "clear" in c or "sun" in c: return "☀"
        if "mist" in c or "fog" in c: return "≈"
        return "·"

    # ── weather fetch (cached, best-effort) ────────────────────────────────

    def _maybe_refresh_weather(self) -> None:
        now = time.monotonic()
        if self._weather is not None and (now - self._weather_fetched_at) < _WEATHER_TTL_S:
            return
        key = secrets.get_secret("openweathermap_api_key")
        if not key:
            return
        try:
            r = httpx.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": self._location, "appid": key, "units": "metric"},
                timeout=_WEATHER_TIMEOUT_S,
            )
            r.raise_for_status()
            d = r.json()
            self._weather = {
                "temperature_c": d["main"]["temp"],
                "conditions": (d.get("weather") or [{}])[0].get("description", ""),
            }
            self._weather_fetched_at = now
            log.info("chrome.weather_refreshed", location=self._location)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            log.debug("chrome.weather_failed", error=str(exc))
            # Keep prior cached value (if any); don't bash to None.
