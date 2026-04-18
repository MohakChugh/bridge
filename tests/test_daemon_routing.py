"""Tests for daemon message routing — which handler gets called for which input."""

import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from echo_filter import EchoFilter
from config import DEFAULT_CONFIG
from sender import OUTBOUND_MARKER


def make_daemon():
    from daemon import Daemon
    d = Daemon.__new__(Daemon)
    d.config = {
        **DEFAULT_CONFIG,
        "directories": {"default": "/tmp", "home": "/tmp/home"},
        "cli_tool": "claude",
        "self_addresses": ["me@test.com", "+1234567890"],
        "adapters": {"claude": {}, "wasabi": {}, "kiro": {}},
    }
    d.state = {"watermark": 0, "active_session_id": None, "active_session_cwd": None, "message_history": []}
    d.active_session_id = None
    d.active_session_cwd = None
    d._busy = False
    d._current_task = None
    d._active_process = None
    d._task_queue = []
    d._reminders = []
    d._queue_prefix = ""
    d._progress_tracker = None
    d._stuck_detector = None
    d._picker_mode = False
    d._picker_sessions = []
    d._awaiting_keep_end = False
    d._pending_switch_cwd = None
    d._pending_switch_alias = None
    d._picker_timeout_thread = None
    d._awaiting_voice_confirm = False
    d._pending_voice_text = None
    d._awaiting_schedule_confirm = False
    d._pending_schedule = None
    d._awaiting_remind_confirm = False
    d._pending_remind = None
    d.chatdb = MagicMock()
    d.echo_filter = EchoFilter()
    d.running = True
    d._reply = MagicMock()
    return d


def make_msg(text, handle_id="+1234567890", is_from_me=False):
    return {
        "text": text,
        "handle_id": handle_id,
        "is_from_me": is_from_me,
        "chat_guid": "test-chat",
        "rowid": 1,
    }


class TestMessageRouting:
    def test_route_end(self):
        d = make_daemon()
        d._cmd_end = MagicMock()
        d._handle_message(make_msg("/end"))
        d._cmd_end.assert_called_once()

    def test_route_status(self):
        d = make_daemon()
        d._cmd_status = MagicMock()
        d._handle_message(make_msg("/status"))
        d._cmd_status.assert_called_once()

    def test_route_cancel(self):
        d = make_daemon()
        d._cmd_cancel = MagicMock()
        d._handle_message(make_msg("/cancel"))
        d._cmd_cancel.assert_called_once()

    def test_route_help(self):
        d = make_daemon()
        d._cmd_help = MagicMock()
        d._handle_message(make_msg("/help"))
        d._cmd_help.assert_called_once()

    def test_route_history(self):
        d = make_daemon()
        d._cmd_history = MagicMock()
        d._handle_message(make_msg("/history"))
        d._cmd_history.assert_called_once()

    def test_route_sessions(self):
        d = make_daemon()
        d._cmd_sessions = MagicMock()
        d._handle_message(make_msg("/sessions"))
        d._cmd_sessions.assert_called_once()

    def test_route_dirs(self):
        d = make_daemon()
        d._cmd_dirs = MagicMock()
        d._handle_message(make_msg("/dirs"))
        d._cmd_dirs.assert_called_once()

    def test_route_switch(self):
        d = make_daemon()
        d._cmd_switch = MagicMock()
        d._handle_message(make_msg("/switch centralis"))
        d._cmd_switch.assert_called_once_with("centralis")

    def test_route_queue(self):
        d = make_daemon()
        d._cmd_queue = MagicMock()
        d._handle_message(make_msg("/queue do something"))
        d._cmd_queue.assert_called_once_with("do something")

    def test_route_remind(self):
        d = make_daemon()
        d._cmd_remind = MagicMock()
        d._handle_message(make_msg("/remind 5m check"))
        d._cmd_remind.assert_called_once_with("5m check")

    def test_route_tool(self):
        d = make_daemon()
        d._cmd_tool = MagicMock()
        d._handle_message(make_msg("/tool wasabi"))
        d._cmd_tool.assert_called_once()


class TestMessageFiltering:
    def test_skip_from_me(self):
        d = make_daemon()
        d._cmd_help = MagicMock()
        d._handle_message(make_msg("/help", is_from_me=True))
        d._cmd_help.assert_not_called()

    def test_skip_non_self_chat(self):
        d = make_daemon()
        d._cmd_help = MagicMock()
        d._handle_message(make_msg("/help", handle_id="+9999999999"))
        d._cmd_help.assert_not_called()

    def test_skip_empty_text(self):
        d = make_daemon()
        d._cmd_help = MagicMock()
        d._handle_message(make_msg(""))
        d._cmd_help.assert_not_called()

    def test_skip_outbound_marker(self):
        d = make_daemon()
        d._cmd_help = MagicMock()
        d._handle_message(make_msg(f"some text{OUTBOUND_MARKER}"))
        d._cmd_help.assert_not_called()

    def test_skip_echo(self):
        d = make_daemon()
        d.echo_filter.track("test-chat", "echoed text")
        d._cmd_help = MagicMock()
        d._handle_message(make_msg("echoed text"))
        d._cmd_help.assert_not_called()


class TestBusyState:
    def test_busy_blocks_new_prompt(self):
        d = make_daemon()
        d._busy = True
        d.active_session_id = "abc"
        d._handle_message(make_msg("do something"))
        d._reply.assert_called()
        assert "Busy" in str(d._reply.call_args)

    def test_busy_allows_status(self):
        d = make_daemon()
        d._busy = True
        d._current_task = "running"
        d._cmd_status = MagicMock()
        d._handle_message(make_msg("/status"))
        d._cmd_status.assert_called_once()

    def test_busy_allows_cancel(self):
        d = make_daemon()
        d._busy = True
        d._cmd_cancel = MagicMock()
        d._handle_message(make_msg("/cancel"))
        d._cmd_cancel.assert_called_once()

    def test_busy_allows_help(self):
        d = make_daemon()
        d._busy = True
        d._cmd_help = MagicMock()
        d._handle_message(make_msg("/help"))
        d._cmd_help.assert_called_once()
