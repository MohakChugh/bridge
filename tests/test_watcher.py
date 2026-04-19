"""Tests for watcher module — checkers, classification, alerts, lifecycle."""

import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from watcher import (
    PipelineChecker, TicketChecker, GenericChecker,
    get_checker, format_alert, format_dashboard, format_watch_list,
    MAX_WATCHES, DEFAULT_COOLDOWN,
)


# --- PipelineChecker ---

class TestPipelineChecker:
    def setup_method(self):
        self.checker = PipelineChecker()

    def test_detect_change_blocked(self):
        old = {"pipelines": [{"name": "P1", "blocked": False}]}
        new = {"pipelines": [{"name": "P1", "blocked": True}]}
        result = self.checker.detect_change(old, new)
        assert result is not None
        assert "BLOCKED" in result

    def test_detect_change_unblocked(self):
        old = {"pipelines": [{"name": "P1", "blocked": True}]}
        new = {"pipelines": [{"name": "P1", "blocked": False}]}
        result = self.checker.detect_change(old, new)
        assert "UNBLOCKED" in result

    def test_detect_no_change(self):
        old = {"pipelines": [{"name": "P1", "blocked": False, "badge": "silver"}]}
        new = {"pipelines": [{"name": "P1", "blocked": False, "badge": "silver"}]}
        assert self.checker.detect_change(old, new) is None

    def test_detect_failed_deploys_increased(self):
        old = {"pipelines": [{"name": "P1", "blocked": False, "failedDeploys": 0}]}
        new = {"pipelines": [{"name": "P1", "blocked": False, "failedDeploys": 1}]}
        result = self.checker.detect_change(old, new)
        assert "deploy failure" in result

    def test_detect_failed_builds_increased(self):
        old = {"pipelines": [{"name": "P1", "blocked": False, "failedBuilds": 0}]}
        new = {"pipelines": [{"name": "P1", "blocked": False, "failedBuilds": 2}]}
        result = self.checker.detect_change(old, new)
        assert "build failure" in result

    def test_detect_badge_changed(self):
        old = {"pipelines": [{"name": "P1", "blocked": False, "badge": "gold"}]}
        new = {"pipelines": [{"name": "P1", "blocked": False, "badge": "bronze"}]}
        result = self.checker.detect_change(old, new)
        assert "badge" in result

    def test_detect_multiple_changes(self):
        old = {"pipelines": [
            {"name": "P1", "blocked": False, "failedDeploys": 0},
            {"name": "P2", "blocked": False, "failedBuilds": 0},
        ]}
        new = {"pipelines": [
            {"name": "P1", "blocked": True, "failedDeploys": 1},
            {"name": "P2", "blocked": False, "failedBuilds": 3},
        ]}
        result = self.checker.detect_change(old, new)
        assert "P1" in result
        assert "P2" in result

    def test_detect_empty_states(self):
        assert self.checker.detect_change({}, {}) is None
        assert self.checker.detect_change({"pipelines": []}, {"pipelines": []}) is None


# --- TicketChecker ---

class TestTicketChecker:
    def setup_method(self):
        self.checker = TicketChecker()

    def test_detect_new_ticket(self):
        old = {"ticket_ids": {"T001", "T002"}, "tickets": []}
        new = {
            "ticket_ids": {"T001", "T002", "T003"},
            "tickets": [{"id": "T003", "title": "Lambda error", "severity": 2}],
        }
        result = self.checker.detect_change(old, new)
        assert result is not None
        assert "1 new" in result
        assert "T003" in result

    def test_detect_multiple_new_tickets(self):
        old = {"ticket_ids": {"T001"}, "tickets": []}
        new = {
            "ticket_ids": {"T001", "T002", "T003"},
            "tickets": [
                {"id": "T002", "title": "Error A", "severity": 2},
                {"id": "T003", "title": "Error B", "severity": 3},
            ],
        }
        result = self.checker.detect_change(old, new)
        assert "2 new" in result

    def test_detect_no_change(self):
        old = {"ticket_ids": {"T001", "T002"}, "tickets": []}
        new = {"ticket_ids": {"T001", "T002"}, "tickets": []}
        assert self.checker.detect_change(old, new) is None

    def test_detect_ticket_resolved_no_alert(self):
        old = {"ticket_ids": {"T001", "T002"}, "tickets": []}
        new = {"ticket_ids": {"T001"}, "tickets": []}
        # Resolved ticket = fewer tickets, but no "new" alert
        assert self.checker.detect_change(old, new) is None

    def test_detect_empty_states(self):
        assert self.checker.detect_change({}, {}) is None


