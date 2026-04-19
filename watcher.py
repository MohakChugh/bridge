"""Watch mode — monitor pipelines, tickets, alarms with change detection.

Core principle: Alert on STATE CHANGE only. Never alert on same state twice.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
import json
import logging
import os
import re
import shlex
import subprocess
import time

log = logging.getLogger("imessage-bridge")

MAX_WATCHES = 20
DEFAULT_COOLDOWN = 1800  # 30 min
DEFAULT_INTERVALS = {"critical": 60, "standard": 300, "low": 900}


# --- Checkers ---

class WatchChecker:
    """Base checker — subclasses implement check() and detect_change()."""

    def check(self, target, filters: dict, config: dict) -> dict:
        """Poll current state. Returns comparable state dict."""
        raise NotImplementedError

    def detect_change(self, old_state: dict, new_state: dict) -> Optional[str]:
        """If meaningful change, return alert summary. Else None."""
        raise NotImplementedError


class PipelineChecker(WatchChecker):
    """Monitor pipeline health via GetPipelineHealth MCP tool."""

    def check(self, target, filters: dict, config: dict) -> dict:
        targets = [target] if isinstance(target, str) else target
        try:
            # Use adapter to query — it has MCP access
            from adapters import get_adapter
            from adapters.base import get_login_shell_env
            env = get_login_shell_env()
            tool = config.get("cli_tool", "claude")
            prompt = (
                f"Check pipeline health for: {', '.join(targets)}. "
                f"Reply ONLY with JSON: "
                f'{{"pipelines": [{{"name": "X", "blocked": true/false, "badge": "gold/silver/bronze", '
                f'"failedBuilds": N, "failedDeploys": N, "pendingApprovals": N}}]}}'
            )
            adapter = get_adapter(tool)
            result = adapter.spawn(prompt=prompt, cwd="/tmp", timeout=30, config=config)
            if result["success"]:
                try:
                    text = result["output"]
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(text[start:end])
                except (json.JSONDecodeError, ValueError):
                    pass
            return {"pipelines": [], "error": result.get("error", "")}
        except Exception as e:
            log.warning(f"Pipeline check failed: {e}")
            return {"pipelines": [], "error": str(e)}

    def detect_change(self, old_state: dict, new_state: dict) -> Optional[str]:
        old_pipes = {p.get("name", ""): p for p in old_state.get("pipelines", [])}
        new_pipes = {p.get("name", ""): p for p in new_state.get("pipelines", [])}
        changes = []
        for name, new_p in new_pipes.items():
            old_p = old_pipes.get(name, {})
            if old_p.get("blocked") != new_p.get("blocked"):
                if new_p.get("blocked"):
                    changes.append(f"Pipeline {name} BLOCKED")
                else:
                    changes.append(f"Pipeline {name} UNBLOCKED")
            if old_p.get("failedDeploys", 0) < new_p.get("failedDeploys", 0):
                changes.append(f"Pipeline {name}: new deploy failure")
            if old_p.get("failedBuilds", 0) < new_p.get("failedBuilds", 0):
                changes.append(f"Pipeline {name}: new build failure")
            if old_p.get("badge") != new_p.get("badge") and old_p.get("badge"):
                changes.append(f"Pipeline {name}: badge {old_p['badge']} -> {new_p['badge']}")
        return ". ".join(changes) if changes else None


class TicketChecker(WatchChecker):
    """Monitor resolver group for new tickets."""

    def check(self, target, filters: dict, config: dict) -> dict:
        targets = [target] if isinstance(target, str) else target
        try:
            from adapters import get_adapter
            tool = config.get("cli_tool", "claude")
            sev = filters.get("minimumSeverity", 5)
            groups_str = ", ".join(targets)
            prompt = (
                f"Search for open tickets on resolver groups: {groups_str} "
                f"with minimum severity {sev}. "
                f"Reply ONLY with JSON: "
                f'{{"tickets": [{{"id": "T123", "title": "...", "severity": N, "status": "...", "assignee": "..."}}]}}'
            )
            adapter = get_adapter(tool)
            result = adapter.spawn(prompt=prompt, cwd="/tmp", timeout=30, config=config)
            if result["success"]:
                try:
                    text = result["output"]
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        data = json.loads(text[start:end])
                        data["ticket_ids"] = {t.get("id", "") for t in data.get("tickets", [])}
                        return data
                except (json.JSONDecodeError, ValueError):
                    pass
            return {"tickets": [], "ticket_ids": set()}
        except Exception as e:
            log.warning(f"Ticket check failed: {e}")
            return {"tickets": [], "ticket_ids": set()}

    def detect_change(self, old_state: dict, new_state: dict) -> Optional[str]:
        old_ids = set(old_state.get("ticket_ids", set()))
        new_ids = set(new_state.get("ticket_ids", set()))
        new_tickets = new_ids - old_ids
        if new_tickets:
            # Find details of new tickets
            details = []
            for t in new_state.get("tickets", []):
                if t.get("id") in new_tickets:
                    details.append(f'{t["id"]}: {t.get("title", "?")[:40]} (Sev-{t.get("severity", "?")})')
            return f"{len(new_tickets)} new ticket(s): " + "; ".join(details)
        return None


class GenericChecker(WatchChecker):
    """Fallback checker — uses CLI tool with natural language prompt."""

    def __init__(self, check_prompt: str = ""):
        self.check_prompt = check_prompt

    def check(self, target, filters: dict, config: dict) -> dict:
        try:
            from adapters import get_adapter
            tool = config.get("cli_tool", "claude")
            prompt = (
                f"Check the current state of: {target}. "
                f"Reply ONLY with JSON describing the current state. "
                f"Keep it brief."
            )
            adapter = get_adapter(tool)
            result = adapter.spawn(prompt=prompt, cwd="/tmp", timeout=30, config=config)
            if result["success"]:
                return {"raw": result["output"], "timestamp": time.time()}
            return {"raw": "", "error": result.get("error", ""), "timestamp": time.time()}
        except Exception as e:
            return {"raw": "", "error": str(e), "timestamp": time.time()}

    def detect_change(self, old_state: dict, new_state: dict) -> Optional[str]:
        old_raw = old_state.get("raw", "")
        new_raw = new_state.get("raw", "")
        if old_raw != new_raw and old_raw:
            return f"State changed: {new_raw[:100]}"
        return None


# --- Checker Registry ---

CHECKERS = {
    "pipeline": PipelineChecker(),
    "tickets": TicketChecker(),
    "ticket": TicketChecker(),
    "generic": GenericChecker(),
}

def get_checker(watch_type: str) -> WatchChecker:
    return CHECKERS.get(watch_type, CHECKERS["generic"])


# --- Classification ---

def classify_watch(natural_text: str, config: dict, env: dict) -> Optional[dict]:
    """Use LLM to classify natural language watch command into structured config."""
    groups = ", ".join(config.get("watch_resolver_groups", [
        "MyTeam-Resolver", "MyTeam-SIS", "MyTeam-Platform", "MyTeam-Tasks"
    ]))
    pipelines = ", ".join(config.get("watch_pipelines", [
        "MyBackendService", "MyFrontendModule"
    ]))

    prompt = (
        f"Parse this watch command into JSON. "
        f"User's resolver groups: {groups}. "
        f"User's pipelines: {pipelines}. "
        f"Input: {natural_text}. "
        f"Reply ONLY with JSON: "
        f'{{"type": "pipeline|tickets|ticket|alarm|cr|deploy|generic", '
        f'"target": "specific target name or list", '
        f'"filters": {{}}, '
        f'"interval": seconds_between_checks, '
        f'"human": "readable description"}}'
    )
    try:
        result = subprocess.run(
            ["zsh", "-i", "-c",
             f"claude -p {shlex.quote(prompt)} "
             f"--output-format json --dangerously-skip-permissions --effort low"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode == 0:
            outer = json.loads(result.stdout)
            text = outer.get("result", "")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if "type" in parsed and "human" in parsed:
                    return parsed
    except Exception as e:
        log.warning(f"Watch classify failed: {e}")
    return None


# --- Alert Formatting ---

def format_alert(change: str, watch: dict, diagnosis: str = "", fix: str = "") -> str:
    """Format watch alert for iMessage. Severity-based detail level."""
    watch_type = watch.get("type", "generic")
    human = watch.get("human", "Watch alert")
    lines = [f"WATCH: {human}", change]

    if diagnosis:
        lines.append("")
        lines.append(f"Diagnosis: {diagnosis[:200]}")

    if fix:
        lines.append("")
        lines.append(f"Suggested fix: {fix[:100]}")
        lines.append("Execute? (y/n)")

    return "\n".join(lines)


def format_dashboard(watches: list, recent_alerts: list, mute_until: float) -> str:
    """Format /watch dashboard for iMessage."""
    active = [w for w in watches if w.get("status") == "active"]
    paused = [w for w in watches if w.get("status") == "paused"]
    alert_count = len([a for a in recent_alerts if a.get("ts", 0) > time.time() - 3600])

    lines = [f"{len(active)} active watches | {len(paused)} paused | {alert_count} alerts in last hour"]

    if mute_until > time.time():
        remaining = int((mute_until - time.time()) / 60)
        lines.append(f"MUTED for {remaining}min")

    if watches:
        lines.append("")
        lines.append("Watches:")
        for i, w in enumerate(watches, 1):
            status = "[paused] " if w.get("status") == "paused" else ""
            snoozed = "[snoozed] " if w.get("snooze_until", 0) > time.time() else ""
            human = w.get("human", "?")[:40]
            interval_m = w.get("interval", 300) // 60
            alerts = w.get("alert_count", 0)
            lines.append(f"  {i}. {status}{snoozed}{human} ({interval_m}m) — {alerts} alerts")

    if recent_alerts:
        lines.append("")
        lines.append("Recent:")
        for a in recent_alerts[-3:]:
            dt = datetime.fromtimestamp(a.get("ts", 0))
            lines.append(f"  {dt.strftime('%I:%M %p')}: {a.get('summary', '?')[:50]}")

    return "\n".join(lines)


def format_watch_list(watches: list) -> str:
    """Format /watch list for iMessage."""
    if not watches:
        return "No active watches."
    lines = ["Watches:"]
    for i, w in enumerate(watches, 1):
        status = "[paused] " if w.get("status") == "paused" else ""
        snoozed = "[snoozed] " if w.get("snooze_until", 0) > time.time() else ""
        human = w.get("human", "?")[:40]
        wtype = w.get("type", "?")
        interval_m = w.get("interval", 300) // 60
        lines.append(f"  {i}. {status}{snoozed}[{wtype}] {human} (every {interval_m}m)")
    return "\n".join(lines)
