"""AI document generation + diagram pipeline.

Generates markdown content via LLM with RAG context retrieval,
streams chunks to the UI via event bus, and produces architecture
diagrams using the ``diagrams`` Python library.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import Optional

log = logging.getLogger("doc_gen")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 60
CHUNK_DELAY_S = 0.04          # 40 ms between streamed chunks
HEARTBEAT_INTERVAL_S = 3.0    # empty chunk every 3 s while waiting for LLM
MAX_RAG_CONTEXT_CHARS = 12000
MAX_EXISTING_CHARS = 3000
RAG_PRIMARY_LIMIT = 7
RAG_SECONDARY_LIMIT = 4
RAG_MAX_RESULTS = 7
RAG_MIN_SCORE = 0.15
LLM_TIMEOUT = 300
DIAGRAM_SUBPROCESS_TIMEOUT = 60

# ---------------------------------------------------------------------------
# Wrapper patterns stripped from raw LLM output
# ---------------------------------------------------------------------------

_WRAPPER_PREFIXES = [
    "Here is the content:\n\n",
    "Here is the markdown content:\n\n",
    "Here is the generated content:\n\n",
    "Here's the content:\n\n",
    "Here's the markdown content:\n\n",
    "Here's the generated content:\n\n",
    "Sure, here is the content:\n\n",
    "Sure, here's the content:\n\n",
]


# ===================================================================
# Public API
# ===================================================================

def generate_content(
    doc_id: str,
    generation_id: str,
    prompt: str,
    existing_content: str,
    insert_at: Optional[int],
    config: dict,
) -> None:
    """Run content generation in a background thread.

    Publishes events via the event bus:
      - doc.generation.started
      - doc.generation.chunk   (repeated)
      - doc.generation.completed | doc.generation.failed
    """
    t = threading.Thread(
        target=_generate_content_worker,
        args=(doc_id, generation_id, prompt, existing_content, insert_at, config),
        daemon=True,
    )
    t.start()


def edit_selection(
    doc_id: str,
    generation_id: str,
    selected_text: str,
    line_start: int,
    line_end: int,
    feedback: str,
    full_content: str,
    config: dict,
) -> None:
    """Edit a selection of text based on user feedback."""
    t = threading.Thread(
        target=_edit_selection_worker,
        args=(doc_id, generation_id, selected_text, line_start, line_end,
              feedback, full_content, config),
        daemon=True,
    )
    t.start()


def generate_diagram(
    doc_id: str,
    diagram_id: str,
    prompt: str,
    config: dict,
) -> None:
    """Run diagram generation in a background thread.

    Publishes events via the event bus:
      - doc.diagram.started
      - doc.diagram.completed | doc.diagram.failed
    """
    t = threading.Thread(
        target=_generate_diagram_worker,
        args=(doc_id, diagram_id, prompt, config),
        daemon=True,
    )
    t.start()


# ===================================================================
# Content generation worker
# ===================================================================

def _generate_content_worker(
    doc_id: str,
    generation_id: str,
    prompt: str,
    existing_content: str,
    insert_at: Optional[int],
    config: dict,
) -> None:
    from event_bus import get_event_bus

    bus = get_event_bus()

    try:
        # 1. Publish started
        bus.publish("doc.generation.started", {
            "doc_id": doc_id,
            "generation_id": generation_id,
            "prompt": prompt,
        })

        # 2. Start heartbeat thread
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(bus, doc_id, generation_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()

        # 3. RAG context
        context = _retrieve_context(prompt, existing_content)

        # 4. Build prompt
        full_prompt = _build_generation_prompt(prompt, existing_content, context)

        # 5. Call LLM (blocking)
        from llm_parser import parse_with_llm

        raw = parse_with_llm(full_prompt, config, timeout=LLM_TIMEOUT)

        # 6. Stop heartbeat
        heartbeat_stop.set()
        heartbeat.join(timeout=5)

        if not raw:
            bus.publish("doc.generation.failed", {
                "doc_id": doc_id,
                "generation_id": generation_id,
                "error": "LLM returned empty output",
            })
            return

        # 7. Clean output
        content = _clean_output(raw)

        # 8. Stream chunks
        _stream_chunks(bus, doc_id, generation_id, content)

        # 9. Auto-save
        _auto_save(doc_id, content, insert_at)

        # 10. Publish completed
        bus.publish("doc.generation.completed", {
            "doc_id": doc_id,
            "generation_id": generation_id,
            "length": len(content),
        })

    except Exception as exc:
        log.exception("Content generation failed for doc=%s gen=%s", doc_id, generation_id)
        # Ensure heartbeat is stopped on error path
        try:
            heartbeat_stop.set()
        except Exception:
            pass
        bus.publish("doc.generation.failed", {
            "doc_id": doc_id,
            "generation_id": generation_id,
            "error": str(exc),
        })


# ===================================================================
# Diagram generation worker
# ===================================================================

def _generate_diagram_worker(
    doc_id: str,
    diagram_id: str,
    prompt: str,
    config: dict,
) -> None:
    from event_bus import get_event_bus

    bus = get_event_bus()

    try:
        # 1. Publish started
        bus.publish("doc.diagram.started", {
            "doc_id": doc_id,
            "diagram_id": diagram_id,
            "prompt": prompt,
        })

        # 2. Build diagram prompt
        diagram_prompt = _build_diagram_prompt(prompt)

        # 3. Call LLM
        from llm_parser import parse_with_llm

        raw = parse_with_llm(diagram_prompt, config, timeout=LLM_TIMEOUT)
        if not raw:
            bus.publish("doc.diagram.failed", {
                "doc_id": doc_id,
                "diagram_id": diagram_id,
                "error": "LLM returned empty output",
            })
            return

        # 4. Extract Python code from markdown code blocks
        code = _extract_python_code(raw)
        if not code:
            bus.publish("doc.diagram.failed", {
                "doc_id": doc_id,
                "diagram_id": diagram_id,
                "error": "No Python code block found in LLM output",
            })
            return

        # 5. Determine output path and patch code
        import doc_store

        asset_dir = doc_store.get_asset_dir(doc_id)
        os.makedirs(asset_dir, exist_ok=True)
        png_basename = f"diagram_{diagram_id}"
        png_path = os.path.join(asset_dir, png_basename)  # without .png — diagrams adds it
        patched_code = _patch_diagram_output(code, png_path)

        # 6. Execute in subprocess
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=tempfile.gettempdir()
        ) as tmp:
            tmp.write(patched_code)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["python3", tmp_path],
                capture_output=True,
                text=True,
                timeout=DIAGRAM_SUBPROCESS_TIMEOUT,
                cwd=asset_dir,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                log.error("Diagram subprocess failed: %s", stderr)
                bus.publish("doc.diagram.failed", {
                    "doc_id": doc_id,
                    "diagram_id": diagram_id,
                    "error": f"Subprocess error: {stderr[:500]}",
                })
                return
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # 7. Save PNG via doc_store
        png_file = png_path + ".png"
        if not os.path.isfile(png_file):
            bus.publish("doc.diagram.failed", {
                "doc_id": doc_id,
                "diagram_id": diagram_id,
                "error": "Diagram PNG was not generated",
            })
            return

        url = doc_store.save_asset(doc_id, png_file)

        # 8. Publish completed
        bus.publish("doc.diagram.completed", {
            "doc_id": doc_id,
            "diagram_id": diagram_id,
            "url": url,
        })

    except Exception as exc:
        log.exception("Diagram generation failed for doc=%s diagram=%s", doc_id, diagram_id)
        bus.publish("doc.diagram.failed", {
            "doc_id": doc_id,
            "diagram_id": diagram_id,
            "error": str(exc),
        })


# ===================================================================
# Selection edit worker
# ===================================================================

def _edit_selection_worker(
    doc_id: str,
    generation_id: str,
    selected_text: str,
    line_start: int,
    line_end: int,
    feedback: str,
    full_content: str,
    config: dict,
) -> None:
    from event_bus import get_event_bus

    bus = get_event_bus()

    try:
        bus.publish("doc.generation.started", {
            "doc_id": doc_id, "generation_id": generation_id,
            "mode": "edit_selection",
        })

        # Heartbeat
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=_heartbeat_loop,
            args=(bus, doc_id, generation_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()

        # RAG context for the selection
        context = _retrieve_context(selected_text + " " + feedback, full_content)

        # Build selection-aware prompt
        prompt = _build_edit_selection_prompt(
            selected_text, line_start, line_end, feedback, full_content, context,
        )

        from llm_parser import parse_with_llm

        raw = parse_with_llm(prompt, config, timeout=LLM_TIMEOUT)

        heartbeat_stop.set()
        heartbeat.join(timeout=5)

        if not raw:
            bus.publish("doc.generation.failed", {
                "doc_id": doc_id, "generation_id": generation_id,
                "error": "LLM returned empty",
            })
            return

        replacement = _clean_output(raw)

        # Replace the selection in the full content
        new_content = full_content.replace(selected_text, replacement, 1)

        # Stream the replacement
        _stream_chunks(bus, doc_id, generation_id, replacement)

        # Save the full updated document
        from doc_store import get_doc_store

        get_doc_store().update(doc_id, content=new_content)

        bus.publish("doc.generation.completed", {
            "doc_id": doc_id, "generation_id": generation_id,
            "length": len(replacement), "mode": "edit_selection",
            "original_length": len(selected_text),
        })
    except Exception as exc:
        log.exception("Selection edit failed")
        try:
            heartbeat_stop.set()
        except Exception:
            pass
        bus.publish("doc.generation.failed", {
            "doc_id": doc_id, "generation_id": generation_id,
            "error": str(exc),
        })


def _build_edit_selection_prompt(
    selected_text: str,
    line_start: int,
    line_end: int,
    feedback: str,
    full_content: str,
    context: list[dict],
) -> str:
    parts = [
        "You are editing a specific section of a markdown document.",
        "The user has selected text and provided feedback on how to change it.",
        "Output ONLY the replacement text — no explanations, no wrapper.",
        "Maintain the same markdown formatting level (headings, lists, etc.).",
        "",
    ]

    if context:
        parts.append("KNOWLEDGE CONTEXT:")
        total = 0
        for r in context:
            block = f"[{r.get('collection', '')}] {r.get('text', '')[:800]}\n"
            if total + len(block) > 6000:
                break
            parts.append(block)
            total += len(block)
        parts.append("")

    # Show surrounding document context (300 chars before/after)
    sel_pos = full_content.find(selected_text)
    if sel_pos >= 0:
        before = full_content[max(0, sel_pos - 300):sel_pos].strip()
        after = full_content[sel_pos + len(selected_text):sel_pos + len(selected_text) + 300].strip()
        if before:
            parts.append(f"CONTEXT BEFORE SELECTION:\n...{before}\n")
        if after:
            parts.append(f"CONTEXT AFTER SELECTION:\n{after}...\n")

    parts.append(f"SELECTED TEXT (lines {line_start}-{line_end}):")
    parts.append(f"```markdown\n{selected_text}\n```")
    parts.append(f"\nUSER FEEDBACK: {feedback}")
    parts.append("\nWrite the replacement text now:")

    return "\n".join(parts)


# ===================================================================
# Helpers — RAG context
# ===================================================================

def _retrieve_context(prompt: str, existing_content: str) -> list[dict]:
    """Retrieve RAG context from shared memory.

    Searches prompt (limit=8) and first 200 chars of existing content
    (limit=4). Deduplicates by ID, filters score > 0.0, caps at 10 results.
    """
    from shared_memory import get_shared_memory

    mem = get_shared_memory()
    seen_ids: set[int] = set()
    results: list[dict] = []

    # Primary search on prompt
    try:
        primary = mem.search(prompt, limit=RAG_PRIMARY_LIMIT)
        for r in primary:
            if r["id"] not in seen_ids and r["score"] > RAG_MIN_SCORE:
                seen_ids.add(r["id"])
                results.append(r)
    except Exception as exc:
        log.warning("RAG primary search failed: %s", exc)

    # Secondary search on beginning of existing content
    snippet = (existing_content or "")[:200].strip()
    if snippet:
        try:
            secondary = mem.search(snippet, limit=RAG_SECONDARY_LIMIT)
            for r in secondary:
                if r["id"] not in seen_ids and r["score"] > RAG_MIN_SCORE:
                    seen_ids.add(r["id"])
                    results.append(r)
        except Exception as exc:
            log.warning("RAG secondary search failed: %s", exc)

    # Sort by score descending, cap at max
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:RAG_MAX_RESULTS]


# ===================================================================
# Helpers — prompt building
# ===================================================================

def _build_generation_prompt(
    prompt: str,
    existing_content: str,
    context: list[dict],
) -> str:
    """Assemble the full prompt sent to the LLM for content generation."""

    # Build knowledge context block with source attribution
    context_parts: list[str] = []
    char_count = 0
    for i, chunk in enumerate(context, 1):
        text = chunk.get("text", "")
        collection = chunk.get("collection", "unknown")
        score = chunk.get("score", 0)
        source_line = f"[Source {i}: {collection} (relevance: {score:.0%})]"
        entry = f"{source_line}\n{text}"
        if char_count + len(entry) > MAX_RAG_CONTEXT_CHARS:
            remaining = MAX_RAG_CONTEXT_CHARS - char_count
            if remaining > 150:
                entry = entry[:remaining]
            else:
                break
        context_parts.append(entry)
        char_count += len(entry)

    knowledge_block = "\n---\n".join(context_parts) if context_parts else "(no context available)"

    # Truncate existing content
    existing_block = ""
    if existing_content:
        truncated = existing_content[:MAX_EXISTING_CHARS]
        if len(existing_content) > MAX_EXISTING_CHARS:
            truncated += "\n... (truncated)"
        existing_block = truncated

    parts = [
        "You are a technical document writer. Generate well-structured markdown content.",
        "Rules:",
        "- Use proper markdown: ##, ###, bullets, code blocks, bold, tables",
        "- Be thorough and detailed",
        "- Incorporate knowledge context naturally",
        "- Use ```mermaid blocks for flowcharts/sequences/ERDs",
        "- Output ONLY markdown content, no wrapper text",
        "",
        f"KNOWLEDGE CONTEXT:\n{knowledge_block}",
        "",
    ]

    if existing_block:
        parts.append(f"EXISTING DOCUMENT:\n{existing_block}")
        parts.append("")

    parts.append(f"USER REQUEST: {prompt}")
    parts.append("Generate the markdown content now:")

    return "\n".join(parts)


def _build_diagram_prompt(prompt: str) -> str:
    """Build the LLM prompt for diagram code generation."""
    return (
        "You are a Python code generator. Generate Python code that uses the "
        "`diagrams` library (https://diagrams.mingrammer.com/) to create an "
        "architecture diagram.\n\n"
        "Rules:\n"
        "- Import from `diagrams`, `diagrams.aws.*`, `diagrams.onprem.*`, "
        "`diagrams.generic.*`, etc. as needed\n"
        "- Use `with Diagram(...)` context manager\n"
        "- Set `show=False` so it only saves the file\n"
        "- Output ONLY the Python code inside a ```python code block\n"
        "- Do NOT include pip install commands or explanations\n\n"
        f"DIAGRAM REQUEST: {prompt}\n\n"
        "Generate the Python code now:"
    )


# ===================================================================
# Helpers — streaming
# ===================================================================

def _stream_chunks(
    bus: object,
    doc_id: str,
    generation_id: str,
    content: str,
) -> None:
    """Stream content in fixed-size chunks with delay between each."""
    offset = 0
    while offset < len(content):
        chunk = content[offset:offset + CHUNK_SIZE]
        bus.publish("doc.generation.chunk", {
            "doc_id": doc_id,
            "generation_id": generation_id,
            "chunk": chunk,
            "offset": offset,
        })
        offset += len(chunk)
        time.sleep(CHUNK_DELAY_S)


def _heartbeat_loop(
    bus: object,
    doc_id: str,
    generation_id: str,
    stop_event: threading.Event,
) -> None:
    """Publish empty heartbeat chunks every few seconds while LLM is working."""
    while not stop_event.is_set():
        stop_event.wait(timeout=HEARTBEAT_INTERVAL_S)
        if stop_event.is_set():
            break
        bus.publish("doc.generation.chunk", {
            "doc_id": doc_id,
            "generation_id": generation_id,
            "chunk": "",
            "offset": -1,
        })


# ===================================================================
# Helpers — output cleaning
# ===================================================================

def _clean_output(raw: str) -> str:
    """Strip common LLM wrapper preambles from generated content."""
    cleaned = raw
    for prefix in _WRAPPER_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Also strip leading/trailing whitespace
    cleaned = cleaned.strip()
    return cleaned


# ===================================================================
# Helpers — diagram code extraction & patching
# ===================================================================

def _extract_python_code(text: str) -> Optional[str]:
    """Extract Python code from markdown code blocks in LLM output."""
    # Try ```python ... ``` first
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fall back to generic ``` ... ```
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        # Heuristic: must contain "import" or "from" to look like Python
        if "import " in code or "from " in code:
            return code

    return None


def _patch_diagram_output(code: str, png_path: str) -> str:
    """Patch the generated diagram code to set the output filename and disable show."""
    # Replace or inject filename= in the Diagram() constructor
    # Handle: Diagram("name", ...) or Diagram("name")
    patched = re.sub(
        r'(Diagram\s*\([^)]*?)(\))',
        lambda m: _inject_diagram_args(m.group(1), m.group(2), png_path),
        code,
    )
    return patched


def _inject_diagram_args(before: str, closing: str, png_path: str) -> str:
    """Inject or replace filename= and show= in a Diagram() call."""
    # Remove existing filename= and show= if present
    cleaned = re.sub(r',?\s*filename\s*=\s*["\'][^"\']*["\']', '', before)
    cleaned = re.sub(r',?\s*show\s*=\s*(True|False)', '', cleaned)

    # Ensure trailing comma if there are existing args
    cleaned = cleaned.rstrip().rstrip(',')

    # Append our args
    return f'{cleaned}, filename="{png_path}", show=False{closing}'


# ===================================================================
# Helpers — auto-save
# ===================================================================

def _auto_save(doc_id: str, content: str, insert_at: Optional[int]) -> None:
    """Read the document from doc_store, append/insert content, and update."""
    try:
        import doc_store

        doc = doc_store.get_document(doc_id)
        if not doc:
            log.warning("Auto-save: document %s not found in doc_store", doc_id)
            return

        existing = doc.get("content", "")

        if insert_at is not None and 0 <= insert_at <= len(existing):
            updated = existing[:insert_at] + content + existing[insert_at:]
        else:
            # Append with separator
            if existing and not existing.endswith("\n"):
                updated = existing + "\n\n" + content
            elif existing:
                updated = existing + "\n" + content
            else:
                updated = content

        doc_store.update_document(doc_id, updated)
        log.info("Auto-saved %d chars to doc %s", len(content), doc_id)

    except Exception as exc:
        log.warning("Auto-save failed for doc %s: %s", doc_id, exc)
