"""Session persistence — save/load past sessions to sessions.json."""

from __future__ import annotations
import json
import os
import time
from typing import Optional

SESSIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.json")
MAX_SESSIONS = 100


def load_sessions(path: str = SESSIONS_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_sessions(sessions: list[dict], path: str = SESSIONS_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sessions, f, separators=(",", ":"))
    os.replace(tmp, path)


def save_session(session: dict, path: str = SESSIONS_PATH) -> None:
    sessions = load_sessions(path)
    sid = session.get("id")
    if not sid:
        return
    idx = next((i for i, s in enumerate(sessions) if s.get("id") == sid), -1)
    session["message_count"] = len(session.get("message_history", []))
    if idx >= 0:
        sessions[idx] = session
    else:
        sessions.insert(0, session)
    sessions.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
    if len(sessions) > MAX_SESSIONS:
        sessions = sessions[:MAX_SESSIONS]
    save_sessions(sessions, path)


def get_session(sid: str, path: str = SESSIONS_PATH) -> Optional[dict]:
    for s in load_sessions(path):
        if s.get("id") == sid:
            return s
    return None


def delete_session(sid: str, path: str = SESSIONS_PATH) -> bool:
    sessions = load_sessions(path)
    before = len(sessions)
    sessions = [s for s in sessions if s.get("id") != sid]
    if len(sessions) < before:
        save_sessions(sessions, path)
        return True
    return False
