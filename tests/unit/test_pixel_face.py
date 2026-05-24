"""Tests for the kawaii PixelFaceRenderer redesign.

Focus on the contract, not pixel-by-pixel exactness — that would make
every art tweak a test-breaking change. We assert:
  * Each LumiState produces a renderable frame at the expected size
  * Background is the cream colour we picked (not the old dark grey)
  * The accent colour the user picks shows up SOMEWHERE on every state
    (so the theming UX promise holds)
  * IDLE blinks at the expected cadence
  * SPEAK mouth pattern animates frame-to-frame
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from lumi.runtime.state_machine import LumiState
from lumi.ui.face.pixel import PixelFaceRenderer, _BG, _BLUSH, _EYE_DARK


@pytest.fixture(autouse=True)
def _headless_pygame():
    """SDL needs a video driver even for offscreen surfaces."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame  # noqa: PLC0415

    pygame.init()
    yield
    pygame.quit()


def _frame_for(state: LumiState, tick: int = 0, accent=(255, 107, 157)) -> np.ndarray:
    r = PixelFaceRenderer(480, 320, fg_color=accent)
    return r.render(state, tick).pixels


def _has_colour(pixels: np.ndarray, colour: tuple[int, int, int]) -> bool:
    target = np.array(colour, dtype=pixels.dtype)
    return bool(np.any(np.all(pixels == target, axis=-1)))


# ── Output shape / background ──────────────────────────────────────────────


def test_render_returns_frame_at_display_resolution() -> None:
    pixels = _frame_for(LumiState.IDLE)
    assert pixels.shape == (320, 480, 3)


def test_every_state_renders_without_error() -> None:
    for state in (LumiState.IDLE, LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK):
        pixels = _frame_for(state)
        assert pixels.shape == (320, 480, 3), f"{state} produced wrong shape"


def test_background_is_warm_cream_not_dark_grey() -> None:
    """Audit: previous face used a near-black background which read as
    creepy in the user's feedback. The redesign moves to a warm cream."""
    pixels = _frame_for(LumiState.IDLE)
    # The cream is the dominant colour in the upper edge of the frame
    # (above the eyes / chin shadow zone).
    top_band = pixels[:40]
    assert _has_colour(top_band, _BG)
    # And the old dark grey is gone.
    assert not _has_colour(top_band, (26, 26, 26))


# ── Eye + blush palette ────────────────────────────────────────────────────


def test_eyes_use_the_dark_kawaii_palette() -> None:
    """The eye colour is part of the style — fixed regardless of accent."""
    pixels = _frame_for(LumiState.IDLE, accent=(0, 200, 0))   # bright green accent
    assert _has_colour(pixels, _EYE_DARK)


def test_blush_shows_on_emotive_states_but_not_when_thinking() -> None:
    """THINK is a sober expression — the spec drops the blush so the
    contemplative read is unambiguous. The other three keep it.
    (IDLE drops blush during the brief blink window — sample at a tick
    where the eyes are open.)"""
    for state in (LumiState.IDLE, LumiState.LISTEN, LumiState.SPEAK):
        pixels = _frame_for(state, tick=50)        # post-blink for IDLE
        assert _has_colour(pixels, _BLUSH), f"{state} missing blush"
    pixels = _frame_for(LumiState.THINK, tick=50)
    assert not _has_colour(pixels, _BLUSH), "THINK should not show blush"


# ── Accent colour theming (the user-pickable colour) ───────────────────────


def test_accent_colour_shows_up_on_every_state() -> None:
    """The fg_color the user picks under /settings/face tints the eyebrows
    + the thinking dots. It must be visible on every state so the
    'pick your colour' UX doesn't break for any face state."""
    accent = (0, 200, 0)        # bright green — won't collide with the kawaii palette
    for state in (LumiState.IDLE, LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK):
        if state == LumiState.IDLE:
            # IDLE blinks; on blink frames the brow is omitted. Use tick=10
            # which is post-blink so the brow IS drawn.
            pixels = _frame_for(state, tick=10, accent=accent)
        else:
            pixels = _frame_for(state, accent=accent)
        assert _has_colour(pixels, accent), f"{state} missing accent colour"


# ── Animation contracts ────────────────────────────────────────────────────


def test_idle_blinks_periodically() -> None:
    """IDLE drops the brow during the blink window — comparing tick=2
    (blinking) to tick=50 (eyes open) the pixel sets must differ."""
    open_frame = _frame_for(LumiState.IDLE, tick=50)
    blink_frame = _frame_for(LumiState.IDLE, tick=2)
    assert not np.array_equal(open_frame, blink_frame), \
        "IDLE blink frame should differ from eyes-open frame"


def test_speak_mouth_animates_frame_to_frame() -> None:
    """The mouth alternates wide/narrow on every ~6 ticks so speech reads
    as talking, not a static expression."""
    wide = _frame_for(LumiState.SPEAK, tick=0)
    narrow = _frame_for(LumiState.SPEAK, tick=6)
    assert not np.array_equal(wide, narrow)


def test_listen_is_stable_across_ticks() -> None:
    """LISTEN has no animation — it's an alert pose. Same tick output
    across the whole listen window so the user gets a steady visual."""
    frames = [_frame_for(LumiState.LISTEN, tick=t) for t in (0, 5, 20, 100)]
    for f in frames[1:]:
        assert np.array_equal(frames[0], f)


# ── Cross-state visual distinction ─────────────────────────────────────────


def test_each_state_produces_a_distinct_expression() -> None:
    """Two different states must NEVER produce identical pixel output —
    catches refactors that accidentally collapse expressions."""
    frames = {
        s: _frame_for(s, tick=50)        # post-blink for IDLE
        for s in (LumiState.IDLE, LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK)
    }
    states = list(frames.keys())
    for i, a in enumerate(states):
        for b in states[i + 1:]:
            assert not np.array_equal(frames[a], frames[b]), \
                f"{a} and {b} render identically — expressions collapsed"
