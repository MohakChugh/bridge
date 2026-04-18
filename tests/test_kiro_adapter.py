import os
import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.kiro_adapter import KiroAdapter

# Sample kiro stdout — response with ANSI codes
SAMPLE_STDOUT = """\x1b[38;5;141m> \x1b[0mHello! The answer is 42.\x1b[0m\x1b[0m
"""

SAMPLE_STDOUT_MULTILINE = """\x1b[38;5;141m> \x1b[0mLine one of response\x1b[0m
\x1b[38;5;141m\x1b[0mLine two continues\x1b[0m
"""

SAMPLE_STDOUT_TOOL = """\x1b[0mCreating: /tmp/test/hello.py
\x1b[38;5;244m - Completed in 0.3s\x1b[0m

\x1b[38;5;141m> \x1b[0mCreated hello.py successfully\x1b[0m
"""

SAMPLE_STDERR = """\x1b[38;5;11mWARNING: \x1b[0mDuplicate agent
\x1b[32mAll tools are now trusted\x1b[0m
\x1b[38;5;141mUsing amzn-builder agent\x1b[0m
\x1b[38;5;8m
 ▸ Credits: 0.28 • Time: 5s
\x1b[0m
"""

SAMPLE_STDERR_ERROR = """error: Model 'nonexistent' does not exist. Available models: auto, claude-opus-4.7
"""


@pytest.fixture
def adapter():
    return KiroAdapter()


def test_name(adapter):
    assert adapter.name() == "kiro"


def test_extract_response_simple(adapter):
    result = adapter._extract_response(SAMPLE_STDOUT)
    assert "Hello" in result
    assert "42" in result
    assert "\x1b" not in result


def test_extract_response_strips_ansi(adapter):
    result = adapter._extract_response(SAMPLE_STDOUT)
    assert "[38;5" not in result
    assert "[0m" not in result


def test_extract_response_removes_prefix(adapter):
    result = adapter._extract_response(SAMPLE_STDOUT)
    assert not result.startswith(">")


def test_extract_response_multiline(adapter):
    result = adapter._extract_response(SAMPLE_STDOUT_MULTILINE)
    assert "Line one" in result
    assert "Line two" in result


def test_extract_response_tool_output(adapter):
    result = adapter._extract_response(SAMPLE_STDOUT_TOOL)
    assert "Created hello.py" in result
    # Tool artifacts should be stripped
    assert "Completed in" not in result
    assert "Creating:" not in result


def test_extract_error(adapter):
    error = adapter._extract_error(SAMPLE_STDERR_ERROR)
    assert "nonexistent" in error


def test_extract_error_empty(adapter):
    error = adapter._extract_error(SAMPLE_STDERR)
    assert error == ""


def test_spawn_success(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_STDOUT, SAMPLE_STDERR)
    mock_proc.returncode = 0

    with patch("adapters.kiro_adapter.subprocess.Popen", return_value=mock_proc):
        with patch.object(adapter, "_ensure_agent_config"):
            result = adapter.spawn("Say hello", "/tmp", timeout=60)
            assert result["success"] is True
            assert "Hello" in result["output"]


def test_spawn_error(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", SAMPLE_STDERR_ERROR)
    mock_proc.returncode = 1

    with patch("adapters.kiro_adapter.subprocess.Popen", return_value=mock_proc):
        with patch.object(adapter, "_ensure_agent_config"):
            result = adapter.spawn("hello", "/tmp", timeout=60)
            assert result["success"] is False
            assert "nonexistent" in result["error"]


def test_spawn_timeout(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="kiro-cli", timeout=60)
    mock_proc.kill = MagicMock()

    with patch("adapters.kiro_adapter.subprocess.Popen", return_value=mock_proc):
        with patch.object(adapter, "_ensure_agent_config"):
            result = adapter.spawn("do something", "/tmp", timeout=60)
            assert result["success"] is False
            assert "timed out" in result["error"].lower()


def test_spawn_with_resume(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_STDOUT, SAMPLE_STDERR)
    mock_proc.returncode = 0

    with patch("adapters.kiro_adapter.subprocess.Popen", return_value=mock_proc) as mock_popen:
        with patch.object(adapter, "_ensure_agent_config"):
            result = adapter.spawn("continue", "/tmp", resume_session_id="abc-123")
            assert result["success"] is True
            cmd = mock_popen.call_args[0][0]
            assert "--resume-id" in cmd
            assert "abc-123" in cmd


def test_spawn_with_auto_resume(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_STDOUT, SAMPLE_STDERR)
    mock_proc.returncode = 0

    with patch("adapters.kiro_adapter.subprocess.Popen", return_value=mock_proc) as mock_popen:
        with patch.object(adapter, "_ensure_agent_config"):
            result = adapter.spawn("continue", "/tmp", resume_session_id="auto")
            cmd = mock_popen.call_args[0][0]
            assert "--resume" in cmd
            assert "--resume-id" not in cmd
