"""Shared Memory — sqlite-vec vector DB with named collections.

Single local .db file. Semantic search via all-MiniLM-L6-v2 embeddings (384 dims).
Used by all tools (Claude/Wasabi/Kiro) for context retrieval.
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
import struct
import time
from typing import Optional

log = logging.getLogger("shared_memory")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared-memory.db")
EMBEDDING_DIM = 384
SIMILARITY_THRESHOLD = 0.75

_instance: Optional["SharedMemory"] = None


def get_shared_memory(db_path: str = DB_PATH) -> "SharedMemory":
    global _instance
    if _instance is None:
        _instance = SharedMemory(db_path)
    return _instance


def _serialize_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SharedMemory:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._model = None
        self._init_schema()

    def _init_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                source TEXT DEFAULT 'manual',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_collection ON memories(collection_id);
        """)
        self.db.commit()

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            log.info("Loaded embedding model: all-MiniLM-L6-v2")
        return self._model

    def _embed(self, text: str) -> list[float]:
        return self._get_model().encode(text).tolist()

    # ---- Collections ----

    def create_collection(self, name: str, description: str = "") -> int:
        try:
            cur = self.db.execute(
                "INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?)",
                (name, description, time.time()),
            )
            self.db.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            row = self.db.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
            return row["id"] if row else 0

    def list_collections(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT c.name, c.description, c.created_at,
                   COUNT(m.id) as entry_count
            FROM collections c
            LEFT JOIN memories m ON m.collection_id = c.id
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall()
        return [dict(r) for r in rows]

    def delete_collection(self, name: str) -> bool:
        row = self.db.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        if not row:
            return False
        self.db.execute("DELETE FROM memories WHERE collection_id = ?", (row["id"],))
        self.db.execute("DELETE FROM collections WHERE id = ?", (row["id"],))
        self.db.commit()
        return True

    def _get_collection_id(self, name: str) -> Optional[int]:
        row = self.db.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        return row["id"] if row else None

    # ---- Add ----

    def add(self, text: str, collection: str, metadata: Optional[dict] = None, source: str = "manual") -> int:
        cid = self._get_collection_id(collection)
        if cid is None:
            cid = self.create_collection(collection)
        vec = self._embed(text)
        cur = self.db.execute(
            "INSERT INTO memories (collection_id, text, embedding, metadata, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cid, text, _serialize_vector(vec), json.dumps(metadata or {}), source, time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def add_batch(self, items: list[dict], collection: str) -> int:
        cid = self._get_collection_id(collection)
        if cid is None:
            cid = self.create_collection(collection)
        count = 0
        for item in items:
            text = item.get("text", "")
            if not text:
                continue
            vec = self._embed(text)
            self.db.execute(
                "INSERT INTO memories (collection_id, text, embedding, metadata, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cid, text, _serialize_vector(vec), json.dumps(item.get("metadata", {})), item.get("source", "import"), time.time()),
            )
            count += 1
        self.db.commit()
        return count

    # ---- Search ----

    def search(self, query: str, collections: Optional[list[str]] = None, limit: int = 5) -> list[dict]:
        query_vec = self._embed(query)
        if collections:
            placeholders = ",".join("?" for _ in collections)
            rows = self.db.execute(
                f"""SELECT m.id, m.text, m.embedding, m.metadata, m.source, m.created_at, c.name as collection
                    FROM memories m JOIN collections c ON c.id = m.collection_id
                    WHERE c.name IN ({placeholders})""",
                collections,
            ).fetchall()
        else:
            rows = self.db.execute(
                """SELECT m.id, m.text, m.embedding, m.metadata, m.source, m.created_at, c.name as collection
                   FROM memories m JOIN collections c ON c.id = m.collection_id"""
            ).fetchall()

        results = []
        for row in rows:
            if row["embedding"]:
                stored_vec = _deserialize_vector(row["embedding"])
                score = _cosine_similarity(query_vec, stored_vec)
                results.append({
                    "id": row["id"],
                    "text": row["text"],
                    "collection": row["collection"],
                    "score": round(score, 4),
                    "metadata": json.loads(row["metadata"] or "{}"),
                    "source": row["source"],
                    "created_at": row["created_at"],
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    # ---- Delete ----

    def delete(self, memory_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.db.commit()
        return cur.rowcount > 0

    # ---- Stats ----

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        collections = self.list_collections()
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {
            "total_entries": total,
            "collections": {c["name"]: c["entry_count"] for c in collections},
            "db_size_bytes": db_size,
        }

    # ---- Entries ----

    def list_entries(self, collection: str, limit: int = 50, offset: int = 0) -> list[dict]:
        cid = self._get_collection_id(collection)
        if cid is None:
            return []
        rows = self.db.execute(
            "SELECT id, text, metadata, source, created_at FROM memories WHERE collection_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (cid, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Import ----

    def import_file(self, path: str, collection: str, chunk_size: int = 500) -> int:
        if not os.path.isfile(path):
            return 0
        with open(path) as f:
            text = f.read()
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        items = [{"text": chunk, "metadata": {"file": os.path.basename(path)}, "source": "import"} for chunk in chunks if chunk.strip()]
        return self.add_batch(items, collection)

    def import_directory(self, dir_path: str, collection: str, extensions: Optional[list[str]] = None) -> int:
        extensions = extensions or [".md", ".py", ".txt", ".json", ".yaml", ".yml"]
        total = 0
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if any(fname.endswith(ext) for ext in extensions):
                    fpath = os.path.join(root, fname)
                    total += self.import_file(fpath, collection)
        return total
