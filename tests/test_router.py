import os
import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from router import spawn_claude_session


def test_spawn_claude_session_success():
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ('{"result": "I fixed the bug", "session_id": "abc"}', "")
    mock_proc.returncode = 0

    with patch("router.subprocess.Popen", return_value=mock_proc):
        result = spawn_claude_session("fix the bug", "/tmp/project", timeout=60)
        assert result["success"] is True
        assert "fixed" in result["output"].lower()
        assert result["session_id"] == "abc"


def test_spawn_claude_session_timeout():
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)
    mock_proc.kill = MagicMock()

    with patch("router.subprocess.Popen", return_value=mock_proc):
        result = spawn_claude_session("do something", "/tmp", timeout=60)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()


def test_spawn_claude_session_error():
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "something broke")
    mock_proc.returncode = 1

    with patch("router.subprocess.Popen", return_value=mock_proc):
        result = spawn_claude_session("do something", "/tmp", timeout=60)
        assert result["success"] is False
        assert "something broke" in result["error"]
