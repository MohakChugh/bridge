"""FastAPI gateway — REST + WebSocket for web UI.

Runs in its own thread inside the daemon process. Exposes:
  REST /api/sessions, /api/reminders, /api/schedules, /api/watches, /api/dashboard
  WS   /ws/events — live firehose of all daemon events

Binds to 127.0.0.1 only.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import queue
import threading
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from event_bus import get_event_bus

log = logging.getLogger("gateway")

WEB_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")


class CreateSessionBody(BaseModel):
    tool: str
    cwd: str
    title: Optional[str] = None


class SendMessageBody(BaseModel):
    text: str


class ReminderBody(BaseModel):
    text: str


class ReminderDirectBody(BaseModel):
    message: str
    fire_at_epoch: float  # unix epoch seconds
    human: Optional[str] = None


class ScheduleBody(BaseModel):
    text: str
    tool: Optional[str] = None
    cwd: Optional[str] = None


class ScheduleDirectBody(BaseModel):
    cron: str
    human: str
    prompt: str
    tool: Optional[str] = None
    cwd: Optional[str] = None


class WatchBody(BaseModel):
    text: str


class ParseBody(BaseModel):
    text: str
    kind: str  # "remind" | "schedule" | "watch"


class WorkflowBody(BaseModel):
    name: str
    description: str = ""
    tool: str = "wasabi"
    cwd: str = "/tmp"
    require_approval: bool = False
    nodes: list = []
    edges: list = []
    schedule: Optional[dict] = None


class WorkflowApprovalBody(BaseModel):
    action: str  # "approve" | "abort"


def create_app(session_manager, daemon_ref) -> FastAPI:
    app = FastAPI(title="iMessage Bridge Gateway")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:7777"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Config / metadata ----

    @app.get("/api/health")
    def health():
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/api/config")
    def get_config():
        cfg = daemon_ref.config
        return {
            "directories": cfg.get("directories", {}),
            "tools": ["claude", "wasabi", "kiro"],
            "active_tool": cfg.get("cli_tool", "claude"),
            "max_parallel_sessions": cfg.get("max_parallel_sessions", 4),
        }

    @app.get("/api/tools")
    def list_tools():
        from adapters import list_adapters
        return {"tools": list_adapters(), "active": daemon_ref.config.get("cli_tool", "claude")}

    @app.get("/api/directories")
    def list_directories():
        return daemon_ref.config.get("directories", {})

    # ---- Sessions ----

    @app.get("/api/sessions")
    def list_sessions():
        return {"sessions": [s.to_dict() for s in session_manager.list()]}

    @app.post("/api/sessions")
    def create_session(body: CreateSessionBody):
        if not os.path.isdir(body.cwd):
            raise HTTPException(status_code=400, detail=f"Directory not found: {body.cwd}")
        session = session_manager.create(tool=body.tool, cwd=body.cwd, title=body.title)
        return session.to_dict()

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        session = session_manager.get(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict()

    @app.post("/api/sessions/{sid}/message")
    def send_message(sid: str, body: SendMessageBody):
        session = session_manager.get(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status == "busy":
            raise HTTPException(status_code=409, detail="Session busy, cancel first")
        success = session_manager.execute(sid, body.text)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to start execution")
        return {"status": "started", "session_id": sid}

    @app.post("/api/sessions/{sid}/cancel")
    def cancel_session(sid: str):
        ok = session_manager.cancel(sid)
        return {"cancelled": ok}

    @app.delete("/api/sessions/{sid}")
    def delete_session(sid: str):
        ok = session_manager.delete(sid)
        if not ok:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"deleted": True}

    # ---- Reminders ----

    @app.get("/api/reminders")
    def list_reminders():
        reminders = daemon_ref.state.get("reminders", [])
        for i, r in enumerate(reminders):
            r["id"] = i  # stable index-based id
        return {"reminders": reminders}

    @app.post("/api/reminders/parse")
    def parse_reminder(body: ReminderBody):
        from adapters.base import get_login_shell_env
        env = get_login_shell_env()
        parsed = daemon_ref._parse_remind_via_llm(body.text, env)
        if not parsed:
            raise HTTPException(status_code=400, detail="Could not parse reminder")
        return parsed

    @app.post("/api/reminders")
    def create_reminder(body: ReminderDirectBody):
        import time as t
        reminder = {
            "fire_at": body.fire_at_epoch,
            "message": body.message,
            "human": body.human or "",
        }
        daemon_ref._reminders.append(reminder)
        daemon_ref.state.setdefault("reminders", []).append(reminder)
        from config import save_state
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("reminder.created", reminder)
        return reminder

    @app.delete("/api/reminders/{idx}")
    def delete_reminder(idx: int):
        reminders = daemon_ref.state.get("reminders", [])
        if idx < 0 or idx >= len(reminders):
            raise HTTPException(status_code=404, detail="Reminder not found")
        removed = reminders.pop(idx)
        daemon_ref._reminders = [r for r in daemon_ref._reminders if r.get("message") != removed.get("message")]
        from config import save_state
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("reminder.deleted", {"id": idx})
        return {"deleted": True}

    # ---- Schedules ----

    @app.get("/api/schedules")
    def list_schedules():
        return {"schedules": daemon_ref.state.get("scheduled_tasks", [])}

    @app.post("/api/schedules/parse")
    def parse_schedule(body: ScheduleBody):
        from scheduler import parse_schedule_via_llm
        from adapters.base import get_login_shell_env
        env = get_login_shell_env()
        parsed = parse_schedule_via_llm(body.text, env)
        if not parsed:
            raise HTTPException(status_code=400, detail="Could not parse schedule")
        return parsed

    @app.post("/api/schedules")
    def create_schedule(body: ScheduleDirectBody):
        import time as t
        from scheduler import next_cron_fire
        from config import save_state
        tasks = daemon_ref.state.setdefault("scheduled_tasks", [])
        task_id = max([task.get("id", 0) for task in tasks], default=0) + 1
        task = {
            "id": task_id,
            "cron": body.cron,
            "human": body.human,
            "prompt": body.prompt,
            "tool": body.tool or daemon_ref.config.get("cli_tool", "claude"),
            "cwd": body.cwd or daemon_ref.config["directories"].get("default", "/tmp"),
            "next_fire": next_cron_fire(body.cron),
            "status": "active",
            "created_at": t.time(),
            "last_ran": None,
            "last_result": None,
        }
        tasks.append(task)
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("schedule.created", task)
        return task

    @app.delete("/api/schedules/{sched_id}")
    def delete_schedule(sched_id: int):
        from config import save_state
        tasks = daemon_ref.state.get("scheduled_tasks", [])
        idx = next((i for i, t in enumerate(tasks) if t.get("id") == sched_id), -1)
        if idx < 0:
            raise HTTPException(status_code=404, detail="Schedule not found")
        tasks.pop(idx)
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("schedule.deleted", {"id": sched_id})
        return {"deleted": True}

    @app.post("/api/schedules/{sched_id}/pause")
    def pause_schedule(sched_id: int):
        return _update_schedule_status(daemon_ref, sched_id, "paused")

    @app.post("/api/schedules/{sched_id}/resume")
    def resume_schedule(sched_id: int):
        return _update_schedule_status(daemon_ref, sched_id, "active")

    # ---- Watches ----

    @app.get("/api/watches")
    def list_watches():
        return {"watches": daemon_ref.state.get("watches", [])}

    @app.post("/api/watches/parse")
    def parse_watch(body: WatchBody):
        from watcher import classify_watch
        from adapters.base import get_login_shell_env
        env = get_login_shell_env()
        parsed = classify_watch(body.text, env)
        if not parsed:
            raise HTTPException(status_code=400, detail="Could not parse watch")
        return parsed

    @app.post("/api/watches")
    def create_watch(body: dict):
        import time as t
        from config import save_state
        watches = daemon_ref.state.setdefault("watches", [])
        watch_id = max([w.get("id", 0) for w in watches], default=0) + 1
        watch = {
            "id": watch_id,
            "target": body.get("target", ""),
            "check_type": body.get("check_type", "generic"),
            "description": body.get("description", body.get("target", "watch")),
            "interval_minutes": body.get("interval_minutes", 5),
            "status": "active",
            "created_at": t.time(),
            "last_check": None,
            "last_state": None,
            "alert_count": 0,
            "cooldown_until": 0,
        }
        watches.append(watch)
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("watch.created", watch)
        return watch

    @app.delete("/api/watches/{watch_id}")
    def delete_watch(watch_id: int):
        from config import save_state
        watches = daemon_ref.state.get("watches", [])
        idx = next((i for i, w in enumerate(watches) if w.get("id") == watch_id), -1)
        if idx < 0:
            raise HTTPException(status_code=404, detail="Watch not found")
        watches.pop(idx)
        save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("watch.deleted", {"id": watch_id})
        return {"deleted": True}

    @app.post("/api/watches/{watch_id}/pause")
    def pause_watch(watch_id: int):
        return _update_watch_status(daemon_ref, watch_id, "paused")

    @app.post("/api/watches/{watch_id}/resume")
    def resume_watch(watch_id: int):
        return _update_watch_status(daemon_ref, watch_id, "active")

    # ---- Activity feed ----

    @app.get("/api/activity")
    def get_activity():
        """Recent events + session history timeline."""
        sessions = session_manager.list()
        events = []
        for s in sessions:
            for msg in s.message_history[-20:]:
                events.append({
                    "type": "message",
                    "session_id": s.id,
                    "session_title": s.title,
                    "role": msg["role"],
                    "text": msg["text"][:200],
                    "timestamp": msg["timestamp"],
                })
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return {"events": events[:50]}

    # ---- Dashboard ----

    @app.get("/api/dashboard")
    def dashboard():
        session_snap = session_manager.snapshot()
        state = daemon_ref.state
        reminders = state.get("reminders", [])
        schedules = state.get("scheduled_tasks", [])
        watches = state.get("watches", [])
        return {
            "sessions": session_snap,
            "reminders": {
                "total": len(reminders),
                "upcoming": sorted(
                    [r for r in reminders if r.get("status") != "done"],
                    key=lambda r: r.get("fire_at", 0),
                )[:5],
            },
            "schedules": {
                "total": len(schedules),
                "active": [s for s in schedules if s.get("status") == "active"][:5],
            },
            "watches": {
                "total": len(watches),
                "active": [w for w in watches if w.get("status") == "active"][:5],
            },
            "timestamp": time.time(),
        }

    # ---- Workflows ----

    from workflow_store import load_workflows, get_workflow as _get_wf, upsert_workflow, delete_workflow as _del_wf, WORKFLOWS_PATH
    from workflow_engine import WorkflowEngine
    wf_engine = WorkflowEngine(session_manager, lambda: daemon_ref.config, daemon_ref=daemon_ref)

    @app.post("/api/workflows/generate")
    def generate_workflow_endpoint(body: dict):
        from workflow_generator import generate_workflow
        text = body.get("text", "")
        tool = body.get("tool", daemon_ref.config.get("cli_tool", "wasabi"))
        cwd = body.get("cwd", daemon_ref.config["directories"].get("default", "/tmp"))
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        wf = generate_workflow(text, tool=tool, cwd=cwd)
        if not wf:
            raise HTTPException(status_code=500, detail="Failed to generate workflow")
        return wf

    @app.get("/api/workflows")
    def list_workflows():
        return {"workflows": load_workflows(WORKFLOWS_PATH)}

    @app.post("/api/workflows")
    def create_workflow(body: WorkflowBody):
        wf = body.model_dump()
        return upsert_workflow(WORKFLOWS_PATH, wf)

    @app.get("/api/workflows/{wf_id}")
    def get_workflow_by_id(wf_id: str):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return wf

    @app.put("/api/workflows/{wf_id}")
    def update_workflow(wf_id: str, body: WorkflowBody):
        wf = body.model_dump()
        wf["id"] = wf_id
        return upsert_workflow(WORKFLOWS_PATH, wf)

    @app.delete("/api/workflows/{wf_id}")
    def delete_workflow_by_id(wf_id: str):
        ok = _del_wf(WORKFLOWS_PATH, wf_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"deleted": True}

    @app.post("/api/workflows/{wf_id}/run")
    def run_workflow(wf_id: str):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        wf_run = wf_engine.run(wf)
        return wf_run.to_dict()

    @app.get("/api/workflows/{wf_id}/runs")
    def list_workflow_runs(wf_id: str):
        runs = wf_engine.list_runs(wf_id)
        return {"runs": [r.to_dict() for r in runs]}

    @app.get("/api/workflows/{wf_id}/runs/{run_id}")
    def get_workflow_run(wf_id: str, run_id: str):
        wf_run = wf_engine.get_run(run_id)
        if not wf_run:
            raise HTTPException(status_code=404, detail="Run not found")
        return wf_run.to_dict()

    @app.post("/api/workflows/{wf_id}/runs/{run_id}/approve")
    def approve_workflow_run(wf_id: str, run_id: str):
        ok = wf_engine.approve(run_id)
        return {"approved": ok}

    @app.post("/api/workflows/{wf_id}/runs/{run_id}/abort")
    def abort_workflow_run(wf_id: str, run_id: str):
        ok = wf_engine.abort(run_id)
        return {"aborted": ok}

    @app.post("/api/workflows/{wf_id}/schedule")
    def schedule_workflow(wf_id: str, body: dict):
        from scheduler import parse_schedule_via_llm, next_cron_fire
        from adapters.base import get_login_shell_env
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        text = body.get("text", "")
        cron = body.get("cron")
        human = body.get("human")
        if not cron and text:
            env = get_login_shell_env()
            parsed = parse_schedule_via_llm(text, env)
            if not parsed:
                raise HTTPException(status_code=400, detail="Could not parse schedule")
            cron = parsed.get("cron")
            human = parsed.get("human")
        if not cron:
            raise HTTPException(status_code=400, detail="No cron expression")
        wf["schedule"] = {"cron": cron, "human": human or cron, "next_fire": next_cron_fire(cron)}
        upsert_workflow(WORKFLOWS_PATH, wf)
        get_event_bus().publish("workflow.scheduled", {"id": wf_id, "schedule": wf["schedule"]})
        return wf

    @app.delete("/api/workflows/{wf_id}/schedule")
    def unschedule_workflow(wf_id: str):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        wf["schedule"] = None
        upsert_workflow(WORKFLOWS_PATH, wf)
        return {"unscheduled": True}

    @app.get("/api/workflow-runs")
    def list_all_workflow_runs():
        runs = wf_engine.list_runs()
        return {"runs": [r.to_dict() for r in runs[:50]]}

    @app.get("/api/operations")
    def get_operations():
        """Unified snapshot: running workflows + active sessions + watches + schedules."""
        all_runs = wf_engine.list_runs()
        running_runs = [r.to_dict() for r in all_runs if r.status in ("running", "paused")]
        recent_runs = [r.to_dict() for r in all_runs[:20]]
        sessions = [s.to_dict() for s in session_manager.list()]
        state = daemon_ref.state

        scheduled_workflows = []
        for wf in load_workflows(WORKFLOWS_PATH):
            if wf.get("schedule"):
                scheduled_workflows.append({
                    "id": wf["id"],
                    "name": wf["name"],
                    "schedule": wf["schedule"],
                    "tool": wf.get("tool"),
                })

        return {
            "running_workflows": running_runs,
            "recent_runs": recent_runs,
            "scheduled_workflows": scheduled_workflows,
            "sessions": {
                "total": len(sessions),
                "busy": sum(1 for s in sessions if s["status"] == "busy"),
                "items": sessions,
            },
            "watches": {
                "total": len(state.get("watches", [])),
                "active": [w for w in state.get("watches", []) if w.get("status") == "active"],
            },
            "schedules": {
                "total": len(state.get("scheduled_tasks", [])),
                "active": [s for s in state.get("scheduled_tasks", []) if s.get("status") == "active"],
            },
            "reminders": {
                "total": len(state.get("reminders", [])),
            },
            "timestamp": time.time(),
        }

    # ---- WebSocket ----

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        await websocket.accept()
        bus = get_event_bus()
        sub = bus.subscribe()
        log.info("WS client connected")

        async def reader():
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                return
            except Exception:
                return

        reader_task = asyncio.create_task(reader())

        try:
            loop = asyncio.get_event_loop()
            while True:
                try:
                    event = await loop.run_in_executor(None, sub.get, True, 30)
                    await websocket.send_text(json.dumps(event))
                except queue.Empty:
                    try:
                        await websocket.send_text(json.dumps({"type": "ping", "data": {}, "timestamp": time.time()}))
                    except Exception:
                        break
                except Exception as e:
                    log.debug(f"WS send failed: {e}")
                    break
        finally:
            bus.unsubscribe(sub)
            reader_task.cancel()
            try:
                await websocket.close()
            except Exception:
                pass
            log.info("WS client disconnected")

    # ---- Static (React build) ----

    if os.path.isdir(WEB_DIST):
        assets_dir = os.path.join(WEB_DIST, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/")
        def root():
            index = os.path.join(WEB_DIST, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)
            return HTMLResponse(_fallback_html())

        @app.get("/{path:path}")
        def spa_catchall(path: str):
            # SPA routing: all unknown paths → index.html
            if path.startswith("api/") or path.startswith("ws/"):
                raise HTTPException(status_code=404)
            index = os.path.join(WEB_DIST, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)
            return HTMLResponse(_fallback_html())
    else:
        @app.get("/")
        def root_no_build():
            return HTMLResponse(_fallback_html())

    return app


def _update_schedule_status(daemon_ref, sched_id: int, status: str):
    from config import save_state
    tasks = daemon_ref.state.get("scheduled_tasks", [])
    for task in tasks:
        if task.get("id") == sched_id:
            task["status"] = status
            save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
            get_event_bus().publish("schedule.updated", task)
            return task
    raise HTTPException(status_code=404, detail="Schedule not found")


def _update_watch_status(daemon_ref, watch_id: int, status: str):
    from config import save_state
    watches = daemon_ref.state.get("watches", [])
    for watch in watches:
        if watch.get("id") == watch_id:
            watch["status"] = status
            save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
            get_event_bus().publish("watch.updated", watch)
            return watch
    raise HTTPException(status_code=404, detail="Watch not found")


def _fallback_html() -> str:
    return """<!doctype html>
