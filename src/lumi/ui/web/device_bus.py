"""In-process broadcaster for device-display state.

The device display's React app subscribes via SSE; whatever wants to
push a state change (the web chat session, the voice loop's HTTP push
at /api/state, a periodic weather fetcher) calls `bus.publish(snapshot)`.
Each connected subscriber gets the next snapshot delivered to its own
asyncio.Queue and yielded over the wire.

Design notes:
  * One queue per subscriber, bounded — slow clients don't back up the
    publishers. A full queue drops oldest first.
  * Last-known snapshot is cached so a new subscriber gets the current
    state immediately on connect (no waiting for the next transition).
  * Lock-free reads of the cache because asyncio is single-threaded
    within a process; we only need a Lock if cross-thread access lands.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

_QUEUE_MAX = 16          # frames buffered per subscriber before drop-oldest


class DeviceBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._cache: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def publish(self, snapshot: dict[str, Any]) -> None:
        """Push `snapshot` to every subscriber. Merge-into rather than
        replace the cache so partial updates (e.g. just CPU) work too."""
        async with self._lock:
            self._cache = {**(self._cache or {}), **snapshot}
            payload = dict(self._cache)
        for q in list(self._subscribers):
            if q.full():
                # Drop the oldest frame to keep the queue moving.
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    def latest(self) -> dict[str, Any] | None:
        """Last published snapshot, or None if nothing's been published."""
        return None if self._cache is None else dict(self._cache)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield snapshots forever. Cancelled with the consuming task."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.add(q)
        try:
            if self._cache is not None:
                # Deliver current state immediately so the client doesn't
                # paint a blank face for up to a state-machine cycle.
                await q.put(dict(self._cache))
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)


def get_bus(app) -> DeviceBus:
    """Lazy singleton hung off app.state. Routes call this on first use."""
    bus = getattr(app.state, "device_bus", None)
    if bus is None:
        bus = DeviceBus()
        app.state.device_bus = bus
    return bus
