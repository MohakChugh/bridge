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
        return daemon_ref.config.get("directories", {})

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
        parsed = parse_schedule_via_llm(body.text, env, config=daemon_ref.config)
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
        limit = body.get("limit", 5)
        results = get_shared_memory().search(query, collections=collections, limit=limit)
        return {"results": results, "query": query}

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
        return {"id": doc_id, "name": name, "status": "registered"}

    @app.delete("/api/knowledge/documents/{doc_id}")
    def delete_kb_document(doc_id: str):
        from shared_memory import get_shared_memory
        get_shared_memory().delete_document(doc_id)
        return {"deleted": True}

    @app.post("/api/knowledge/documents/{doc_id}/refresh")
    def refresh_kb_document(doc_id: str):
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        doc = mem.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        mem.refresh_document(doc_id)
        # Re-ingest based on source type
        source_type = doc["source_type"]
        source_url = doc["source_url"]
        collection = doc["collection"]
        if source_type in ("file", "code"):
            if os.path.isdir(source_url):
                count = mem.import_directory(source_url, collection)
            elif os.path.isfile(source_url):
                count = mem.import_file(source_url, collection)
            else:
                count = 0
            mem.update_document_chunks(doc_id, count)
            return {"refreshed": True, "chunks": count}
        return {"refreshed": True, "chunks": 0, "note": "URL refresh requires ingestion pipeline"}

    @app.post("/api/knowledge/refresh-all")
    def refresh_all_kb():
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        results = []
        for doc in mem.list_documents():
            doc_id = doc["id"]
            mem.refresh_document(doc_id)
            source_type = doc["source_type"]
            source_url = doc["source_url"]
            collection = doc["collection"]
            count = 0
            if source_type in ("file", "code") and os.path.exists(source_url):
                if os.path.isdir(source_url):
                    count = mem.import_directory(source_url, collection)
                else:
                    count = mem.import_file(source_url, collection)
            mem.update_document_chunks(doc_id, count)
            results.append({"id": doc_id, "name": doc["name"], "chunks": count})
        return {"refreshed": len(results), "documents": results}

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
        daemon_ref.config["personas"] = [p for p in personas if p.get("name") != name]
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
        wf["schedules"] = [s for s in scheds if s.get("id") != sched_id]
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
