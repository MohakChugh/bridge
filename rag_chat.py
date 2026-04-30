"""RAG Chat — retrieval-augmented chatbot with action support.

Powers the floating chat overlay. Searches knowledge base, reports
system status, and can trigger actions (workflows, sessions, discovery).
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Optional

log = logging.getLogger("rag_chat")

STATUS_KEYWORDS = {
    "running", "status", "active", "busy", "progress", "happening",
    "jobs", "workflow", "session", "watch", "schedule", "operation",
    "bank", "rotation", "cipher", "outage", "pgp", "tls", "cert",
    "deprecat", "migration", "maintenance",
}
ACTION_KEYWORDS = {
    "run", "start", "create", "trigger", "launch", "refresh",
    "ingest", "discover", "search for", "execute",
}
RAG_THRESHOLD = 0.0
RAG_LIMIT = 10
RAG_TOP_K = 6
MAX_NEIGHBORS = 3
MAX_CONTEXT_CHARS = 16000


def _classify_intent(query: str) -> set[str]:
    lower = query.lower()
    intents = set()
    if any(kw in lower for kw in STATUS_KEYWORDS):
        intents.add("status")
    if any(kw in lower for kw in ACTION_KEYWORDS):
        intents.add("action")
    intents.add("knowledge")
    return intents


def _retrieve(query: str) -> tuple[list[dict], list[dict]]:
    from shared_memory import get_shared_memory
    mem = get_shared_memory()
    results = mem.search(query, collections=None, limit=RAG_LIMIT)
    relevant = [r for r in results if r["score"] > RAG_THRESHOLD][:RAG_TOP_K]

    sources = []
    for r in relevant:
        edges = mem.get_edges(r["id"])
        neighbor_summaries = []
        seen = set()
        for e in edges:
            nid = e["target_id"] if e["source_id"] == r["id"] else e["source_id"]
            if nid in seen:
                continue
            seen.add(nid)
            if len(neighbor_summaries) >= MAX_NEIGHBORS:
                break
            row = mem.db.execute(
                "SELECT summary, text FROM memories WHERE id = ?", (nid,)
            ).fetchone()
            if row:
                neighbor_summaries.append(
                    row["summary"] or (row["text"][:150] + "...")
                )
        r["neighbors"] = neighbor_summaries
        sources.append({
            "collection": r["collection"],
            "text_preview": r["text"][:120],
            "score": r["score"],
        })
    return relevant, sources


def _build_status(session_manager, daemon_ref) -> str:
    parts = []
    try:
        sessions = session_manager.list()
        busy = [s for s in sessions if s.status == "busy"]
        parts.append(f"{len(sessions)} sessions ({len(busy)} busy)")
        if busy:
            names = ", ".join(s.title[:30] for s in busy[:3])
            parts.append(f"  busy: {names}")
    except Exception:
        parts.append("sessions: unavailable")

    try:
        from workflow_store import load_workflows
        from workflow_engine import WorkflowEngine
        wfs = load_workflows()
        parts.append(f"{len(wfs)} workflows defined")
    except Exception:
        pass

    try:
        state = daemon_ref.state if hasattr(daemon_ref, "state") else {}
        watches = state.get("watches", [])
        active_watches = [w for w in watches if isinstance(w, dict) and w.get("status") == "active"]
        parts.append(f"{len(active_watches)} active watches")

        schedules = state.get("schedules", [])
        active_sched = [s for s in schedules if isinstance(s, dict) and s.get("status") != "paused"]
        parts.append(f"{len(active_sched)} active schedules")

        reminders = state.get("reminders", [])
        parts.append(f"{len(reminders)} reminders")
    except Exception:
        pass

    return "\n".join(parts) if parts else "No status data available."


def _build_prompt(query: str, history: list[dict], chunks: list[dict],
                  status_text: str, intents: set[str]) -> str:
    prompt = """You are Bridge Assistant — AI for a knowledge management and automation platform.

CAPABILITIES:
- Answer questions using KNOWLEDGE CONTEXT below
- Report system status from LIVE STATUS below
- Suggest actions the user can take

When you want to suggest a clickable action button, emit EXACTLY this format on its own lines:
[ACTION type="search_memory" params='{"query":"example"}' label="Search for Example"]

Supported types: run_workflow, create_session, refresh_document, discover, search_memory, navigate

Rules:
- Answer based PRIMARILY on KNOWLEDGE CONTEXT. Use it fully.
- Be thorough. Use markdown: headers, bullet lists, bold, code blocks.
- Cite the collection name in parentheses when referencing knowledge.
- If context has relevant info, synthesize a comprehensive answer.
- Only say "no info" if context is truly empty or irrelevant.

