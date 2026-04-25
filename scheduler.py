"""Cron-based task scheduler for iMessage Bridge."""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import json
import logging
import os
import shlex
import subprocess
import time

log = logging.getLogger("imessage-bridge")


def cron_matches(cron: str, dt: datetime) -> bool:
    """Check if 5-field cron expression matches datetime.

    Format: minute hour day_of_month month day_of_week
    Fields: *, N, N-M, N,M, */N
    Day of week: 0=Sun, 1=Mon, ..., 6=Sat
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return False

    fields = [
        (parts[0], dt.minute),
        (parts[1], dt.hour),
        (parts[2], dt.day),
        (parts[3], dt.month),
        (parts[4], dt.weekday()),  # 0=Mon in Python, but cron uses 0=Sun
    ]
    # Adjust weekday: Python weekday() is 0=Mon, cron is 0=Sun
    # Convert: python 0(Mon)->1, 1(Tue)->2, ..., 6(Sun)->0
    python_dow = dt.weekday()
    cron_dow = (python_dow + 1) % 7

    fields[4] = (parts[4], cron_dow)

    for pattern, value in fields:
        if not _field_matches(pattern, value):
            return False
    return True


def _field_matches(pattern: str, value: int) -> bool:
    """Check if a single cron field matches a value."""
    if pattern == "*":
        return True

    for part in pattern.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                if value % step == 0:
                    return True
            elif "-" in base:
                lo, hi = map(int, base.split("-"))
                if lo <= value <= hi and (value - lo) % step == 0:
                    return True
        elif "-" in part:
            lo, hi = map(int, part.split("-"))
            if lo <= value <= hi:
                return True
        else:
            if int(part) == value:
                return True

    return False


def next_cron_fire(cron: str, after: Optional[datetime] = None) -> float:
    """Calculate next fire time as unix timestamp."""
    dt = after or datetime.now()
    # Start checking from next minute
    dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)

    # Search up to 366 days ahead
    for _ in range(366 * 24 * 60):
        if cron_matches(cron, dt):
            return dt.timestamp()
        dt += timedelta(minutes=1)

    # Fallback: 24h from now
    return time.time() + 86400


def parse_schedule_via_llm(natural_text: str, env: dict) -> Optional[dict]:
    """Use Claude Code (cheap) to parse natural language into cron.

    Returns: {"cron": "0 9 * * *", "human": "daily at 9:00 AM"} or None
    """
    prompt = (
        f"Parse this schedule into cron format. "
        f"Input: {natural_text}. "
        f"Reply ONLY with valid JSON, no other text: "
        f'{{\"cron\": \"minute hour day month weekday\", \"human\": \"readable description\"}}. '
        f"Use 5-field cron. Day of week: 0=Sun, 6=Sat."
    )
    try:
        result = subprocess.run(
            ["zsh", "-i", "-c",
             f"claude -p {shlex.quote(prompt)} "
             f"--output-format json --dangerously-skip-permissions --effort low"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode == 0:
            outer = json.loads(result.stdout)
            text = outer.get("result", "")
            # Extract JSON from response (may have surrounding text)
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if "cron" in parsed and "human" in parsed:
                    return parsed
    except Exception as e:
        log.warning(f"Schedule LLM parse failed: {e}")
    return None


def format_schedule_list(tasks: list) -> str:
    """Format scheduled tasks as numbered list for iMessage."""
    if not tasks:
        return "No active schedules."

    lines = ["Active schedules:"]
    for i, t in enumerate(tasks, 1):
        status = "[paused] " if t.get("status") == "paused" else ""
        human = t.get("human", "unknown")
        prompt = t.get("prompt", "?")[:40]
        next_fire = t.get("next_fire", 0)
        if next_fire > 0:
            dt = datetime.fromtimestamp(next_fire)
            next_str = dt.strftime("%b %d %I:%M %p")
        else:
            next_str = "?"
        lines.append(f"  {i}. {status}{human} — {prompt} (next: {next_str})")

    return "\n".join(lines)
