"""Simple thread-safe pub/sub event bus for daemon -> UI live updates."""

from __future__ import annotations
import json
import queue
import threading
import time
from typing import Any, Callable

# Stale subscriber threshold in seconds (5 minutes)
_STALE_THRESHOLD = 300
# Sweep every N publish() calls (amortized cost)
_SWEEP_INTERVAL = 100


class _TrackedQueue:
    """Thin wrapper around queue.Queue that tracks last-read time."""

    __slots__ = ("queue", "last_read")

    def __init__(self, q: queue.Queue) -> None:
        self.queue = q
        self.last_read: float = time.time()

    def touch(self) -> None:
        self.last_read = time.time()


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[_TrackedQueue] = []
        self._lock = threading.RLock()
        self._publish_count: int = 0

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        tracked = _TrackedQueue(q)
        with self._lock:
            self._subscribers.append(tracked)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers = [t for t in self._subscribers if t.queue is not q]

    def sweep(self) -> int:
        """Remove subscribers whose queue has not been read in 5+ minutes.

        Returns the number of stale subscribers removed.
        """
        now = time.time()
        removed = 0
        with self._lock:
            before = len(self._subscribers)
            self._subscribers = [
                t for t in self._subscribers
                if (now - t.last_read) < _STALE_THRESHOLD
            ]
            removed = before - len(self._subscribers)
        return removed

    def _touch(self, q: queue.Queue) -> None:
        """Update the last-read timestamp for a subscriber queue.

        Called externally when a consumer reads from the queue so the
        sweep() logic knows the subscriber is still alive.
        """
        with self._lock:
            for t in self._subscribers:
                if t.queue is q:
                    t.touch()
                    break

    def publish(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        if not event_type.startswith("log."):
            try:
                from log_store import get_log_store
                get_log_store().write_event(event["timestamp"], event_type, data if isinstance(data, str) else json.dumps(data, default=str), "event_bus")
            except Exception:
                pass

        # Amortized sweep: every _SWEEP_INTERVAL publishes, remove stale subs
        self._publish_count += 1
        if self._publish_count >= _SWEEP_INTERVAL:
            self._publish_count = 0
            self.sweep()

        with self._lock:
            subs = list(self._subscribers)
        for t in subs:
            try:
                t.queue.put_nowait(event)
            except queue.Full:
                pass


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
