"""Tests for all daemon command handlers — /end, /status, /cancel, /help, etc.

Uses a mock daemon pattern: Daemon.__new__ skips __init__, all deps mocked.
Tests verify ONLY the command handler logic, not chat.db or iMessage."""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DEFAULT_CONFIG
from echo_filter import EchoFilter


def make_daemon():
    """Create a daemon instance with mocked dependencies — no chat.db needed."""
    # Import here to avoid module-level side effects
    from daemon import Daemon, HELP_TEXT

    d = Daemon.__new__(Daemon)
    d.config = {
        **DEFAULT_CONFIG,
        "directories": {"default": "/tmp", "home": "/tmp/home", "centralis": "/tmp/centralis"},
        "cli_tool": "claude",
        "adapters": {"claude": {"effort": "max"}, "wasabi": {}, "kiro": {}},
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
    d.echo_filter = EchoFilter()
    d.running = True

    replies = []
    d._reply = lambda text, **kw: replies.append(text)
    return d, replies


# --- /end ---

class TestCmdEnd:
    def test_end_with_session(self):
        d, replies = make_daemon()
        d.active_session_id = "abc-123"
        d.active_session_cwd = "/tmp"
        with patch("daemon.save_state"):
            d._cmd_end()
        assert d.active_session_id is None
        assert d.active_session_cwd is None
        assert "Session ended" in replies[0]

    def test_end_no_session(self):
        d, replies = make_daemon()
        d._cmd_end()
        assert "No active session" in replies[0]


# --- /status ---

class TestCmdStatus:
    def test_status_busy(self):
        d, replies = make_daemon()
        d._busy = True
        d._current_task = "fix auth handler"
        d._cmd_status()
        assert "Working on" in replies[0]
        assert "fix auth handler" in replies[0]

    def test_status_busy_with_queue(self):
        d, replies = make_daemon()
        d._busy = True
        d._current_task = "build"
        d._task_queue = ["task2", "task3"]
        d._cmd_status()
        assert "2 queued" in replies[0]

    def test_status_idle_with_session(self):
        d, replies = make_daemon()
        d.active_session_id = "abc"
        d.active_session_cwd = "/tmp/home"
        d._cmd_status()
        assert "Idle" in replies[0]

    def test_status_idle_no_session(self):
        d, replies = make_daemon()
        d._cmd_status()
        assert "Idle" in replies[0]
        assert "No session" in replies[0]


# --- /cancel ---

class TestCmdCancel:
    def test_cancel_with_process(self):
        d, replies = make_daemon()
        d._busy = True
        d._current_task = "running task"
        mock_proc = MagicMock()
        d._active_process = mock_proc
        d._cmd_cancel()
        mock_proc.kill.assert_called_once()
        assert d._busy is False
        assert d._current_task is None
        assert "Cancelled" in replies[0]

    def test_cancel_busy_no_process(self):
        d, replies = make_daemon()
        d._busy = True
        d._current_task = "something"
        d._cmd_cancel()
        assert d._busy is False
        assert "Cancelled" in replies[0]

    def test_cancel_nothing_running(self):
        d, replies = make_daemon()
        d._cmd_cancel()
        assert "Nothing running" in replies[0]


# --- /help ---

class TestCmdHelp:
    def test_help_returns_text(self):
        from daemon import HELP_TEXT
        d, replies = make_daemon()
        d._cmd_help()
        assert len(replies) == 1
        assert "/status" in replies[0]
        assert "/end" in replies[0]
        assert "/cancel" in replies[0]


# --- /history ---

class TestCmdHistory:
    def test_history_with_messages(self):
        d, replies = make_daemon()
        d.active_session_id = "abc"
        d.state["message_history"] = [
            {"role": "user", "text": "hello", "ts": 1},
            {"role": "assistant", "text": "hi there", "ts": 2},
            {"role": "user", "text": "fix bug", "ts": 3},
        ]
        d._cmd_history()
        assert "You: hello" in replies[0]
        assert "Claude: hi there" in replies[0]

    def test_history_empty(self):
        d, replies = make_daemon()
        d.active_session_id = "abc"
        d.state["message_history"] = []
        d._cmd_history()
        assert "No history" in replies[0]

    def test_history_no_session(self):
        d, replies = make_daemon()
        d._cmd_history()
        assert "No active session" in replies[0]

    def test_history_max_5(self):
        d, replies = make_daemon()
        d.active_session_id = "abc"
        d.state["message_history"] = [
            {"role": "user", "text": f"msg{i}", "ts": i} for i in range(10)
        ]
        d._cmd_history()
        # Should only show last 5
        assert "msg5" in replies[0]
        assert "msg9" in replies[0]


# --- /dirs ---

class TestCmdDirs:
    def test_dirs_lists_all(self):
        d, replies = make_daemon()
        d._cmd_dirs()
        assert "default:" in replies[0]
        assert "home:" in replies[0]
        assert "centralis:" in replies[0]

    def test_dirs_marks_active(self):
        d, replies = make_daemon()
        d.active_session_cwd = "/tmp/home"
        d._cmd_dirs()
        assert "(active)" in replies[0]


# --- /switch ---

class TestCmdSwitch:
    def _add_picker_attrs(self, d):
        """Add picker state attributes needed by enhanced /switch."""
        d._picker_mode = False
        d._picker_sessions = []
        d._awaiting_keep_end = False
        d._pending_switch_cwd = None
        d._pending_switch_alias = None
        d._picker_timeout_thread = None
        d._progress_tracker = None
        d._stuck_detector = None

    def test_switch_no_session_shows_listing(self):
        d, replies = make_daemon()
        self._add_picker_attrs(d)
        d.config["directories"]["home"] = "/tmp"
        with patch("daemon.save_state"):
            with patch("daemon.get_adapter") as mock_get:
                mock_adapter = MagicMock()
                mock_adapter.list_sessions.return_value = []
                mock_get.return_value = mock_adapter
                d._cmd_switch("home")
        assert d.active_session_cwd == "/tmp"
        assert "No sessions" in replies[0]

    def test_switch_with_session_asks_keep_end(self):
        d, replies = make_daemon()
        self._add_picker_attrs(d)
        d.active_session_id = "abc-123"
        d.config["directories"]["home"] = "/tmp"
        d._cmd_switch("home")
        assert d._awaiting_keep_end is True
        assert "end" in replies[0].lower() and "keep" in replies[0].lower()

    def test_switch_invalid(self):
        d, replies = make_daemon()
        self._add_picker_attrs(d)
        d._cmd_switch("nonexistent")
        assert "Unknown" in replies[0]
        assert "Available" in replies[0]

    def test_switch_dir_not_found(self):
        d, replies = make_daemon()
        self._add_picker_attrs(d)
        d.config["directories"]["broken"] = "/nonexistent/path"
        d._cmd_switch("broken")
        assert "Directory not found" in replies[0]

    def test_switch_busy_blocked(self):
        d, replies = make_daemon()
        self._add_picker_attrs(d)
        d._busy = True
        d._cmd_switch("home")
        assert "Busy" in replies[0]


# --- /queue ---

class TestCmdQueue:
    def test_queue_add(self):
        d, replies = make_daemon()
        d._cmd_queue("do something")
        assert len(d._task_queue) == 1
        assert "Queued (1 total)" in replies[0]

    def test_queue_add_multiple(self):
        d, replies = make_daemon()
        d._cmd_queue("task1")
        d._cmd_queue("task2")
        assert len(d._task_queue) == 2
        assert "2 total" in replies[1]

    def test_queue_show_items(self):
        d, replies = make_daemon()
        d._task_queue = ["task one", "task two"]
        d._cmd_queue("")
        assert "Queue:" in replies[0]
        assert "task one" in replies[0]

    def test_queue_empty(self):
        d, replies = make_daemon()
        d._cmd_queue("")
        assert "Queue empty" in replies[0]


# --- /tool ---

class TestCmdTool:
    def test_tool_show_current(self):
        d, replies = make_daemon()
        d._cmd_tool("")
        assert "Current: claude" in replies[0]
        assert "Available:" in replies[0]

    def test_tool_switch_valid(self):
        d, replies = make_daemon()
        with patch("daemon.save_config"):
            with patch("daemon.get_adapter") as mock_get:
                mock_adapter = MagicMock()
                mock_adapter.is_available.return_value = True
                mock_get.return_value = mock_adapter
                d._cmd_tool("wasabi")
        assert d.config["cli_tool"] == "wasabi"
        assert "Switched to wasabi" in replies[0]

    def test_tool_switch_invalid(self):
        d, replies = make_daemon()
        with patch("daemon.get_adapter", side_effect=KeyError("Unknown CLI tool: fake")):
            d._cmd_tool("fake")
        assert "Unknown" in replies[0]

    def test_tool_not_available(self):
        d, replies = make_daemon()
        with patch("daemon.get_adapter") as mock_get:
            mock_adapter = MagicMock()
            mock_adapter.is_available.return_value = False
            mock_get.return_value = mock_adapter
            d._cmd_tool("wasabi")
        assert "not found in PATH" in replies[0]


# --- /remind ---

class TestCmdRemind:
    def test_remind_valid(self):
        d, replies = make_daemon()
        d._cmd_remind("5m check build")
        assert len(d._reminders) == 1
        assert "Reminder set" in replies[0]

    def test_remind_bad_time(self):
        d, replies = make_daemon()
        d._cmd_remind("abc check build")
        assert "Bad time format" in replies[0]

    def test_remind_missing_message(self):
        d, replies = make_daemon()
        d._cmd_remind("5m")
        assert "Usage:" in replies[0]
