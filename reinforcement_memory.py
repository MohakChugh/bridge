"""Reinforcement Memory — Self-learning from corrections.

ISOLATION RULES:
- This module has its OWN SQLite database (reinforcement.db)
- It NEVER imports from shared_memory.py or knowledge_ingestion.py
- It NEVER reads/writes shared-memory.db
- KB features (code review, doc writer, RAG chat) NEVER read from reinforcement.db
- Session manager injects reinforcement context as "BEHAVIORAL GUIDANCE",
  distinct from "KNOWLEDGE CONTEXT"
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reinforcement.db")

_instance: Optional[ReinforcementMemory] = None
_instance_lock = threading.Lock()


def get_reinforcement_memory() -> ReinforcementMemory:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ReinforcementMemory(DB_PATH)
    return _instance


class ReinforcementMemory:

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS lessons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain TEXT NOT NULL DEFAULT 'general',
                        tool TEXT DEFAULT NULL,
                        pattern TEXT NOT NULL,
                        correction TEXT NOT NULL,
                        right_approach TEXT NOT NULL,
                        tags TEXT DEFAULT '[]',
                        source_session_id TEXT DEFAULT NULL,
                        hit_count INTEGER DEFAULT 0,
                        created_at REAL NOT NULL,
                        last_used_at REAL DEFAULT NULL
                    );

                    CREATE TABLE IF NOT EXISTS corrections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        user_message TEXT NOT NULL,
                        ai_output TEXT NOT NULL,
                        correction_text TEXT NOT NULL,
                        extracted_lesson_id INTEGER DEFAULT NULL,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (extracted_lesson_id) REFERENCES lessons(id)
                    );

                    CREATE TABLE IF NOT EXISTS preferences (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        confidence REAL DEFAULT 0.5,
                        updated_at REAL NOT NULL,
                        UNIQUE(category, key)
                    );

                    CREATE INDEX IF NOT EXISTS idx_lessons_domain ON lessons(domain);
                    CREATE INDEX IF NOT EXISTS idx_lessons_tool ON lessons(tool);
                    CREATE INDEX IF NOT EXISTS idx_corrections_session ON corrections(session_id);
                    CREATE INDEX IF NOT EXISTS idx_preferences_category ON preferences(category);
                """)
                conn.commit()
            finally:
                conn.close()

    def add_lesson(
        self,
        pattern: str,
        correction: str,
        right_approach: str,
        domain: str = "general",
        tool: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source_session_id: Optional[str] = None,
    ) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """INSERT INTO lessons (domain, tool, pattern, correction, right_approach, tags, source_session_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (domain, tool, pattern, correction, right_approach,
                     json.dumps(tags or []), source_session_id, time.time()),
                )
                conn.commit()
                lesson_id = cur.lastrowid
                log.info("Lesson #%d stored: domain=%s pattern=%s", lesson_id, domain, pattern[:60])
                return lesson_id
            finally:
                conn.close()

    def record_correction(
        self,
        session_id: str,
        user_message: str,
        ai_output: str,
        correction_text: str,
        lesson_id: Optional[int] = None,
    ) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    """INSERT INTO corrections (session_id, user_message, ai_output, correction_text, extracted_lesson_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, user_message[:2000], ai_output[:2000],
                     correction_text[:2000], lesson_id, time.time()),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def set_preference(self, category: str, key: str, value: str, confidence: float = 0.5) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    """INSERT INTO preferences (category, key, value, confidence, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(category, key) DO UPDATE SET
                           value = excluded.value,
                           confidence = excluded.confidence,
                           updated_at = excluded.updated_at""",
                    (category, key, value, confidence, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def search_lessons(
        self,
        domain: Optional[str] = None,
        tool: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                conditions = []
                params = []
                if domain:
                    conditions.append("domain = ?")
                    params.append(domain)
                if tool:
                    conditions.append("(tool = ? OR tool IS NULL)")
                    params.append(tool)

                where = "WHERE " + " AND ".join(conditions) if conditions else ""
                params.append(limit)

                rows = conn.execute(
                    f"""SELECT id, domain, tool, pattern, correction, right_approach, tags, hit_count, created_at
                        FROM lessons {where}
                        ORDER BY hit_count DESC, created_at DESC
                        LIMIT ?""",
                    params,
                ).fetchall()

                results = []
                for r in rows:
                    results.append({
                        "id": r["id"],
                        "domain": r["domain"],
                        "tool": r["tool"],
                        "pattern": r["pattern"],
                        "correction": r["correction"],
                        "right_approach": r["right_approach"],
                        "tags": json.loads(r["tags"]),
                        "hit_count": r["hit_count"],
                    })
                return results
            finally:
                conn.close()

    def get_preferences(self, category: Optional[str] = None) -> list[dict]:
        with self._lock:
            conn = self._conn()
            try:
                if category:
                    rows = conn.execute(
                        "SELECT category, key, value, confidence FROM preferences WHERE category = ? ORDER BY confidence DESC",
                        (category,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT category, key, value, confidence FROM preferences ORDER BY category, confidence DESC",
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def mark_lesson_used(self, lesson_id: int) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "UPDATE lessons SET hit_count = hit_count + 1, last_used_at = ? WHERE id = ?",
                    (time.time(), lesson_id),
                )
                conn.commit()
            finally:
                conn.close()

    def build_guidance_block(
        self,
        domain: Optional[str] = None,
        tool: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        lessons = self.search_lessons(domain=domain, tool=tool, limit=limit)
        prefs = self.get_preferences(category="response_style")

        if not lessons and not prefs:
            return ""

        parts = ["BEHAVIORAL GUIDANCE (from past corrections — follow these):"]

        for i, lesson in enumerate(lessons, 1):
            parts.append(
                f"{i}. When {lesson['pattern']} → {lesson['right_approach']}"
            )
            self.mark_lesson_used(lesson["id"])

        if prefs:
            parts.append("")
            parts.append("User preferences:")
            for p in prefs:
                parts.append(f"- {p['key']}: {p['value']}")

        return "\n".join(parts) + "\n"

    def stats(self) -> dict:
        with self._lock:
            conn = self._conn()
            try:
                lesson_count = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
                correction_count = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
                pref_count = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
                top_domains = conn.execute(
                    "SELECT domain, COUNT(*) as cnt FROM lessons GROUP BY domain ORDER BY cnt DESC LIMIT 5"
                ).fetchall()
                return {
                    "lessons": lesson_count,
                    "corrections": correction_count,
                    "preferences": pref_count,
                    "top_domains": [{"domain": r[0], "count": r[1]} for r in top_domains],
                    "db_path": self._db_path,
                }
            finally:
                conn.close()


# ---------- Correction Detection ----------

CORRECTION_SIGNALS = [
    "no,", "no ", "not that", "wrong", "don't", "dont", "stop",
    "instead", "actually", "I said", "I meant", "that's not",
    "thats not", "please don't", "never", "always use",
    "I want", "I need", "do it like", "not like that",
]


def detect_correction(user_message: str) -> bool:
    lower = user_message.lower().strip()
    return any(lower.startswith(s) or f" {s}" in lower for s in CORRECTION_SIGNALS)


def extract_lesson_from_correction(
    user_message: str,
    ai_output: str,
    config: dict,
) -> Optional[dict]:
    """Use LLM to extract a structured lesson from a correction.

    Returns {"pattern": ..., "correction": ..., "right_approach": ..., "domain": ..., "tags": [...]}
    or None if extraction fails.
    """
    from llm_parser import parse_json_with_llm

    prompt = (
        "A user corrected an AI assistant. Extract a reusable lesson.\n\n"
        f"AI OUTPUT (what was wrong):\n{ai_output[:500]}\n\n"
        f"USER CORRECTION:\n{user_message[:500]}\n\n"
        "Return JSON:\n"
        '{"pattern": "when the AI does X", "correction": "the user said Y was wrong", '
        '"right_approach": "instead, always do Z", "domain": "coding|review|docs|general", '
        '"tags": ["tag1", "tag2"]}\n\n'
        "Be concise. Pattern and right_approach should be actionable rules."
    )

    result = parse_json_with_llm(prompt, config, timeout=30)
    if result and "pattern" in result and "right_approach" in result:
        return result
    return None
