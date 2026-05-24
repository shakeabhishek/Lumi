"""Tests for the device-display background samplers (CPU + weather).

Both samplers feed the in-process DeviceBus that the React device
display reads via SSE. Tests pin three things:
  1. CPU sampler publishes a numeric cpuPct field.
  2. Weather sampler reads `settings.weather_location`, calls
     `fetch_weather()` (mocked), and publishes a WeatherSnapshot-shaped
     payload that matches what the React WidgetBar expects.
  3. Sampler tasks are cancellable — the FastAPI lifespan cleanup
     relies on this.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from lumi.ui.web.device_bus import DeviceBus
from lumi.ui.web.device_samplers import cpu_sampler, weather_sampler


@pytest.mark.asyncio
async def test_cpu_sampler_publishes_a_number_then_can_be_cancelled() -> None:
    bus = DeviceBus()
    # Shrink the interval so the test doesn't wait 5s for the first publish.
    with patch("lumi.ui.web.device_samplers._CPU_INTERVAL_S", 0.05):
        task = asyncio.create_task(cpu_sampler(bus))
        # Give it time for two publish cycles.
        await asyncio.sleep(0.15)
        task.cancel()
        # Sampler catches CancelledError internally for clean shutdown.
        await task

    snapshot = bus.latest()
    assert snapshot is not None
    assert "cpuPct" in snapshot
    assert isinstance(snapshot["cpuPct"], int)
    assert 0 <= snapshot["cpuPct"] <= 100


@pytest.mark.asyncio
async def test_weather_sampler_skips_when_location_empty(tmp_path: Path) -> None:
    """No location → no fetch attempt, but the bus gets weather=None so
    the React WidgetBar shows the '—' placeholder instead of stale data."""
    bus = DeviceBus()
    with (
        patch("lumi.ui.web.device_samplers._WEATHER_INTERVAL_S", 60.0),
        patch("lumi.ui.web.device_samplers._WEATHER_RETRY_INTERVAL_S", 0.05),
        patch("lumi.skills.openclaw_bridge.fetch_weather") as mock_fetch,
    ):
        task = asyncio.create_task(weather_sampler(bus, tmp_path))
        await asyncio.sleep(0.1)
        task.cancel()
        # Sampler catches CancelledError internally for clean shutdown.
        await task

    mock_fetch.assert_not_called()
    snapshot = bus.latest()
    assert snapshot == {"weather": None}


@pytest.mark.asyncio
async def test_weather_sampler_publishes_react_shaped_payload(tmp_path: Path) -> None:
    """When fetch_weather returns a snapshot, the sampler converts it to
    the WidgetBar's WeatherSnapshot shape (tempC + condition + location)."""
    from lumi.ui.web.persistence import UserSettings, save_settings  # noqa: PLC0415

    s = UserSettings(weather_location="Tokyo")
    save_settings(tmp_path, s)

    fake_snapshot = {
        "location": "Tokyo",
        "temperature_c": 22.7,
        "feels_like_c": 21.0,
        "humidity_pct": 64,
        "conditions": "few clouds",
        "wind_mps": 3.2,
        "condition": "cloudy",
    }

    bus = DeviceBus()
    with (
        patch("lumi.ui.web.device_samplers._WEATHER_INTERVAL_S", 0.5),
        patch("lumi.ui.web.device_samplers._WEATHER_RETRY_INTERVAL_S", 0.05),
        patch("lumi.skills.openclaw_bridge.fetch_weather", return_value=fake_snapshot),
    ):
        task = asyncio.create_task(weather_sampler(bus, tmp_path))
        await asyncio.sleep(0.1)        # one cycle is enough
        task.cancel()
        # Sampler catches CancelledError internally for clean shutdown.
        await task

    snapshot = bus.latest()
    assert snapshot is not None
    weather = snapshot.get("weather")
    assert weather == {"tempC": 23, "condition": "cloudy", "location": "Tokyo"}


@pytest.mark.asyncio
async def test_weather_sampler_keeps_last_good_reading_on_fetch_error(tmp_path: Path) -> None:
    """If fetch_weather returns None (network down, bad key, 4xx), don't
    clobber the cached reading — the React WidgetBar keeps showing the
    last temperature it had rather than reverting to '—'."""
    from lumi.ui.web.persistence import UserSettings, save_settings  # noqa: PLC0415

    s = UserSettings(weather_location="London")
    save_settings(tmp_path, s)

    bus = DeviceBus()
    # Seed with a previous good reading so we can verify it survives.
    await bus.publish({"weather": {"tempC": 12, "condition": "rainy", "location": "London"}})

    with (
        patch("lumi.ui.web.device_samplers._WEATHER_INTERVAL_S", 0.5),
        patch("lumi.ui.web.device_samplers._WEATHER_RETRY_INTERVAL_S", 0.05),
        patch("lumi.skills.openclaw_bridge.fetch_weather", return_value=None),
    ):
        task = asyncio.create_task(weather_sampler(bus, tmp_path))
        await asyncio.sleep(0.15)
        task.cancel()
        # Sampler catches CancelledError internally for clean shutdown.
        await task

    snapshot = bus.latest()
    assert snapshot is not None
    # Last good reading is still there.
    assert snapshot["weather"] == {"tempC": 12, "condition": "rainy", "location": "London"}
