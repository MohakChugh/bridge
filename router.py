"""Route messages: tmux injection or claude -p subprocess spawn."""

from __future__ import annotations
from typing import Optional
import json
import re
import subprocess
import time


def tmux_session_exists(session_name: str) -> bool:
    """Check if a tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )
    return result.returncode == 0


def tmux_send_keys(session_name: str, text: str) -> None:
    """Send keystrokes to a tmux session."""
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, text, "Enter"],
        capture_output=True,
    )


def tmux_capture_pane(session_name: str, lines: int = 50) -> str:
    """Capture recent output from a tmux pane."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def poll_until_idle(
    session_name: str,
    check_interval: float = 5.0,
    stabilization_checks: int = 2,
    max_timeout: float = 600.0,
) -> str:
    """Poll tmux pane until output stabilizes, then return captured output."""
    start = time.time()
    prev_snapshot = ""
    stable_count = 0

    while time.time() - start < max_timeout:
        time.sleep(check_interval)
        snapshot = tmux_capture_pane(session_name, lines=50)

        if snapshot == prev_snapshot:
            stable_count += 1
            if stable_count >= stabilization_checks:
                return snapshot
        else:
            stable_count = 0
            prev_snapshot = snapshot

    return prev_snapshot


def _extract_summary(output: str, max_chars: int = 500) -> str:
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
    text = text.strip()

    if len(text) > max_chars:
        return text[:max_chars - 3] + "..."
    return text


def _extract_pane_summary(pane_output: str, max_chars: int = 500) -> str:
    """Extract summary from tmux captured pane output."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", pane_output)
    lines = [l for l in text.splitlines() if l.strip()]
    summary_lines = lines[-10:] if len(lines) > 10 else lines
    text = "\n".join(summary_lines).strip()
    if len(text) > max_chars:
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


def spawn_claude_session(prompt: str, cwd: str, timeout: int = 600, resume_session_id: Optional[str] = None) -> dict:
    """Spawn a new claude -p session (or resume existing) and capture output."""
    try:
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            summary = _extract_summary(result.stdout)
            session_id = _extract_session_id(result.stdout)
            return {"success": True, "output": summary, "error": "", "session_id": session_id}
        else:
            return {
                "success": False,
                "output": "",
                "error": result.stderr[:200] or f"exit code {result.returncode}",
                "session_id": None,
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
    except FileNotFoundError:
        return {"success": False, "output": "", "error": "claude CLI not found in PATH", "session_id": None}


def inject_into_session(
    session_name: str,
    prompt: str,
    check_interval: float = 5.0,
    stabilization_checks: int = 2,
    max_timeout: float = 600.0,
) -> dict:
    """Inject a prompt into a running tmux Claude session and wait for output."""
    if not tmux_session_exists(session_name):
        return {
            "success": False,
            "output": "",
            "error": "No active Claude session. Use 'new:' prefix to start one.",
        }

    tmux_send_keys(session_name, f"[iMessage] {prompt}")

    pane_output = poll_until_idle(
        session_name,
        check_interval=check_interval,
        stabilization_checks=stabilization_checks,
        max_timeout=max_timeout,
    )

    summary = _extract_pane_summary(pane_output)
    timed_out = not summary or pane_output == ""
    return {
        "success": not timed_out,
        "output": summary or "Still running, check terminal",
        "error": "" if not timed_out else "Timed out waiting for output",
    }
