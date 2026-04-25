"""Knowledge ingestion pipeline — fetch, chunk, summarize, tag, link, store.

Multi-pass LLM enrichment for wikis, code, quip docs, web URLs, files.
Handles file/directory ingestion with AST analysis for code packages.
"""

from __future__ import annotations
import json
import logging
import os
import re
import time
import uuid
from typing import Optional

log = logging.getLogger("knowledge_ingestion")

CHUNK_SIZE = 500


def ingest_document(doc_id: str, config: dict) -> dict:
    """Full ingestion pipeline for a registered document.

    Returns: {chunks: int, tags: [], edges: int}
    """
    from shared_memory import get_shared_memory
    mem = get_shared_memory()
    doc = mem.get_document(doc_id)
    if not doc:
        return {"error": "Document not found"}

    # Delete existing data for this document (atomic refresh)
    mem.refresh_document(doc_id)

    source_type = doc["source_type"]
    source_url = doc["source_url"]
    collection = doc["collection"]
    doc_tags = json.loads(doc.get("tags") or "[]")

    # Step 1: Fetch content
    log.info(f"Ingesting {source_type}: {source_url}")
    raw_chunks = _fetch_and_chunk(source_type, source_url, config)
    if not raw_chunks:
        return {"chunks": 0, "error": "No content fetched"}

    # Step 2-5: Process each chunk (summarize, tag, embed, store)
    total_chunks = 0
    total_edges = 0
    all_tags = set(doc_tags)

    for i, chunk in enumerate(raw_chunks):
        if not chunk.get("text", "").strip():
            continue

        text = chunk["text"]
        chunk_meta = chunk.get("metadata", {})

        # Pass 2: Summarize (LLM)
        summary = _summarize_chunk(text, config)

        # Pass 3: Auto-tag (LLM)
        auto_tags = _generate_tags(summary or text, config)
        combined_tags = list(set(doc_tags + auto_tags))
        all_tags.update(auto_tags)

        # Pass 4-5: Embed + Store
        mid = mem.add_enriched(
            text=text,
            collection=collection,
            document_id=doc_id,
            chunk_index=i,
            summary=summary,
            tags=combined_tags,
            metadata={**chunk_meta, "source_url": source_url},
            source=source_type,
        )

        # Pass 6: Link to existing entries
        edges = _find_and_create_links(mem, mid, summary or text)
        total_edges += edges
        total_chunks += 1

    mem.update_document_chunks(doc_id, total_chunks)
    log.info(f"Ingested {total_chunks} chunks, {total_edges} edges, {len(all_tags)} tags")

    return {
        "chunks": total_chunks,
        "edges": total_edges,
        "tags": list(all_tags),
    }


def _fetch_and_chunk(source_type: str, source_url: str, config: dict) -> list[dict]:
    """Fetch content and split into chunks based on source type."""
    if source_type in ("file", "wiki", "quip", "web"):
        return _fetch_text_source(source_type, source_url, config)
    elif source_type == "code":
        return _fetch_code_package(source_url)
    return []


def _fetch_text_source(source_type: str, source_url: str, config: dict) -> list[dict]:
    """Fetch and chunk text sources (files, wikis, web URLs)."""
    content = ""

    if source_type == "file":
        if os.path.isdir(source_url):
            return _chunk_directory(source_url)
        elif os.path.isfile(source_url):
            with open(source_url) as f:
                content = f.read()
        else:
            return []
    elif source_type in ("wiki", "quip", "web"):
        content = _fetch_url_via_tool(source_url, source_type, config)
        if not content:
            return []

    return _chunk_text(content, metadata={"file": os.path.basename(source_url) if source_type == "file" else source_url})


def _fetch_url_via_tool(url: str, source_type: str, config: dict) -> str:
    """Fetch URL content using configured parsing tool."""
    from llm_parser import parse_with_llm

    prompt = f"Read the content from this URL and return the full text: {url}"
    if source_type == "wiki":
        prompt = f"Read the wiki page at {url}. Return the full content as plain text."
    elif source_type == "quip":
        prompt = f"Read the Quip document at {url}. Return the full content as plain text."

    result = parse_with_llm(prompt, config, timeout=300)
    return result or ""


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, metadata: Optional[dict] = None) -> list[dict]:
    """Split text into chunks preserving paragraph boundaries."""
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) > chunk_size and current:
            chunks.append({"text": current.strip(), "metadata": metadata or {}})
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append({"text": current.strip(), "metadata": metadata or {}})

    return chunks


def _chunk_directory(dir_path: str) -> list[dict]:
    """Chunk all text files in directory."""
    extensions = [".md", ".txt", ".py", ".java", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".xml", ".html", ".cfg", ".ini", ".sh"]
    chunks = []
    for root, _, files in os.walk(dir_path):
        if any(skip in root for skip in ["node_modules", "__pycache__", ".git", "build", "dist", ".gradle"]):
            continue
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, dir_path)
            try:
                with open(fpath) as f:
                    content = f.read()
                if len(content) > 50:
                    for chunk in _chunk_text(content, metadata={"file": relpath}):
                        chunk["metadata"]["file"] = relpath
                        chunks.append(chunk)
            except Exception:
                continue
    return chunks


