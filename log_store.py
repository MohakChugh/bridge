"""Core SQLite log persistence module.

Singleton pattern (module-level _store + get_log_store()) matching event_bus.py.
Async writer thread batches inserts; query methods use a separate reader connection.
Uses print() for internal logging to avoid infinite recursion with the logging module.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


_DB_DIR = Path.home() / ".claude" / "imessage-bridge" / "logs"
_DB_PATH = _DB_DIR / "logs.db"

_MAX_QUEUE = 10_000
_PRUNE_INTERVAL = 1_000
_MAX_LOGS = 100_000
_MAX_REQUESTS = 10_000
_MAX_EVENTS = 50_000


class LogStore:
    """Thread-safe SQLite log store with async writer and sync reader."""

    def __init__(self) -> None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)

        # Writer connection — only used by the writer thread
        self._writer_conn = sqlite3.connect(
            str(_DB_PATH), check_same_thread=False
        )
        self._writer_conn.execute("PRAGMA journal_mode=WAL")
        self._writer_conn.execute("PRAGMA synchronous=NORMAL")

        # Reader connection — used by query methods from any thread
        self._reader_conn = sqlite3.connect(
            str(_DB_PATH), check_same_thread=False
        )
        self._reader_conn.row_factory = sqlite3.Row
        self._reader_conn.execute("PRAGMA journal_mode=WAL")

        self._init_schema()
        self._dropped = 0

        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._insert_count = 0
        self._insert_lock = threading.Lock()

        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="log-store-writer"
        )
        self._writer_thread.start()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        cur = self._writer_conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                level TEXT NOT NULL,
                logger TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                correlation_id TEXT,
                source TEXT DEFAULT 'backend'
            );
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
            CREATE INDEX IF NOT EXISTS idx_logs_logger ON logs(logger);
            CREATE INDEX IF NOT EXISTS idx_logs_corr ON logs(correlation_id);

            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status INTEGER,
                duration_ms REAL,
                request_body TEXT,
                response_body TEXT,
                correlation_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(timestamp);
            CREATE INDEX IF NOT EXISTS idx_req_path ON requests(path);
            CREATE INDEX IF NOT EXISTS idx_req_status ON requests(status);
            CREATE INDEX IF NOT EXISTS idx_req_corr ON requests(correlation_id);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                type TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                source TEXT DEFAULT 'event_bus'
            );
            CREATE INDEX IF NOT EXISTS idx_evt_ts ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_evt_type ON events(type);
        """)
        self._writer_conn.commit()

    def _truncate_all(self) -> None:
        cur = self._writer_conn.cursor()
        cur.execute("DELETE FROM logs")
        cur.execute("DELETE FROM requests")
        cur.execute("DELETE FROM events")
        self._writer_conn.commit()

    # ------------------------------------------------------------------
    # Async writer
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        while self._running:
            batches: dict[str, list[tuple]] = {
                "logs": [],
                "requests": [],
                "events": [],
            }
            # Drain queue
            while True:
                try:
                    table, values = self._queue.get_nowait()
                    if table in batches:
                        batches[table].append(values)
                except queue.Empty:
                    break

            wrote = False
            try:
                if batches["logs"]:
                    self._writer_conn.executemany(
                        "INSERT INTO logs (timestamp, level, logger, message, data, correlation_id, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batches["logs"],
                    )
                    wrote = True

                if batches["requests"]:
                    self._writer_conn.executemany(
                        "INSERT INTO requests (timestamp, method, path, status, duration_ms, request_body, response_body, correlation_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batches["requests"],
                    )
                    wrote = True

                if batches["events"]:
                    self._writer_conn.executemany(
                        "INSERT INTO events (timestamp, type, data, source) "
                        "VALUES (?, ?, ?, ?)",
                        batches["events"],
                    )
                    wrote = True

                if wrote:
                    self._writer_conn.commit()
                    total_inserted = (
                        len(batches["logs"])
                        + len(batches["requests"])
                        + len(batches["events"])
                    )
                    self._maybe_prune(total_inserted)

            except Exception as exc:
                print(f"[log_store] writer error: {exc}")

            time.sleep(0.1)

    def _maybe_prune(self, count: int) -> None:
        with self._insert_lock:
            self._insert_count += count
            if self._insert_count < _PRUNE_INTERVAL:
                return
            self._insert_count = 0

        try:
            cur = self._writer_conn.cursor()

            cur.execute("SELECT COUNT(*) FROM logs")
            if cur.fetchone()[0] > _MAX_LOGS:
                cur.execute(
                    "DELETE FROM logs WHERE id IN "
                    "(SELECT id FROM logs ORDER BY timestamp ASC LIMIT "
                    "(SELECT COUNT(*) - ? FROM logs))",
                    (_MAX_LOGS,),
                )

            cur.execute("SELECT COUNT(*) FROM requests")
            if cur.fetchone()[0] > _MAX_REQUESTS:
                cur.execute(
                    "DELETE FROM requests WHERE id IN "
                    "(SELECT id FROM requests ORDER BY timestamp ASC LIMIT "
                    "(SELECT COUNT(*) - ? FROM requests))",
                    (_MAX_REQUESTS,),
                )

            cur.execute("SELECT COUNT(*) FROM events")
            if cur.fetchone()[0] > _MAX_EVENTS:
                cur.execute(
                    "DELETE FROM events WHERE id IN "
                    "(SELECT id FROM events ORDER BY timestamp ASC LIMIT "
                    "(SELECT COUNT(*) - ? FROM events))",
                    (_MAX_EVENTS,),
                )

            self._writer_conn.commit()
        except Exception as exc:
            print(f"[log_store] prune error: {exc}")

    # ------------------------------------------------------------------
    # Write methods (non-blocking, queue-based)
    # ------------------------------------------------------------------

    def write_log(
        self,
        timestamp: float,
        level: str,
        logger: str,
        message: str,
        data: str = "{}",
        correlation_id: str | None = None,
        source: str = "backend",
    ) -> None:
        if self._queue.qsize() > _MAX_QUEUE:
            self._dropped += 1
            return
        try:
            self._queue.put_nowait(
                ("logs", (timestamp, level, logger, message, data, correlation_id, source))
            )
        except queue.Full:
            pass

    def write_request(
        self,
        timestamp: float,
        method: str,
        path: str,
        status: int | None,
        duration_ms: float | None,
        request_body: str = "",
        response_body: str = "",
        correlation_id: str | None = None,
    ) -> None:
        if self._queue.qsize() > _MAX_QUEUE:
            self._dropped += 1
            return
        try:
            self._queue.put_nowait(
                ("requests", (timestamp, method, path, status, duration_ms, request_body, response_body, correlation_id))
            )
        except queue.Full:
            pass

    def write_event(
        self,
        timestamp: float,
        event_type: str,
        data: str = "{}",
        source: str = "event_bus",
    ) -> None:
        if self._queue.qsize() > _MAX_QUEUE:
            self._dropped += 1
            return
        try:
            self._queue.put_nowait(
                ("events", (timestamp, event_type, data, source))
            )
        except queue.Full:
            pass

    # ------------------------------------------------------------------
    # Query methods (blocking, reader connection)
    # ------------------------------------------------------------------

    def _build_where(
        self, conditions: list[str], params: list[Any]
    ) -> str:
        if not conditions:
            return ""
        return " WHERE " + " AND ".join(conditions)

    def _query_with_count(
        self, table: str, columns: str, where: str, params: list[Any], limit: int, offset: int
    ) -> dict:
        cur = self._reader_conn.cursor()

        cur.execute(f"SELECT COUNT(*) FROM {table}{where}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT {columns} FROM {table}{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        return {"rows": rows, "total": total}

    def query_logs(
        self,
        level: str | None = None,
        logger: str | None = None,
        since: float | None = None,
        until: float | None = None,
        q: str | None = None,
        correlation_id: str | None = None,
        source: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []

        if level is not None:
            conditions.append("level = ?")
            params.append(level)
        if logger is not None:
            conditions.append("logger = ?")
            params.append(logger)
        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until)
        if q is not None:
            conditions.append("message LIKE ?")
            params.append(f"%{q}%")
        if correlation_id is not None:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        where = self._build_where(conditions, params)
        return self._query_with_count("logs", "*", where, params, limit, offset)

    def query_requests(
        self,
        method: str | None = None,
        path: str | None = None,
        status_min: int | None = None,
        status_max: int | None = None,
        since: float | None = None,
        until: float | None = None,
        correlation_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []

        if method is not None:
            conditions.append("method = ?")
            params.append(method)
        if path is not None:
            conditions.append("path = ?")
            params.append(path)
        if status_min is not None:
            conditions.append("status >= ?")
            params.append(status_min)
        if status_max is not None:
            conditions.append("status <= ?")
            params.append(status_max)
        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until)
        if correlation_id is not None:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)

        where = self._build_where(conditions, params)
        return self._query_with_count("requests", "*", where, params, limit, offset)

    def query_events(
        self,
        type_pattern: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []

        if type_pattern is not None:
            conditions.append("type LIKE ?")
            params.append(f"%{type_pattern}%")
        if since is not None:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = self._build_where(conditions, params)
        return self._query_with_count("events", "*", where, params, limit, offset)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        cur = self._reader_conn.cursor()

        # Counts by level
        cur.execute("SELECT level, COUNT(*) as cnt FROM logs GROUP BY level")
        counts_by_level = {row["level"]: row["cnt"] for row in cur.fetchall()}

        # Top 20 loggers
        cur.execute(
            "SELECT logger, COUNT(*) as cnt FROM logs GROUP BY logger ORDER BY cnt DESC LIMIT 20"
        )
        counts_by_logger = {row["logger"]: row["cnt"] for row in cur.fetchall()}

        # Total requests
        cur.execute("SELECT COUNT(*) FROM requests")
        total_requests = cur.fetchone()[0]

        # Error rate (status >= 400)
        cur.execute("SELECT COUNT(*) FROM requests WHERE status >= 400")
        error_count = cur.fetchone()[0]
        error_rate = (error_count / total_requests) if total_requests > 0 else 0.0

        # Total events
        cur.execute("SELECT COUNT(*) FROM events")
        total_events = cur.fetchone()[0]

        # Top 5 error messages
        cur.execute(
            "SELECT message, COUNT(*) as cnt FROM logs "
            "WHERE level IN ('ERROR', 'CRITICAL', 'FATAL') "
            "GROUP BY message ORDER BY cnt DESC LIMIT 5"
        )
        top_errors = [
            {"message": row["message"], "count": row["cnt"]}
            for row in cur.fetchall()
        ]

        return {
            "counts_by_level": counts_by_level,
            "counts_by_logger": counts_by_logger,
            "total_requests": total_requests,
            "error_rate": round(error_rate, 4),
            "total_events": total_events,
            "top_errors": top_errors,
            "dropped_writes": self._dropped,
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> None:
        cur = self._writer_conn.cursor()
        cur.execute("DELETE FROM logs")
        cur.execute("DELETE FROM requests")
        cur.execute("DELETE FROM events")
        self._writer_conn.commit()
        cur.execute("VACUUM")

    def stop(self) -> None:
        self._running = False
        self._writer_thread.join(timeout=2)
        try:
            self._writer_conn.close()
        except Exception:
            pass
        try:
            self._reader_conn.close()
        except Exception:
            pass


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_store: LogStore | None = None


def get_log_store() -> LogStore:
    global _store
    if _store is None:
        _store = LogStore()
    return _store
