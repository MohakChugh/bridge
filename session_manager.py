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
import session_store

log = logging.getLogger("session_manager")

MAX_HISTORY = 500


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
    queued_messages: list[str] = field(default_factory=list)

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
            "queued_count": len(self.queued_messages),
        }


class SessionManager:
    def __init__(self, config_provider: Callable[[], dict], max_parallel: int = 4):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._session_locks: dict[str, threading.RLock] = {}
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
            self._session_locks[sid] = threading.RLock()
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
            if len(session.message_history) > MAX_HISTORY:
                session.message_history = session.message_history[-MAX_HISTORY:]
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

            # Auto-inject memory context if enabled
            use_memory = session.meta.get("use_memory", config.get("auto_memory_inject", True))
            if use_memory:
                try:
                    from shared_memory import get_shared_memory, SIMILARITY_THRESHOLD
                    mem = get_shared_memory()
                    if mem.stats()["total_entries"] > 0:
                        collections = session.meta.get("persona_collections")
                        results = mem.search(prompt, collections=collections, limit=3)
                        relevant = [r for r in results if r["score"] > SIMILARITY_THRESHOLD]
                        if relevant:
                            context = "CONTEXT FROM SHARED MEMORY:\n"
                            for r in relevant:
                                context += f"- [{r['collection']}] {r['text'][:200]}\n"
                            context += "\nUSER REQUEST:\n"
                            prompt = context + prompt
                except Exception as e:
                    log.debug(f"Memory injection skipped: {e}")

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
            self._persist_session(session)

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
            self._persist_session(session)
            self._bus.publish("session.failed", {
                "id": session.id,
                "error": str(e),
            })

        # Drain queued messages
        sid = session.id
        while session.queued_messages:
            next_msg = session.queued_messages.pop(0)
            log.info(f"Draining queued message for session {sid}: {next_msg[:60]}")
            self.execute(sid, next_msg)
            break  # execute() spawns a new worker, which will drain next on its completion

    def _persist_session(self, session: Session) -> None:
        try:
            session_store.save_session(session.to_dict())
        except Exception as e:
            log.warning(f"Failed to persist session {session.id}: {e}")
        # Auto-ingest to shared memory
        if session.last_output and len(session.last_output) > 30:
            try:
                from shared_memory import get_shared_memory
                mem = get_shared_memory()
                summary = f"Session '{session.title}' ({session.tool}): {session.last_output[:400]}"
                mem.add(summary, collection="sessions", source="session",
                        metadata={"session_id": session.id, "tool": session.tool})
            except Exception as e:
                log.debug(f"Memory auto-ingest skipped: {e}")

    def persist_all(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                self._persist_session(session)

    def list_archived(self) -> list[dict]:
        active_ids = set(self._sessions.keys())
        return [s for s in session_store.load_sessions() if s.get("id") not in active_ids]

    def resume(self, archived_id: str) -> Optional[Session]:
        archived = session_store.get_session(archived_id)
        if not archived:
            return None
        session = Session(
            id=archived["id"],
            title=archived.get("title", "Resumed session"),
            tool=archived.get("tool", "wasabi"),
            cwd=archived.get("cwd", "/tmp"),
            status="idle",
            tool_session_id=archived.get("tool_session_id"),
            created_at=archived.get("created_at", time.time()),
            updated_at=time.time(),
            message_history=archived.get("message_history", []),
            last_output=archived.get("last_output"),
            last_error=None,
        )
        with self._lock:
            self._sessions[session.id] = session
            self._session_locks[session.id] = threading.RLock()
        self._bus.publish("session.resumed", session.to_dict())
        log.info(f"Session resumed: {session.id} ({session.title})")
        return session

    def delete_archived(self, sid: str) -> bool:
        return session_store.delete_session(sid)

    def snapshot(self) -> dict:
        with self._lock:
            sessions = [s.to_dict() for s in self._sessions.values()]
        busy = sum(1 for s in sessions if s["status"] == "busy")
        return {
            "total": len(sessions),
            "busy": busy,
            "sessions": sessions,
        }
