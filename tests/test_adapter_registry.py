import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import get_adapter, list_adapters
from adapters.base import BaseAdapter
from adapters.claude_adapter import ClaudeAdapter
from adapters.wasabi_adapter import WasabiAdapter


def test_get_claude_adapter():
    adapter = get_adapter("claude")
    assert isinstance(adapter, ClaudeAdapter)
    assert adapter.name() == "claude"


def test_get_wasabi_adapter():
    adapter = get_adapter("wasabi")
    assert isinstance(adapter, WasabiAdapter)
    assert adapter.name() == "wasabi"


def test_get_unknown_adapter_raises():
    with pytest.raises(KeyError, match="Unknown CLI tool"):
        get_adapter("nonexistent")


def test_list_adapters():
    names = list_adapters()
    assert "claude" in names
    assert "wasabi" in names


def test_adapters_implement_base():
    for name in list_adapters():
        adapter = get_adapter(name)
        assert isinstance(adapter, BaseAdapter)
        assert hasattr(adapter, "spawn")
        assert hasattr(adapter, "clear_session")
        assert hasattr(adapter, "is_available")
        assert hasattr(adapter, "name")
