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


class ScheduleBody(BaseModel):
    text: str


class WatchBody(BaseModel):
    text: str


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

    # ---- Reminders / Schedules / Watches (read-only for now, via daemon state) ----

    @app.get("/api/reminders")
    def list_reminders():
        return {"reminders": daemon_ref.state.get("reminders", [])}

    @app.get("/api/schedules")
    def list_schedules():
        return {"schedules": daemon_ref.state.get("scheduled_tasks", [])}

    @app.get("/api/watches")
    def list_watches():
        return {"watches": daemon_ref.state.get("watches", [])}

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