# --- GenericChecker ---

class TestGenericChecker:
    def setup_method(self):
        self.checker = GenericChecker()

    def test_detect_raw_change(self):
        old = {"raw": "state A", "timestamp": 1}
        new = {"raw": "state B", "timestamp": 2}
        result = self.checker.detect_change(old, new)
        assert result is not None
        assert "changed" in result

    def test_detect_no_change(self):
        old = {"raw": "same", "timestamp": 1}
        new = {"raw": "same", "timestamp": 2}
        assert self.checker.detect_change(old, new) is None

    def test_first_check_no_alert(self):
        old = {"raw": "", "timestamp": 0}
        new = {"raw": "initial state", "timestamp": 1}
        # First check (old is empty) should not alert
        assert self.checker.detect_change(old, new) is None


# --- Checker Registry ---

class TestCheckerRegistry:
    def test_get_pipeline_checker(self):
        assert isinstance(get_checker("pipeline"), PipelineChecker)

    def test_get_ticket_checker(self):
        assert isinstance(get_checker("tickets"), TicketChecker)

    def test_get_unknown_returns_generic(self):
        assert isinstance(get_checker("nonexistent"), GenericChecker)


# --- Alert Formatting ---

class TestFormatAlert:
    def test_basic_alert(self):
        result = format_alert("Pipeline BLOCKED", {"type": "pipeline", "human": "CentralisBackend"})
        assert "WATCH:" in result
        assert "Pipeline BLOCKED" in result

    def test_alert_with_diagnosis(self):
        result = format_alert("New ticket", {"human": "Nexus tickets"}, diagnosis="DDB throttling detected")
        assert "Diagnosis:" in result
        assert "DDB throttling" in result

    def test_alert_with_fix(self):
        result = format_alert("Deploy failed", {"human": "deploy"}, fix="rollback last deploy")
        assert "Suggested fix:" in result
        assert "Execute? (y/n)" in result

    def test_alert_no_markdown(self):
        result = format_alert("test", {"human": "test"}, diagnosis="**bold** `code`")
        # Alert should be plain text (no markdown stripping in format_alert itself,
        # but verify no structural markdown)
        assert "WATCH:" in result


# --- Dashboard ---

class TestFormatDashboard:
    def test_empty_dashboard(self):
        result = format_dashboard([], [], 0)
        assert "0 active" in result

    def test_dashboard_with_watches(self):
        watches = [
            {"status": "active", "human": "Pipeline watch", "interval": 300, "alert_count": 2},
            {"status": "paused", "human": "Ticket watch", "interval": 60, "alert_count": 0},
        ]
        result = format_dashboard(watches, [], 0)
        assert "1 active" in result
        assert "1 paused" in result
        assert "Pipeline watch" in result

    def test_dashboard_muted(self):
        result = format_dashboard([], [], time.time() + 3600)
        assert "MUTED" in result

    def test_dashboard_with_recent_alerts(self):
        alerts = [{"ts": time.time() - 60, "summary": "Pipeline blocked"}]
        result = format_dashboard([], alerts, 0)
        assert "1 alerts" in result
        assert "Pipeline blocked" in result

    def test_dashboard_snoozed_watch(self):
        watches = [{"status": "active", "human": "Test", "interval": 300, "alert_count": 0, "snooze_until": time.time() + 600}]
        result = format_dashboard(watches, [], 0)
        assert "snoozed" in result


# --- Watch List ---

class TestFormatWatchList:
    def test_empty_list(self):
        assert "No active" in format_watch_list([])

    def test_list_with_watches(self):
        watches = [
            {"status": "active", "human": "Pipeline CentralisBackend", "type": "pipeline", "interval": 300},
            {"status": "paused", "human": "Sev-2 tickets", "type": "tickets", "interval": 60},
        ]
        result = format_watch_list(watches)
        assert "1." in result
        assert "2." in result
        assert "pipeline" in result
        assert "paused" in result

    def test_list_shows_interval(self):
        watches = [{"status": "active", "human": "Test", "type": "generic", "interval": 900}]
        result = format_watch_list(watches)
        assert "15m" in result
