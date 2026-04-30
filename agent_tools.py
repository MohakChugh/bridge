"""Tool registry and implementations for the Agent Brain.

Each tool wraps existing system calls (SessionManager, SharedMemory,
WorkflowEngine, etc.) behind a uniform interface that the Anthropic
tool_use API can invoke.
"""

from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

log = logging.getLogger("agent_tools")

MAX_OUTPUT = 4000


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 20] + "\n...[truncated]"


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------

@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict  # JSON Schema for tool_use format
    func: Callable[..., str]
    needs_approval: bool = False
    always_confirm: bool = False  # even in yellow mode


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return tool.func(**args)

    def to_tool_defs(self) -> list[dict]:
        """Format for Anthropic tool_use API."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in self._tools.values()
        ]

    def describe_all(self) -> str:
        lines = []
        for t in self._tools.values():
            props = t.parameters.get("properties", {})
            params = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in props.items())
            lines.append(f"- {t.name}({params}): {t.description}")
        return "\n".join(lines)

    def names(self) -> list[str]:
        return list(self._tools.keys())


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

_ALLOWED_PREFIXES: tuple[str, ...] = ()


def _init_sandbox_prefixes():
    global _ALLOWED_PREFIXES
    bridge_dir = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude", "imessage-bridge"))
    # /tmp often symlinks to /private/tmp on macOS — include realpath of both
    tmp_real = os.path.realpath("/tmp")
    _ALLOWED_PREFIXES = (bridge_dir, "/tmp", tmp_real)


def _check_sandbox(path: str) -> str:
    """Return realpath if inside sandbox, else raise ValueError."""
    if not _ALLOWED_PREFIXES:
        _init_sandbox_prefixes()
    real = os.path.realpath(os.path.expanduser(path))
    for prefix in _ALLOWED_PREFIXES:
        if real.startswith(prefix):
            return real
    raise ValueError(
        f"Access denied: path '{path}' is outside the sandbox. "
        f"Only paths under ~/.claude/imessage-bridge/ and /tmp/ are allowed."
    )


# ---------------------------------------------------------------------------
# build_tool_registry
# ---------------------------------------------------------------------------

def build_tool_registry(
    session_manager,
    daemon_ref,
    config_provider: Callable[[], dict],
    agent_store,
) -> ToolRegistry:
    """Build and return a fully-populated ToolRegistry."""

    from event_bus import get_event_bus
    bus = get_event_bus()
    registry = ToolRegistry()

    # -----------------------------------------------------------------------
    # Information tools (needs_approval=False)
    # -----------------------------------------------------------------------

    # 1. memory_search
    def memory_search(query: str, collections: str = None, limit: int = 5) -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            coll_list = None
            if collections:
                coll_list = [c.strip() for c in collections.split(",") if c.strip()]
            results = mem.search(query, collections=coll_list, limit=limit)
            if not results:
                return "No results found."
            lines = [f"Search results for '{query}' ({len(results)} hits):"]
            for r in results:
                lines.append(
                    f"  [{r['collection']}] (score: {r['score']:.2f}) "
                    f"{r['text'][:200]}"
                )
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error searching memory: {e}"

    registry.register(AgentTool(
        name="memory_search",
        description="Search shared memory for relevant context.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "collections": {
                    "type": "string",
                    "description": "Comma-separated collection names to search (optional)",
                },
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
        func=memory_search,
    ))

    # 2. system_status
    def system_status() -> str:
        try:
            parts = []
            # Sessions
            sessions = session_manager.list()
            busy = sum(1 for s in sessions if s.status == "busy")
            parts.append(f"Sessions: {len(sessions)} total, {busy} busy")

            # Workflows
            try:
                from workflow_engine import WorkflowEngine
                # Access workflow runs via daemon_ref if available
                if daemon_ref and hasattr(daemon_ref, "state"):
                    wf_list = daemon_ref.state.get("workflows", [])
                    parts.append(f"Workflows: {len(wf_list)} defined")
            except Exception:
                parts.append("Workflows: unavailable")

            # Watches
            if daemon_ref and hasattr(daemon_ref, "state"):
                watches = daemon_ref.state.get("watches", [])
                parts.append(f"Watches: {len(watches)} active")

                schedules = daemon_ref.state.get("scheduled_tasks", [])
                parts.append(f"Schedules: {len(schedules)} active")

                reminders = daemon_ref.state.get("reminders", [])
                parts.append(f"Reminders: {len(reminders)} pending")
            else:
                parts.append("Watches/Schedules/Reminders: daemon ref not available")

            # Memory stats
            try:
                from shared_memory import get_shared_memory
                mem = get_shared_memory()
                stats = mem.stats()
                parts.append(
                    f"Memory: {stats['total_entries']} entries, "
                    f"{len(stats['collections'])} collections, "
                    f"{stats['db_size_bytes'] // 1024}KB"
                )
            except Exception:
                parts.append("Memory: unavailable")

            return "\n".join(parts)
        except Exception as e:
            return f"Error getting system status: {e}"

    registry.register(AgentTool(
        name="system_status",
        description="Get overview of system status: sessions, workflows, watches, schedules, reminders, memory stats.",
        parameters={"type": "object", "properties": {}},
        func=system_status,
    ))

    # 3. check_session
    def check_session(session_id: str) -> str:
        try:
            session = session_manager.get(session_id)
            if not session:
                return f"Session {session_id} not found."
            d = session.to_dict()
            lines = [
                f"Session: {d['id']}",
                f"Title: {d['title']}",
                f"Tool: {d['tool']}",
                f"Status: {d['status']}",
                f"Messages: {len(d['message_history'])}",
                f"Current task: {d.get('current_task') or 'none'}",
            ]
            if d.get("last_output"):
                lines.append(f"Last output:\n{d['last_output'][:2000]}")
            if d.get("last_error"):
                lines.append(f"Last error: {d['last_error']}")
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error checking session: {e}"

    registry.register(AgentTool(
        name="check_session",
        description="Check status, last output, and message count for a session.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to check"},
            },
            "required": ["session_id"],
        },
        func=check_session,
    ))

    # 4. check_workflow
    def check_workflow(run_id: str) -> str:
        try:
            from workflow_engine import WorkflowEngine
            # Try to get workflow engine from daemon_ref
            engine = None
            if daemon_ref and hasattr(daemon_ref, "_workflow_engine"):
                engine = daemon_ref._workflow_engine
            if not engine:
                # Build a lightweight reference
                engine = WorkflowEngine(session_manager, config_provider, daemon_ref)
            wf_run = engine.get_run(run_id)
            if not wf_run:
                return f"Workflow run {run_id} not found."
            d = wf_run.to_dict()
            lines = [
                f"Run: {d['id']}",
                f"Workflow: {d['workflow_name']} ({d['workflow_id']})",
                f"Status: {d['status']}",
            ]
            for nid, ns in d.get("node_states", {}).items():
                status = ns.get("status", "?")
                output = (ns.get("output") or "")[:120]
                error = ns.get("error") or ""
                entry = f"  {nid}: {status}"
                if output:
                    entry += f" — {output}"
                if error:
                    entry += f" [ERROR: {error}]"
                lines.append(entry)
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error checking workflow: {e}"

    registry.register(AgentTool(
        name="check_workflow",
        description="Check workflow run status and node states.",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Workflow run ID"},
            },
            "required": ["run_id"],
        },
        func=check_workflow,
    ))

    # 5. list_documents
    def list_documents() -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            docs = mem.list_documents()
            if not docs:
                return "No documents registered."
            lines = [f"Documents ({len(docs)}):"]
            for doc in docs:
                name = doc.get("name", "?")
                stype = doc.get("source_type", "?")
                chunks = doc.get("chunk_count", 0)
                coll = doc.get("collection", "?")
                lines.append(f"  [{doc.get('id', '?')}] {name} ({stype}) — {chunks} chunks in '{coll}'")
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error listing documents: {e}"

    registry.register(AgentTool(
        name="list_documents",
        description="List registered documents with names, types, and chunk counts.",
        parameters={"type": "object", "properties": {}},
        func=list_documents,
    ))

    # 6. list_sessions
    def list_sessions() -> str:
        try:
            sessions = session_manager.list()
            if not sessions:
                return "No active sessions."
            lines = [f"Active sessions ({len(sessions)}):"]
            for s in sessions:
                d = s.to_dict()
                lines.append(
                    f"  [{d['id'][:8]}...] {d['title']} — {d['status']} "
                    f"({d['tool']}, {len(d['message_history'])} msgs)"
                )
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error listing sessions: {e}"

    registry.register(AgentTool(
        name="list_sessions",
        description="List active sessions with titles and statuses.",
        parameters={"type": "object", "properties": {}},
        func=list_sessions,
    ))

    # 7. read_file
    def read_file(path: str) -> str:
        try:
            real = _check_sandbox(path)
            if not os.path.isfile(real):
                return f"File not found: {path}"
            with open(real) as f:
                content = f.read()
            return _truncate(content)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error reading file: {e}"

    registry.register(AgentTool(
        name="read_file",
        description="Read a file. SANDBOXED: only ~/.claude/imessage-bridge/ and /tmp/ paths allowed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
        func=read_file,
    ))

    # 8. list_files
    def list_files(path: str, pattern: str = None) -> str:
        try:
            real = _check_sandbox(path)
            if not os.path.isdir(real):
                return f"Not a directory: {path}"
            entries = sorted(os.listdir(real))
            if pattern:
                import fnmatch
                entries = [e for e in entries if fnmatch.fnmatch(e, pattern)]
            lines = [f"Directory: {path} ({len(entries)} entries)"]
            for e in entries:
                full = os.path.join(real, e)
                kind = "dir" if os.path.isdir(full) else "file"
                size = os.path.getsize(full) if os.path.isfile(full) else 0
                lines.append(f"  {e} ({kind}, {size}B)")
            return _truncate("\n".join(lines))
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error listing files: {e}"

    registry.register(AgentTool(
        name="list_files",
        description="List directory contents. SANDBOXED: only ~/.claude/imessage-bridge/ and /tmp/ paths allowed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "pattern": {"type": "string", "description": "Glob pattern to filter (optional)"},
            },
            "required": ["path"],
        },
        func=list_files,
    ))

    # 9. update_progress
    def update_progress(task_id: str, message: str, percent: int = None) -> str:
        try:
            task = agent_store.get_task(task_id)
            if not task:
                return f"Task {task_id} not found."
            task["progress_msg"] = message
            if percent is not None:
                task["progress_pct"] = max(0, min(100, percent))
            agent_store.save_task(task)
            bus.publish("agent.task.progress", {
                "task_id": task_id,
                "message": message,
                "percent": task.get("progress_pct", 0),
            })
            return f"Progress updated: {message} ({task.get('progress_pct', 0)}%)"
        except Exception as e:
            return f"Error updating progress: {e}"

    registry.register(AgentTool(
        name="update_progress",
        description="Update progress on an agent task (message and optional percent).",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to update"},
                "message": {"type": "string", "description": "Progress message"},
                "percent": {"type": "integer", "description": "Progress percentage 0-100 (optional)"},
            },
            "required": ["task_id", "message"],
        },
        func=update_progress,
    ))

    # -----------------------------------------------------------------------
    # Action tools (needs_approval=True)
    # -----------------------------------------------------------------------

    # 10. spawn_session
    def spawn_session(tool: str, prompt: str, cwd: str = "/tmp") -> str:
        try:
            session = session_manager.create(tool=tool, cwd=cwd, title=f"Agent: {prompt[:50]}")
            session_manager.execute(session.id, prompt)
            return f"Session spawned: {session.id} (tool={tool}, cwd={cwd})"
        except Exception as e:
            return f"Error spawning session: {e}"

    registry.register(AgentTool(
        name="spawn_session",
        description="Create a new session and send it a prompt.",
        parameters={
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "CLI tool to use (claude, wasabi, kiro)"},
                "prompt": {"type": "string", "description": "Prompt to send to the session"},
                "cwd": {"type": "string", "description": "Working directory", "default": "/tmp"},
            },
            "required": ["tool", "prompt"],
        },
        func=spawn_session,
        needs_approval=True,
    ))

    # 11. wait_for_session
    def wait_for_session(session_id: str, timeout: int = 600) -> str:
        try:
            start = time.time()
            last_status = ""
            while time.time() - start < timeout:
                session = session_manager.get(session_id)
                if not session:
                    return f"Session {session_id} not found."
                status = session.status
                if status != last_status:
                    bus.publish("agent.session.poll", {
                        "session_id": session_id,
                        "status": status,
                        "elapsed": int(time.time() - start),
                    })
                    last_status = status
                if status == "completed":
                    output = session.last_output or "(no output)"
                    return _truncate(f"Session completed.\n\n{output}")
                if status == "failed":
                    error = session.last_error or "Unknown error"
                    output = session.last_output or ""
                    return _truncate(f"Session failed: {error}\n\n{output}")
                if status == "idle" and session.last_output:
                    # Session finished between polls
                    return _truncate(f"Session idle (completed).\n\n{session.last_output}")
                time.sleep(5)
            return f"Timeout after {timeout}s. Session status: {last_status}"
        except Exception as e:
            return f"Error waiting for session: {e}"

    registry.register(AgentTool(
        name="wait_for_session",
        description="Poll a session until it completes or fails, returning the output.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to wait on"},
                "timeout": {"type": "integer", "description": "Max wait in seconds", "default": 600},
            },
            "required": ["session_id"],
        },
        func=wait_for_session,
        needs_approval=True,
    ))

    # 12. send_to_session
    def send_to_session(session_id: str, message: str) -> str:
        try:
            session = session_manager.get(session_id)
            if not session:
                return f"Session {session_id} not found."
            ok = session_manager.execute(session_id, message)
            if ok:
                return f"Message sent to session {session_id}."
            return f"Failed to send message to session {session_id}."
        except Exception as e:
            return f"Error sending to session: {e}"

    registry.register(AgentTool(
        name="send_to_session",
        description="Send a follow-up message to an existing session.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Target session ID"},
                "message": {"type": "string", "description": "Message to send"},
            },
            "required": ["session_id", "message"],
        },
        func=send_to_session,
        needs_approval=True,
    ))

    # 13. run_workflow
    def run_workflow(workflow_id: str) -> str:
        try:
            from workflow_engine import WorkflowEngine
            # Find the workflow definition
            workflows = []
            if daemon_ref and hasattr(daemon_ref, "state"):
                workflows = daemon_ref.state.get("workflows", [])
            wf_def = None
            for wf in workflows:
                if wf.get("id") == workflow_id:
                    wf_def = wf
                    break
            if not wf_def:
                return f"Workflow '{workflow_id}' not found."

            engine = None
            if daemon_ref and hasattr(daemon_ref, "_workflow_engine"):
                engine = daemon_ref._workflow_engine
            if not engine:
                engine = WorkflowEngine(session_manager, config_provider, daemon_ref)

            wf_run = engine.run(wf_def)
            return f"Workflow started: run_id={wf_run.id}, name='{wf_run.workflow_name}'"
        except Exception as e:
            return f"Error running workflow: {e}"

    registry.register(AgentTool(
        name="run_workflow",
        description="Trigger a workflow run by workflow ID.",
        parameters={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Workflow ID to run"},
            },
            "required": ["workflow_id"],
        },
        func=run_workflow,
        needs_approval=True,
    ))

    # 14. wait_for_workflow
    def wait_for_workflow(run_id: str, timeout: int = 600) -> str:
        try:
            from workflow_engine import WorkflowEngine
            engine = None
            if daemon_ref and hasattr(daemon_ref, "_workflow_engine"):
                engine = daemon_ref._workflow_engine
            if not engine:
                engine = WorkflowEngine(session_manager, config_provider, daemon_ref)

            start = time.time()
            last_status = ""
            while time.time() - start < timeout:
                wf_run = engine.get_run(run_id)
                if not wf_run:
                    return f"Workflow run {run_id} not found."
                status = wf_run.status
                if status != last_status:
                    bus.publish("agent.workflow.poll", {
                        "run_id": run_id,
                        "status": status,
                        "elapsed": int(time.time() - start),
                    })
                    last_status = status
                if status == "completed":
                    d = wf_run.to_dict()
                    lines = [f"Workflow completed: {d['workflow_name']}"]
                    for nid, ns in d.get("node_states", {}).items():
                        output = (ns.get("output") or "")[:200]
                        if output:
                            lines.append(f"  {nid}: {output}")
                    return _truncate("\n".join(lines))
                if status in ("failed", "aborted"):
                    d = wf_run.to_dict()
                    lines = [f"Workflow {status}: {d['workflow_name']}"]
                    for nid, ns in d.get("node_states", {}).items():
                        if ns.get("error"):
                            lines.append(f"  {nid}: ERROR — {ns['error']}")
                    return _truncate("\n".join(lines))
                time.sleep(5)
            return f"Timeout after {timeout}s. Workflow status: {last_status}"
        except Exception as e:
            return f"Error waiting for workflow: {e}"

    registry.register(AgentTool(
        name="wait_for_workflow",
        description="Poll a workflow run until it completes, fails, or times out.",
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Workflow run ID to wait on"},
                "timeout": {"type": "integer", "description": "Max wait in seconds", "default": 600},
            },
            "required": ["run_id"],
        },
        func=wait_for_workflow,
        needs_approval=True,
    ))

    # 15. memory_add
    def memory_add(text: str, collection: str, metadata: str = None) -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            meta_dict = None
            if metadata:
                try:
                    meta_dict = json.loads(metadata)
                except json.JSONDecodeError:
                    meta_dict = {"raw": metadata}
            mid = mem.add(text, collection=collection, metadata=meta_dict, source="agent")
            return f"Added to '{collection}' (memory_id={mid}). Text: {text[:100]}"
        except Exception as e:
            return f"Error adding to memory: {e}"

    registry.register(AgentTool(
        name="memory_add",
        description="Add a text entry to shared memory in a given collection.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text content to store"},
                "collection": {"type": "string", "description": "Collection name"},
                "metadata": {"type": "string", "description": "JSON metadata string (optional)"},
            },
            "required": ["text", "collection"],
        },
        func=memory_add,
        needs_approval=True,
    ))

    # 16. register_document
    def register_document(name: str, source_type: str, source_url: str, collection: str) -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            doc_id = mem.register_document(
                name=name,
                source_type=source_type,
                source_url=source_url,
                collection=collection,
            )
            return f"Document registered: doc_id={doc_id}, name='{name}', collection='{collection}'"
        except Exception as e:
            return f"Error registering document: {e}"

    registry.register(AgentTool(
        name="register_document",
        description="Register a new document for ingestion into the knowledge base.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Document name"},
                "source_type": {"type": "string", "description": "Source type: wiki, code, quip, web, or file"},
                "source_url": {"type": "string", "description": "URL or path to the document"},
                "collection": {"type": "string", "description": "Target collection name"},
            },
            "required": ["name", "source_type", "source_url", "collection"],
        },
        func=register_document,
        needs_approval=True,
    ))

    # 17. refresh_document
    def refresh_document(doc_id: str) -> str:
        try:
            from shared_memory import get_shared_memory
            from knowledge_ingestion import ingest_document
            mem = get_shared_memory()
            doc = mem.get_document(doc_id)
            if not doc:
                return f"Document {doc_id} not found."
            mem.refresh_document(doc_id)
            config = config_provider()
            result = ingest_document(doc_id, config)
            chunks = result.get("chunks", 0)
            return f"Document '{doc.get('name', doc_id)}' refreshed: {chunks} chunks ingested."
        except Exception as e:
            return f"Error refreshing document: {e}"

    registry.register(AgentTool(
        name="refresh_document",
        description="Clear old chunks and re-ingest a document.",
        parameters={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document ID to refresh"},
            },
            "required": ["doc_id"],
        },
        func=refresh_document,
        needs_approval=True,
    ))

    # 18. create_reminder
    def create_reminder(message: str, fire_at_epoch: float) -> str:
        try:
            import uuid
            reminder = {
                "id": str(uuid.uuid4())[:8],
                "message": message,
                "fire_at": fire_at_epoch,
                "created_at": time.time(),
            }
            if daemon_ref and hasattr(daemon_ref, "state"):
                daemon_ref.state.setdefault("reminders", []).append(reminder)
                if hasattr(daemon_ref, "_reminders"):
                    daemon_ref._reminders.append(reminder)
                # Persist state
                try:
                    from config import save_state, STATE_PATH
                    save_state(STATE_PATH, daemon_ref.state)
                except Exception:
                    pass
                from datetime import datetime
                fire_str = datetime.fromtimestamp(fire_at_epoch).strftime("%b %d %I:%M %p")
                return f"Reminder created (id={reminder['id']}): '{message}' at {fire_str}"
            return "Error: daemon reference not available for reminders."
        except Exception as e:
            return f"Error creating reminder: {e}"

    registry.register(AgentTool(
        name="create_reminder",
        description="Create a timed reminder that fires at a specific epoch timestamp.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Reminder message"},
                "fire_at_epoch": {"type": "number", "description": "Unix timestamp when reminder should fire"},
            },
            "required": ["message", "fire_at_epoch"],
        },
        func=create_reminder,
        needs_approval=True,
    ))

    # 19. send_notification
    def send_notification(message: str) -> str:
        try:
            if daemon_ref and hasattr(daemon_ref, "_reply"):
                daemon_ref._reply(message)
                return f"Notification sent via iMessage: {message[:100]}"
            return "Error: daemon _reply not available. Cannot send notification."
        except Exception as e:
            return f"Error sending notification: {e}"

    registry.register(AgentTool(
        name="send_notification",
        description="Send a notification message to the user via iMessage.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification message to send"},
            },
            "required": ["message"],
        },
        func=send_notification,
        needs_approval=True,
    ))

    # 20. discover
    def _discover(target: str, collection: str = None) -> str:
        try:
            from knowledge_discovery import DiscoveryJob, discover_and_ingest
            from shared_memory import get_shared_memory
            import uuid

            mem = get_shared_memory()
            config = config_provider()
            coll = collection or target.lower().replace(" ", "-")
            tool = config.get("cli_tool", "wasabi")

            job = DiscoveryJob(
                id=str(uuid.uuid4())[:8],
                target=target,
                tool=tool,
                scope=[],
                collection=coll,
                auto_ingest=True,
            )
            result = discover_and_ingest(job, config, mem)
            new_count = len(result.ingested)
            skip_count = len(result.skipped)
            total = len(result.discovered)
            lines = [
                f"Discovery completed for '{target}'.",
                f"Found: {total} resources",
                f"New ingested: {new_count}",
                f"Skipped (already known): {skip_count}",
            ]
            if result.errors:
                lines.append(f"Errors: {len(result.errors)}")
                for err in result.errors[:3]:
                    lines.append(f"  - {err[:150]}")
            return _truncate("\n".join(lines))
        except Exception as e:
            return f"Error running discovery: {e}"

    registry.register(AgentTool(
        name="discover",
        description="Start a knowledge discovery job for a target topic. Finds and ingests relevant docs.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Topic or target to discover knowledge about"},
                "collection": {"type": "string", "description": "Collection to ingest into (optional, defaults to target)"},
            },
            "required": ["target"],
        },
        func=_discover,
        needs_approval=True,
    ))

    # -----------------------------------------------------------------------
    # Red-line tools (always_confirm=True)
    # -----------------------------------------------------------------------

    # 21. purge_knowledge
    def purge_knowledge() -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            result = mem.purge_all()
            return (
                f"Knowledge base purged. Deleted: "
                f"{result['memories']} memories, {result['documents']} documents, "
                f"{result['collections']} collections, {result['edges']} edges."
            )
        except Exception as e:
            return f"Error purging knowledge: {e}"

    registry.register(AgentTool(
        name="purge_knowledge",
        description="DESTRUCTIVE: Purge all data from the shared knowledge base.",
        parameters={"type": "object", "properties": {}},
        func=purge_knowledge,
        needs_approval=True,
        always_confirm=True,
    ))

    # 22. delete_document
    def delete_document(doc_id: str) -> str:
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            doc = mem.get_document(doc_id)
            if not doc:
                return f"Document {doc_id} not found."
            name = doc.get("name", doc_id)
            ok = mem.delete_document(doc_id)
            if ok:
                return f"Document '{name}' ({doc_id}) deleted with all chunks and edges."
            return f"Failed to delete document {doc_id}."
        except Exception as e:
            return f"Error deleting document: {e}"

    registry.register(AgentTool(
        name="delete_document",
        description="DESTRUCTIVE: Delete a document and all its chunks from the knowledge base.",
        parameters={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document ID to delete"},
            },
            "required": ["doc_id"],
        },
        func=delete_document,
        needs_approval=True,
        always_confirm=True,
    ))

    # 23. kill_session
    def kill_session(session_id: str) -> str:
        try:
            session = session_manager.get(session_id)
            if not session:
                return f"Session {session_id} not found."
            title = session.title
            ok = session_manager.cancel(session_id)
            if ok:
                return f"Session '{title}' ({session_id}) killed."
            return f"Failed to kill session {session_id}. It may not have an active process."
        except Exception as e:
            return f"Error killing session: {e}"

    registry.register(AgentTool(
        name="kill_session",
        description="DESTRUCTIVE: Kill a running session's active process.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to kill"},
            },
            "required": ["session_id"],
        },
        func=kill_session,
        needs_approval=True,
        always_confirm=True,
    ))

    return registry
