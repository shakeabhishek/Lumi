"""Tests for RainScene/SnowScene allocation behaviour (audit #17).

Goal: make sure the gradient backdrop and alpha wash get cached on
resize and reused frame-to-frame, not reallocated every render call.
This was the dominant idle-loop cost on Pi-class hardware.
"""

from __future__ import annotations

import pygame
import pytest

from lumi.ui.face.idle_scenes import RainScene, SnowScene


@pytest.fixture(autouse=True)
def _headless_pygame():
    """Run pygame in headless mode for CI."""
    import os  # noqa: PLC0415
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()


def test_rain_caches_gradient_and_wash_after_first_render() -> None:
    """After one render call, the gradient + wash surfaces exist and
    survive across subsequent calls at the same size."""
    scene = RainScene()
    surf = pygame.Surface((100, 50))

    assert scene._gradient is None and scene._wash is None  # not built yet

    scene.render(surf, tick=0, w=100, h=50)
    grad_id = id(scene._gradient)
    wash_id = id(scene._wash)
    assert scene._gradient is not None
    assert scene._wash is not None

    scene.render(surf, tick=1, w=100, h=50)
    scene.render(surf, tick=2, w=100, h=50)
    # Same surfaces — not reallocated per frame.
    assert id(scene._gradient) == grad_id
    assert id(scene._wash) == wash_id


def test_rain_rebuilds_caches_on_resize() -> None:
    """If the window resizes, the cached surfaces are stale and must be
    rebuilt at the new dimensions."""
    scene = RainScene()
    surf_small = pygame.Surface((100, 50))
    surf_big = pygame.Surface((200, 80))

    scene.render(surf_small, tick=0, w=100, h=50)
    small_id = id(scene._gradient)
    assert scene._gradient.get_size() == (100, 50)

    scene.render(surf_big, tick=0, w=200, h=80)
    big_id = id(scene._gradient)
    assert scene._gradient.get_size() == (200, 80)
    assert big_id != small_id


def test_rain_uses_instance_rng_not_global_random() -> None:
    """The drop-reposition path used to call the module-level random.uniform.
    Now it goes through the seeded instance RNG, so scene state is
    deterministic per instance (test-isolation friendly)."""
    a = RainScene()
    b = RainScene()
    # Just ensuring construct + first render don't share global RNG state.
    surf = pygame.Surface((50, 50))
    a.render(surf, tick=0, w=50, h=50)
    b.render(surf, tick=0, w=50, h=50)
    # Both should have identical drop positions because they seed from the
    # same constant.
    assert [d["x"] for d in a._drops] == [d["x"] for d in b._drops]


def test_snow_renders_without_error() -> None:
    """Smoke test — SnowScene was also touched (RNG moved to instance)."""
    scene = SnowScene()
    surf = pygame.Surface((100, 50))
    scene.render(surf, tick=0, w=100, h=50)
    scene.render(surf, tick=1, w=100, h=50)
    assert len(scene._flakes) > 0
