"""Screen chrome — pretty status bar around the face.

Layout (the Pi display is 480×320):

  ┌─────────────────────────────────────────────────┐
  │  21:47           ☀  18°C                        │   < ~44px top bar
  │  Wed, May 21         partly cloudy              │     time + day/date
  ├─────────────────────────────────────────────────┤     weather icon + condition
  │                                                 │
  │                                                 │
  │            (FACE or IDLE SCENE)                 │   < middle area
  │                                                 │
  │                                                 │
  ├─────────────────────────────────────────────────┤
  │  ✦ Listening…                                   │   < ~22px bottom band
  └─────────────────────────────────────────────────┘     (hidden when idle)

Idle ambient: when state == IDLE *and* an `idle_scene` is set, the chrome
delegates the middle area to that scene instead of the face renderer. Lets
us swap in "raindrops", "sleeping cat", "mario walking", etc. Restraint:
default is None (just the face floating), user picks the mood.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Protocol

import httpx
import numpy as np

from ...hardware.base import Frame
from ...log import get_logger
from ...runtime import secrets
from ...runtime.state_machine import LumiState

log = get_logger(__name__)

_TOP_H = 44
_BOTTOM_H = 22
_BG = (26, 26, 26)
_BG_BAR = (38, 38, 44)               # very subtle separation from the face area
_FG = (235, 235, 235)
_FG_DIM = (155, 155, 165)
_ACCENT = (255, 122, 201)

_WEATHER_TTL_S = 30 * 60
_WEATHER_TIMEOUT_S = 8.0

# OpenWeatherMap "main" categories → bigger, nicer glyph than the previous
# single-char fallback. Two-char where helpful so we can scale comfortably.
_WX_ICON = {
    "Clear":        "☀",
    "Clouds":       "☁",
    "Rain":         "☂",
    "Drizzle":      "☂",
    "Thunderstorm": "⛈",
    "Snow":         "❄",
    "Mist":         "≈",
    "Fog":          "≈",
    "Haze":         "≈",
    "Smoke":        "≈",
}


class IdleScene(Protocol):
    """An ambient scene drawn during IDLE state instead of the face."""

    def render(self, surface: object, tick: int, w: int, h: int) -> None: ...


class ScreenCompositor:
    """Wraps a face renderer with the pretty chrome + optional IdleScene."""

    def __init__(
        self,
        face_renderer: object,
        width: int,
        height: int,
        location: str = "",
        idle_scene: IdleScene | None = None,
    ) -> None:
        self._face = face_renderer
        self._w = width
        self._h = height
        self._location = location
        self._idle_scene = idle_scene
        self._status: str = ""
        self._weather: dict[str, Any] | None = None
        self._weather_fetched_at: float = 0.0
        # lazy-init pygame Font objects
        self._font_lg: object | None = None        # 22px — clock + temp
        self._font_sm: object | None = None        # 12px — date + condition
        self._font_status: object | None = None    # 13px — bottom band
        self._font_wx: object | None = None        # 28px — weather glyph

    # ── public surface ─────────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        self._status = (text or "").strip()

    def set_location(self, location: str) -> None:
        self._location = (location or "").strip()
        self._weather_fetched_at = 0.0

    def set_idle_scene(self, scene: IdleScene | None) -> None:
        self._idle_scene = scene

    def render(self, state: LumiState, tick: int) -> Frame:
        import pygame  # noqa: PLC0415

        self._maybe_refresh_weather()

        surface = pygame.Surface((self._w, self._h))
        surface.fill(_BG)

        body_h = self._h - _TOP_H - (_BOTTOM_H if self._status else 0)
        body_y = _TOP_H

        # Middle area: idle scene during IDLE if configured, else the face.
        if state == LumiState.IDLE and self._idle_scene is not None:
            sub = pygame.Surface((self._w, body_h))
            sub.fill(_BG)
            self._idle_scene.render(sub, tick, self._w, body_h)
            surface.blit(sub, (0, body_y))
        else:
            face_frame = self._face.render(state, tick)
            face_arr = face_frame.pixels
            face_surface = pygame.surfarray.make_surface(np.transpose(face_arr, (1, 0, 2)))
            if face_surface.get_width() != self._w or face_surface.get_height() != body_h:
                face_surface = pygame.transform.smoothscale(face_surface, (self._w, body_h))
            surface.blit(face_surface, (0, body_y))

        self._draw_top_bar(surface)
        if self._status:
            self._draw_bottom_band(surface)

        pixels = np.transpose(pygame.surfarray.array3d(surface), (1, 0, 2))
        return Frame(pixels=pixels)

    # ── drawing ────────────────────────────────────────────────────────────

    def _font(self, attr: str, size: int, bold: bool = False) -> object:
        import pygame  # noqa: PLC0415

        cached = getattr(self, attr)
        if cached is None:
            try:
                cached = pygame.font.SysFont("Menlo,SF Pro Display,Helvetica,sans-serif",
                                              size, bold=bold)
            except Exception:
                cached = pygame.font.Font(None, size)
            setattr(self, attr, cached)
        return cached

    def _draw_top_bar(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        pygame.draw.rect(surface, _BG_BAR, (0, 0, self._w, _TOP_H))
        pygame.draw.line(surface, (60, 60, 70), (0, _TOP_H - 1), (self._w, _TOP_H - 1))

        font_lg = self._font("_font_lg", 22, bold=True)
        font_sm = self._font("_font_sm", 12, bold=False)
        now = datetime.now()

        # ── left: time + day/date ──
        time_img = font_lg.render(now.strftime("%H:%M"), True, _FG)  # type: ignore[attr-defined]
        date_img = font_sm.render(now.strftime("%a, %b %-d"), True, _FG_DIM)  # type: ignore[attr-defined]
        surface.blit(time_img, (12, 6))
        surface.blit(date_img, (12, 6 + time_img.get_height() - 2))

        # ── right: weather icon + temp, condition below ──
        if self._weather:
            font_wx = self._font("_font_wx", 28, bold=False)
            main = self._weather.get("main", "")
            temp = self._weather.get("temperature_c")
            cond = self._weather.get("conditions", "")
            glyph = _WX_ICON.get(main, "·")

            glyph_img = font_wx.render(glyph, True, _ACCENT)  # type: ignore[attr-defined]
            temp_text = f"{round(temp)}°C" if temp is not None else "—"
            temp_img = font_lg.render(temp_text, True, _FG)  # type: ignore[attr-defined]
            cond_img = font_sm.render(cond[:24], True, _FG_DIM)  # type: ignore[attr-defined]

            x_right = self._w - 12
            # bottom-align temp with date line; glyph aligned with time
            temp_x = x_right - temp_img.get_width()
            glyph_x = temp_x - glyph_img.get_width() - 6
            surface.blit(glyph_img, (glyph_x, 4))
            surface.blit(temp_img, (temp_x, 6))
            surface.blit(cond_img, (x_right - cond_img.get_width(),
                                     6 + temp_img.get_height() - 2))

    def _draw_bottom_band(self, surface: object) -> None:
        import pygame  # noqa: PLC0415

        y0 = self._h - _BOTTOM_H
        pygame.draw.rect(surface, _BG_BAR, (0, y0, self._w, _BOTTOM_H))
        pygame.draw.line(surface, (60, 60, 70), (0, y0), (self._w, y0))
        font = self._font("_font_status", 13, bold=True)
        pygame.draw.circle(surface, _ACCENT, (12, y0 + _BOTTOM_H // 2), 3)
        text_img = font.render(self._status, True, _FG)  # type: ignore[attr-defined]
        surface.blit(text_img, (22, y0 + (_BOTTOM_H - text_img.get_height()) // 2))

    # ── weather fetch ──────────────────────────────────────────────────────

    def _maybe_refresh_weather(self) -> None:
        if not self._location:
            return
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
            wx0 = (d.get("weather") or [{}])[0]
            self._weather = {
                "temperature_c": d["main"]["temp"],
                "conditions": wx0.get("description", ""),
                "main": wx0.get("main", ""),
            }
            self._weather_fetched_at = now
            log.info("chrome.weather_refreshed", location=self._location, main=wx0.get("main"))
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            log.debug("chrome.weather_failed", error=str(exc))
