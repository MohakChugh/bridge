"""Agent Store — SQLite persistence for agent tasks and audit log.

Uses the same shared-memory.db as SharedMemory. Provides CRUD for
agent_tasks and agent_audit tables.
"""

from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared-memory.db")

_store: Optional["AgentStore"] = None
_store_lock = threading.Lock()


def get_agent_store(db_path: str = DB_PATH) -> "AgentStore":
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AgentStore(db_path)
    return _store


class AgentStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                mode TEXT DEFAULT 'safe',
                messages TEXT DEFAULT '[]',
                turns INTEGER DEFAULT 0,
                cost REAL DEFAULT 0.0,
                result TEXT,
                error TEXT,
                progress_pct INTEGER DEFAULT 0,
                progress_msg TEXT DEFAULT '',
                parent_id TEXT,
                created_at REAL,
                updated_at REAL,
                completed_at REAL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_agent_tasks_parent ON agent_tasks(parent_id);

            CREATE TABLE IF NOT EXISTS agent_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                tool TEXT,
                args TEXT,
                result TEXT,
                is_error INTEGER DEFAULT 0,
                approved_by TEXT,
                timestamp REAL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_audit_task ON agent_audit(task_id);
        """)

    def save_task(self, task: dict) -> None:
        now = time.time()
        task.setdefault("created_at", now)
        task["updated_at"] = now
        messages = task.get("messages", [])
        if isinstance(messages, list):
            messages = json.dumps(messages)
        metadata = task.get("metadata", {})
        if isinstance(metadata, dict):
            metadata = json.dumps(metadata)
        with self._lock:
            self.db.execute(
                """INSERT OR REPLACE INTO agent_tasks
                   (id, title, description, status, mode, messages, turns, cost,
                    result, error, progress_pct, progress_msg, parent_id,
                    created_at, updated_at, completed_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task["id"], task["title"], task["description"],
                    task.get("status", "pending"), task.get("mode", "safe"),
                    messages, task.get("turns", 0), task.get("cost", 0.0),
                    task.get("result"), task.get("error"),
                    task.get("progress_pct", 0), task.get("progress_msg", ""),
                    task.get("parent_id"),
                    task["created_at"], task["updated_at"],
                    task.get("completed_at"), metadata,
                ),
            )
            self.db.commit()

    def get_task(self, task_id: str) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM agent_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_tasks(self, status: str = None, limit: int = 50) -> list[dict]:
        if status:
            rows = self.db.execute(
                "SELECT * FROM agent_tasks WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM agent_tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            self.db.execute("DELETE FROM agent_audit WHERE task_id = ?", (task_id,))
            cur = self.db.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))
            self.db.commit()
            return cur.rowcount > 0

    def save_audit(self, task_id: str, tool: str, args: str, result: str,
                   is_error: bool = False, approved_by: str = "auto") -> int:
        with self._lock:
            cur = self.db.execute(
                """INSERT INTO agent_audit (task_id, tool, args, result, is_error, approved_by, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task_id, tool, args, result, int(is_error), approved_by, time.time()),
            )
            self.db.commit()
            return cur.lastrowid

    def list_audit(self, task_id: str = None, limit: int = 100) -> list[dict]:
        if task_id:
            rows = self.db.execute(
                "SELECT * FROM agent_audit WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM agent_audit ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["messages"] = json.loads(d.get("messages") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["messages"] = []
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        return d
