import os
import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from router import (
    tmux_session_exists, tmux_send_keys, tmux_capture_pane,
    spawn_claude_session, poll_until_idle,
)


def test_tmux_session_exists_returns_true():
    with patch("router.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        assert tmux_session_exists("claude-session") is True
        mock.assert_called_once_with(
            ["tmux", "has-session", "-t", "claude-session"],
            capture_output=True,
        )


def test_tmux_session_exists_returns_false():
    with patch("router.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=1)
        assert tmux_session_exists("claude-session") is False


def test_tmux_send_keys():
    with patch("router.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0)
        tmux_send_keys("claude-session", "[iMessage] do something")
        mock.assert_called_once_with(
            ["tmux", "send-keys", "-t", "claude-session", "[iMessage] do something", "Enter"],
            capture_output=True,
        )


def test_tmux_capture_pane():
    with patch("router.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="line1\nline2\nline3\n")
        output = tmux_capture_pane("claude-session", lines=50)
        assert output == "line1\nline2\nline3\n"


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