"""
    if chunks:
        prompt += "KNOWLEDGE CONTEXT:\n"
        total = 0
        for r in chunks:
            block = f"[{r['collection']}] (score: {r['score']})\n{r['text'][:1500]}\n"
            for nb in r.get("neighbors", []):
                block += f"  Related: {nb}\n"
            block += "\n"
            if total + len(block) > MAX_CONTEXT_CHARS:
                break
            prompt += block
            total += len(block)

    if "status" in intents or "action" in intents:
        prompt += f"LIVE STATUS:\n{status_text}\n\n"

    if history:
        prompt += "CONVERSATION:\n"
        for h in history[-6:]:
            prompt += f"{h['role'].upper()}: {h['text'][:300]}\n"
        prompt += "\n"

    prompt += f"USER: {query}\n\nASSISTANT:"
    return prompt


def _parse_actions(text: str) -> tuple[str, list[dict]]:
    actions = []
    pattern = r'\[ACTION\s+type=["\']?([^"\'"\s]+)["\']?\s+params=["\']?(\{[^}]*\})["\']?\s+label=["\']?([^"\'"\]]+)["\']?\s*\]'
    for m in re.finditer(pattern, text, re.IGNORECASE):
        action_type = m.group(1).strip()
        try:
            params = json.loads(m.group(2).strip())
        except (json.JSONDecodeError, ValueError):
            params = {}
        label = m.group(3).strip()
        if action_type and label:
            actions.append({"type": action_type, "params": params, "label": label})

    clean = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    clean = re.sub(r"[│|]+\s*(?:>{2,3})?\s*ACTION.*?<<<\s*ACTION", "", clean, flags=re.DOTALL).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean, actions


def chat(query: str, history: list[dict], config: dict,
         session_manager, daemon_ref) -> dict:
    if not query.strip():
        return {"response": "Please ask a question.", "sources": [], "actions": [], "status_included": False}

    intents = _classify_intent(query)
    chunks, sources = _retrieve(query)
    status_text = ""
    if "status" in intents or "action" in intents:
        status_text = _build_status(session_manager, daemon_ref)

    prompt = _build_prompt(query, history, chunks, status_text, intents)

    from llm_parser import parse_with_llm
    raw = parse_with_llm(prompt, config, timeout=120)

    if not raw:
        return {
            "response": "Sorry, I couldn't generate a response. The LLM adapter may be unavailable.",
            "sources": sources,
            "actions": [],
            "status_included": bool(status_text),
        }

    clean_text, actions = _parse_actions(raw)
    return {
        "response": clean_text,
        "sources": sources,
        "actions": actions,
        "status_included": bool(status_text),
    }


def execute_action(action_type: str, params: dict, config: dict,
                   session_manager, daemon_ref) -> dict:
    try:
        if action_type == "search_memory":
            from shared_memory import get_shared_memory
            q = params.get("query", "")
            results = get_shared_memory().search(q, limit=params.get("limit", 5))
            text = "\n".join(
                f"- [{r['collection']}] {r['text'][:200]} (score: {r['score']})"
                for r in results
            )
            return {"success": True, "result": text or "No results found."}

        elif action_type == "run_workflow":
            from workflow_store import load_workflows
            from workflow_engine import WorkflowEngine
            wf_id = params.get("workflow_id", "")
            wfs = load_workflows()
            wf = next((w for w in wfs if w["id"] == wf_id), None)
            if not wf:
                return {"success": False, "result": f"Workflow '{wf_id}' not found."}
            engine = WorkflowEngine(session_manager, lambda: config, daemon_ref=daemon_ref)
            run = engine.run(wf)
            return {"success": True, "result": f"Workflow '{wf.get('name', wf_id)}' started. Run ID: {run['id']}"}

        elif action_type == "create_session":
            tool = params.get("tool", config.get("cli_tool", "claude"))
            cwd = params.get("cwd", "/tmp")
            prompt = params.get("prompt", "")
            sess = session_manager.create(tool=tool, cwd=cwd, title=prompt[:50])
            if prompt:
                session_manager.execute(sess.id, prompt)
            return {"success": True, "result": f"Session '{sess.title}' created (ID: {sess.id})."}

        elif action_type == "refresh_document":
            doc_id = params.get("doc_id", "")
            from shared_memory import get_shared_memory
            from knowledge_ingestion import ingest_document
            import threading
            def _refresh():
                try:
                    ingest_document(doc_id, config)
                except Exception as e:
                    log.error(f"Refresh failed for {doc_id}: {e}")
            threading.Thread(target=_refresh, daemon=True).start()
            return {"success": True, "result": f"Document refresh started for '{doc_id}'."}

        elif action_type == "discover":
            target = params.get("target", "")
            from knowledge_discovery import start_discovery
            job = start_discovery(target, config, params.get("scope"), params.get("collection"))
            return {"success": True, "result": f"Discovery started for '{target}'. Job ID: {job.get('job_id', 'unknown')}"}

        elif action_type == "delegate_to_agent":
            title = params.get("title", "Agent Task")
            description = params.get("description", "")
            mode = params.get("mode")
            try:
                from agent_brain import get_agent_brain
                brain = get_agent_brain()
                task = brain.create_task(title, description, mode)
                return {"success": True, "result": f"Agent task '{title}' created (ID: {task['id']}). View in Agent tab.", "navigate": "agent"}
            except Exception as e:
                return {"success": False, "result": f"Failed to create agent task: {e}"}

        elif action_type == "navigate":
            view = params.get("view", "dashboard")
            return {"success": True, "result": f"Navigate to: {view}", "navigate": view}

        else:
            return {"success": False, "result": f"Unknown action type: {action_type}"}

    except Exception as e:
        log.error(f"Action execution failed: {action_type} — {e}")
        return {"success": False, "result": f"Action failed: {str(e)}"}
