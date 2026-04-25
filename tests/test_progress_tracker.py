"""Tests for ProgressTracker and StuckDetector."""

import json
import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from progress_tracker import ProgressTracker, StuckDetector


# --- ProgressTracker Tests ---

class TestProgressTrackerInit:
    def test_init_sets_start_time(self):
        before = time.time()
        pt = ProgressTracker(session_id="test")
        after = time.time()
        assert before <= pt.start_time <= after

    def test_init_defaults(self):
        pt = ProgressTracker()
        assert pt.session_id is None
        assert pt.tool_calls == []
        assert pt.current_action is None
        assert pt.completed is False


class TestProgressTrackerEvents:
    def test_process_tool_use_event(self):
        pt = ProgressTracker()
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Write"}]
            }
        }
        pt.process_event(event)
        assert len(pt.tool_calls) == 1
        assert pt.tool_calls[0]["name"] == "Write"
        assert pt.current_action == "Write"

    def test_process_text_event(self):
        pt = ProgressTracker()
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Hello there"}]
            }
        }
        pt.process_event(event)
        assert "Hello there" in pt.text_chunks

    def test_process_result_event(self):
        pt = ProgressTracker()
        pt.process_event({"type": "result"})
        assert pt.completed is True

    def test_process_unknown_event(self):
        pt = ProgressTracker()
        pt.process_event({"type": "unknown_event"})
        assert pt.completed is False
        assert len(pt.tool_calls) == 0

    def test_process_string_content(self):
        pt = ProgressTracker()
        event = {"type": "assistant", "message": {"content": "plain text response"}}
        pt.process_event(event)
        assert "plain text response" in pt.text_chunks

    def test_multiple_tool_calls(self):
        pt = ProgressTracker()
        for name in ["Read", "Edit", "Bash", "Write"]:
            pt.process_event({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": name}]}
            })
        assert len(pt.tool_calls) == 4
        assert pt.current_action == "Write"  # Last one


class TestProgressTrackerProgress:
    def test_get_progress_no_tasks(self):
        pt = ProgressTracker()
        pt.tool_calls = [{"name": "Bash", "ts": 1}]
        p = pt.get_progress()
        assert p["tasks_total"] == 0
        assert p["tool_call_count"] == 1
        assert p["eta_seconds"] is None

    def test_get_progress_with_task_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "test-session"
            task_dir = os.path.join(tmpdir, session_id)
            os.makedirs(task_dir)
            # Create task files
            for i, status in enumerate(["completed", "completed", "in_progress", "pending"]):
                with open(os.path.join(task_dir, f"{i}.json"), "w") as f:
                    json.dump({"id": str(i), "subject": f"Task {i}", "status": status}, f)

            pt = ProgressTracker(session_id=session_id)
            with patch.object(pt, "_read_task_files") as mock_read:
                mock_read.return_value = [
                    {"id": "0", "subject": "Task 0", "status": "completed"},
                    {"id": "1", "subject": "Task 1", "status": "completed"},
                    {"id": "2", "subject": "Task 2", "status": "in_progress"},
                    {"id": "3", "subject": "Task 3", "status": "pending"},
                ]
                p = pt.get_progress()

            assert p["tasks_total"] == 4
            assert p["tasks_done"] == 2
            assert p["tasks_pending"] == 1
            assert p["tasks_in_progress"] == 1
            assert "Task 0" in p["done_list"]
            assert "Task 3" in p["pending_list"]

    def test_eta_calculation(self):
        pt = ProgressTracker()
        pt.start_time = time.time() - 120  # 2 minutes ago
        with patch.object(pt, "_read_task_files") as mock_read:
            mock_read.return_value = [
                {"status": "completed", "subject": "a"},
                {"status": "completed", "subject": "b"},
                {"status": "pending", "subject": "c"},
                {"status": "pending", "subject": "d"},
            ]
            p = pt.get_progress()
        # 2 done in 120s = 1 per 60s. 2 remaining = ~120s ETA
        assert p["eta_seconds"] is not None
        assert 100 < p["eta_seconds"] < 140

    def test_eta_no_completed_tasks(self):
        pt = ProgressTracker()
        with patch.object(pt, "_read_task_files") as mock_read:
            mock_read.return_value = [
                {"status": "pending", "subject": "a"},
            ]
            p = pt.get_progress()
        assert p["eta_seconds"] is None


class TestProgressTrackerFormat:
    def test_format_eta_with_tasks(self):
        pt = ProgressTracker()
        pt.start_time = time.time() - 222  # 3m 42s
        pt.current_action = "Write"
        with patch.object(pt, "_read_task_files") as mock_read:
            mock_read.return_value = [
                {"status": "completed", "subject": "create file"},
                {"status": "completed", "subject": "write tests"},
                {"status": "in_progress", "subject": "fix bug"},
                {"status": "pending", "subject": "commit"},
            ]
            msg = pt.format_eta_message()
        assert "Running for:" in msg
        assert "Current: Write" in msg
        assert "2/4 tasks done" in msg
        assert "Done:" in msg
        assert "Remaining:" in msg

    def test_format_eta_no_tasks(self):
        pt = ProgressTracker()
        pt.tool_calls = [{"name": "x", "ts": 1}] * 5
        msg = pt.format_eta_message()
        assert "Tool calls: 5" in msg

    def test_format_completion_with_tasks(self):
        pt = ProgressTracker()
        pt.start_time = time.time() - 252  # 4m 12s
        with patch.object(pt, "_read_task_files") as mock_read:
            mock_read.return_value = [
                {"status": "completed", "subject": "a"},
                {"status": "completed", "subject": "b"},
            ]
            summary = pt.format_completion_summary()
        assert "Completed 2/2" in summary
        assert "4m" in summary

    def test_format_completion_no_tasks(self):
        pt = ProgressTracker()
        pt.start_time = time.time() - 30
        pt.tool_calls = [{"name": "x", "ts": 1}] * 3
        summary = pt.format_completion_summary()
        assert "3 tool calls" in summary

    def test_format_completion_minimal(self):
        pt = ProgressTracker()
        pt.start_time = time.time() - 10
        summary = pt.format_completion_summary()
        assert "Completed in" in summary