# ---- Code Package AST Analysis ----

def _fetch_code_package(dir_path: str) -> list[dict]:
    """Parse code package with function-level extraction."""
    if not os.path.isdir(dir_path):
        return []

    chunks = []
    code_extensions = {
        ".py": _extract_python_functions,
        ".java": _extract_java_functions,
        ".ts": _extract_ts_functions,
        ".tsx": _extract_ts_functions,
        ".js": _extract_ts_functions,
    }

    for root, _, files in os.walk(dir_path):
        if any(skip in root for skip in ["node_modules", "__pycache__", ".git", "build", "dist", ".gradle", "test"]):
            continue
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1]
            if ext not in code_extensions:
                continue
            fpath = os.path.join(root, fname)
            relpath = os.path.relpath(fpath, dir_path)
            try:
                with open(fpath) as f:
                    content = f.read()
                # Extract functions
                extractor = code_extensions[ext]
                functions = extractor(content, relpath)
                for func in functions:
                    chunks.append(func)
                # Also add file-level summary
                if len(content) > 100:
                    chunks.append({
                        "text": f"File: {relpath}\n{content[:500]}",
                        "metadata": {"file": relpath, "type": "file_summary"},
                    })
            except Exception:
                continue
    return chunks


def _extract_python_functions(content: str, filepath: str) -> list[dict]:
    """Extract Python functions/classes with docstrings."""
    chunks = []
    # Simple regex-based extraction (no tree-sitter dependency)
    pattern = r'^(class |def )(\w+)\s*\(([^)]*)\).*?(?=\n(?:class |def )|\Z)'
    for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
        kind = "class" if match.group(1).startswith("class") else "function"
        name = match.group(2)
        params = match.group(3)
        body = match.group(0)[:800]
        # Extract imports from file
        imports = [line.strip() for line in content.split("\n") if line.strip().startswith(("import ", "from "))][:10]
        text = f"{kind} {name}({params}) in {filepath}\n\n{body}"
        chunks.append({
            "text": text,
            "metadata": {
                "file": filepath,
                "type": kind,
                "name": name,
                "imports": imports[:5],
            },
        })
    return chunks


def _extract_java_functions(content: str, filepath: str) -> list[dict]:
    """Extract Java methods/classes."""
    chunks = []
    pattern = r'(public|private|protected)\s+(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+(?:\s*,\s*\w+)*)?\s*\{'
    for match in re.finditer(pattern, content):
        name = match.group(2)
        params = match.group(3)
        start = match.start()
        snippet = content[max(0, start - 50):start + 500]
        text = f"method {name}({params}) in {filepath}\n\n{snippet}"
        chunks.append({
            "text": text,
            "metadata": {"file": filepath, "type": "method", "name": name},
        })
    return chunks


def _extract_ts_functions(content: str, filepath: str) -> list[dict]:
    """Extract TypeScript/JavaScript functions."""
    chunks = []
    patterns = [
        r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
        r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            name = match.group(1)
            params = match.group(2)
            start = match.start()
            snippet = content[max(0, start):start + 500]
            text = f"function {name}({params}) in {filepath}\n\n{snippet}"
            chunks.append({
                "text": text,
                "metadata": {"file": filepath, "type": "function", "name": name},
            })
    return chunks


# ---- LLM Enrichment Passes ----

def _summarize_chunk(text: str, config: dict) -> Optional[str]:
    """Pass 2: LLM summarizes chunk in 2-3 sentences."""
    from llm_parser import parse_with_llm
    try:
        prompt = f"Summarize in 2-3 sentences. Be specific about services, APIs, functions mentioned:\n\n{text[:600]}"
        result = parse_with_llm(prompt, config, timeout=60)
        return result[:300] if result else None
    except Exception:
        return None


def _generate_tags(text: str, config: dict) -> list[str]:
    """Pass 3: LLM auto-generates tags."""
    from llm_parser import parse_json_with_llm
    try:
        prompt = f'Generate 3-5 tags for this content. Tags: project name, service name, technology, domain. Reply ONLY with JSON array: ["tag1", "tag2"]\n\nContent: {text[:400]}'
        result = parse_json_with_llm(prompt, config, timeout=60)
        if isinstance(result, list):
            return [str(t).lower().strip() for t in result[:5]]
        if isinstance(result, dict) and "tags" in result:
            return [str(t).lower().strip() for t in result["tags"][:5]]
    except Exception:
        pass
    return []


def _find_and_create_links(mem, memory_id: int, text: str) -> int:
    """Pass 6: Find related entries and create knowledge graph edges."""
    try:
        results = mem.search(text, limit=5)
        edge_count = 0
        for r in results:
            if r["id"] != memory_id and r["score"] > 0.6:
                mem.create_edge(memory_id, r["id"], "related")
                edge_count += 1
        return edge_count
    except Exception:
        return 0
