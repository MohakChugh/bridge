"""Abstract base class for CLI tool adapters."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
import re


class BaseAdapter(ABC):
    """Interface that all CLI adapters must implement."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the CLI tool."""
        ...

    @abstractmethod
    def spawn(
        self,
        prompt: str,
        cwd: str,
        timeout: int = 18000,
        resume_session_id: Optional[str] = None,
        process_holder: object = None,
        config: Optional[dict] = None,
    ) -> dict:
        """Run a prompt and return result.

        Returns: {"success": bool, "output": str, "error": str, "session_id": str|None}
        """
        ...

    @abstractmethod
    def clear_session(self, cwd: str, config: Optional[dict] = None) -> None:
        """Clear/end the session for the given working directory."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the CLI tool is installed and accessible."""
        ...

    @staticmethod
    def strip_markdown(text: str) -> str:
        """Strip markdown formatting from text."""
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # ANSI
        text = re.sub(r"```[\s\S]*?```", "", text)   # code blocks
        text = re.sub(r"`([^`]+)`", r"\1", text)      # inline code
        text = re.sub(r"#{1,6}\s+", "", text)          # headers
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text) # bold
        text = re.sub(r"\*([^*]+)\*", r"\1", text)     # italic
        text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
        return text.strip()
