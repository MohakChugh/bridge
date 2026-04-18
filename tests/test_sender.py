import os
import sys
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sender import send_imessage, SEND_SCRIPT


def test_send_imessage_calls_osascript():
    with patch("sender.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        err = send_imessage("chat-guid-123", "Hello from test")
        assert err is None
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0][0] == "osascript"
        # Text has invisible marker appended
        assert any("Hello from test" in str(a) for a in args[0][0])
        assert "chat-guid-123" in args[0][0]


def test_send_imessage_returns_error_on_failure():
    with patch("sender.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Messages got an error")
        err = send_imessage("chat-guid-123", "Hello")
        assert err is not None
        assert "Messages got an error" in err


def test_send_imessage_text_not_interpolated_into_source():
    assert "item 1 of argv" in SEND_SCRIPT
    assert "item 2 of argv" in SEND_SCRIPT
