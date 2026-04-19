"""Real-time progress tracking and stuck detection for Claude Code sessions."""

from __future__ import annotations
from typing import Optional
import json
import logging
import os
import re
import subprocess
import time

log = logging.getLogger("imessage-bridge")


class ProgressTracker:
    """Tracks progress of a running Claude Code session via stream-json events
    and on-disk task files."""

    def __init__(self, session_id: Optional[str] = None, pid: Optional[int] = None):
        self.start_time = time.time()
        self.session_id = session_id
        self._pid = pid
        self.tool_calls: list[dict] = []
        self.current_action: Optional[str] = None
        self.text_chunks: list[str] = []
        self.completed = False
        self._last_event_time = time.time()

    def process_event(self, event: dict) -> None:
        """Process a single stream-json event line."""
        self._last_event_time = time.time()
        etype = event.get("type", "")
        subtype = event.get("subtype", "")

        if etype == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            self.tool_calls.append({
                                "name": tool_name,
                                "ts": time.time(),
                            })
                            self.current_action = tool_name
                        elif block.get("type") == "text":
                            self.text_chunks.append(block.get("text", ""))
            elif isinstance(content, str) and content:
                self.text_chunks.append(content)

        elif etype == "result":
            self.completed = True

    def get_progress(self) -> dict:
        """Return structured progress data."""
        elapsed = time.time() - self.start_time
        tasks = self._read_task_files()

        # If no session-specific tasks, try scanning ALL recent task dirs
        if not tasks:
            tasks = self._scan_recent_tasks()

        done = [t for t in tasks if t.get("status") == "completed"]
        pending = [t for t in tasks if t.get("status") == "pending"]
        in_progress = [t for t in tasks if t.get("status") == "in_progress"]

        # ETA: hybrid of elapsed time + completion rate
        eta_seconds = None
        if tasks and len(done) > 0:
            rate = len(done) / elapsed if elapsed > 0 else 0
            remaining = len(pending) + len(in_progress)
            eta_seconds = remaining / rate if rate > 0 else None

        # Get current action from child processes if not set via events
        current = self.current_action
        if not current and self._pid:
            current = self._get_current_action_from_pid()

        return {
            "elapsed": elapsed,
            "current_action": current,
            "tasks_total": len(tasks),
            "tasks_done": len(done),
            "tasks_pending": len(pending),
            "tasks_in_progress": len(in_progress),
            "done_list": [t.get("subject", "?") for t in done],
            "pending_list": [t.get("subject", "?") for t in pending],
            "in_progress_list": [t.get("subject", "?") for t in in_progress],
            "tool_call_count": len(self.tool_calls),
            "eta_seconds": eta_seconds,
            "completed": self.completed,
        }

    def format_eta_message(self) -> str:
        """Format progress as plain-text iMessage."""
        p = self.get_progress()
        elapsed_min = int(p["elapsed"] // 60)
        elapsed_sec = int(p["elapsed"] % 60)
        elapsed_str = f"{elapsed_min}m {elapsed_sec}s"

        lines = [f"Running for: {elapsed_str}"]

        if p["current_action"]:
            lines.append(f"Current: {p['current_action']}")

        if p["tasks_total"] > 0:
            pct = int(p["tasks_done"] / p["tasks_total"] * 100)
            lines.append(f"Progress: {p['tasks_done']}/{p['tasks_total']} tasks done ({pct}%)")
            if p["done_list"]:
                lines.append(f"  Done: {', '.join(p['done_list'][:5])}")
            remaining = p["pending_list"] + p["in_progress_list"]
            if remaining:
                lines.append(f"  Remaining: {', '.join(remaining[:5])}")
        else:
            lines.append(f"Tool calls: {p['tool_call_count']}")

        if p["eta_seconds"] is not None:
            eta_min = max(1, int(p["eta_seconds"] // 60))
            lines.append(f"ETA: ~{eta_min}-{eta_min + 2} minutes")

        return "\n".join(lines)

    def format_completion_summary(self) -> str:
        """One-line completion summary appended to result."""
        p = self.get_progress()
        elapsed_min = int(p["elapsed"] // 60)
        elapsed_sec = int(p["elapsed"] % 60)
        if p["tasks_total"] > 0:
            return f"Completed {p['tasks_done']}/{p['tasks_total']} tasks in {elapsed_min}m {elapsed_sec}s."
        elif p["tool_call_count"] > 0:
            return f"Completed in {elapsed_min}m {elapsed_sec}s ({p['tool_call_count']} tool calls)."
        else:
            return f"Completed in {elapsed_min}m {elapsed_sec}s."

    def _get_current_action_from_pid(self) -> Optional[str]:
        """Inspect child processes to determine what's happening right now."""
        if not self._pid:
            return None
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(self._pid)],
                capture_output=True, text=True, timeout=5,
            )
            child_pids = [p for p in result.stdout.strip().split("\n") if p.strip()]
            if not child_pids:
                return "Processing..."
            # Get command of deepest child
            for cpid in reversed(child_pids):
                r = subprocess.run(
                    ["ps", "-o", "command=", "-p", cpid],
                    capture_output=True, text=True, timeout=5,
                )
                cmd = r.stdout.strip()
                if cmd:
                    # Extract meaningful part
                    if "brazil-build" in cmd:
                        return "Running brazil-build"
                    if "ada credentials" in cmd:
                        return "Refreshing ADA credentials"
                    if "cdk deploy" in cmd or "cdk synth" in cmd:
                        return "CDK deploy"
                    if "pytest" in cmd or "python" in cmd.lower() and "test" in cmd.lower():
                        return "Running tests"
                    if "git" in cmd:
                        return "Git operation"
                    if "claude" in cmd:
                        return "Thinking..."
                    # Generic: first 40 chars
                    return cmd[:40]
            return "Processing..."
        except Exception:
            return "Processing..."

    def _scan_recent_tasks(self) -> list:
        """Scan all task dirs for the most recently active tasks.

        Claude -p sessions create tasks under their own session ID,
        which differs from the print-mode session ID we store. So we
        scan ALL task dirs and pick the one with most recent activity.
        """
        tasks_base = os.path.expanduser("~/.claude/tasks")
        if not os.path.isdir(tasks_base):
            return []

        # Find the most recently modified task dir
        best_dir = None
        best_mtime = 0
        try:
            for session_dir in os.listdir(tasks_base):
                dir_path = os.path.join(tasks_base, session_dir)
                if not os.path.isdir(dir_path):
                    continue
                try:
                    # Check mtime of files inside the dir (not just dir itself)
                    for fname in os.listdir(dir_path):
                        fpath = os.path.join(dir_path, fname)
                        mtime = os.path.getmtime(fpath)
                        if mtime > best_mtime:
                            best_mtime = mtime
                            best_dir = dir_path
                except OSError:
                    continue
        except OSError:
            return []

        # Only use if modified since this tracker started (task is from current run)
        if best_dir and best_mtime >= self.start_time:
            return self._parse_task_dir(best_dir)
        return []

    def _read_task_files(self) -> list:
        """Read task progress from ~/.claude/tasks/ matching current session."""
        if not self.session_id:
            return []
        # Claude Code stores tasks in session-specific dirs
        tasks_base = os.path.expanduser("~/.claude/tasks")
        if not os.path.isdir(tasks_base):
            return []

        # Try session-specific task dir
        session_dir = os.path.join(tasks_base, self.session_id)
        if os.path.isdir(session_dir):
            return self._parse_task_dir(session_dir)

        # Fallback: check all task dirs for recent files
        return []

    @staticmethod
    def _parse_task_dir(task_dir: str) -> list:
        tasks = []
        try:
            for fname in sorted(os.listdir(task_dir)):
                if fname.endswith(".json"):
                    fpath = os.path.join(task_dir, fname)
                    try:
                        with open(fpath) as f:
                            task = json.load(f)
                        if isinstance(task, dict) and "status" in task:
                            tasks.append(task)
                    except (json.JSONDecodeError, IOError):
                        continue
        except OSError:
            pass
        return tasks


class StuckDetector:
    """Detects when a task is stuck — process running but child PIDs unchanged."""

    def __init__(self, pid: int, config: dict):
        self.pid = pid
        self.threshold = config.get("stuck_threshold", 5400)  # 90min
        self.alert_interval = config.get("stuck_alert_interval", 1800)  # 30min
        self.max_alerts = config.get("stuck_max_alerts", 3)
        self.stale_minutes = config.get("stuck_stale_child_minutes", 10)
        self.alerts_sent = 0
        self.last_child_pids: set[str] = set()
        self.child_unchanged_since: Optional[float] = None
        self.start_time = time.time()
        self.last_alert_time = 0.0

    def check(self) -> Optional[dict]:
        """Check if task is stuck. Returns diagnostic dict or None."""
        elapsed = time.time() - self.start_time
        if elapsed < self.threshold:
            return None
        if self.alerts_sent >= self.max_alerts:
            return None
        # Respect alert interval
        if self.alerts_sent > 0 and (time.time() - self.last_alert_time) < self.alert_interval:
            return None

        current_children = self._get_child_pids()

        if current_children != self.last_child_pids:
            self.last_child_pids = current_children
            self.child_unchanged_since = time.time()
            return None

        if self.child_unchanged_since is None:
            self.child_unchanged_since = time.time()
            return None

        stale_duration = time.time() - self.child_unchanged_since
        if stale_duration < self.stale_minutes * 60:
            return None

        # STUCK
        self.alerts_sent += 1
        self.last_alert_time = time.time()
        child_cmds = self._get_child_commands()
        return {
            "elapsed": elapsed,
            "stale_minutes": stale_duration / 60,
            "child_commands": child_cmds,
            "child_pids": list(current_children),
            "alert_number": self.alerts_sent,
            "max_alerts": self.max_alerts,
        }

    def format_stuck_alert(self, diagnostic: dict, diagnosis: str = "") -> str:
        """Format stuck alert for iMessage."""
        elapsed_min = int(diagnostic["elapsed"] // 60)
        stale_min = int(diagnostic["stale_minutes"])
        lines = [
            "STUCK ALERT",
            f"Running: {elapsed_min}min",
        ]
        if diagnostic["child_commands"]:
            cmd = diagnostic["child_commands"][0]
            # Truncate long commands
            if len(cmd) > 80:
                cmd = cmd[:77] + "..."
            lines.append(f"Stuck on: {cmd}")
        lines.append(f"Unchanged for: {stale_min}min")
        lines.append(f"Alert {diagnostic['alert_number']}/{diagnostic['max_alerts']}")

        if diagnosis:
            lines.append("")
            lines.append(f"Diagnosis: {diagnosis}")

        lines.append("")
        lines.append("Send /cancel to kill it.")
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset detector state (called on /cancel or task completion)."""
        self.alerts_sent = 0
        self.last_child_pids = set()
        self.child_unchanged_since = None
        self.last_alert_time = 0.0

    def _get_child_pids(self) -> set:
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(self.pid)],
                capture_output=True, text=True, timeout=5,
            )
            pids = result.stdout.strip().split("\n")
            return {p for p in pids if p.strip()}
        except Exception:
            return set()

    def _get_child_commands(self) -> list:
        pids = self._get_child_pids()
        if not pids:
            return []
        try:
            pid_list = ",".join(pids)
            result = subprocess.run(
                ["ps", "-o", "command=", "-p", pid_list],
                capture_output=True, text=True, timeout=5,
            )
            return [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        except Exception:
            return []