class TestProgressTrackerTaskFiles:
    def test_read_task_files_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = os.path.join(tmpdir, "test-session")
            os.makedirs(task_dir)
            with open(os.path.join(task_dir, "1.json"), "w") as f:
                json.dump({"id": "1", "subject": "Test", "status": "completed"}, f)

            pt = ProgressTracker(session_id="test-session")
            # Override tasks base path
            with patch("progress_tracker.os.path.expanduser", return_value=tmpdir):
                tasks = pt._read_task_files()

            # Won't find tasks because dir structure doesn't match default
            # but _parse_task_dir works directly:
            tasks = pt._parse_task_dir(task_dir)
            assert len(tasks) == 1
            assert tasks[0]["status"] == "completed"

    def test_parse_task_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks = ProgressTracker._parse_task_dir(tmpdir)
            assert tasks == []

    def test_parse_task_dir_missing(self):
        tasks = ProgressTracker._parse_task_dir("/nonexistent/path")
        assert tasks == []

    def test_parse_task_dir_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "1.json"), "w") as f:
                f.write("{corrupt json")
            tasks = ProgressTracker._parse_task_dir(tmpdir)
            assert tasks == []

    def test_read_no_session_id(self):
        pt = ProgressTracker(session_id=None)
        assert pt._read_task_files() == []


# --- StuckDetector Tests ---

class TestStuckDetectorInit:
    def test_init_defaults(self):
        sd = StuckDetector(pid=12345, config={})
        assert sd.pid == 12345
        assert sd.threshold == 5400
        assert sd.max_alerts == 3
        assert sd.alerts_sent == 0

    def test_init_custom_config(self):
        sd = StuckDetector(pid=1, config={"stuck_threshold": 3600, "stuck_max_alerts": 5})
        assert sd.threshold == 3600
        assert sd.max_alerts == 5


class TestStuckDetectorCheck:
    def test_not_stuck_below_threshold(self):
        sd = StuckDetector(pid=1, config={"stuck_threshold": 5400})
        sd.start_time = time.time() - 60  # Only 1 min
        assert sd.check() is None

    def test_not_stuck_children_changing(self):
        sd = StuckDetector(pid=1, config={"stuck_threshold": 1})  # 1s threshold
        sd.start_time = time.time() - 10
        with patch.object(sd, "_get_child_pids", return_value={"100"}):
            assert sd.check() is None
        with patch.object(sd, "_get_child_pids", return_value={"200"}):  # Changed!
            assert sd.check() is None

    def test_stuck_detected(self):
        sd = StuckDetector(pid=1, config={"stuck_threshold": 1, "stuck_stale_child_minutes": 0})
        sd.start_time = time.time() - 10
        sd.last_child_pids = {"100"}
        sd.child_unchanged_since = time.time() - 60
        with patch.object(sd, "_get_child_pids", return_value={"100"}):
            with patch.object(sd, "_get_child_commands", return_value=["ada credentials update"]):
                result = sd.check()
        assert result is not None
        assert result["alert_number"] == 1
        assert "ada credentials update" in result["child_commands"]

    def test_max_alerts_respected(self):
        sd = StuckDetector(pid=1, config={"stuck_threshold": 1, "stuck_stale_child_minutes": 0, "stuck_max_alerts": 2})
        sd.start_time = time.time() - 100
        sd.alerts_sent = 2
        sd.last_child_pids = {"100"}
        sd.child_unchanged_since = time.time() - 60
        with patch.object(sd, "_get_child_pids", return_value={"100"}):
            assert sd.check() is None  # Max reached

    def test_reset(self):
        sd = StuckDetector(pid=1, config={})
        sd.alerts_sent = 3
        sd.last_child_pids = {"100", "200"}
        sd.reset()
        assert sd.alerts_sent == 0
        assert sd.last_child_pids == set()


class TestStuckDetectorFormat:
    def test_format_alert_basic(self):
        sd = StuckDetector(pid=1, config={})
        diag = {
            "elapsed": 5520,
            "stale_minutes": 15,
            "child_commands": ["ada credentials update --account 123456789012"],
            "child_pids": ["79779"],
            "alert_number": 1,
            "max_alerts": 3,
        }
        msg = sd.format_stuck_alert(diag)
        assert "STUCK ALERT" in msg
        assert "92min" in msg
        assert "ada credentials" in msg
        assert "/cancel" in msg
        assert "1/3" in msg

    def test_format_alert_with_diagnosis(self):
        sd = StuckDetector(pid=1, config={})
        diag = {
            "elapsed": 6000,
            "stale_minutes": 20,
            "child_commands": ["ada credentials update"],
            "child_pids": ["100"],
            "alert_number": 1,
            "max_alerts": 3,
        }
        msg = sd.format_stuck_alert(diag, diagnosis="ADA waiting for browser auth")
        assert "Diagnosis: ADA waiting for browser auth" in msg

    def test_format_alert_no_child_commands(self):
        sd = StuckDetector(pid=1, config={})
        diag = {
            "elapsed": 6000,
            "stale_minutes": 20,
            "child_commands": [],
            "child_pids": [],
            "alert_number": 2,
            "max_alerts": 3,
        }
        msg = sd.format_stuck_alert(diag)
        assert "STUCK ALERT" in msg
        assert "2/3" in msg
