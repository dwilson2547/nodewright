"""In-process fan-out of canvas changes to open browser tabs (SSE).

Events are queued on the SQLAlchemy session and published only after its
commit succeeds (db.py), so a tab never hears about a write that rolled back.

One process only: the chart runs a single replica. A second replica would need
Postgres LISTEN/NOTIFY behind publish().
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict

QUEUE_LIMIT = 100


class Broker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = \
            defaultdict(set)

    def subscribe(self, canvas_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(QUEUE_LIMIT)
        with self._lock:
            self._subs[canvas_id].add((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, canvas_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(canvas_id)
            if subs is None:
                return
            subs.difference_update({e for e in subs if e[1] is q})
            if not subs:
                del self._subs[canvas_id]

    def publish(self, canvas_id: str, event: dict) -> None:
        """Safe from any thread (sync route handlers run in a pool)."""
        with self._lock:
            targets = list(self._subs.get(canvas_id, ()))
        for loop, q in targets:
            loop.call_soon_threadsafe(_offer, q, event)

    def subscriber_count(self, canvas_id: str) -> int:
        with self._lock:
            return len(self._subs.get(canvas_id, ()))


def _offer(q: asyncio.Queue, event: dict) -> None:
    # A tab that stopped reading loses events rather than growing memory; it
    # still has the revision check on its next save.
    if not q.full():
        q.put_nowait(event)


def queue(session, canvas_id: str, event: dict) -> None:
    session.info.setdefault("nw_events", []).append((canvas_id, event))
