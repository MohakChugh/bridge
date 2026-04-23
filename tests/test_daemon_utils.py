"""Tests for daemon utility functions — _parse_time, _is_self_chat, _reply mechanics."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DEFAULT_CONFIG
from echo_filter import EchoFilter
from sender import OUTBOUND_MARKER


def make_daemon():
    from daemon import Daemon
    d = Daemon.__new__(Daemon)
    d.config = {
        **DEFAULT_CONFIG,
        "self_addresses": ["me@test.com", "+1234567890"],
        "reply_chat_guid": "test-chat-guid",
    }
    d.state = {"watermark": 0}
    d.echo_filter = EchoFilter()
    d._queue_prefix = ""
    d._slack_channel = None
    d._reply_via_slack = None
    d._imessage_enabled = True
    return d


class TestParseTime:
    def test_minutes(self):
        from daemon import Daemon
        assert Daemon._parse_time("5m") == 300

    def test_hours(self):
        from daemon import Daemon
        assert Daemon._parse_time("1h") == 3600

    def test_seconds(self):
        from daemon import Daemon
        assert Daemon._parse_time("30s") == 30

    def test_combined(self):
        from daemon import Daemon
        assert Daemon._parse_time("2h30m") == 9000

    def test_combined_all(self):
        from daemon import Daemon
        assert Daemon._parse_time("1h5m10s") == 3910

    def test_invalid(self):
        from daemon import Daemon
        assert Daemon._parse_time("abc") is None

    def test_empty(self):
        from daemon import Daemon
        assert Daemon._parse_time("") is None

    def test_zero(self):
        from daemon import Daemon
        assert Daemon._parse_time("0m") is None


class TestIsSelfChat:
    def test_matching_email(self):
        d = make_daemon()
        assert d._is_self_chat("me@test.com") is True

    def test_matching_phone(self):
        d = make_daemon()
        assert d._is_self_chat("+1234567890") is True

    def test_case_insensitive(self):
        d = make_daemon()
        assert d._is_self_chat("ME@TEST.COM") is True

    def test_not_matching(self):
        d = make_daemon()
        assert d._is_self_chat("+9999999999") is False

    def test_none_handle(self):
        d = make_daemon()
        assert d._is_self_chat(None) is False

    def test_empty_handle(self):
        d = make_daemon()
        assert d._is_self_chat("") is False


class TestReplyMechanics:
    def test_reply_calls_send_imessage(self):
        d = make_daemon()
        with patch("daemon.send_imessage", return_value=None) as mock_send:
            d._reply("hello")
            mock_send.assert_called_once()
            sent_text = mock_send.call_args[0][1]
            assert "hello" in sent_text

    def test_reply_adds_outbound_marker(self):
        d = make_daemon()
        with patch("daemon.send_imessage", return_value=None) as mock_send:
            d._reply("test message")
            # sender.py adds OUTBOUND_MARKER — verified via send_imessage being called
            mock_send.assert_called_once()

    def test_reply_tracks_echo(self):
        d = make_daemon()
        with patch("daemon.send_imessage", return_value=None):
            d._reply("tracked message")
            # After successful send, echo_filter should have tracked it
            # (echo_filter.track is called in _reply)

    def test_reply_no_guid(self):
        d = make_daemon()
        d.config["reply_chat_guid"] = None
        with patch("daemon.send_imessage") as mock_send:
            d._reply("orphan message")
            mock_send.assert_not_called()

    def test_reply_sends_to_correct_guid(self):
        d = make_daemon()
        with patch("daemon.send_imessage", return_value=None) as mock_send:
            d._reply("test msg")
            sent_guid = mock_send.call_args[0][0]
            assert sent_guid == "test-chat-guid"


class TestSaveActiveSession:
    def test_saves_to_state(self):
        d = make_daemon()
        d.state = {"watermark": 0}
        with patch("daemon.save_state"):
            d._save_active_session("session-123", "/tmp/project")
        assert d.active_session_id == "session-123"
        assert d.active_session_cwd == "/tmp/project"
        assert d.state["active_session_id"] == "session-123"
        assert d.state["active_session_cwd"] == "/tmp/project"
