"""Workflow persistence — CRUD for workflows.json."""

from __future__ import annotations
import json
import os
import threading as _threading
import time
import uuid
from typing import Optional

WORKFLOWS_PATH = os.environ.get(
    "BRIDGE_WORKFLOWS_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflows.json"),
)

# Reentrant lock — upsert/delete call load/save internally while holding the lock.
_STORE_LOCK = _threading.RLock()


def load_workflows(path: str = WORKFLOWS_PATH) -> list[dict]:
    with _STORE_LOCK:
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []


def save_workflows(path: str, workflows: list[dict]) -> None:
    with _STORE_LOCK:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(workflows, f, indent=2)
        os.replace(tmp, path)


def get_workflow(path: str, wf_id: str) -> Optional[dict]:
    with _STORE_LOCK:
        for wf in load_workflows(path):
            if wf.get("id") == wf_id:
                return wf
        return None


def upsert_workflow(path: str, wf: dict) -> dict:
    with _STORE_LOCK:
        workflows = load_workflows(path)
        now = time.time()
        if not wf.get("id"):
            wf["id"] = str(uuid.uuid4())
            wf["created_at"] = now
        wf["updated_at"] = now
        idx = next((i for i, w in enumerate(workflows) if w.get("id") == wf["id"]), -1)
        if idx >= 0:
            workflows[idx] = wf
        else:
            workflows.append(wf)
        save_workflows(path, workflows)
        return wf


def delete_workflow(path: str, wf_id: str) -> bool:
    with _STORE_LOCK:
        workflows = load_workflows(path)
        before = len(workflows)
        workflows = [w for w in workflows if w.get("id") != wf_id]
        if len(workflows) < before:
            save_workflows(path, workflows)
            return True
        return False
