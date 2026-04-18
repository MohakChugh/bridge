"""Cross-adapter contract tests — ensures ALL adapters return identical structure.

Each adapter MUST return {"success": bool, "output": str, "error": str, "session_id": str|None}
from spawn(). This catches adapter-specific regressions."""

import os
import sys
import subprocess
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import get_adapter
from adapters.claude_adapter import ClaudeAdapter
from adapters.wasabi_adapter import WasabiAdapter
from adapters.kiro_adapter import KiroAdapter

# Sample outputs for each adapter
CLAUDE_SUCCESS = '{"result": "Hello from Claude", "session_id": "abc-123"}'
WASABI_SUCCESS = (
    '{"timestamp":"2026-04-18T12:53:13.738Z","level":"INFO","message":"Hello from Wasabi","sessionId":"xyz"}\n'
    '{"timestamp":"2026-04-18T12:53:13.935Z","level":"INFO","message":"Tokens used: 100","sessionId":"xyz"}\n'
)
KIRO_SUCCESS_STDOUT = "\x1b[38;5;141m> \x1b[0mHello from Kiro\x1b[0m\n"
KIRO_SUCCESS_STDERR = "\x1b[38;5;8m\n ▸ Credits: 0.15\n\x1b[0m\n"

ADAPTERS = [
    ("claude", ClaudeAdapter, CLAUDE_SUCCESS, ""),
    ("wasabi", WasabiAdapter, WASABI_SUCCESS, ""),
    ("kiro", KiroAdapter, KIRO_SUCCESS_STDOUT, KIRO_SUCCESS_STDERR),
]


@pytest.mark.parametrize("name,cls,stdout,stderr", ADAPTERS, ids=["claude", "wasabi", "kiro"])
class TestAdapterContract:
    def test_spawn_success_returns_correct_keys(self, name, cls, stdout, stderr):
        adapter = cls()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, stderr)
        mock_proc.returncode = 0

        popen_path = f"adapters.{name}_adapter.subprocess.Popen"
        extra_patches = {}
        if name == "kiro":
            extra_patches["target"] = "adapters.kiro_adapter.KiroAdapter._ensure_agent_config"

        with patch(popen_path, return_value=mock_proc):
            with patch.object(adapter, "_ensure_agent_config", create=True):
                result = adapter.spawn("test", "/tmp", timeout=60)

        assert "success" in result
        assert "output" in result
        assert "error" in result
        assert "session_id" in result

    def test_spawn_success_has_output(self, name, cls, stdout, stderr):
        adapter = cls()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, stderr)
        mock_proc.returncode = 0

        popen_path = f"adapters.{name}_adapter.subprocess.Popen"
        with patch(popen_path, return_value=mock_proc):
            with patch.object(adapter, "_ensure_agent_config", create=True):
                result = adapter.spawn("test", "/tmp", timeout=60)

        assert result["success"] is True
        assert len(result["output"]) > 0
        assert result["error"] == ""

    def test_spawn_timeout_returns_error(self, name, cls, stdout, stderr):
        adapter = cls()
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=60)
        mock_proc.kill = MagicMock()

        popen_path = f"adapters.{name}_adapter.subprocess.Popen"
        with patch(popen_path, return_value=mock_proc):
            with patch.object(adapter, "_ensure_agent_config", create=True):
                result = adapter.spawn("test", "/tmp", timeout=60)

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert result["session_id"] is None

    def test_response_no_raw_ansi(self, name, cls, stdout, stderr):
        """Extracted response must not contain raw ANSI escape codes."""
        adapter = cls()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (stdout, stderr)
        mock_proc.returncode = 0

        popen_path = f"adapters.{name}_adapter.subprocess.Popen"
        with patch(popen_path, return_value=mock_proc):
            with patch.object(adapter, "_ensure_agent_config", create=True):
                result = adapter.spawn("test", "/tmp", timeout=60)

        assert "\x1b[" not in result["output"]
        assert "[38;5;" not in result["output"]

    def test_name_returns_string(self, name, cls, stdout, stderr):
        adapter = cls()
        assert adapter.name() == name
        assert isinstance(adapter.name(), str)

    def test_spawn_error_has_error_msg(self, name, cls, stdout, stderr):
        adapter = cls()
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "something failed")
        mock_proc.returncode = 1

        popen_path = f"adapters.{name}_adapter.subprocess.Popen"
        with patch(popen_path, return_value=mock_proc):
            with patch.object(adapter, "_ensure_agent_config", create=True):
                result = adapter.spawn("test", "/tmp", timeout=60)

        assert result["success"] is False
        assert result["session_id"] is None
