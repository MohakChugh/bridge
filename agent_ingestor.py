"""Continuous knowledge ingestor — auto-ingests session/workflow/task results into memory.

Subscribes to event bus. On completion events, ingests outputs into shared memory
so the agent brain gets smarter over time.
"""

from __future__ import annotations
import json
import logging
import queue
import threading
import time
from typing import Optional

from event_bus import get_event_bus

log = logging.getLogger("agent_ingestor")


class ContinuousIngestor:
    def __init__(self, config_provider):
        self._config = config_provider
        self._bus = get_event_bus()
        self._queue = self._bus.subscribe()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._ingested_keys: set[str] = set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="agent-ingestor")
        self._thread.start()
        log.info("ContinuousIngestor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self._bus.unsubscribe(self._queue)
        except Exception:
            pass
        log.info("ContinuousIngestor stopped")

    def _run(self):
        while self._running:
            try:
                event = self._queue.get(timeout=2)
            except queue.Empty:
                continue
            except Exception:
                continue

            try:
                self._handle_event(event)
            except Exception as e:
                log.debug(f"Ingestor error handling event: {e}")

    def _handle_event(self, event: dict):
        etype = event.get("type", "")
        data = event.get("data", {})

        if etype == "session.completed":
            self._ingest_session(data)
        elif etype == "workflow.run.completed":
            self._ingest_workflow(data)
        elif etype == "agent.task.completed":
            self._ingest_agent_task(data)

    def _ingest_session(self, data: dict):
        sid = data.get("session_id", "")
        if not sid:
            return
        dedup_key = f"session:{sid}"
        if dedup_key in self._ingested_keys:
            return

        text_parts = []
        final_msg = data.get("final_message", {})
        if final_msg and final_msg.get("text"):
            text_parts.append(final_msg["text"][:2000])

        if not text_parts:
            return

        text = f"Session {sid} completed:\n" + "\n".join(text_parts)
        self._add_to_memory(text, "sessions", {"session_id": sid, "source": "auto_ingest"})
        self._ingested_keys.add(dedup_key)

    def _ingest_workflow(self, data: dict):
        run_id = data.get("id", "") or data.get("run_id", "")
        if not run_id:
            return
        dedup_key = f"workflow:{run_id}"
        if dedup_key in self._ingested_keys:
            return

        wf_name = data.get("workflow_name", "unknown")
        status = data.get("status", "unknown")
        text = f"Workflow '{wf_name}' run {run_id}: {status}"

        node_states = data.get("node_states", {})
        if isinstance(node_states, dict):
            for nid, ns in list(node_states.items())[:10]:
                output = ""
                if isinstance(ns, dict):
                    output = ns.get("output", "")
                elif hasattr(ns, "output"):
                    output = getattr(ns, "output", "")
                if output:
                    text += f"\n  {nid}: {str(output)[:300]}"

        self._add_to_memory(text[:4000], "workflows", {"run_id": run_id, "source": "auto_ingest"})
        self._ingested_keys.add(dedup_key)

    def _ingest_agent_task(self, data: dict):
        task_id = data.get("task_id", "")
        if not task_id:
            return
        dedup_key = f"agent_task:{task_id}"
        if dedup_key in self._ingested_keys:
            return

        result = data.get("result", "")
        if not result:
            return

        text = f"Agent task {task_id} completed:\n{str(result)[:3000]}"
        self._add_to_memory(text, "agent_tasks", {"task_id": task_id, "source": "auto_ingest"})
        self._ingested_keys.add(dedup_key)

    def _add_to_memory(self, text: str, collection: str, metadata: dict):
        try:
            from shared_memory import get_shared_memory
            mem = get_shared_memory()
            mem.add(text, collection=collection, source="auto_ingest", metadata=metadata)
            log.info(f"Auto-ingested into '{collection}': {text[:80]}...")
        except Exception as e:
            log.debug(f"Auto-ingest failed: {e}")
