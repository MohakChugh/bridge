"""Track outbound messages to filter echoes in self-chat."""

from __future__ import annotations
import re
import time


class EchoFilter:
    """Tracks recently sent messages to detect and consume echoes."""

    def __init__(self, window_seconds: float = 15.0):
        self._window = window_seconds
        self._echoes: dict[str, float] = {}

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison: strip signature, collapse whitespace, truncate."""
        text = re.sub(r"\s*Sent by Claude\s*$", "", text)
        text = re.sub(r"[\u200d\ufe00-\ufe0f]", "", text)
        text = re.sub(r"[\u2018\u2019]", "'", text)
        text = re.sub(r"[\u201c\u201d]", '"', text)
        text = text.strip()
        text = re.sub(r"\s+", " ", text)
        return text[:120]

    def _key(self, chat_guid: str, text: str) -> str:
        return f"{chat_guid}\x00{self._normalize(text)}"

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, t in self._echoes.items() if now - t > self._window]
        for k in expired:
            del self._echoes[k]

    def track(self, chat_guid: str, text: str) -> None:
        """Record an outbound message to filter its echo later."""
        self._prune()
        self._echoes[self._key(chat_guid, text)] = time.time()

    def is_echo(self, chat_guid: str, text: str) -> bool:
        """Check if this inbound message is an echo of a recent outbound. Consumes the echo."""
        key = self._key(chat_guid, text)
        ts = self._echoes.get(key)
        if ts is None or time.time() - ts > self._window:
            return False
        del self._echoes[key]
        return True
