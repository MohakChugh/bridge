"""Simple thread-safe pub/sub event bus for daemon -> UI live updates."""

from __future__ import annotations
import queue
import threading
import time
from typing import Any, Callable


class EventBus:
    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.RLock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus
