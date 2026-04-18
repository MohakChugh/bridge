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

    # Strip ANSI codes and markdown formatting
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"```[\s\S]*?```", "", text)  # code blocks
    text = re.sub(r"`([^`]+)`", r"\1", text)     # inline code
    text = re.sub(r"#{1,6}\s+", "", text)         # headers
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*([^*]+)\*", r"\1", text)      # italic
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
    text = text.strip()

    if max_chars > 0 and len(text) > max_chars:
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


def _shell_quote(s: str) -> str:
    """Shell-escape a string for safe embedding in a zsh -c command."""
    import shlex
    return shlex.quote(s)


def _extract_session_id(output: str) -> Optional[str]:
    """Extract session_id from claude -p JSON output."""
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            return data.get("session_id")
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def spawn_claude_session(prompt: str, cwd: str, timeout: int = 600, resume_session_id: Optional[str] = None, process_holder: object = None) -> dict:
    """Spawn a new claude -p session (or resume existing) and capture output."""
    try:
        brief_instruction = "You are replying via iMessage text. Respond like a WhatsApp or text message — casual, short, plain text. No markdown ever (no backticks, asterisks, hashes, bullets, code blocks). Just natural conversational text like you are texting a friend who asked for help. If sharing code or commands, just write them inline as plain text. Keep it brief but complete."
        claude_cmd = "claude -p " + _shell_quote(prompt) + " --output-format json --dangerously-skip-permissions --effort max --append-system-prompt " + _shell_quote(brief_instruction)
        if resume_session_id:
            claude_cmd += " --resume " + _shell_quote(resume_session_id)

        proc = subprocess.Popen(
            ["zsh", "-l", "-c", claude_cmd],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Store process handle for /cancel support
        if process_holder and hasattr(process_holder, '_active_process'):
            process_holder._active_process = proc

        stdout, stderr = proc.communicate(timeout=timeout)

        if proc.returncode == 0:
            summary = _extract_summary(stdout)
            session_id = _extract_session_id(stdout)
            return {"success": True, "output": summary, "error": "", "session_id": session_id}
        else:
            return {
                "success": False,
                "output": "",
                "error": stderr[:200] or f"exit code {proc.returncode}",
                "session_id": None,
            }
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
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
