"""CLI adapter registry. Maps tool names to adapter instances."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseAdapter

_ADAPTERS = {}


def _register_defaults():
    """Lazy-register built-in adapters."""
    if _ADAPTERS:
        return
    from .claude_adapter import ClaudeAdapter
    from .wasabi_adapter import WasabiAdapter
    from .kiro_adapter import KiroAdapter
    _ADAPTERS["claude"] = ClaudeAdapter()
    _ADAPTERS["wasabi"] = WasabiAdapter()
    _ADAPTERS["kiro"] = KiroAdapter()


def get_adapter(name: str) -> "BaseAdapter":
    """Get adapter by name. Raises KeyError if unknown."""
    _register_defaults()
    if name not in _ADAPTERS:
        available = ", ".join(_ADAPTERS.keys())
        raise KeyError(f"Unknown CLI tool: {name}. Available: {available}")
    return _ADAPTERS[name]


def list_adapters() -> list[str]:
    """List available adapter names."""
    _register_defaults()
    return list(_ADAPTERS.keys())