<html><head><title>Bridge Gateway</title>
<style>body{font-family:-apple-system,sans-serif;max-width:600px;margin:80px auto;padding:0 20px;color:#333}
h1{color:#111}code{background:#f4f4f4;padding:2px 6px;border-radius:4px}</style></head>
<body>
<h1>⚡ Bridge Gateway is running</h1>
<p>The FastAPI backend is alive, but the React UI hasn't been built yet.</p>
<p>To build the UI:</p>
<pre><code>cd ~/.claude/imessage-bridge/web
pnpm install
pnpm build</code></pre>
<p>API endpoints are available at <code>/api/*</code>.</p>
<ul>
  <li><a href="/api/health">/api/health</a></li>
  <li><a href="/api/dashboard">/api/dashboard</a></li>
  <li><a href="/api/sessions">/api/sessions</a></li>
</ul>
</body></html>
"""


def start_gateway(session_manager, daemon_ref, port: int = 7777) -> threading.Thread:
    """Start uvicorn in a daemon thread. Non-blocking."""
    import uvicorn

    app = create_app(session_manager, daemon_ref)

    def run():
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        try:
            asyncio.run(server.serve())
        except Exception as e:
            log.error(f"Gateway crashed: {e}")

    thread = threading.Thread(target=run, daemon=True, name="gateway")
    thread.start()
    return thread
