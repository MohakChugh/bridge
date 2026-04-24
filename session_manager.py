"""Multi-session manager for parallel execution.

Each Session has its own state, history, and execution thread. The manager
runs sessions concurrently up to `max_parallel` limit (semaphore).

Channels (iMessage, Slack) and the gateway API both go through SessionManager
to spawn and interact with sessions.
"""

from __future__ import annotations
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

from event_bus import get_event_bus

log = logging.getLogger("session_manager")


@dataclass
class Session:
    id: str
    title: str
    tool: str
    cwd: str
    status: str = "idle"  # idle | busy | completed | failed
    tool_session_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    message_history: list[dict] = field(default_factory=list)
    current_task: Optional[str] = None
    active_process: Optional[object] = None
    last_output: Optional[str] = None
    last_error: Optional[str] = None
    meta: dict = field(default_factory=dict)  # channel-specific (slack ctx, imessage guid)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "cwd": self.cwd,
            "status": self.status,
            "tool_session_id": self.tool_session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_history": list(self.message_history),
            "current_task": self.current_task,
            "last_output": self.last_output,
            "last_error": self.last_error,
            "meta": dict(self.meta) if self.meta else {},
        }


class SessionManager:
    def __init__(self, config_provider: Callable[[], dict], max_parallel: int = 4):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._session_locks: dict[str, threading.Lock] = {}
        self._semaphore = threading.Semaphore(max_parallel)
        self._config_provider = config_provider
        self._bus = get_event_bus()

    def create(self, tool: str, cwd: str, title: Optional[str] = None, meta: Optional[dict] = None) -> Session:
        sid = str(uuid.uuid4())
        title = title or f"{tool}:{os.path.basename(cwd.rstrip('/')) or 'session'}"
        session = Session(
            id=sid,
            title=title,
            tool=tool,
            cwd=cwd,
            meta=meta or {},
        )
        with self._lock:
            self._sessions[sid] = session
            self._session_locks[sid] = threading.Lock()
        self._bus.publish("session.created", session.to_dict())
        log.info(f"Session created: {sid} ({title})")
        return session

    def get(self, sid: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(sid)

    def list(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def delete(self, sid: str) -> bool:
        with self._lock:
            session = self._sessions.pop(sid, None)
            self._session_locks.pop(sid, None)
        if session:
            self._bus.publish("session.deleted", {"id": sid})
            log.info(f"Session deleted: {sid}")
            return True
        return False

    def update_title(self, sid: str, title: str) -> bool:
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return False
            session.title = title
            session.updated_at = time.time()
        self._bus.publish("session.updated", session.to_dict())
        return True

    def append_message(self, sid: str, role: str, text: str) -> None:
        with self._lock:
            session = self._sessions.get(sid)
            if not session:
                return
            entry = {"role": role, "text": text, "timestamp": time.time()}
            session.message_history.append(entry)
            session.updated_at = time.time()
        self._bus.publish("message.appended", {"session_id": sid, "message": entry})

    def cancel(self, sid: str) -> bool:
        with self._lock:
            session = self._sessions.get(sid)
        if not session or not session.active_process:
            return False
        try:
            session.active_process.kill()
            session.status = "idle"
            session.current_task = None
            session.active_process = None
            session.updated_at = time.time()
            self._bus.publish("session.cancelled", session.to_dict())
            log.info(f"Session cancelled: {sid}")
            return True
        except Exception as e:
            log.warning(f"Cancel failed for {sid}: {e}")
            return False

    def execute(self, sid: str, prompt: str, on_complete: Optional[Callable] = None) -> bool:
        """Execute prompt on session in background thread. Returns False if session not found."""
        session = self.get(sid)
        if not session:
            return False

        self.append_message(sid, "user", prompt)
        thread = threading.Thread(
            target=self._execute_worker,
            args=(sid, prompt, on_complete),
            daemon=True,
        )
        thread.start()
        return True

    def _execute_worker(self, sid: str, prompt: str, on_complete: Optional[Callable]) -> None:
        session = self.get(sid)
        if not session:
            return

        # Per-session serialization (same session can't run 2 prompts concurrently)
        # Different sessions run in parallel via semaphore
        with self._lock:
            session_lock = self._session_locks.get(sid)
        if not session_lock:
            return

        with session_lock:
            with self._semaphore:
                self._run_task(session, prompt, on_complete)

    def _run_task(self, session: Session, prompt: str, on_complete: Optional[Callable]) -> None:
        from adapters import get_adapter

        session.status = "busy"
        session.current_task = prompt[:80]
        session.updated_at = time.time()
        self._bus.publish("session.busy", session.to_dict())

        try:
            adapter = get_adapter(session.tool)
            config = self._config_provider()
            timeout = config.get("claude_p_timeout", 18000)

            # Hold process reference for cancel
            class ProcessHolder:
                _active_process = None

            holder = ProcessHolder()

            def poll_process():
                while session.status == "busy":
                    if holder._active_process:
                        session.active_process = holder._active_process
                        break
                    time.sleep(0.1)

            threading.Thread(target=poll_process, daemon=True).start()

            spawn_kwargs = dict(
                prompt=prompt,
                cwd=session.cwd,
                timeout=timeout,
                resume_session_id=session.tool_session_id,
                process_holder=holder,
                config=config,
            )
            # Pass history for adapters that support it (wasabi needs it)
            try:
                import inspect
                sig = inspect.signature(adapter.spawn)
                if "history" in sig.parameters:
                    spawn_kwargs["history"] = list(session.message_history)
            except Exception:
                pass

            result = adapter.spawn(**spawn_kwargs)

            session.active_process = None

            if result.get("success"):
                session.status = "completed"
                session.last_output = result.get("output", "")
                session.last_error = None
                if result.get("session_id"):
                    session.tool_session_id = result["session_id"]
                self.append_message(session.id, "assistant", result.get("output", ""))
                self._bus.publish("session.completed", {
                    "id": session.id,
                    "output": result.get("output", ""),
                })
            else:
                session.status = "failed"
                session.last_error = result.get("error", "Unknown error")
                self._bus.publish("session.failed", {
                    "id": session.id,
                    "error": session.last_error,
                })

            session.current_task = None
            session.updated_at = time.time()

            if on_complete:
                try:
                    on_complete(session, result)
                except Exception as e:
                    log.warning(f"on_complete callback error: {e}")

        except Exception as e:
            log.exception(f"Task execution failed for {session.id}")
            session.status = "failed"
            session.last_error = str(e)
            session.current_task = None
            session.active_process = None
            session.updated_at = time.time()
            self._bus.publish("session.failed", {
                "id": session.id,
                "error": str(e),
            })

    def snapshot(self) -> dict:
        """Dashboard snapshot — all sessions with summary."""
        with self._lock:
            sessions = [s.to_dict() for s in self._sessions.values()]
        busy = sum(1 for s in sessions if s["status"] == "busy")
        return {
            "total": len(sessions),
            "busy": busy,
            "sessions": sessions,
        }
