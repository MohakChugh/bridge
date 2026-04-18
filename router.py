"""Route messages: legacy router kept for backward compat with old tests.

All actual routing now goes through adapters/. This file retains
spawn_claude_session for existing test_router.py compatibility."""

from __future__ import annotations
from typing import Optional
import json
import re
import shlex
import subprocess


def _extract_summary(output: str, max_chars: int = 0) -> str:
    """Extract a readable summary from claude -p JSON output."""
    try:
        data = json.loads(output)
        if isinstance(data, dict) and "result" in data:
            text = data["result"]
        elif isinstance(data, dict) and "content" in data:
            text = data["content"]
        else:
            text = str(data)
    except (json.JSONDecodeError, TypeError):
        text = output

    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = text.strip()

    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars - 3] + "..."
    return text


def _extract_session_id(output: str) -> Optional[str]:
    """Extract session_id from claude -p JSON output."""
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            return data.get("session_id")
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def spawn_claude_session(prompt: str, cwd: str, timeout: int = 18000, resume_session_id: Optional[str] = None, process_holder: object = None) -> dict:
    """Legacy spawn function — kept for test compatibility."""
    try:
        brief_instruction = "You are replying via iMessage text. Respond like a WhatsApp or text message — casual, short, plain text. No markdown ever. Keep it brief but complete."
        cmd = "claude -p " + shlex.quote(prompt) + " --output-format json --dangerously-skip-permissions --effort max --append-system-prompt " + shlex.quote(brief_instruction)
        if resume_session_id:
            cmd += " --resume " + shlex.quote(resume_session_id)

        proc = subprocess.Popen(
            ["zsh", "-i", "-c", cmd],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if process_holder and hasattr(process_holder, '_active_process'):
            process_holder._active_process = proc

        stdout, stderr = proc.communicate(timeout=timeout)

        if proc.returncode == 0:
            summary = _extract_summary(stdout)
            session_id = _extract_session_id(stdout)
            return {"success": True, "output": summary, "error": "", "session_id": session_id}
        else:
            return {"success": False, "output": "", "error": stderr[:200] or f"exit code {proc.returncode}", "session_id": None}
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "claude CLI not found in PATH", "session_id": None}
