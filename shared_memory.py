"""Shared Memory — sqlite-vec vector DB with named collections.

Single local .db file. Semantic search via all-MiniLM-L6-v2 embeddings (384 dims).
Used by all tools (Claude/Wasabi/Kiro) for context retrieval.
"""

from __future__ import annotations
import collections
import json
import logging
import os
import sqlite3
import struct
import time
from typing import Optional

import threading as _threading
from event_bus import get_event_bus

log = logging.getLogger("shared_memory")

DB_PATH = os.environ.get(
    "BRIDGE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared-memory.db"),
)
EMBEDDING_DIM = 384
SIMILARITY_THRESHOLD = 0.75
MAX_DOC_LOCKS = 256

_instance: Optional["SharedMemory"] = None

_doc_locks: collections.OrderedDict[str, _threading.RLock] = collections.OrderedDict()
_doc_locks_guard = _threading.Lock()

def get_doc_lock(doc_id: str) -> _threading.RLock:
    """Get or create a per-document lock to serialize concurrent ingestion."""
    with _doc_locks_guard:
        if doc_id not in _doc_locks:
            _doc_locks[doc_id] = _threading.RLock()
        if len(_doc_locks) > MAX_DOC_LOCKS:
            _doc_locks.popitem(last=False)
        return _doc_locks[doc_id]


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
                created_at REAL NOT NULL,
                document_id TEXT,
                chunk_index INTEGER,
                summary TEXT,
                tags TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_memories_collection ON memories(collection_id);
            CREATE INDEX IF NOT EXISTS idx_memories_document ON memories(document_id);

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT,
                collection TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                persona TEXT,
                last_refreshed REAL,
                created_at REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique
                ON edges(source_id, target_id, relation);

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_tags (
                memory_id INTEGER REFERENCES memories(id) ON DELETE CASCADE,
                tag_id INTEGER REFERENCES tags(id),
                PRIMARY KEY (memory_id, tag_id)
            );
        """)
        # Migrate existing memories table if columns missing
        try:
            self.db.execute("SELECT document_id FROM memories LIMIT 1")
        except sqlite3.OperationalError:
            self.db.execute("ALTER TABLE memories ADD COLUMN document_id TEXT")
            self.db.execute("ALTER TABLE memories ADD COLUMN chunk_index INTEGER")
            self.db.execute("ALTER TABLE memories ADD COLUMN summary TEXT")
            self.db.execute("ALTER TABLE memories ADD COLUMN tags TEXT DEFAULT '[]'")
        self.db.commit()
        try:
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_url_collection "
                "ON documents(source_url, collection)"
            )
            self.db.commit()
        except sqlite3.OperationalError:
            pass

        # Agent Brain tables
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

    # ---- Documents ----

    def register_document(self, name: str, source_type: str, source_url: str, collection: str, tags: Optional[list[str]] = None, persona: Optional[str] = None) -> str:
        import uuid
        existing = self.db.execute(
            "SELECT id FROM documents WHERE source_url = ? AND collection = ?",
            (source_url, collection),
        ).fetchone()
        if existing:
            get_event_bus().publish("document.register.duplicate", {
                "doc_id": existing["id"],
                "source_url": source_url,
                "collection": collection,
            })
            return existing["id"]
        doc_id = str(uuid.uuid4())[:12]
        self.db.execute(
            "INSERT OR REPLACE INTO documents (id, name, source_type, source_url, collection, tags, persona, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, name, source_type, source_url, collection, json.dumps(tags or []), persona, time.time()),
        )
        self.db.commit()
        self.create_collection(collection)
        get_event_bus().publish("document.registered", {
            "doc_id": doc_id,
            "name": name,
            "source_type": source_type,
            "source_url": source_url,
            "collection": collection,
            "tags": tags or [],
        })
        return doc_id

    def list_documents(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_document(self, doc_id: str) -> Optional[dict]:
        row = self.db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def delete_document(self, doc_id: str) -> bool:
        doc = self.get_document(doc_id)
        if not doc:
            return False
        # Collect memory IDs BEFORE deleting anything
        memory_ids = [r[0] for r in self.db.execute(
            "SELECT id FROM memories WHERE document_id = ?", (doc_id,)
        ).fetchall()]
        chunk_count = len(memory_ids)
        if memory_ids:
            placeholders = ",".join("?" for _ in memory_ids)
            edge_count = self.db.execute(
                f"SELECT COUNT(*) FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                (*memory_ids, *memory_ids),
            ).fetchone()[0]
        else:
            edge_count = 0
        get_event_bus().publish("document.deleting", {
            "doc_id": doc_id, "name": doc.get("name"),
            "chunks_to_delete": chunk_count, "edges_to_delete": edge_count,
        })
        # Delete edges FIRST (while memory IDs still exist for reference)
        if memory_ids:
            self.db.execute(
                f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                (*memory_ids, *memory_ids),
            )
        # Then delete memories
        self.db.execute("DELETE FROM memories WHERE document_id = ?", (doc_id,))
        # Finally delete the document record
        self.db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self.db.commit()
        get_event_bus().publish("document.deleted", {
            "doc_id": doc_id, "name": doc.get("name"),
            "chunks_deleted": chunk_count, "edges_deleted": edge_count,
            "collection": doc.get("collection"),
        })
        return True

    def update_document_chunks(self, doc_id: str, chunk_count: int) -> None:
        self.db.execute("UPDATE documents SET chunk_count = ?, last_refreshed = ? WHERE id = ?", (chunk_count, time.time(), doc_id))
        self.db.commit()
        get_event_bus().publish("document.ingested", {
            "doc_id": doc_id, "chunk_count": chunk_count,
        })

    def refresh_document(self, doc_id: str) -> None:
        doc_lock = get_doc_lock(doc_id)
        with doc_lock:
            # Collect memory IDs BEFORE deleting anything
            memory_ids = [r[0] for r in self.db.execute(
                "SELECT id FROM memories WHERE document_id = ?", (doc_id,)
            ).fetchall()]
            chunk_count = len(memory_ids)
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                edge_count = self.db.execute(
                    f"SELECT COUNT(*) FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                    (*memory_ids, *memory_ids),
                ).fetchone()[0]
            else:
                edge_count = 0
            if chunk_count > 0 or edge_count > 0:
                get_event_bus().publish("document.refresh.started", {
                    "doc_id": doc_id, "chunks_clearing": chunk_count, "edges_clearing": edge_count,
                })
            # Delete edges FIRST (while memory IDs still available)
            if memory_ids:
                self.db.execute(
                    f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                    (*memory_ids, *memory_ids),
                )
            # Then delete memories
            self.db.execute("DELETE FROM memories WHERE document_id = ?", (doc_id,))
            self.db.commit()
            get_event_bus().publish("document.refresh.cleared", {
                "doc_id": doc_id, "chunks_deleted": chunk_count, "edges_deleted": edge_count,
            })

    # ---- Edges (Knowledge Graph) ----

    def create_edge(self, source_id: int, target_id: int, relation: str, metadata: Optional[dict] = None) -> int:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, relation, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (source_id, target_id, relation, json.dumps(metadata or {}), time.time()),
        )
        self.db.commit()
        if cur.lastrowid and cur.rowcount > 0:
            return cur.lastrowid
        # Edge already existed — return its id
        row = self.db.execute(
            "SELECT id FROM edges WHERE source_id = ? AND target_id = ? AND relation = ?",
            (source_id, target_id, relation),
        ).fetchone()
        return row["id"] if row else 0

    def get_edges(self, memory_id: Optional[int] = None) -> list[dict]:
        if memory_id:
            rows = self.db.execute("SELECT * FROM edges WHERE source_id = ? OR target_id = ?", (memory_id, memory_id)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM edges").fetchall()
        return [dict(r) for r in rows]

    def get_graph(self) -> dict:
        # Clean orphaned edges first (refs to deleted memories)
        self.db.execute(
            "DELETE FROM edges WHERE source_id NOT IN (SELECT id FROM memories) "
            "OR target_id NOT IN (SELECT id FROM memories)"
        )
        self.db.commit()

        edges = self.db.execute(
            "SELECT e.*, "
            "m1.text as source_text, m1.summary as source_summary, m1.tags as source_tags, "
            "c1.name as source_collection, d1.name as source_document, "
            "m2.text as target_text, m2.summary as target_summary, m2.tags as target_tags, "
            "c2.name as target_collection, d2.name as target_document "
            "FROM edges e "
            "JOIN memories m1 ON m1.id = e.source_id "
            "LEFT JOIN collections c1 ON c1.id = m1.collection_id "
            "LEFT JOIN documents d1 ON d1.id = m1.document_id "
            "JOIN memories m2 ON m2.id = e.target_id "
            "LEFT JOIN collections c2 ON c2.id = m2.collection_id "
            "LEFT JOIN documents d2 ON d2.id = m2.document_id"
        ).fetchall()
        nodes_set = set()
        node_list = []
        edge_list = []
        for e in edges:
            for nid, text, summary, tags, collection, document in [
                (e["source_id"], e["source_text"], e["source_summary"], e["source_tags"], e["source_collection"], e["source_document"]),
                (e["target_id"], e["target_text"], e["target_summary"], e["target_tags"], e["target_collection"], e["target_document"]),
            ]:
                if nid not in nodes_set:
                    nodes_set.add(nid)
                    parsed_tags = []
                    if tags:
                        try:
                            parsed_tags = json.loads(tags)
                        except (json.JSONDecodeError, TypeError):
                            parsed_tags = []
                    node_list.append({
                        "id": nid,
                        "text": (text or "")[:100],
                        "summary": summary or "",
                        "tags": parsed_tags,
                        "collection": collection or "",
                        "document_name": document or "",
                    })
            edge_list.append({"source": e["source_id"], "target": e["target_id"], "relation": e["relation"]})
        return {"nodes": node_list, "edges": edge_list}

    def delete_edge(self, edge_id: int) -> bool:
        cur = self.db.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
        self.db.commit()
        return cur.rowcount > 0

    def purge_all(self) -> dict:
        edges = self.db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        memories = self.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        documents = self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        collections = self.db.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
        self.db.execute("DELETE FROM edges")
        self.db.execute("DELETE FROM memory_tags")
        self.db.execute("DELETE FROM memories")
        self.db.execute("DELETE FROM documents")
        self.db.execute("DELETE FROM collections")
        self.db.execute("DELETE FROM tags")
        self.db.commit()
        return {"edges": edges, "memories": memories, "documents": documents, "collections": collections}

    # ---- Tags ----

    def add_tags(self, memory_id: int, tag_names: list[str]) -> None:
        for name in tag_names:
            self.db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_row = self.db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            if tag_row:
                self.db.execute("INSERT OR IGNORE INTO memory_tags (memory_id, tag_id) VALUES (?, ?)", (memory_id, tag_row["id"]))
        self.db.commit()

    def list_tags(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT t.name, COUNT(mt.memory_id) as count
            FROM tags t LEFT JOIN memory_tags mt ON mt.tag_id = t.id
            GROUP BY t.id ORDER BY count DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def search_by_tags(self, tag_names: list[str], limit: int = 20) -> list[dict]:
        placeholders = ",".join("?" for _ in tag_names)
        rows = self.db.execute(f"""
            SELECT DISTINCT m.id, m.text, m.summary, m.tags, m.source, m.created_at, c.name as collection
            FROM memories m
            JOIN collections c ON c.id = m.collection_id
            JOIN memory_tags mt ON mt.memory_id = m.id
            JOIN tags t ON t.id = mt.tag_id
            WHERE t.name IN ({placeholders})
            ORDER BY m.created_at DESC
            LIMIT ?
        """, (*tag_names, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---- Enhanced Add (with tags + document_id) ----

    def add_enriched(self, text: str, collection: str, document_id: Optional[str] = None,
                     chunk_index: Optional[int] = None, summary: Optional[str] = None,
                     tags: Optional[list[str]] = None, metadata: Optional[dict] = None,
                     source: str = "manual") -> int:
        cid = self._get_collection_id(collection)
        if cid is None:
            cid = self.create_collection(collection)
        vec = self._embed(summary or text)
        cur = self.db.execute(
            """INSERT INTO memories (collection_id, text, embedding, metadata, source, created_at,
               document_id, chunk_index, summary, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cid, text, _serialize_vector(vec), json.dumps(metadata or {}), source, time.time(),
             document_id, chunk_index, summary, json.dumps(tags or [])),
        )
        mid = cur.lastrowid
        self.db.commit()
        if tags:
            self.add_tags(mid, tags)
        return mid

    def import_directory(self, dir_path: str, collection: str, extensions: Optional[list[str]] = None) -> int:
        extensions = extensions or [".md", ".py", ".txt", ".json", ".yaml", ".yml"]
        total = 0
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if any(fname.endswith(ext) for ext in extensions):
                    fpath = os.path.join(root, fname)
                    total += self.import_file(fpath, collection)
        return total
