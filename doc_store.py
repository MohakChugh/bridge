"""Filesystem-based document store with YAML frontmatter and asset management."""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import yaml


_BASE_DIR = os.path.expanduser("~/.claude/imessage-bridge/docs")


class DocStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._base = Path(_BASE_DIR)
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # ID / path helpers
    # ------------------------------------------------------------------

    def _id_to_path(self, doc_id: str) -> Path:
        """Convert ``architecture::overview`` to ``architecture/overview.md``."""
        return self._base / (doc_id.replace("::", "/") + ".md")

    def _path_to_id(self, rel_path: str) -> str:
        """Convert ``architecture/overview.md`` to ``architecture::overview``."""
        p = rel_path
        if p.endswith(".md"):
            p = p[:-3]
        return p.replace("/", "::")

    def _asset_dir(self, doc_id: str) -> Path:
        """Absolute path to the asset subdirectory for *doc_id*."""
        md_path = self._id_to_path(doc_id)
        return md_path.parent / md_path.stem

    # ------------------------------------------------------------------
    # Frontmatter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict, str]:
        """Return ``(meta_dict, body_str)`` from a Markdown file's content.

        Handles files without frontmatter gracefully by returning an empty
        dict and the original content.
        """
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        raw_meta = parts[1]
        body = parts[2]
        if body.startswith("\n"):
            body = body[1:]

        try:
            meta = yaml.safe_load(raw_meta) or {}
        except yaml.YAMLError:
            meta = {}

        return meta, body

    @staticmethod
    def _render_frontmatter(meta: dict, body: str) -> str:
        """Combine *meta* and *body* into a full file string."""
        fm = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False)
        return f"---\n{fm}---\n{body}"

    # ------------------------------------------------------------------
    # Internal metadata builder
    # ------------------------------------------------------------------

    def _build_meta(self, doc_id: str, md_path: Path, meta: dict) -> dict:
        rel = md_path.relative_to(self._base)
        return {
            "id": doc_id,
            "path": str(rel),
            "title": meta.get("title", ""),
            "collection": meta.get("collection", ""),
            "tags": meta.get("tags", []),
            "created_at": meta.get("created_at", 0),
            "updated_at": meta.get("updated_at", 0),
            "has_assets": self._asset_dir(doc_id).is_dir(),
        }

    # ------------------------------------------------------------------
    # Event publishing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _publish(event_type: str, data: dict) -> None:
        try:
            from event_bus import get_event_bus
            get_event_bus().publish(event_type, data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        path: str,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
        collection: str = "",
    ) -> dict:
        """Create a new document at *path* (relative to base_dir).

        Raises ``FileExistsError`` if the file already exists.
        """
        if tags is None:
            tags = []

        with self._lock:
            full = self._base / path
            if full.exists():
                raise FileExistsError(f"Document already exists: {path}")

            full.parent.mkdir(parents=True, exist_ok=True)

            now = time.time()
            meta: dict[str, Any] = {
                "title": title,
                "created_at": now,
                "updated_at": now,
                "tags": list(tags),
                "collection": collection or full.parent.name,
                "order": 0,
            }

            full.write_text(self._render_frontmatter(meta, content), encoding="utf-8")

            doc_id = self._path_to_id(str(full.relative_to(self._base)))
            result = self._build_meta(doc_id, full, meta)
            self._publish("doc.created", {"id": result["id"], "path": result["path"], "title": result["title"]})
            return result

    def read(self, doc_id: str) -> dict | None:
        """Read a document by *doc_id*. Returns ``None`` if not found."""
        with self._lock:
            md_path = self._id_to_path(doc_id)
            if not md_path.is_file():
                return None

            raw = md_path.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(raw)

            asset_path = self._asset_dir(doc_id)
            assets: list[str] = []
            if asset_path.is_dir():
                assets = [f.name for f in asset_path.iterdir() if f.is_file()]

            return {
                "id": doc_id,
                "path": str(md_path.relative_to(self._base)),
                "title": meta.get("title", ""),
                "content": body,
                "frontmatter": meta,
                "assets": assets,
            }

    def update(
        self,
        doc_id: str,
        content: str | None = None,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing document. Only provided fields are changed."""
        with self._lock:
            md_path = self._id_to_path(doc_id)
            if not md_path.is_file():
                raise FileNotFoundError(f"Document not found: {doc_id}")

            raw = md_path.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(raw)

            if title is not None:
                meta["title"] = title
            if tags is not None:
                meta["tags"] = list(tags)
            if content is not None:
                body = content

            meta["updated_at"] = time.time()

            md_path.write_text(self._render_frontmatter(meta, body), encoding="utf-8")

            result = self._build_meta(doc_id, md_path, meta)
            self._publish("doc.updated", {"id": result["id"], "path": result["path"], "title": result["title"]})
            return result

    def delete(self, doc_id: str) -> bool:
        """Delete a document and its asset directory. Returns ``True`` on success."""
        with self._lock:
            md_path = self._id_to_path(doc_id)
            if not md_path.is_file():
                return False

            rel_path = str(md_path.relative_to(self._base))
            title = ""
            try:
                raw = md_path.read_text(encoding="utf-8")
                meta, _ = self._parse_frontmatter(raw)
                title = meta.get("title", "")
            except Exception:
                pass

            md_path.unlink()

            asset_path = self._asset_dir(doc_id)
            if asset_path.is_dir():
                shutil.rmtree(asset_path)

            self._publish("doc.deleted", {"id": doc_id, "path": rel_path, "title": title})
            return True

    def list_all(self) -> list[dict]:
        """Walk docs/ recursively and return a flat list of metadata dicts."""
        results: list[dict] = []
        with self._lock:
            for root, _dirs, files in os.walk(self._base):
                for fname in files:
                    if fname.startswith(".") or fname == ".doc-meta.json":
                        continue
                    if not fname.endswith(".md"):
                        continue

                    full = Path(root) / fname
                    rel = str(full.relative_to(self._base))
                    doc_id = self._path_to_id(rel)

                    try:
                        raw = full.read_text(encoding="utf-8")
                        meta, _ = self._parse_frontmatter(raw)
                    except Exception:
                        meta = {}

                    results.append(self._build_meta(doc_id, full, meta))
        return results

    def create_folder(self, folder_path: str) -> bool:
        """Create a directory under docs/."""
        with self._lock:
            target = self._base / folder_path
            target.mkdir(parents=True, exist_ok=True)
            return True

    def rename(self, doc_id: str, new_name: str) -> dict:
        """Rename a document file (not move). *new_name* should end with ``.md``."""
        with self._lock:
            old_path = self._id_to_path(doc_id)
            if not old_path.is_file():
                raise FileNotFoundError(f"Document not found: {doc_id}")

            new_path = old_path.parent / new_name
            old_path.rename(new_path)

            # Rename asset directory if it exists
            old_asset = self._asset_dir(doc_id)
            if old_asset.is_dir():
                new_stem = new_name[:-3] if new_name.endswith(".md") else new_name
                new_asset = old_path.parent / new_stem
                old_asset.rename(new_asset)

            rel = str(new_path.relative_to(self._base))
            new_id = self._path_to_id(rel)

            raw = new_path.read_text(encoding="utf-8")
            meta, _ = self._parse_frontmatter(raw)
            meta["updated_at"] = time.time()
            body_raw = raw
            _, body = self._parse_frontmatter(body_raw)
            new_path.write_text(self._render_frontmatter(meta, body), encoding="utf-8")

            result = self._build_meta(new_id, new_path, meta)
            self._publish("doc.renamed", {"id": result["id"], "path": result["path"], "title": result["title"], "old_id": doc_id})
            return result

    def move(self, doc_id: str, new_parent_path: str) -> dict:
        """Move a document (and its asset dir) to *new_parent_path*."""
        with self._lock:
            old_path = self._id_to_path(doc_id)
            if not old_path.is_file():
                raise FileNotFoundError(f"Document not found: {doc_id}")

            new_parent = self._base / new_parent_path
            new_parent.mkdir(parents=True, exist_ok=True)
            new_path = new_parent / old_path.name

            old_path.rename(new_path)

            # Move asset directory
            old_asset = self._asset_dir(doc_id)
            if old_asset.is_dir():
                new_asset = new_parent / old_asset.name
                old_asset.rename(new_asset)

            rel = str(new_path.relative_to(self._base))
            new_id = self._path_to_id(rel)

            raw = new_path.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(raw)
            meta["updated_at"] = time.time()
            meta["collection"] = new_parent.name
            new_path.write_text(self._render_frontmatter(meta, body), encoding="utf-8")

            result = self._build_meta(new_id, new_path, meta)
            self._publish("doc.moved", {"id": result["id"], "path": result["path"], "title": result["title"], "old_id": doc_id})
            return result

    def get_tree(self) -> list[dict]:
        """Return a nested tree of folders and documents.

        Folders sort first (alphabetical), then documents (alphabetical).
        Hidden files are skipped.
        """
        with self._lock:
            return self._walk_tree(self._base)

    def _walk_tree(self, directory: Path) -> list[dict]:
        folders: list[dict] = []
        docs: list[dict] = []

        try:
            entries = sorted(directory.iterdir(), key=lambda e: e.name)
        except OSError:
            return []

        for entry in entries:
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                # Skip asset directories (they sit next to their .md file)
                md_sibling = entry.parent / (entry.name + ".md")
                if md_sibling.is_file():
                    continue

                children = self._walk_tree(entry)
                folders.append({
                    "type": "folder",
                    "name": entry.name,
                    "path": str(entry.relative_to(self._base)),
                    "children": children,
                })
            elif entry.is_file() and entry.suffix == ".md":
                rel = str(entry.relative_to(self._base))
                doc_id = self._path_to_id(rel)
                try:
                    raw = entry.read_text(encoding="utf-8")
                    meta, _ = self._parse_frontmatter(raw)
                except Exception:
                    meta = {}

                docs.append({
                    "type": "doc",
                    "name": entry.name,
                    "id": doc_id,
                    "path": rel,
                    "title": meta.get("title", ""),
                    "collection": meta.get("collection", ""),
                    "tags": meta.get("tags", []),
                    "created_at": meta.get("created_at", 0),
                    "updated_at": meta.get("updated_at", 0),
                    "order": meta.get("order", 0),
                    "has_assets": self._asset_dir(doc_id).is_dir(),
                })

        return folders + docs

    def save_asset(self, doc_id: str, filename: str, data: bytes) -> str:
        """Save binary *data* as an asset for *doc_id*. Returns an API URL."""
        with self._lock:
            md_path = self._id_to_path(doc_id)
            if not md_path.is_file():
                raise FileNotFoundError(f"Document not found: {doc_id}")

            asset_path = self._asset_dir(doc_id)
            asset_path.mkdir(parents=True, exist_ok=True)

            (asset_path / filename).write_bytes(data)
            return f"/api/docs/assets/{doc_id}/{filename}"

    def list_assets(self, doc_id: str) -> list[str]:
        """List filenames in the asset directory for *doc_id*."""
        with self._lock:
            asset_path = self._asset_dir(doc_id)
            if not asset_path.is_dir():
                return []
            return [f.name for f in asset_path.iterdir() if f.is_file()]

    def get_asset_path(self, doc_id: str, filename: str) -> str | None:
        """Return the absolute path to an asset file, or ``None``."""
        with self._lock:
            asset_path = self._asset_dir(doc_id) / filename
            if asset_path.is_file():
                return str(asset_path)
            return None


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_instance = DocStore()


def get_doc_store() -> DocStore:
    return _instance
