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
import uuid as _uuid_mod
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from event_bus import get_event_bus

log = logging.getLogger("gateway")

# Protects all read-modify-write operations on daemon_ref.state.
# FastAPI runs sync endpoints in a thread pool, so concurrent mutations
# (reminders, schedules, watches) can race.  An RLock is used so that
# helpers called from an endpoint that already holds the lock don't deadlock.
_STATE_LOCK = threading.RLock()

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
    tool: str = ""
    cwd: str = "/tmp"
    require_approval: bool = False
    variables: list = []
    nodes: list = []
    edges: list = []
    schedule: Optional[dict] = None
    schedules: list = []


class WorkflowApprovalBody(BaseModel):
    action: str  # "approve" | "abort"


class CRLoadBody(BaseModel):
    cr_id: str
    tool: Optional[str] = None


class CRCommentBody(BaseModel):
    file: str = ""
    line: int = 0
    content: str = ""
    question: str = ""


class ChatBody(BaseModel):
    message: str
    history: list = []


class ChatActionBody(BaseModel):
    action_type: str
    params: dict = {}


class DocCreateBody(BaseModel):
    path: str
    title: str
    content: str = ""
    tags: list = []
    collection: str = ""

class DocUpdateBody(BaseModel):
    content: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[list] = None

class DocMoveBody(BaseModel):
    new_parent: str

class DocRenameBody(BaseModel):
    new_name: str

class DocFolderBody(BaseModel):
    path: str

class DocGenerateBody(BaseModel):
    prompt: str
    insert_at: Optional[int] = None

class DocDiagramBody(BaseModel):
    prompt: str
    diagram_type: str = "mermaid"

class DocEditSelectionBody(BaseModel):
    selected_text: str
    line_start: int = 0
    line_end: int = 0
    feedback: str


class AgentTaskBody(BaseModel):
    title: str
    description: str
    mode: Optional[str] = None

class AgentModeBody(BaseModel):
    mode: str

class AgentMessageBody(BaseModel):
    text: str


def _build_refresh_workflow(docs: list[dict], daemon_ref) -> dict:
    """Build a deterministic refresh workflow — one ingest node per document, sequential."""
    import uuid as _uuid
    nodes = [{"id": "start", "type": "start", "position": {"x": 250, "y": 0}, "data": {}}]
    edges = []
    prev_id = "start"
    y = 150

    for i, doc in enumerate(docs):
        node_id = f"ingest-{doc['id'][:8]}"
        nodes.append({
            "id": node_id,
            "type": "ingest",
            "position": {"x": 250, "y": y},
            "data": {
                "source_url": doc["source_url"],
                "source_type": doc["source_type"],
                "collection": doc["collection"],
                "doc_id": doc["id"],
                "doc_name": doc["name"],
                "auto_dedup": False,
            },
        })
        edges.append({"id": f"e-{prev_id}-{node_id}", "source": prev_id, "target": node_id})
        prev_id = node_id
        y += 150

    notify_id = "notify-complete"
    nodes.append({
        "id": notify_id, "type": "notify", "position": {"x": 250, "y": y},
        "data": {"channel": "imessage", "message": f"Summarize the refresh results: how many documents were re-ingested, total chunks, tags, and graph edges created."},
    })
    edges.append({"id": f"e-{prev_id}-{notify_id}", "source": prev_id, "target": notify_id})
    y += 150

    nodes.append({"id": "end", "type": "end", "position": {"x": 250, "y": y}, "data": {}})
    edges.append({"id": f"e-{notify_id}-end", "source": notify_id, "target": "end"})

    is_single = len(docs) == 1
    name = f"Refresh: {docs[0]['name']}" if is_single else f"Refresh All ({len(docs)} docs)"
    metadata = {"_refresh": True}
    if is_single:
        metadata["_refresh_doc"] = docs[0]["id"]
    else:
        metadata["_refresh_all"] = True

    return {
        "name": name,
        "description": f"Re-ingest {len(docs)} document(s)",
        "tool": daemon_ref.config.get("cli_tool", "wasabi"),
        "cwd": daemon_ref.config["directories"].get("default", "/tmp"),
        "nodes": nodes,
        "edges": edges,
        "metadata": metadata,
    }


def _get_all_schedules(state: dict, workflows_path: str) -> list:
    """Merge legacy scheduled_tasks + workflow schedules. Used by dashboard + operations."""
    from workflow_store import load_workflows
    legacy = list(state.get("scheduled_tasks", []))
    wf_scheds = []
    try:
        for wf in load_workflows(workflows_path):
            for s in (wf.get("schedules") or []):
                wf_scheds.append({
                    "id": f"wf-{wf['id']}-{s.get('id', '')}",
                    "cron": s.get("cron"), "human": s.get("human"),
                    "prompt": wf.get("name", "workflow"),
                    "status": s.get("status", "active"),
                    "next_fire": s.get("next_fire"), "workflow_id": wf["id"],
                })
            single = wf.get("schedule")
            if single:
                wf_scheds.append({
                    "id": f"wf-{wf['id']}-legacy",
                    "cron": single.get("cron"), "human": single.get("human"),
                    "prompt": wf.get("name", "workflow"), "status": "active",
                    "next_fire": single.get("next_fire"), "workflow_id": wf["id"],
                })
    except Exception:
        pass
    return legacy + wf_scheds


