import os
import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.claude_adapter import ClaudeAdapter


@pytest.fixture
def adapter():
    return ClaudeAdapter()


def test_name(adapter):
    assert adapter.name() == "claude"


def test_spawn_success(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ('{"result": "I fixed the bug", "session_id": "abc"}', "")
    mock_proc.returncode = 0

    with patch("adapters.claude_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("fix the bug", "/tmp/project", timeout=60)
        assert result["success"] is True
        assert "fixed" in result["output"].lower()
        assert result["session_id"] == "abc"


def test_spawn_timeout(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)
    mock_proc.kill = MagicMock()

    with patch("adapters.claude_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("do something", "/tmp", timeout=60)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()


def test_spawn_error(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "something broke")
    mock_proc.returncode = 1

    with patch("adapters.claude_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("do something", "/tmp", timeout=60)
        assert result["success"] is False
        assert "something broke" in result["error"]


def test_spawn_with_resume(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ('{"result": "continued", "session_id": "def"}', "")
    mock_proc.returncode = 0

    with patch("adapters.claude_adapter.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = adapter.spawn("continue", "/tmp", resume_session_id="abc-123")
        assert result["success"] is True
        # Verify --resume was in the command
        cmd = mock_popen.call_args[0][0]
        assert "--resume" in " ".join(cmd)


def test_spawn_with_config(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ('{"result": "ok"}', "")
    mock_proc.returncode = 0

    config = {"adapters": {"claude": {"effort": "high"}}}
    with patch("adapters.claude_adapter.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = adapter.spawn("test", "/tmp", config=config)
        assert result["success"] is True
        cmd = " ".join(mock_popen.call_args[0][0])
        assert "--effort" in cmd


def test_extract_response_strips_markdown(adapter):
    result = adapter._extract_response('{"result": "**bold** and `code`"}')
    assert "**" not in result
    assert "`" not in result
