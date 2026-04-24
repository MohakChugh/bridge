import os
import sys
import subprocess
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.wasabi_adapter import WasabiAdapter


SAMPLE_WASABI_OUTPUT = """{"timestamp":"2026-04-18T12:53:05.640Z","level":"INFO","message":"Initializing 5 MCP servers...","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:05.663Z","level":"WARN","message":"Warning: Command 'uvx' not found","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:08.550Z","level":"INFO","message":"Prompt: Say hello","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:08.550Z","level":"INFO","message":"Press ESC to cancel the request","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:08.896Z","level":"INFO","message":"Waiting for response...","sessionId":"abc","type":"loading_state","isLoading":true}
{"timestamp":"2026-04-18T12:53:13.569Z","level":"INFO","message":"✨ Responding... ~0 tokens","sessionId":"abc","type":"loading_state","isLoading":true}
{"timestamp":"2026-04-18T12:53:13.738Z","level":"INFO","message":"Hello! How can I help?","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:13.935Z","level":"INFO","message":"Tokens used: 93122 → $1.00 [5.0s]","sessionId":"abc"}
"""

SAMPLE_ERROR_OUTPUT = """{"timestamp":"2026-04-18T12:54:57.271Z","level":"ERROR","message":"non-interactive mode requires a prompt","sessionId":"abc"}
"""

SAMPLE_MULTILINE_OUTPUT = """{"timestamp":"2026-04-18T12:53:05.640Z","level":"INFO","message":"Initializing 5 MCP servers...","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:08.550Z","level":"INFO","message":"Prompt: test multi","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:08.896Z","level":"INFO","message":"Waiting for response...","sessionId":"abc","type":"loading_state","isLoading":true}
{"timestamp":"2026-04-18T12:53:13.738Z","level":"INFO","message":"Line one of response","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:13.739Z","level":"INFO","message":"Line two of response","sessionId":"abc"}
{"timestamp":"2026-04-18T12:53:13.935Z","level":"INFO","message":"Tokens used: 100 → $0.01 [1.0s]","sessionId":"abc"}
"""


@pytest.fixture
def adapter():
    return WasabiAdapter()


def test_name(adapter):
    assert adapter.name() == "wasabi"


def test_extract_response_simple(adapter):
    result = adapter._extract_response(SAMPLE_WASABI_OUTPUT)
    assert "Hello! How can I help?" in result


def test_extract_response_filters_noise(adapter):
    result = adapter._extract_response(SAMPLE_WASABI_OUTPUT)
    assert "Initializing" not in result
    assert "Tokens used" not in result
    assert "Press ESC" not in result
    assert "Waiting for response" not in result
    assert "Responding" not in result


def test_extract_response_multiline(adapter):
    result = adapter._extract_response(SAMPLE_MULTILINE_OUTPUT)
    assert "Line one" in result
    assert "Line two" in result


def test_has_error_true(adapter):
    assert adapter._has_error(SAMPLE_ERROR_OUTPUT) is True


def test_has_error_false(adapter):
    assert adapter._has_error(SAMPLE_WASABI_OUTPUT) is False


def test_extract_error(adapter):
    error = adapter._extract_error(SAMPLE_ERROR_OUTPUT)
    assert "non-interactive mode requires a prompt" in error


def test_spawn_success(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_WASABI_OUTPUT, "")
    mock_proc.returncode = 0

    with patch("adapters.wasabi_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("Say hello", "/tmp", timeout=60)
        assert result["success"] is True
        assert "Hello" in result["output"]
        assert result["session_id"] is None  # wasabi has no session_id


def test_spawn_error(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_ERROR_OUTPUT, "")
    mock_proc.returncode = 0  # wasabi always returns 0

    with patch("adapters.wasabi_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("", "/tmp", timeout=60)
        assert result["success"] is False
        assert "requires a prompt" in result["error"]


def test_spawn_timeout(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="wasabi", timeout=60)
    mock_proc.kill = MagicMock()

    with patch("adapters.wasabi_adapter.subprocess.Popen", return_value=mock_proc):
        result = adapter.spawn("do something", "/tmp", timeout=60)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()


def test_spawn_with_config(adapter):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (SAMPLE_WASABI_OUTPUT, "")
    mock_proc.returncode = 0

    config = {"adapters": {"wasabi": {"account": "999999999999", "model": "test-model"}}}
    with patch("adapters.wasabi_adapter.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = adapter.spawn("test", "/tmp", config=config)
        assert result["success"] is True
        cmd = " ".join(mock_popen.call_args[0][0])
        assert "999999999999" in cmd


def test_extract_response_with_escape_codes(adapter):
    noisy = "\x1b[K" + SAMPLE_WASABI_OUTPUT + "\x1b[K"
    result = adapter._extract_response(noisy)
    assert "Hello" in result
