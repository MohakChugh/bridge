"""CLI adapter registry — auto-discovers adapters from *_adapter.py files.

Drop a new file like `opencode_adapter.py` with a class extending BaseAdapter
and it's automatically registered. No code changes needed.
"""

from __future__ import annotations
import importlib
import inspect
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseAdapter

log = logging.getLogger("adapters")

_ADAPTERS: dict[str, "BaseAdapter"] = {}


def _register_defaults():
    """Auto-discover and register all *_adapter.py files in this directory."""
    if _ADAPTERS:
        return

    from .base import BaseAdapter as _Base

    adapter_dir = os.path.dirname(os.path.abspath(__file__))
    for fname in sorted(os.listdir(adapter_dir)):
        if not fname.endswith("_adapter.py"):
            continue
        module_name = fname[:-3]
        try:
            mod = importlib.import_module(f".{module_name}", package="adapters")
            for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, _Base) and cls is not _Base:
                    instance = cls()
                    name = instance.name()
                    if name not in _ADAPTERS:
                        _ADAPTERS[name] = instance
                        log.debug(f"Registered adapter: {name} ({cls_name})")
        except Exception as e:
            log.warning(f"Failed to load adapter {fname}: {e}")


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