def create_app(session_manager, daemon_ref, agent_brain=None) -> FastAPI:
    app = FastAPI(title="iMessage Bridge Gateway")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:7777"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from log_handler import set_correlation_id, clear_correlation_id

    @app.middleware("http")
    async def log_request_middleware(request, call_next):
        import time as _time
        from log_store import get_log_store

        cid = str(_uuid_mod.uuid4())[:8]
        set_correlation_id(cid)
        start = _time.time()

        # Read request body for non-WS, non-GET requests
        req_body = ""
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                req_body = body_bytes.decode("utf-8", errors="replace")[:10240]
                # Redact secrets
                import re as _re
                req_body = _re.sub(r'("(?:token|password|secret|api_key)":\s*)"[^"]*"', r'\1"[REDACTED]"', req_body)
            except Exception:
                pass

        response = await call_next(request)

        duration = (_time.time() - start) * 1000
        response.headers["X-Correlation-ID"] = cid

        # Don't log the /ws/events or /api/logs paths to avoid noise
        path = request.url.path
        if not path.startswith("/ws/") and not path.startswith("/api/logs"):
            try:
                get_log_store().write_request(
                    timestamp=start,
                    method=request.method,
                    path=path,
                    status=response.status_code,
                    duration_ms=round(duration, 2),
                    request_body=req_body,
                    response_body="",  # Can't easily read streaming response body
                    correlation_id=cid,
                )
            except Exception:
                pass

        clear_correlation_id()
        return response

    # ---- Config / metadata ----

    @app.get("/api/health")
    def health():
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/api/config")
    def get_config():
        from adapters import list_adapters
        cfg = daemon_ref.config
        return {
            "directories": cfg.get("directories", {}),
            "tools": list_adapters(),
            "active_tool": cfg.get("cli_tool", "claude"),
            "parsing_tool": cfg.get("parsing_tool", "claude"),
            "max_parallel_sessions": cfg.get("max_parallel_sessions", 4),
        }

    @app.get("/api/settings")
    def get_settings():
        from adapters import list_adapters, get_adapter
        cfg = daemon_ref.config
        tools_status = []
        for name in list_adapters():
            try:
                adapter = get_adapter(name)
                tools_status.append({"name": name, "available": adapter.is_available()})
            except Exception:
                tools_status.append({"name": name, "available": False})
        return {
            "cli_tool": cfg.get("cli_tool", "claude"),
            "parsing_tool": cfg.get("parsing_tool", "claude"),
            "max_parallel_sessions": cfg.get("max_parallel_sessions", 4),
            "gateway_port": cfg.get("gateway", {}).get("port", 7777),
            "slack_enabled": cfg.get("slack", {}).get("enabled", False),
            "imessage_enabled": getattr(daemon_ref, '_imessage_enabled', False),
            "tools": tools_status,
            "directories": cfg.get("directories", {}),
        }

    @app.post("/api/settings")
    def update_settings(body: dict):
        from config import save_config
        cfg = daemon_ref.config
        changed = []
        for key in ["cli_tool", "parsing_tool", "max_parallel_sessions"]:
            if key in body and body[key] != cfg.get(key):
                cfg[key] = body[key]
                changed.append(key)
        if changed:
            save_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), cfg)
            get_event_bus().publish("settings.changed", {"changed": changed})
        return {"saved": True, "changed": changed}

    @app.get("/api/tools")
    def list_tools():
        from adapters import list_adapters
        return {"tools": list_adapters(), "active": daemon_ref.config.get("cli_tool", "claude")}

    @app.get("/api/directories")
    def list_directories():
        """Return dynamically discovered workspaces + any config overrides."""
        import glob as _glob_mod

        discovered = {}

        # 1. Config overrides always included
        for k, v in daemon_ref.config.get("directories", {}).items():
            if os.path.isdir(v):
                discovered[k] = v

        # 2. Scan for Brazil workspaces (have packageInfo or .brazil/)
        scan_roots = [
            os.path.expanduser("~/workplace"),
            os.path.expanduser("~/workspaces"),
            "/Volumes/workplace",
            "/Volumes/workspace",
        ]
        for root in scan_roots:
            if not os.path.isdir(root):
                continue
            for entry in os.scandir(root):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                ws_path = entry.path
                # Brazil workspace: has packageInfo or .brazil/
                if os.path.exists(os.path.join(ws_path, "packageInfo")) or os.path.isdir(os.path.join(ws_path, ".brazil")):
                    label = entry.name
                    discovered[label] = ws_path
                    # Also add individual packages under src/
                    src_dir = os.path.join(ws_path, "src")
                    if os.path.isdir(src_dir):
                        for pkg in os.scandir(src_dir):
                            if pkg.is_dir() and not pkg.name.startswith("."):
                                discovered[f"{label}/{pkg.name}"] = pkg.path

        # 3. Scan for git repos in home
        home = os.path.expanduser("~")
        for candidate in ["projects", "repos", "code", "dev", "src", ".claude/imessage-bridge"]:
            cpath = os.path.join(home, candidate)
            if os.path.isdir(cpath):
                if os.path.isdir(os.path.join(cpath, ".git")):
                    discovered[candidate] = cpath
                else:
                    for entry in os.scandir(cpath):
                        if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
                            discovered[f"{candidate}/{entry.name}"] = entry.path

        # 4. CR workspaces
        bridge_dir = os.path.dirname(os.path.abspath(__file__))
        for entry in os.scandir(bridge_dir):
            if entry.is_dir() and entry.name.startswith("CR-"):
                discovered[entry.name] = entry.path

        # 5. Always include /tmp and home
        discovered.setdefault("tmp", "/tmp")
        discovered.setdefault("home", home)
        discovered.setdefault("bridge", bridge_dir)

        return dict(sorted(discovered.items()))

    # ---- Sessions ----

    @app.get("/api/sessions")
    def list_sessions():
        return {"sessions": [s.to_dict() for s in session_manager.list()]}

    @app.get("/api/sessions/archived")
    def list_archived_sessions():
        return {"sessions": session_manager.list_archived()}

    @app.post("/api/sessions/archived/{sid}/resume")
    def resume_archived_session(sid: str):
        session = session_manager.resume(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Archived session not found")
        return session.to_dict()

    @app.delete("/api/sessions/archived/{sid}")
    def delete_archived_session(sid: str):
        ok = session_manager.delete_archived(sid)
        if not ok:
            raise HTTPException(status_code=404, detail="Archived session not found")
        return {"deleted": True}

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
            session.queued_messages.append(body.text)
            get_event_bus().publish("session.message.queued", {"session_id": sid, "queue_depth": len(session.queued_messages)})
            return {"status": "queued", "queue_depth": len(session.queued_messages), "session_id": sid}
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
        # Backfill stable UUIDs for any legacy reminders that lack one
        dirty = False
        for r in reminders:
            if "id" not in r:
                r["id"] = str(_uuid_mod.uuid4())
                dirty = True
        if dirty:
            from config import save_state
            save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
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
            "id": str(_uuid_mod.uuid4()),
            "fire_at": body.fire_at_epoch,
            "message": body.message,
            "human": body.human or "",
        }
        with _STATE_LOCK:
            daemon_ref._reminders.append(reminder)
            daemon_ref.state.setdefault("reminders", []).append(reminder)
            from config import save_state
            save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("reminder.created", reminder)
        return reminder

    @app.delete("/api/reminders/{reminder_id}")
    def delete_reminder(reminder_id: str):
        with _STATE_LOCK:
            reminders = daemon_ref.state.get("reminders", [])
            idx = next((i for i, r in enumerate(reminders) if r.get("id") == reminder_id), -1)
            if idx < 0:
                raise HTTPException(status_code=404, detail="Reminder not found")
            reminders.pop(idx)
            daemon_ref._reminders = [r for r in daemon_ref._reminders if r.get("id") != reminder_id]
            from config import save_state
            save_state(os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"), daemon_ref.state)
        get_event_bus().publish("reminder.deleted", {"id": reminder_id})
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
        parsed = parse_schedule_via_llm(body.text, env, config=daemon_ref.config)
        if not parsed:
            raise HTTPException(status_code=400, detail="Could not parse schedule")
        return parsed

    @app.post("/api/schedules")
    def create_schedule(body: ScheduleDirectBody):
        import time as t
        from scheduler import next_cron_fire
        from config import save_state
        with _STATE_LOCK:
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
        with _STATE_LOCK:
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
        with _STATE_LOCK:
            watches = daemon_ref.state.setdefault("watches", [])
            watch_id = max([w.get("id", 0) for w in watches], default=0) + 1
            watch = {
                "id": watch_id,
                "target": body.get("target", ""),
                "type": body.get("check_type", "generic"),
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
        with _STATE_LOCK:
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
        watches = state.get("watches", [])
        all_schedules = _get_all_schedules(state, WORKFLOWS_PATH)
        active_schedules = [s for s in all_schedules if s.get("status") == "active"]
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
                "total": len(all_schedules),
                "active": active_schedules[:5],
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

    # ---- Code Review ----

    @app.post("/api/cr/pull")
    def pull_cr_endpoint(body: CRLoadBody):
        """Phase 1: Adapter checkout + static git diff. Returns files."""
        from code_review import pull_cr
        tool = body.tool or daemon_ref.config.get("cli_tool", "wasabi")
        result = pull_cr(body.cr_id, tool, daemon_ref.config, session_manager)
        return result

    @app.post("/api/cr/load-workspace")
    def load_workspace_endpoint(body: dict):
        """Load diff from an existing workspace (user ran cr-pull manually)."""
        from code_review import _extract_diff_static, parse_unified_diff
        workspace = body.get("workspace", "")
        cr_id = body.get("cr_id", "")
        if not os.path.isdir(workspace):
            raise HTTPException(status_code=400, detail=f"Workspace not found: {workspace}")
        packages, diff_text = _extract_diff_static(workspace)
        if not diff_text:
            raise HTTPException(status_code=400, detail="No diff found in workspace")
        files = parse_unified_diff(diff_text)
        return {"workspace": workspace, "packages": packages, "files": files, "raw_diff": diff_text, "cr_id": cr_id}

    @app.post("/api/cr/fetch-comments")
    def fetch_cr_comments_endpoint(body: dict):
        """Fetch existing CR comments via wasabi. Returns session_id to poll."""
        from code_review import fetch_cr_comments
        cr_id = body.get("cr_id", "")
        tool = body.get("tool") or daemon_ref.config.get("cli_tool", "wasabi")
        workspace = body.get("workspace", "")
        packages = body.get("packages", [])
        if not cr_id:
            raise HTTPException(status_code=400, detail="cr_id required")
        sid = fetch_cr_comments(cr_id, tool, workspace, packages, daemon_ref.config, session_manager)
        return {"session_id": sid}

    @app.post("/api/cr/parse-comments")
    def parse_cr_comments_endpoint(body: dict):
        """Parse raw CR comment output into structured format."""
        from code_review import parse_cr_comments_structured
        output = body.get("output", "")
        diff_files = body.get("diff_files", [])
        comments = parse_cr_comments_structured(output, diff_files)
        return {"comments": comments}

    @app.post("/api/cr/analyze")
    def analyze_cr_endpoint(body: dict):
        """Phase 2: Start parallel AI sessions for review, comments, build."""
        from code_review import start_analysis
        cr_id = body.get("cr_id", "")
        workspace = body.get("workspace", "")
        raw_diff = body.get("raw_diff", "")
        packages = body.get("packages", [])
        tool = body.get("tool") or daemon_ref.config.get("cli_tool", "wasabi")
        if not workspace or not raw_diff:
            raise HTTPException(status_code=400, detail="workspace and raw_diff required")
        sessions = start_analysis(cr_id, workspace, raw_diff, packages, tool, daemon_ref.config, session_manager)
        return {"sessions": sessions}

    @app.post("/api/cr/comment")
    def cr_comment_endpoint(body: dict):
        """Each comment = own session. Returns session_id to poll."""
        from code_review import spawn_comment_session
        tool = body.get("tool") or daemon_ref.config.get("cli_tool", "wasabi")
        sid = spawn_comment_session(
            cr_id=body.get("cr_id", ""),
            workspace=body.get("workspace", ""),
            packages=body.get("packages", []),
            tool=tool,
            file_path=body.get("file", ""),
            line_num=body.get("line", 0),
            line_content=body.get("content", ""),
            question=body.get("question", ""),
            config=daemon_ref.config,
            session_manager=session_manager,
        )
        return {"session_id": sid}

    @app.post("/api/cr/chat")
    def cr_chat_endpoint(body: dict):
        """General CR question = own session."""
        from code_review import spawn_chat_session
        tool = body.get("tool") or daemon_ref.config.get("cli_tool", "wasabi")
        sid = spawn_chat_session(
            cr_id=body.get("cr_id", ""),
            workspace=body.get("workspace", ""),
            packages=body.get("packages", []),
            tool=tool,
            question=body.get("question", ""),
            config=daemon_ref.config,
            session_manager=session_manager,
        )
        return {"session_id": sid}

    @app.get("/api/cr/session/{session_id}")
    def cr_session_status(session_id: str):
        """Poll any CR session for result."""
        from code_review import get_session_result
        return get_session_result(session_id, session_manager)

    @app.delete("/api/cr/cleanup")
    def cleanup_cr_endpoint(body: dict):
        """Delete all sessions + workspace."""
        from code_review import cleanup_cr
        cleanup_cr(
            workspace=body.get("workspace", ""),
            session_ids=body.get("session_ids", []),
            session_manager=session_manager,
        )
        return {"deleted": True}

    # ---- RAG Chat ----

    @app.post("/api/chat")
    def chat_endpoint(body: ChatBody):
        from rag_chat import chat
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="message required")
        result = chat(
            query=body.message.strip(),
            history=body.history[-6:],
            config=daemon_ref.config,
            session_manager=session_manager,
            daemon_ref=daemon_ref,
        )
        get_event_bus().publish("chat.message", {
            "query": body.message[:100],
            "has_sources": len(result.get("sources", [])) > 0,
        })
        return result

    @app.post("/api/chat/execute")
    def chat_execute(body: ChatActionBody):
        from rag_chat import execute_action
        result = execute_action(
            action_type=body.action_type,
            params=body.params,
            config=daemon_ref.config,
            session_manager=session_manager,
            daemon_ref=daemon_ref,
        )
        return result

    # ---- Shared Memory ----

    @app.get("/api/memory/collections")
    def list_memory_collections():
        from shared_memory import get_shared_memory
        return {"collections": get_shared_memory().list_collections()}

    @app.post("/api/memory/collections")
    def create_memory_collection(body: dict):
        from shared_memory import get_shared_memory
        name = body.get("name", "")
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        cid = get_shared_memory().create_collection(name, body.get("description", ""))
        return {"id": cid, "name": name}

    @app.delete("/api/memory/collections/{name}")
    def delete_memory_collection(name: str):
        from shared_memory import get_shared_memory
        ok = get_shared_memory().delete_collection(name)
        if not ok:
            raise HTTPException(status_code=404, detail="Collection not found")
        return {"deleted": True}

    @app.post("/api/memory/search")
    def search_memory(body: dict):
        from shared_memory import get_shared_memory
        query = body.get("query", "")
        if not query:
            raise HTTPException(status_code=400, detail="query required")
        collections = body.get("collections")
        limit = body.get("limit", 10)
        tags_filter = body.get("tags")
        results = get_shared_memory().search(query, collections=collections, limit=limit * 3)
        # Post-filter by tags if specified
        if tags_filter and isinstance(tags_filter, list):
            filtered = []
            for r in results:
                entry_tags = []
                try:
                    entry_tags = json.loads(r.get("metadata", "{}")).get("tags", [])
                except Exception:
                    pass
                if not entry_tags:
                    try:
                        entry_tags = json.loads(r.get("tags", "[]"))
                    except Exception:
                        pass
                if any(t in entry_tags for t in tags_filter):
                    filtered.append(r)
            results = filtered
        return {"results": results[:limit], "query": query}

    @app.post("/api/memory/add")
    def add_to_memory(body: dict):
        from shared_memory import get_shared_memory
        text = body.get("text", "")
        collection = body.get("collection", "")
        if not text or not collection:
            raise HTTPException(status_code=400, detail="text and collection required")
        mid = get_shared_memory().add(text, collection, metadata=body.get("metadata"), source=body.get("source", "manual"))
        return {"id": mid}

    @app.delete("/api/memory/{mid}")
    def delete_memory_entry(mid: int):
        from shared_memory import get_shared_memory
        ok = get_shared_memory().delete(mid)
        if not ok:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"deleted": True}

    @app.get("/api/memory/stats")
    def memory_stats():
        from shared_memory import get_shared_memory
        return get_shared_memory().stats()

    @app.get("/api/memory/entries/{collection}")
    def list_memory_entries(collection: str):
        from shared_memory import get_shared_memory
        return {"entries": get_shared_memory().list_entries(collection)}

    @app.post("/api/memory/import")
    def import_to_memory(body: dict):
        from shared_memory import get_shared_memory
        path = body.get("path", "")
        collection = body.get("collection", "")
        if not path or not collection:
            raise HTTPException(status_code=400, detail="path and collection required")
        if os.path.isdir(path):
            count = get_shared_memory().import_directory(path, collection)
        elif os.path.isfile(path):
            count = get_shared_memory().import_file(path, collection)
        else:
            raise HTTPException(status_code=400, detail="Path not found")
        return {"imported": count}

    # ---- Knowledge Base ----

    @app.get("/api/knowledge/documents")
    def list_kb_documents():
        from shared_memory import get_shared_memory
        return {"documents": get_shared_memory().list_documents()}

    @app.get("/api/knowledge/documents/{doc_id}/delete-preview")
    def preview_document_deletion(doc_id: str):
        """Returns what will be deleted if this document is removed."""
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        doc = mem.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        chunk_count = mem.db.execute("SELECT COUNT(*) FROM memories WHERE document_id = ?", (doc_id,)).fetchone()[0]
        edge_count = mem.db.execute("SELECT COUNT(*) FROM edges WHERE source_id IN (SELECT id FROM memories WHERE document_id = ?) OR target_id IN (SELECT id FROM memories WHERE document_id = ?)", (doc_id, doc_id)).fetchone()[0]
        collection = doc.get("collection", "")
        coll_docs = [d for d in mem.list_documents() if d.get("collection") == collection]
        coll_remaining_chunks = sum(d.get("chunk_count", 0) or 0 for d in coll_docs if d["id"] != doc_id)
        return {
            "doc_id": doc_id,
            "name": doc.get("name"),
            "source_url": doc.get("source_url"),
            "chunks_to_delete": chunk_count,
            "edges_to_delete": edge_count,
            "collection": collection,
            "collection_remaining_chunks": coll_remaining_chunks,
            "collection_remaining_docs": len(coll_docs) - 1,
        }

    @app.post("/api/knowledge/documents")
    def register_kb_document(body: dict):
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        name = body.get("name", "")
        source_type = body.get("source_type", "file")
        source_url = body.get("source_url", "")
        collection = body.get("collection", "default")
        tags = body.get("tags", [])
        persona = body.get("persona")
        if not name or not source_url:
            raise HTTPException(status_code=400, detail="name and source_url required")
        doc_id = mem.register_document(name, source_type, source_url, collection, tags, persona)
        # Trigger async ingestion
        import threading
        def _ingest():
            try:
                from knowledge_ingestion import ingest_document
                result = ingest_document(doc_id, daemon_ref.config)
                log.info(f"Ingested document {name}: {result}")
            except Exception as e:
                log.warning(f"Ingestion failed for {name}: {e}")
        threading.Thread(target=_ingest, daemon=False).start()
        return {"id": doc_id, "name": name, "status": "ingesting"}

    @app.delete("/api/knowledge/documents/{doc_id}")
    def delete_kb_document(doc_id: str):
        from shared_memory import get_shared_memory
        ok = get_shared_memory().delete_document(doc_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True}

    @app.delete("/api/knowledge/purge")
    def purge_all_kb():
        from shared_memory import get_shared_memory
        result = get_shared_memory().purge_all()
        log.info(f"Purged all knowledge: {result}")
        return {"purged": True, **result}

    @app.post("/api/knowledge/documents/{doc_id}/refresh")
    def refresh_kb_document(doc_id: str):
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        doc = mem.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        import threading
        def _refresh():
            try:
                from knowledge_ingestion import ingest_document
                result = ingest_document(doc_id, daemon_ref.config)
                log.info(f"Refreshed {doc['name']}: {result}")
            except Exception as e:
                log.warning(f"Refresh failed: {e}")
        threading.Thread(target=_refresh, daemon=False).start()
        return {"refreshed": True, "status": "refreshing"}

    @app.post("/api/knowledge/documents/{doc_id}/refresh-workflow")
    def refresh_kb_document_workflow(doc_id: str):
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        doc = mem.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        wf = _build_refresh_workflow([doc], daemon_ref)
        existing = next((w for w in load_workflows(WORKFLOWS_PATH) if w.get("metadata", {}).get("_refresh_doc") == doc_id), None)
        if existing:
            wf["id"] = existing["id"]
        saved = upsert_workflow(WORKFLOWS_PATH, wf)
        wf_run = wf_engine.run(saved)
        return {"workflow_id": saved["id"], "run_id": wf_run.id, "workflow": saved}

    @app.post("/api/knowledge/refresh-all")
    def refresh_all_kb():
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        docs = mem.list_documents()
        import threading
        from knowledge_ingestion import ingest_document
        for doc in docs:
            def _refresh_one(d=doc):
                try:
                    result = ingest_document(d["id"], daemon_ref.config)
                    log.info(f"Ingested {d['name']}: {result}")
                except Exception as e:
                    log.warning(f"Refresh failed for {d['name']}: {e}")
            threading.Thread(target=_refresh_one, daemon=True).start()
        return {"refreshing": len(docs), "status": "started_parallel"}

    @app.post("/api/knowledge/refresh-all-parallel")
    def refresh_all_parallel(body: dict = {}):
        parallelism = min(max(body.get("parallelism", 3) if body else 3, 1), 10)
        from knowledge_ingestion import start_parallel_refresh
        job = start_parallel_refresh(parallelism, daemon_ref.config)
        return {"job_id": job["id"], "total": job["total"], "cleaned": job["cleaned"], "status": "running"}

    @app.get("/api/knowledge/refresh-status/{job_id}")
    def refresh_status_endpoint(job_id: str):
        from knowledge_ingestion import get_refresh_status
        return get_refresh_status(job_id)

    @app.post("/api/knowledge/refresh-all-workflow")
    def refresh_all_kb_workflow():
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        docs = mem.list_documents()
        if not docs:
            return {"workflows": [], "message": "No documents to refresh"}
        wf = _build_refresh_workflow(docs, daemon_ref)
        existing = next((w for w in load_workflows(WORKFLOWS_PATH) if w.get("metadata", {}).get("_refresh_all")), None)
        if existing:
            wf["id"] = existing["id"]
        saved = upsert_workflow(WORKFLOWS_PATH, wf)
        wf_run = wf_engine.run(saved)
        return {"workflow_id": saved["id"], "run_id": wf_run.id, "workflow": saved}

    @app.get("/api/knowledge/ingestion-status")
    def get_ingestion_status():
        """Snapshot of current ingestion activity.

        Returns aggregate stats and recent events.
        The UI should prefer the WebSocket event stream for real-time updates;
        this endpoint is for initial page load + fallback.
        """
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        docs = mem.list_documents()
        total_docs = len(docs)
        total_chunks = sum(d.get("chunk_count", 0) or 0 for d in docs)

        collections_map = {}
        for d in docs:
            coll = d.get("collection", "default")
            if coll not in collections_map:
                collections_map[coll] = {"name": coll, "doc_count": 0, "chunk_count": 0, "last_refreshed": 0}
            collections_map[coll]["doc_count"] += 1
            collections_map[coll]["chunk_count"] += d.get("chunk_count", 0) or 0
            lr = d.get("last_refreshed") or 0
            if lr > collections_map[coll]["last_refreshed"]:
                collections_map[coll]["last_refreshed"] = lr

        return {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "collections": list(collections_map.values()),
        }

    @app.get("/api/knowledge/tags")
    def list_kb_tags():
        from shared_memory import get_shared_memory
        return {"tags": get_shared_memory().list_tags()}

    @app.get("/api/knowledge/graph")
    def get_kb_graph():
        from shared_memory import get_shared_memory
        return get_shared_memory().get_graph()

    @app.post("/api/knowledge/graph/edges")
    def create_kb_edge(body: dict):
        from shared_memory import get_shared_memory
        source_id = body.get("source_id")
        target_id = body.get("target_id")
        relation = body.get("relation", "related")
        if not source_id or not target_id:
            raise HTTPException(status_code=400, detail="source_id and target_id required")
        eid = get_shared_memory().create_edge(source_id, target_id, relation)
        return {"id": eid}

    @app.delete("/api/knowledge/graph/edges/{eid}")
    def delete_kb_edge(eid: int):
        from shared_memory import get_shared_memory
        ok = get_shared_memory().delete_edge(eid)
        if not ok:
            raise HTTPException(status_code=404, detail="Edge not found")
        return {"deleted": True}

    # ---- Knowledge Discovery ----

    @app.post("/api/knowledge/discover")
    def start_discovery(body: dict):
        from knowledge_discovery import DiscoveryJob, discover_and_ingest, _persist_job
        from shared_memory import get_shared_memory
        import uuid as _uuid

        target = body.get("target", "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="target is required")

        tool = body.get("tool") or daemon_ref.config.get("parsing_tool", "wasabi")
        scope = body.get("scope", [])
        collection = body.get("collection") or target.lower().replace(" ", "-")
        auto_ingest = body.get("auto_ingest", False)
        instructions = body.get("instructions", "")

        job = DiscoveryJob(
            id=str(_uuid.uuid4())[:8],
            target=target, tool=tool, scope=scope,
            collection=collection, status="pending",
            auto_ingest=auto_ingest, instructions=instructions,
            discovered=[], new_links=[], skipped=[], ingested=[], errors=[],
            started_at=time.time(), completed_at=None,
            progress="Starting discovery...",
        )
        _persist_job(job)

        def _run():
            mem = get_shared_memory()
            discover_and_ingest(job, daemon_ref.config, mem)

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job.id, "status": "started", "target": target}

    @app.get("/api/knowledge/discover")
    def list_discovery_jobs():
        from knowledge_discovery import list_jobs
        return {"jobs": list_jobs()}

    @app.get("/api/knowledge/discover/{job_id}")
    def get_discovery_job(job_id: str):
        from knowledge_discovery import get_job
        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Discovery job not found")
        from dataclasses import asdict
        return asdict(job)

    @app.post("/api/knowledge/discover/{job_id}/ingest")
    def ingest_from_discovery(job_id: str, body: dict):
        from knowledge_discovery import get_job
        from shared_memory import get_shared_memory
        from knowledge_ingestion import ingest_document

        job = get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Discovery job not found")

        selected_urls = set(body.get("urls", []))
        if not selected_urls:
            raise HTTPException(status_code=400, detail="urls list required")

        mem = get_shared_memory()
        collection = job.collection
        ingested = []

        for link in job.new_links:
            if link["url"] in selected_urls:
                doc_id = mem.register_document(
                    name=link["name"],
                    source_type=link["source_type"],
                    source_url=link["url"],
                    collection=collection,
                    tags=link.get("tags", []),
                )
                threading.Thread(
                    target=ingest_document, args=(doc_id, daemon_ref.config),
                    daemon=True,
                ).start()
                ingested.append({"doc_id": doc_id, **link})

        return {"ingested": len(ingested), "links": ingested}

    @app.post("/api/knowledge/dedup-check")
    def dedup_check(body: dict):
        from knowledge_discovery import dedup
        from shared_memory import get_shared_memory

        urls = body.get("urls", [])
        if not urls:
            raise HTTPException(status_code=400, detail="urls list required")
        links = [{"url": u, "source_type": "web", "name": u} for u in urls]
        new_links, skipped = dedup(links, get_shared_memory())
        return {"new": [l["url"] for l in new_links], "existing": [l["url"] for l in skipped]}

    @app.post("/api/knowledge/discover-workflow")
    def start_discovery_workflow(body: dict):
        from knowledge_discovery import build_discovery_workflow_prompt
        from workflow_generator import generate_workflow

        target = body.get("target", "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="target is required")

        tool = body.get("tool") or daemon_ref.config.get("cli_tool", "wasabi")
        scope = body.get("scope", [])
        collection = body.get("collection") or target.lower().replace(" ", "-")
        instructions = body.get("instructions", "")

        prompt_text = build_discovery_workflow_prompt(
            target=target, tool=tool, scope=scope,
            collection=collection, instructions=instructions,
        )

        wf = generate_workflow(prompt_text, tool=tool, cwd=daemon_ref.config["directories"].get("default", "/tmp"), config=daemon_ref.config)
        if not wf:
            raise HTTPException(status_code=500, detail="Failed to generate discovery workflow")

        wf["name"] = f"Discover: {target}"
        wf["description"] = f"AI discovery for {target}"
        wf.setdefault("metadata", {})["_discovery"] = True
        wf.setdefault("metadata", {})["target"] = target
        wf.setdefault("metadata", {})["collection"] = collection
        for i, node in enumerate(wf.get("nodes", [])):
            node["position"] = {"x": 250, "y": i * 150}

        # Upsert by target+collection — reuse existing discovery workflow
        existing = next(
            (w for w in load_workflows(WORKFLOWS_PATH)
             if w.get("metadata", {}).get("_discovery") and
                w.get("metadata", {}).get("target") == target and
                w.get("metadata", {}).get("collection") == collection),
            None,
        )
        if existing:
            wf["id"] = existing["id"]
        saved = upsert_workflow(WORKFLOWS_PATH, wf)
        wf_run = wf_engine.run(saved)

        return {"workflow_id": saved["id"], "run_id": wf_run.id, "workflow": saved}

    # ---- Personas ----

    @app.get("/api/personas")
    def list_personas():
        return {"personas": daemon_ref.config.get("personas", [])}

    @app.post("/api/personas")
    def create_persona(body: dict):
        from config import save_config
        personas = daemon_ref.config.setdefault("personas", [])
        persona = {
            "name": body.get("name", "New Persona"),
            "system_prompt": body.get("system_prompt", ""),
            "collections": body.get("collections", []),
            "tool": body.get("tool", daemon_ref.config.get("cli_tool", "wasabi")),
        }
        personas.append(persona)
        save_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), daemon_ref.config)
        return persona

    @app.delete("/api/personas/{name}")
    def delete_persona(name: str):
        from config import save_config
        personas = daemon_ref.config.get("personas", [])
        new_personas = [p for p in personas if p.get("name") != name]
        if len(new_personas) == len(personas):
            raise HTTPException(status_code=404, detail="Persona not found")
        daemon_ref.config["personas"] = new_personas
        save_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), daemon_ref.config)
        return {"deleted": True}

    @app.post("/api/variables/resolve")
    def resolve_variables_endpoint(body: dict):
        from variable_resolver import resolve_variables
        variables = body.get("variables", [])
        overrides = body.get("overrides", {})
        return {"resolved": resolve_variables(variables, overrides)}

    @app.post("/api/workflows/generate")
    def generate_workflow_endpoint(body: dict):
        from workflow_generator import generate_workflow
        text = body.get("text", "")
        tool = body.get("tool", daemon_ref.config.get("cli_tool", "wasabi"))
        cwd = body.get("cwd", daemon_ref.config["directories"].get("default", "/tmp"))
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        wf = generate_workflow(text, tool=tool, cwd=cwd, config=daemon_ref.config)
        if not wf:
            raise HTTPException(status_code=500, detail="Failed to generate workflow")
        return wf

    @app.post("/api/workflows/{wf_id}/refine")
    def refine_workflow_endpoint(wf_id: str, body: dict):
        from workflow_generator import refine_workflow
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        feedback = body.get("feedback", "")
        if not feedback:
            raise HTTPException(status_code=400, detail="feedback is required")
        node_id = body.get("node_id")
        scope = body.get("scope", "node_and_downstream")
        refined = refine_workflow(wf, feedback, node_id=node_id, scope=scope, config=daemon_ref.config)
        if not refined:
            raise HTTPException(status_code=500, detail="Failed to refine workflow")
        refined["id"] = wf_id
        upsert_workflow(WORKFLOWS_PATH, refined)
        old_node_ids = {n["id"] for n in wf.get("nodes", [])}
        new_node_ids = {n["id"] for n in refined.get("nodes", [])}
        diff = {
            "added": list(new_node_ids - old_node_ids),
            "removed": list(old_node_ids - new_node_ids),
            "changed": [n["id"] for n in refined["nodes"] if n["id"] in old_node_ids],
        }
        return {"workflow": refined, "diff": diff}

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
    def run_workflow(wf_id: str, body: dict = {}):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        params = body.get("params") if isinstance(body, dict) else None
        schedule_label = body.get("schedule_label") if isinstance(body, dict) else None
        wf_run = wf_engine.run(wf, params=params, schedule_label=schedule_label)
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

    @app.get("/api/workflows/{wf_id}/schedules")
    def list_workflow_schedules(wf_id: str):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"schedules": wf.get("schedules", [])}

    @app.post("/api/workflows/{wf_id}/schedules")
    def add_workflow_schedule(wf_id: str, body: dict):
        import uuid as _uuid
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        from scheduler import next_cron_fire
        cron = body.get("cron", "")
        if not cron:
            raise HTTPException(status_code=400, detail="cron is required")
        sched = {
            "id": str(_uuid.uuid4())[:8],
            "label": body.get("label", "Schedule"),
            "cron": cron,
            "human": body.get("human", cron),
            "params": body.get("params", {}),
            "next_fire": next_cron_fire(cron),
            "status": "active",
        }
        wf.setdefault("schedules", []).append(sched)
        upsert_workflow(WORKFLOWS_PATH, wf)
        return sched

    @app.delete("/api/workflows/{wf_id}/schedules/{sched_id}")
    def delete_workflow_schedule(wf_id: str, sched_id: str):
        wf = _get_wf(WORKFLOWS_PATH, wf_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        scheds = wf.get("schedules", [])
        new_scheds = [s for s in scheds if s.get("id") != sched_id]
        if len(new_scheds) == len(scheds):
            raise HTTPException(status_code=404, detail="Schedule not found")
        wf["schedules"] = new_scheds
        upsert_workflow(WORKFLOWS_PATH, wf)
        return {"deleted": True}

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
            parsed = parse_schedule_via_llm(text, env, config=daemon_ref.config)
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

    @app.get("/api/workflows/{wf_id}/runs/{run_id}/artifacts")
    def list_run_artifacts(wf_id: str, run_id: str):
        return {"artifacts": wf_engine.list_artifacts(run_id)}

    @app.get("/api/artifacts/{run_id}/{filename}")
    def get_artifact(run_id: str, filename: str):
        path = wf_engine.get_artifact_path(run_id, filename)
        if not path:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(path, filename=filename)

    @app.get("/api/workflows/{wf_id}/analytics")
    def workflow_analytics(wf_id: str):
        from collections import Counter
        from datetime import datetime
        runs = wf_engine.list_runs(wf_id)
        if not runs:
            return {"total_runs": 0, "success_rate": 0, "avg_duration_seconds": 0, "runs_by_day": [], "failure_reasons": [], "param_distribution": {}}

        total = len(runs)
        success = sum(1 for r in runs if r.status == "completed")
        durations = [r.completed_at - r.started_at for r in runs if r.completed_at and r.started_at]
        avg_dur = sum(durations) / len(durations) if durations else 0

        last_fail = None
        for r in sorted(runs, key=lambda x: x.started_at, reverse=True):
            if r.status == "failed":
                errors = [ns.error for ns in r.node_states.values() if ns.error]
                last_fail = {"run_id": r.id, "error": errors[0] if errors else "unknown", "when": r.started_at}
                break

        by_day: dict[str, dict] = {}
        for r in runs:
            day = datetime.fromtimestamp(r.started_at).strftime("%Y-%m-%d")
            if day not in by_day:
                by_day[day] = {"date": day, "success": 0, "failed": 0}
            if r.status == "completed":
                by_day[day]["success"] += 1
            elif r.status in ("failed", "aborted"):
                by_day[day]["failed"] += 1

        error_counter: Counter = Counter()
        for r in runs:
            if r.status == "failed":
                for ns in r.node_states.values():
                    if ns.error:
                        error_counter[ns.error[:80]] += 1

        param_dist: dict[str, Counter] = {}
        for r in runs:
            for k, v in (r.params or {}).items():
                if k not in param_dist:
                    param_dist[k] = Counter()
                param_dist[k][str(v)] += 1

        return {
            "total_runs": total,
            "success_rate": round(success / total * 100) if total else 0,
            "avg_duration_seconds": round(avg_dur),
            "last_failure": last_fail,
            "runs_by_day": sorted(by_day.values(), key=lambda x: x["date"]),
            "failure_reasons": [{"error": e, "count": c} for e, c in error_counter.most_common(10)],
            "param_distribution": {k: dict(v) for k, v in param_dist.items()},
        }

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
                "total": len(_get_all_schedules(state, WORKFLOWS_PATH)),
                "active": [s for s in _get_all_schedules(state, WORKFLOWS_PATH) if s.get("status") == "active"],
            },
            "reminders": {
                "total": len(state.get("reminders", [])),
            },
            "timestamp": time.time(),
        }

    # ---- Log Store API ----

    @app.get("/api/logs")
    def query_logs(
        level: str = None, logger: str = None, since: float = None, until: float = None,
        q: str = None, correlation_id: str = None, source: str = None,
        limit: int = 200, offset: int = 0,
    ):
        from log_store import get_log_store
        result = get_log_store().query_logs(
            level=level, logger=logger, since=since, until=until,
            q=q, correlation_id=correlation_id, source=source,
            limit=limit, offset=offset,
        )
        return result

    @app.delete("/api/logs")
    def clear_logs():
        from log_store import get_log_store
        get_log_store().clear()
        return {"cleared": True}

    @app.post("/api/logs/frontend")
    def receive_frontend_log(body: dict):
        from log_store import get_log_store
        import time as _time
        get_log_store().write_log(
            timestamp=body.get("timestamp", _time.time()),
            level=body.get("level", "ERROR"),
            logger=body.get("component", "frontend"),
            message=body.get("message", ""),
            data=json.dumps({"stack": body.get("stack", ""), "user_action": body.get("user_action", ""), "url": body.get("url", "")}),
            correlation_id=None,
            source="frontend",
        )
        return {"stored": True}

    @app.get("/api/logs/requests")
    def query_requests_log(
        method: str = None, path: str = None,
        status_min: int = None, status_max: int = None,
        since: float = None, until: float = None,
        correlation_id: str = None,
        limit: int = 200, offset: int = 0,
    ):
        from log_store import get_log_store
        result = get_log_store().query_requests(
            method=method, path=path, status_min=status_min, status_max=status_max,
            since=since, until=until, correlation_id=correlation_id,
            limit=limit, offset=offset,
        )
        return result

    @app.get("/api/logs/events")
    def query_events_log(
        type: str = None, since: float = None, until: float = None,
        limit: int = 200, offset: int = 0,
    ):
        from log_store import get_log_store
        result = get_log_store().query_events(
            type_pattern=type, since=since, until=until,
            limit=limit, offset=offset,
        )
        return result

    @app.get("/api/logs/stats")
    def log_stats():
        from log_store import get_log_store
        return get_log_store().stats()

    @app.get("/api/logs/correlation/{correlation_id}")
    def correlation_trace(correlation_id: str):
        from log_store import get_log_store
        store = get_log_store()
        logs = store.query_logs(correlation_id=correlation_id, limit=500)
        reqs = store.query_requests(correlation_id=correlation_id, limit=50)
        evts = store.query_events(limit=0)  # Events don't have correlation_id
        return {"logs": logs["rows"], "requests": reqs["rows"], "events": []}

    # ---- Agent Brain ----

    @app.post("/api/agent/tasks")
    def create_agent_task(body: AgentTaskBody):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        task = agent_brain.create_task(body.title, body.description, body.mode)
        return task

    @app.get("/api/agent/tasks")
    def list_agent_tasks(status: Optional[str] = None, limit: int = 20):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        return {"tasks": agent_brain.list_tasks(status=status, limit=limit)}

    @app.get("/api/agent/tasks/{task_id}")
    def get_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        task = agent_brain.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.post("/api/agent/tasks/{task_id}/approve")
    def approve_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        ok = agent_brain.approve(task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="No pending approval for this task")
        return {"approved": True}

    @app.post("/api/agent/tasks/{task_id}/reject")
    def reject_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        ok = agent_brain.reject(task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="No pending approval for this task")
        return {"rejected": True}

    @app.post("/api/agent/tasks/{task_id}/cancel")
    def cancel_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        agent_brain.cancel(task_id)
        return {"cancelled": True}

    @app.post("/api/agent/tasks/{task_id}/pause")
    def pause_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        agent_brain.pause(task_id)
        return {"paused": True}

    @app.post("/api/agent/tasks/{task_id}/resume")
    def resume_agent_task(task_id: str):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        agent_brain.resume(task_id)
        return {"resumed": True}

    @app.post("/api/agent/tasks/{task_id}/message")
    def send_agent_message(task_id: str, body: AgentMessageBody):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        task = agent_brain.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.get("status") not in ("running", "waiting_approval", "paused"):
            raise HTTPException(status_code=400, detail=f"Task not messageable (status: {task.get('status')})")
        msgs = task.get("messages") or []
        if isinstance(msgs, str):
            import json as _j
            try: msgs = _j.loads(msgs)
            except: msgs = []
        msgs.append({"role": "user", "content": body.text})
        task["messages"] = msgs
        agent_brain._store.save_task(task)
        get_event_bus().publish("agent.message.received", {"task_id": task_id, "text": body.text})
        return {"sent": True, "task_id": task_id}

    @app.get("/api/agent/mode")
    def get_agent_mode():
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        return {"mode": agent_brain.get_mode()}

    @app.post("/api/agent/mode")
    def set_agent_mode(body: AgentModeBody):
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        if body.mode not in ("safe", "yellow"):
            raise HTTPException(status_code=400, detail="Mode must be 'safe' or 'yellow'")
        agent_brain.set_mode(body.mode)
        return {"mode": body.mode}

    @app.get("/api/agent/status")
    def get_agent_status():
        if not agent_brain:
            raise HTTPException(status_code=503, detail="Agent not enabled")
        tasks = agent_brain.list_tasks()
        by_status = {}
        for t in tasks:
            s = t["status"]
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "enabled": True,
            "mode": agent_brain.get_mode(),
            "total_tasks": len(tasks),
            "by_status": by_status,
        }

    # ---- Document Generation Studio ----

    @app.get("/api/docs")
    def list_docs():
        from doc_store import get_doc_store
        return {"documents": get_doc_store().list_all()}

    @app.get("/api/docs/tree")
    def get_doc_tree():
        from doc_store import get_doc_store
        return {"tree": get_doc_store().get_tree()}

    @app.post("/api/docs")
    def create_doc(body: DocCreateBody):
        from doc_store import get_doc_store
        try:
            doc = get_doc_store().create(body.path, body.title, body.content, body.tags, body.collection)
        except FileExistsError:
            raise HTTPException(status_code=409, detail="Document already exists")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return doc

    @app.post("/api/docs/folder")
    def create_doc_folder(body: DocFolderBody):
        from doc_store import get_doc_store
        get_doc_store().create_folder(body.path)
        return {"created": True}

    @app.post("/api/docs/{doc_id:path}/generate")
    def generate_doc(doc_id: str, body: DocGenerateBody):
        from doc_store import get_doc_store
        doc = get_doc_store().read(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        generation_id = str(_uuid_mod.uuid4())[:8]
        import threading as _thr
        def _gen():
            from doc_gen import generate_content
            generate_content(doc_id, generation_id, body.prompt, doc["content"], body.insert_at, daemon_ref.config)
        _thr.Thread(target=_gen, daemon=True).start()
        return {"generation_id": generation_id, "doc_id": doc_id}

    @app.post("/api/docs/{doc_id:path}/diagram")
    def generate_doc_diagram(doc_id: str, body: DocDiagramBody):
        from doc_store import get_doc_store
        if not get_doc_store().read(doc_id):
            raise HTTPException(status_code=404, detail="Document not found")
        diagram_id = str(_uuid_mod.uuid4())[:8]
        import threading as _thr
        def _dia():
            from doc_gen import generate_diagram
            generate_diagram(doc_id, diagram_id, body.prompt, daemon_ref.config)
        _thr.Thread(target=_dia, daemon=True).start()
        return {"diagram_id": diagram_id}

    @app.post("/api/docs/{doc_id:path}/edit-selection")
    def edit_doc_selection(doc_id: str, body: DocEditSelectionBody):
        from doc_store import get_doc_store
        from doc_gen import edit_selection
        store = get_doc_store()
        doc = store.read(doc_id)
        if not doc:
            raise HTTPException(status_code=404)
        generation_id = str(_uuid_mod.uuid4())[:8]
        edit_selection(
            doc_id=doc_id,
            generation_id=generation_id,
            selected_text=body.selected_text,
            line_start=body.line_start,
            line_end=body.line_end,
            feedback=body.feedback,
            full_content=doc["content"],
            config=daemon_ref.config,
        )
        return {"generation_id": generation_id, "doc_id": doc_id}

    @app.post("/api/docs/{doc_id:path}/upload-image")
    async def upload_doc_image(doc_id: str, file: UploadFile):
        from doc_store import get_doc_store
        store = get_doc_store()
        doc = store.read(doc_id)
        if not doc:
            raise HTTPException(status_code=404)

        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename")

        # Sanitize filename
        import re
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename)
        safe_name = f"img-{str(_uuid_mod.uuid4())[:6]}-{safe_name}"

        data = await file.read()
        if len(data) > 10 * 1024 * 1024:  # 10MB limit
            raise HTTPException(status_code=413, detail="File too large (max 10MB)")

        url = store.save_asset(doc_id, safe_name, data)
        return {"url": url, "filename": safe_name}

    @app.post("/api/docs/{doc_id:path}/save-to-memory")
    def save_doc_to_memory(doc_id: str):
        from doc_store import get_doc_store
        from shared_memory import get_shared_memory

        store = get_doc_store()
        doc = store.read(doc_id)
        if not doc:
            raise HTTPException(status_code=404)

        mem = get_shared_memory()

        # Register as a knowledge base document
        kb_doc_id = mem.register_document(
            name=doc["title"],
            source_type="file",
            source_url=f"docs/{doc['path']}",
            collection="docs",
            tags=doc.get("frontmatter", {}).get("tags", []),
        )

        # Ingest the content
        from knowledge_ingestion import ingest_document
        result = ingest_document(kb_doc_id, daemon_ref.config)

        get_event_bus().publish("doc.saved_to_memory", {
            "doc_id": doc_id, "kb_doc_id": kb_doc_id,
            "chunks": result.get("chunks", 0),
        })

        return {
            "kb_doc_id": kb_doc_id,
            "chunks": result.get("chunks", 0),
            "status": "indexed",
        }

    @app.post("/api/docs/{doc_id:path}/rename")
    def rename_doc(doc_id: str, body: DocRenameBody):
        from doc_store import get_doc_store
        try:
            return get_doc_store().rename(doc_id, body.new_name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Document not found")

    @app.post("/api/docs/{doc_id:path}/move")
    def move_doc(doc_id: str, body: DocMoveBody):
        from doc_store import get_doc_store
        try:
            return get_doc_store().move(doc_id, body.new_parent)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Document not found")

    @app.get("/api/docs/assets/{doc_id:path}/{filename}")
    def serve_doc_asset(doc_id: str, filename: str):
        from doc_store import get_doc_store
        path = get_doc_store().get_asset_path(doc_id, filename)
        if not path:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(path, filename=filename)

    @app.get("/api/docs/{doc_id:path}")
    def get_doc(doc_id: str):
        from doc_store import get_doc_store
        doc = get_doc_store().read(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc

    @app.patch("/api/docs/{doc_id:path}")
    def update_doc(doc_id: str, body: DocUpdateBody):
        from doc_store import get_doc_store
        store = get_doc_store()
        if not store.read(doc_id):
            raise HTTPException(status_code=404, detail="Document not found")
        return store.update(doc_id, content=body.content, title=body.title, tags=body.tags)

    @app.delete("/api/docs/{doc_id:path}")
    def delete_doc(doc_id: str):
        from doc_store import get_doc_store
        if not get_doc_store().delete(doc_id):
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True}

    # ---- Calendar ----

    @app.get("/api/calendar")
    def list_calendar_events(start: str = "", end: str = ""):
        import datetime as _dt
        from workflow_store import WORKFLOWS_PATH as _WF_PATH
        events = []
        for sched in _get_all_schedules(daemon_ref.state, _WF_PATH):
            nf = sched.get("next_fire")
            if nf:
                dt = _dt.datetime.fromtimestamp(nf)
                date_str = dt.strftime("%Y-%m-%d")
                if start and date_str < start:
                    continue
                if end and date_str > end:
                    continue
                events.append({
                    "id": sched.get("id", ""),
                    "title": sched.get("prompt", "Schedule"),
                    "start": date_str,
                    "event_type": "schedule",
                    "confidence": 1.0,
                    "source_message_id": "",
                    "subject": sched.get("human", ""),
                    "from_addr": "bridge",
                })
        return events

    @app.get("/api/calendar/export.ics")
    def export_calendar_ics(start: str = "", end: str = ""):
        from fastapi.responses import Response
        events = list_calendar_events(start=start, end=end)
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bridge//EN"]
        for ev in events:
            lines += [
                "BEGIN:VEVENT",
                f"UID:{ev['id']}@bridge",
                f"DTSTART;VALUE=DATE:{ev['start'].replace('-', '')}",
                f"SUMMARY:{ev['title']}",
                f"DESCRIPTION:{ev['subject']}",
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        return Response(content="\r\n".join(lines), media_type="text/calendar")

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
                    bus._touch(sub)
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
    with _STATE_LOCK:
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
    with _STATE_LOCK:
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


def start_gateway(session_manager, daemon_ref, port: int = 7777, agent_brain=None) -> threading.Thread:
    """Start uvicorn in a daemon thread. Non-blocking."""
    import uvicorn

    app = create_app(session_manager, daemon_ref, agent_brain=agent_brain)

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
