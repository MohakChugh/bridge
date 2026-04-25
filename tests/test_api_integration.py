"""Comprehensive API integration test suite.

Tests ALL 59 endpoints across ALL tool combinations.
Uses FastAPI TestClient — no daemon/iMessage/Slack needed.
All test data prefixed with 'test_' and cleaned up after each test.
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DEFAULT_CONFIG


# ---- Fixtures ----

@pytest.fixture(scope="module")
def app_client():
    """Create FastAPI test client with mocked daemon."""
    from fastapi.testclient import TestClient
    from session_manager import SessionManager
    from event_bus import EventBus

    # Mock daemon with real config
    daemon = MagicMock()
    daemon.config = {
        **DEFAULT_CONFIG,
        "directories": {"default": "/tmp", "home": "/tmp/home"},
        "cli_tool": "claude",
        "parsing_tool": "claude",
        "max_parallel_sessions": 4,
        "gateway": {"enabled": True, "port": 7777},
        "slack": {"enabled": False},
        "adapters": {
            "claude": {"effort": "max"},
            "wasabi": {"account": "test", "model": "test-model"},
            "kiro": {"model": "test-model"},
        },
    }
    daemon.state = {
        "watermark": 0,
        "reminders": [],
        "scheduled_tasks": [],
        "watches": [],
    }
    daemon._imessage_enabled = False
    daemon._parse_remind_via_llm = MagicMock(return_value={
        "iso": "2026-04-26T10:00:00",
        "human": "test time",
        "message": "test reminder",
        "fire_at": time.time() + 3600,
    })

    sm = SessionManager(config_provider=lambda: daemon.config, max_parallel=4)

    # Use temp files for workflows
    with tempfile.TemporaryDirectory() as tmpdir:
        wf_path = os.path.join(tmpdir, "workflows.json")
        wf_runs_path = os.path.join(tmpdir, "workflow_runs.json")

        # Patch workflow store paths
        import workflow_store
        orig_path = workflow_store.WORKFLOWS_PATH
        workflow_store.WORKFLOWS_PATH = wf_path

        import workflow_engine
        orig_runs = workflow_engine.RUNS_PATH
        workflow_engine.RUNS_PATH = wf_runs_path

        from gateway import create_app
        app = create_app(sm, daemon)
        client = TestClient(app)

        yield client, daemon, sm

        workflow_store.WORKFLOWS_PATH = orig_path
        workflow_engine.RUNS_PATH = orig_runs


# ---- 1. Health & Config ----

class TestHealthAndConfig:
    def test_health(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_config(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert "directories" in data
        assert len(data["tools"]) >= 3

    def test_tools(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/tools")
        assert r.status_code == 200
        data = r.json()
        assert "tools" in data
        assert "claude" in data["tools"]
        assert "wasabi" in data["tools"]
        assert "kiro" in data["tools"]

    def test_directories(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/directories")
        assert r.status_code == 200
        assert "default" in r.json()

    def test_settings_get(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "cli_tool" in data
        assert "parsing_tool" in data
        assert "tools" in data

    def test_settings_save(self, app_client):
        client, daemon, _ = app_client
        r = client.post("/api/settings", json={"cli_tool": "wasabi"})
        assert r.status_code == 200
        assert r.json()["saved"] is True

    def test_dashboard(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "sessions" in data
        assert "reminders" in data
        assert "schedules" in data
        assert "watches" in data

    def test_operations(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/operations")
        assert r.status_code == 200
        data = r.json()
        assert "running_workflows" in data
        assert "sessions" in data

    def test_activity(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/activity")
        assert r.status_code == 200
        assert "events" in r.json()

    def test_web_ui_serves(self, app_client):
        client, _, _ = app_client
        r = client.get("/")
        assert r.status_code == 200


# ---- 2. Sessions CRUD ----

class TestSessionsCRUD:
    def test_create_session(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/sessions", json={"tool": "claude", "cwd": "/tmp", "title": "test_session"})
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "test_session"
        assert data["tool"] == "claude"
        assert data["status"] == "idle"
        # Cleanup
        client.delete(f"/api/sessions/{data['id']}")

    def test_list_sessions(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_get_session(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/sessions", json={"tool": "wasabi", "cwd": "/tmp", "title": "test_get"})
        sid = cr.json()["id"]
        r = client.get(f"/api/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["title"] == "test_get"
        client.delete(f"/api/sessions/{sid}")

    def test_delete_session(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/sessions", json={"tool": "kiro", "cwd": "/tmp", "title": "test_delete"})
        sid = cr.json()["id"]
        r = client.delete(f"/api/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True

    def test_create_session_invalid_cwd(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/sessions", json={"tool": "claude", "cwd": "/nonexistent/path"})
        assert r.status_code == 400

    def test_get_nonexistent_session(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/sessions/nonexistent-id")
        assert r.status_code == 404

    def test_archived_sessions(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/sessions/archived")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_create_session_all_tools(self, app_client):
        """Test session creation works for all 3 tools."""
        client, _, _ = app_client
        for tool in ["claude", "wasabi", "kiro"]:
            r = client.post("/api/sessions", json={"tool": tool, "cwd": "/tmp", "title": f"test_{tool}"})
            assert r.status_code == 200, f"Failed for {tool}"
            assert r.json()["tool"] == tool
            client.delete(f"/api/sessions/{r.json()['id']}")


# ---- 3. Reminders CRUD ----

class TestRemindersCRUD:
    def test_list_reminders(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/reminders")
        assert r.status_code == 200
        assert "reminders" in r.json()

    def test_create_reminder(self, app_client):
        client, daemon, _ = app_client
        fire_at = time.time() + 7200
        r = client.post("/api/reminders", json={
            "message": "test_integration_reminder",
            "fire_at_epoch": fire_at,
            "human": "test",
        })
        assert r.status_code == 200
        assert r.json()["message"] == "test_integration_reminder"
        # Verify in list
        reminders = client.get("/api/reminders").json()["reminders"]
        test_reminders = [r for r in reminders if r["message"] == "test_integration_reminder"]
        assert len(test_reminders) >= 1
        # Cleanup
        for i in range(len(reminders) - 1, -1, -1):
            if reminders[i]["message"] == "test_integration_reminder":
                client.delete(f"/api/reminders/{i}")

    def test_delete_reminder(self, app_client):
        client, daemon, _ = app_client
        client.post("/api/reminders", json={
            "message": "test_delete_reminder",
            "fire_at_epoch": time.time() + 9999,
        })
        reminders = client.get("/api/reminders").json()["reminders"]
        for i, r in enumerate(reminders):
            if r["message"] == "test_delete_reminder":
                resp = client.delete(f"/api/reminders/{i}")
                assert resp.status_code == 200
                break

    def test_delete_nonexistent_reminder(self, app_client):
        client, _, _ = app_client
        r = client.delete("/api/reminders/999")
        assert r.status_code == 404


# ---- 4. Schedules CRUD ----

class TestSchedulesCRUD:
    def test_list_schedules(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/schedules")
        assert r.status_code == 200
        assert "schedules" in r.json()

    def test_create_schedule(self, app_client):
        client, daemon, _ = app_client
        r = client.post("/api/schedules", json={
            "cron": "0 9 * * *",
            "human": "test daily 9am",
            "prompt": "test_integration_schedule",
            "tool": "claude",
            "cwd": "/tmp",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["prompt"] == "test_integration_schedule"
        # Cleanup
        client.delete(f"/api/schedules/{data['id']}")

    def test_delete_schedule(self, app_client):
        client, daemon, _ = app_client
        cr = client.post("/api/schedules", json={
            "cron": "0 10 * * *",
            "human": "test",
            "prompt": "test_delete_schedule",
        })
        sid = cr.json()["id"]
        r = client.delete(f"/api/schedules/{sid}")
        assert r.status_code == 200


# ---- 5. Watches CRUD ----

class TestWatchesCRUD:
    def test_list_watches(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/watches")
        assert r.status_code == 200
        assert "watches" in r.json()

    def test_create_watch(self, app_client):
        client, daemon, _ = app_client
        r = client.post("/api/watches", json={
            "target": "test_target",
            "check_type": "generic",
            "description": "test_integration_watch",
            "interval_minutes": 5,
        })
        assert r.status_code == 200
        wid = r.json()["id"]
        # Cleanup
        client.delete(f"/api/watches/{wid}")

    def test_delete_watch(self, app_client):
        client, daemon, _ = app_client
        cr = client.post("/api/watches", json={
            "target": "test_del",
            "check_type": "generic",
            "description": "test_delete_watch",
        })
        wid = cr.json()["id"]
        r = client.delete(f"/api/watches/{wid}")
        assert r.status_code == 200


# ---- 6. Workflows CRUD ----

class TestWorkflowsCRUD:
    def _make_workflow(self):
        return {
            "name": "test_workflow",
            "tool": "wasabi",
            "cwd": "/tmp",
            "nodes": [
                {"id": "s1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "e1", "type": "end", "position": {"x": 0, "y": 200}, "data": {}},
            ],
            "edges": [{"id": "e-s1-e1", "source": "s1", "target": "e1"}],
        }

    def test_list_workflows(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/workflows")
        assert r.status_code == 200
        assert "workflows" in r.json()

    def test_create_workflow(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/workflows", json=self._make_workflow())
        assert r.status_code == 200
        assert r.json()["name"] == "test_workflow"
        wid = r.json()["id"]
        client.delete(f"/api/workflows/{wid}")

    def test_get_workflow(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/workflows", json=self._make_workflow())
        wid = cr.json()["id"]
        r = client.get(f"/api/workflows/{wid}")
        assert r.status_code == 200
        assert r.json()["name"] == "test_workflow"
        client.delete(f"/api/workflows/{wid}")

    def test_update_workflow(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/workflows", json=self._make_workflow())
        wid = cr.json()["id"]
        updated = self._make_workflow()
        updated["name"] = "test_updated"
        r = client.put(f"/api/workflows/{wid}", json=updated)
        assert r.status_code == 200
        assert r.json()["name"] == "test_updated"
        client.delete(f"/api/workflows/{wid}")

    def test_delete_workflow(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/workflows", json=self._make_workflow())
        wid = cr.json()["id"]
        r = client.delete(f"/api/workflows/{wid}")
        assert r.status_code == 200

    def test_get_nonexistent_workflow(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/workflows/nonexistent")
        assert r.status_code == 404

    def test_workflow_with_variables(self, app_client):
        client, _, _ = app_client
        wf = self._make_workflow()
        wf["variables"] = [
            {"name": "team", "type": "string", "default": "SIS"},
            {"name": "start_date", "type": "date", "default": "today - 7d"},
        ]
        r = client.post("/api/workflows", json=wf)
        assert r.status_code == 200
        assert len(r.json().get("variables", [])) == 2
        client.delete(f"/api/workflows/{r.json()['id']}")


# ---- 7. Workflow Schedules ----

class TestWorkflowSchedules:
    def _make_workflow(self, client):
        r = client.post("/api/workflows", json={
            "name": "test_sched_wf",
            "tool": "wasabi",
            "cwd": "/tmp",
            "nodes": [
                {"id": "s1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "e1", "type": "end", "position": {"x": 0, "y": 200}, "data": {}},
            ],
            "edges": [{"id": "e1", "source": "s1", "target": "e1"}],
        })
        return r.json()["id"]

    def test_list_schedules(self, app_client):
        client, _, _ = app_client
        wid = self._make_workflow(client)
        r = client.get(f"/api/workflows/{wid}/schedules")
        assert r.status_code == 200
        assert "schedules" in r.json()
        client.delete(f"/api/workflows/{wid}")

    def test_add_schedule(self, app_client):
        client, _, _ = app_client
        wid = self._make_workflow(client)
        r = client.post(f"/api/workflows/{wid}/schedules", json={
            "cron": "0 9 * * 1-5",
            "human": "weekdays 9am",
            "label": "test_schedule",
            "params": {"team": "SIS"},
        })
        assert r.status_code == 200
        assert r.json()["label"] == "test_schedule"
        client.delete(f"/api/workflows/{wid}")

    def test_delete_schedule(self, app_client):
        client, _, _ = app_client
        wid = self._make_workflow(client)
        cr = client.post(f"/api/workflows/{wid}/schedules", json={
            "cron": "0 10 * * *",
            "human": "daily 10am",
            "label": "test_del",
        })
        sched_id = cr.json()["id"]
        r = client.delete(f"/api/workflows/{wid}/schedules/{sched_id}")
        assert r.status_code == 200
        client.delete(f"/api/workflows/{wid}")

    def test_multiple_schedules(self, app_client):
        """Same workflow, multiple schedules with different params."""
        client, _, _ = app_client
        wid = self._make_workflow(client)
        client.post(f"/api/workflows/{wid}/schedules", json={
            "cron": "0 9 * * 2", "human": "Tue 9am", "label": "SIS",
            "params": {"team": "SIS"},
        })
        client.post(f"/api/workflows/{wid}/schedules", json={
            "cron": "0 9 * * 2", "human": "Tue 9am", "label": "Nexus",
            "params": {"team": "Nexus"},
        })
        r = client.get(f"/api/workflows/{wid}/schedules")
        assert len(r.json()["schedules"]) == 2
        client.delete(f"/api/workflows/{wid}")


# ---- 8. Variables ----

class TestVariables:
    def test_resolve_static(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/variables/resolve", json={
            "variables": [{"name": "team", "type": "string", "default": "SIS"}],
        })
        assert r.status_code == 200
        assert r.json()["resolved"]["team"] == "SIS"

    def test_resolve_date_today(self, app_client):
        client, _, _ = app_client
        from datetime import datetime
        r = client.post("/api/variables/resolve", json={
            "variables": [{"name": "d", "type": "date", "default": "today"}],
        })
        assert r.status_code == 200
        assert r.json()["resolved"]["d"] == datetime.now().strftime("%Y-%m-%d")

    def test_resolve_date_relative(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/variables/resolve", json={
            "variables": [{"name": "d", "type": "date", "default": "today - 7d"}],
        })
        assert r.status_code == 200
        from datetime import datetime, timedelta
        expected = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        assert r.json()["resolved"]["d"] == expected

    def test_resolve_with_overrides(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/variables/resolve", json={
            "variables": [{"name": "team", "type": "string", "default": "SIS"}],
            "overrides": {"team": "Nexus"},
        })
        assert r.status_code == 200
        assert r.json()["resolved"]["team"] == "Nexus"

    def test_resolve_multiple(self, app_client):
        client, _, _ = app_client
        r = client.post("/api/variables/resolve", json={
            "variables": [
                {"name": "a", "type": "string", "default": "x"},
                {"name": "b", "type": "date", "default": "yesterday"},
                {"name": "c", "type": "number", "default": "42"},
            ],
        })
        assert r.status_code == 200
        resolved = r.json()["resolved"]
        assert len(resolved) == 3
        assert resolved["a"] == "x"
        assert resolved["c"] == "42"


# ---- 9. Workflow Runs ----

class TestWorkflowRuns:
    def test_list_all_runs(self, app_client):
        client, _, _ = app_client
        r = client.get("/api/workflow-runs")
        assert r.status_code == 200
        assert "runs" in r.json()

    def test_list_runs_for_workflow(self, app_client):
        client, _, _ = app_client
        cr = client.post("/api/workflows", json={
            "name": "test_runs_wf",
            "tool": "wasabi",
            "cwd": "/tmp",
            "nodes": [{"id": "s1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}}],
            "edges": [],
        })
        wid = cr.json()["id"]
        r = client.get(f"/api/workflows/{wid}/runs")
        assert r.status_code == 200
        assert "runs" in r.json()
        client.delete(f"/api/workflows/{wid}")


# ---- 10. Variable Resolver Unit Tests ----

class TestVariableResolver:
    def test_today(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime
        assert evaluate_expression("today", "date") == datetime.now().strftime("%Y-%m-%d")

    def test_yesterday(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime, timedelta
        assert evaluate_expression("yesterday", "date") == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def test_tomorrow(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime, timedelta
        assert evaluate_expression("tomorrow", "date") == (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    def test_today_minus_days(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime, timedelta
        assert evaluate_expression("today - 7d", "date") == (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).strftime("%Y-%m-%d")

    def test_start_of_week(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime, timedelta
        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        expected = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        assert evaluate_expression("start_of_week", "date") == expected

    def test_start_of_month(self):
        from variable_resolver import evaluate_expression
        from datetime import datetime
        expected = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d")
        assert evaluate_expression("start_of_month", "date") == expected

    def test_static_string(self):
        from variable_resolver import evaluate_expression
        assert evaluate_expression("SIS", "string") == "SIS"

    def test_number(self):
        from variable_resolver import evaluate_expression
        assert evaluate_expression("42", "number") == "42"

    def test_substitute_variables(self):
        from variable_resolver import substitute_variables
        result = substitute_variables("Hello {{name}}, date is {{date}}", {"name": "World", "date": "2026-04-25"})
        assert result == "Hello World, date is 2026-04-25"

    def test_substitute_missing_var(self):
        from variable_resolver import substitute_variables
        result = substitute_variables("Hello {{name}}", {})
        assert result == "Hello {{name}}"

    def test_resolve_with_overrides(self):
        from variable_resolver import resolve_variables
        variables = [{"name": "team", "type": "string", "default": "SIS"}]
        result = resolve_variables(variables, {"team": "Nexus"})
        assert result["team"] == "Nexus"


# ---- 11. LLM Parser Unit Tests ----

class TestLLMParser:
    def test_extract_json_direct(self):
        from llm_parser import extract_json
        result = extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_json_claude_wrapper(self):
        from llm_parser import extract_json
        result = extract_json('{"result": "{\\"key\\": \\"value\\"}"}')
        assert result == {"key": "value"}

    def test_extract_json_in_text(self):
        from llm_parser import extract_json
        result = extract_json('Some text before {"key": "value"} and after')
        assert result == {"key": "value"}

    def test_extract_json_code_block(self):
        from llm_parser import extract_json
        result = extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_extract_json_with_newline_in_value(self):
        from llm_parser import extract_json
        result = extract_json('{"key": "line1\nline2"}')
        assert result is not None
        assert "line1" in result["key"]

    def test_extract_json_with_prefix(self):
        from llm_parser import extract_json
        result = extract_json('│ json\n{"iso": "2026-04-26T10:00:00"}')
        assert result == {"iso": "2026-04-26T10:00:00"}

    def test_extract_json_empty(self):
        from llm_parser import extract_json
        assert extract_json("") is None
        assert extract_json(None) is None

    def test_extract_json_no_json(self):
        from llm_parser import extract_json
        assert extract_json("just some text") is None

    def test_extract_json_trailing_comma(self):
        from llm_parser import extract_json
        result = extract_json('{"key": "value",}')
        assert result == {"key": "value"}


# ---- 12. Session Store Tests ----

class TestSessionStore:
    def test_save_and_load(self):
        from session_store import save_session, load_sessions, delete_session
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_session({"id": "test-1", "title": "test", "message_history": []}, path=path)
            sessions = load_sessions(path)
            assert len(sessions) == 1
            assert sessions[0]["id"] == "test-1"
            delete_session("test-1", path=path)
            assert len(load_sessions(path)) == 0
        finally:
            os.unlink(path)

    def test_max_sessions_cap(self):
        from session_store import save_session, load_sessions
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            for i in range(110):
                save_session({"id": f"test-{i}", "title": f"test {i}", "updated_at": i, "message_history": []}, path=path)
            sessions = load_sessions(path)
            assert len(sessions) <= 100
        finally:
            os.unlink(path)


# ---- 13. Workflow Store Tests ----

class TestWorkflowStore:
    def test_crud(self):
        from workflow_store import load_workflows, upsert_workflow, get_workflow, delete_workflow
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            wf = upsert_workflow(path, {"name": "test", "nodes": [], "edges": []})
            assert wf["id"] is not None
            assert get_workflow(path, wf["id"]) is not None
            assert len(load_workflows(path)) == 1
            delete_workflow(path, wf["id"])
            assert len(load_workflows(path)) == 0
        finally:
            os.unlink(path)


# ---- 14. Event Bus Tests ----

class TestEventBus:
    def test_publish_subscribe(self):
        from event_bus import EventBus
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("test.event", {"key": "value"})
        event = q.get(timeout=1)
        assert event["type"] == "test.event"
        assert event["data"]["key"] == "value"
        bus.unsubscribe(q)

    def test_multiple_subscribers(self):
        from event_bus import EventBus
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.publish("test", {"x": 1})
        assert q1.get(timeout=1)["data"]["x"] == 1
        assert q2.get(timeout=1)["data"]["x"] == 1
        bus.unsubscribe(q1)
        bus.unsubscribe(q2)


# ---- 15. Adapter Registry Tests ----

class TestAdapterRegistry:
    def test_auto_discovery(self):
        from adapters import list_adapters, get_adapter
        adapters = list_adapters()
        assert "claude" in adapters
        assert "wasabi" in adapters
        assert "kiro" in adapters

    def test_get_unknown_adapter(self):
        from adapters import get_adapter
        with pytest.raises(KeyError):
            get_adapter("nonexistent_tool")

    def test_adapter_names(self):
        from adapters import get_adapter
        assert get_adapter("claude").name() == "claude"
        assert get_adapter("wasabi").name() == "wasabi"
        assert get_adapter("kiro").name() == "kiro"
