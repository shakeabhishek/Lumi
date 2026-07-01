"""Background samplers that feed the device display via the DeviceBus.

Two long-running asyncio tasks owned by the FastAPI lifespan:

  * System sampler — CPU%, RAM%, and SoC temperature every few seconds. Cheap.
  * Weather sampler — OpenWeatherMap fetch every N minutes, gated on
    settings.weather_location being non-empty AND
    openweathermap_api_key being in the keychain. We keep the cadence
    conservative because OWM's free tier rate-limits.

Both run inside the FastAPI process and publish partial snapshots
(`{"cpuPct": …}` / `{"weather": {...}}`) — the DeviceBus merges them
into the cached snapshot so the React app always sees fresh combined
state regardless of which sampler fired last.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import psutil  # type: ignore[import-not-found]

from ...log import get_logger
from .device_bus import DeviceBus

log = get_logger(__name__)

_CPU_INTERVAL_S = 5.0
_WEATHER_INTERVAL_S = 600.0      # 10 minutes — comfortable for the OWM free tier
_WEATHER_RETRY_INTERVAL_S = 60.0  # back off harder when something's wrong


def _read_cpu_temp_c() -> int | None:
    """SoC temperature in °C. Reads the Linux thermal zone (Pi 5's SoC);
    falls back to psutil sensors; returns None where unavailable (macOS dev)."""
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(raw) / 1000)
    except Exception:
        pass
    try:
        temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
        for entries in temps.values():
            if entries and entries[0].current:
                return round(entries[0].current)
    except Exception:
        pass
    return None


async def cpu_sampler(bus: DeviceBus) -> None:
    """Publish CPU%, RAM%, and SoC temp every _CPU_INTERVAL_S. Never exits
    unless cancelled."""
    # Warm psutil so the first reading isn't 0 (cpu_percent returns the
    # delta since the previous call).
    psutil.cpu_percent(interval=None)
    try:
        while True:
            await asyncio.sleep(_CPU_INTERVAL_S)
            payload: dict[str, object] = {
                "cpuPct": round(psutil.cpu_percent(interval=None)),
                "memPct": round(psutil.virtual_memory().percent),
            }
            temp = _read_cpu_temp_c()
            if temp is not None:
                payload["cpuTempC"] = temp
            await bus.publish(payload)
    except asyncio.CancelledError:
        return


async def weather_sampler(bus: DeviceBus, data_dir: Path) -> None:
    """Periodic OpenWeatherMap fetch. Publishes a WeatherSnapshot-shaped
    payload that the React WidgetBar already knows how to render."""
    # Loaded lazily so a test fixture's monkeypatched ./skills package
    # gets picked up.
    while True:
        try:
            from .persistence import load_settings  # noqa: PLC0415
            from ...skills.openclaw_bridge import fetch_weather  # noqa: PLC0415

            settings = load_settings(data_dir)
            location = (settings.weather_location or "").strip()
            if not location:
                # Nothing to fetch — clear any stale reading so the React
                # widget shows the "—" placeholder rather than yesterday's
                # weather forever.
                await bus.publish({"weather": None})
                await asyncio.sleep(_WEATHER_RETRY_INTERVAL_S)
                continue

            snapshot = await asyncio.to_thread(fetch_weather, location)
            if snapshot is None:
                # No key, hit a 4xx, or network down. Don't clobber the
                # last good reading — leave whatever's in the bus.
                log.info("weather_sampler.fetch_failed", location=location)
                await asyncio.sleep(_WEATHER_RETRY_INTERVAL_S)
                continue

            await bus.publish({
                "weather": {
                    "tempC": round(snapshot["temperature_c"]),
                    "condition": snapshot.get("condition", "cloudy"),
                    "location": snapshot.get("location"),
                },
            })
            await asyncio.sleep(_WEATHER_INTERVAL_S)
        except asyncio.CancelledError:
            return
        except Exception as exc:                   # noqa: BLE001
            # Never let a sampler crash take down the lifespan task — log
            # and try again after the retry interval.
            log.warning("weather_sampler.error", error=str(exc))
            await asyncio.sleep(_WEATHER_RETRY_INTERVAL_S)


def start_samplers(app) -> list[asyncio.Task[None]]:
    """Kick off both samplers; return the tasks so the lifespan can
    cancel them on shutdown. Called from the FastAPI lifespan handler."""
    from .device_bus import get_bus  # noqa: PLC0415

    bus = get_bus(app)
    return [
        asyncio.create_task(cpu_sampler(bus), name="lumi.cpu_sampler"),
        asyncio.create_task(weather_sampler(bus, app.state.data_dir), name="lumi.weather_sampler"),
    ]
