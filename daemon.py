#!/usr/bin/env python3
"""iMessage Bridge Daemon — polls chat.db, routes to Claude Code sessions."""

from __future__ import annotations
from typing import Optional
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time

# Add project directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chatdb import ChatDB
from config import load_config, save_config, load_state, save_state
from echo_filter import EchoFilter
from parser import parse_prefix
from adapters import get_adapter, list_adapters
from progress_tracker import ProgressTracker, StuckDetector
from sender import send_imessage, OUTBOUND_MARKER

BASE_DIR = os.path.expanduser("~/.claude/imessage-bridge")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
LOG_PATH = os.path.join(BASE_DIR, "logs", "daemon.log")
CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3),
    ],
)
log = logging.getLogger("imessage-bridge")

HELP_TEXT = (
    "Commands:\n"
    "\n"
    "Session:\n"
    "/status - what's happening now\n"
    "/end - end current session\n"
    "/cancel - kill running task\n"
    "/history - last 5 messages\n"
    "/sessions - list saved sessions\n"
    "\n"
    "Navigation:\n"
    "/switch <dir> - switch directory (shows sessions, pick by number)\n"
    "/dirs - show directory aliases\n"
    "/tool <name> - switch CLI tool (claude/wasabi/kiro)\n"
    "\n"
    "Progress (Claude Code only):\n"
    "/eta - task progress, todos, ETA\n"
    "/eta interval 5m - auto-update every 5 min (default 15m)\n"
    "/eta stuck 2h - stuck alert threshold (default 90m)\n"
    "/eta stuck off - disable stuck alerts\n"
    "\n"
    "Productivity:\n"
    "/queue <prompt> - run after current task\n"
    "/remind <time> <msg> - timed reminder (5m, 1h, 2h30m)\n"
    "/help - this message\n"
    "\n"
    "Start: new:<dir>: <prompt>\n"
    "Continue: just type normally\n"
    "Dirs: home, centralis, frontend, nexus, default"
)


class Daemon:
    def __init__(self):
        self.running = True
        self.config = load_config(CONFIG_PATH)
        self.state = load_state(STATE_PATH)
        self.echo_filter = EchoFilter(window_seconds=self.config.get("echo_window_seconds", 15))

        # Open chat.db
        try:
            self.chatdb = ChatDB(CHAT_DB_PATH)
        except Exception as e:
            log.error(f"Cannot open chat.db: {e}")
            log.error("Grant Full Disk Access to your terminal in System Settings.")
            self._try_notify_fda_error()
            sys.exit(1)

        # Detect self addresses
        if not self.config.get("self_addresses") or len(self.config["self_addresses"]) <= 1:
            addrs = set(self.chatdb.self_addresses)
            guid = self.config.get("reply_chat_guid") or self.chatdb.find_self_chat_guid()
            if guid:
                handles = self.chatdb.conn.execute(
                    "SELECT DISTINCT h.id FROM handle h "
                    "JOIN chat_handle_join chj ON chj.handle_id = h.ROWID "
                    "JOIN chat c ON c.ROWID = chj.chat_id "
                    "WHERE c.guid = ?", (guid,)
                ).fetchall()
                for h in handles:
                    if h["id"]:
                        addrs.add(h["id"].lower())
            self.config["self_addresses"] = list(addrs)
            log.info(f"Detected self addresses: {self.config['self_addresses']}")
            save_config(CONFIG_PATH, self.config)

        # Detect self-chat GUID
        if not self.config.get("reply_chat_guid"):
            guid = self.chatdb.find_self_chat_guid()
            if guid:
                self.config["reply_chat_guid"] = guid
                log.info(f"Detected self-chat GUID: {guid}")
                save_config(CONFIG_PATH, self.config)
            else:
                log.warning("Could not detect self-chat GUID. Send yourself an iMessage first.")

        # Initialize watermark
        if self.state["watermark"] == 0:
            self.state["watermark"] = self.chatdb.get_max_rowid()
            save_state(STATE_PATH, self.state)
            log.info(f"Initialized watermark to {self.state['watermark']}")

        # Active session tracking
        self.active_session_id = self.state.get("active_session_id")
        self.active_session_cwd = self.state.get("active_session_cwd")
        self._busy = False
        self._current_task = None
        self._active_process = None  # For /cancel
        self._task_queue: list[str] = []  # For /queue
        self._reminders: list[dict] = []  # For /remind
        self._progress_tracker: Optional[ProgressTracker] = None
        self._stuck_detector: Optional[StuckDetector] = None
        # Picker mode for /switch
        self._picker_mode = False
        self._picker_sessions: list[dict] = []
        self._awaiting_keep_end = False
        self._pending_switch_cwd: Optional[str] = None
        self._pending_switch_alias: Optional[str] = None
        self._picker_timeout_thread: Optional[threading.Timer] = None
        if self.active_session_id:
            log.info(f"Resuming active session: {self.active_session_id}")

        # Start reminder checker thread
        threading.Thread(target=self._reminder_loop, daemon=True).start()

        log.info(f"Daemon started. Watching chat.db (watermark={self.state['watermark']})")

    def _try_notify_fda_error(self):
        try:
            cfg = load_config(CONFIG_PATH)
            guid = cfg.get("reply_chat_guid")
            if guid:
                send_imessage(guid, "Daemon needs Full Disk Access.")
        except Exception:
            pass

    def _reply(self, text: str) -> None:
        guid = self.config.get("reply_chat_guid")
        if not guid:
            log.warning(f"No reply_chat_guid — cannot send: {text}")
            return
        err = send_imessage(guid, text)
        if err:
            log.error(f"Failed to send iMessage: {err}")
        else:
            self.echo_filter.track(guid, text)

    def _is_self_chat(self, handle_id: Optional[str]) -> bool:
        if not handle_id:
            return False
        return handle_id.lower() in {a.lower() for a in self.config.get("self_addresses", [])}

    # --- Message Routing ---

    def _handle_message(self, msg: dict) -> None:
        if msg["is_from_me"]:
            return
        if not self._is_self_chat(msg["handle_id"]):
            return

        text = msg["text"]
        if not text or not text.strip():
            return
        if OUTBOUND_MARKER in text:
            return

        chat_guid = msg["chat_guid"]
        if self.echo_filter.is_echo(chat_guid, text):
            return

        log.info(f"New message: {text[:80]}...")

        # Intercept picker/keep-end flows before normal routing
        if self._awaiting_keep_end:
            self._handle_keep_end_reply(text.strip().lower())
            return
        if self._picker_mode:
            self._handle_picker_reply(text.strip())
            return

        # Handle commands (start with /)
        cmd = text.strip()
        cmd_lower = cmd.lower()

        if cmd_lower == "/end":
            self._cmd_end()
            return
        if cmd_lower == "/status":
            self._cmd_status()
            return
        if cmd_lower == "/cancel":
            self._cmd_cancel()
            return
        if cmd_lower == "/help":
            self._cmd_help()
            return
        if cmd_lower == "/history":
            self._cmd_history()
            return
        if cmd_lower == "/sessions":
            self._cmd_sessions()
            return
        if cmd_lower == "/dirs":
            self._cmd_dirs()
            return
        if cmd_lower.startswith("/switch "):
            self._cmd_switch(cmd[8:].strip())
            return
        if cmd_lower.startswith("/queue "):
            self._cmd_queue(cmd[7:].strip())
            return
        if cmd_lower.startswith("/remind "):
            self._cmd_remind(cmd[8:].strip())
            return
        if cmd_lower.startswith("/tool"):
            arg = cmd[5:].strip()
            self._cmd_tool(arg)
            return
        if cmd_lower.startswith("/eta"):
            arg = cmd[4:].strip()
            self._cmd_eta(arg)
            return

        # Regular message — parse prefix
        parsed = parse_prefix(text)
        if parsed is None:
            return

        if self._busy:
            self._reply("Busy. Send /status or /queue <task>.")
            return

        if parsed["action"] == "spawn":
            threading.Thread(target=self._handle_spawn, args=(parsed,), daemon=True).start()
        elif parsed["action"] == "inject":
            threading.Thread(target=self._handle_continue, args=(parsed,), daemon=True).start()

    # --- Commands ---

    def _cmd_end(self) -> None:
        if self.active_session_id:
            log.info(f"Ending session: {self.active_session_id}")
            self.active_session_id = None
            self.active_session_cwd = None
            self.state["active_session_id"] = None
            self.state["active_session_cwd"] = None
            save_state(STATE_PATH, self.state)
            self._reply("Session ended.")
        else:
            self._reply("No active session.")

    def _cmd_status(self) -> None:
        if self._busy and self._current_task:
            queued = f" ({len(self._task_queue)} queued)" if self._task_queue else ""
            self._reply(f"Working on: {self._current_task}{queued}")
        elif self.active_session_id:
            alias = os.path.basename(self.active_session_cwd or "unknown")
            self._reply(f"Idle. Session in {alias}.")
        else:
            self._reply("Idle. No session.")

    def _cmd_cancel(self) -> None:
        if self._active_process:
            try:
                self._active_process.kill()
                log.info("Killed active claude -p process")
            except Exception:
                pass
            self._busy = False
            self._current_task = None
            self._active_process = None
            self._reply("Cancelled.")
        elif self._busy:
            self._busy = False
            self._current_task = None
            self._reply("Cancelled.")
        else:
            self._reply("Nothing running.")

    def _cmd_help(self) -> None:
        self._reply(HELP_TEXT)

    def _cmd_history(self) -> None:
        if not self.active_session_id:
            self._reply("No active session.")
            return
        # Get last 5 messages from session history via state
        history = self.state.get("message_history", [])
        if not history:
            self._reply("No history yet in this session.")
            return
        last5 = history[-5:]
        lines = []
        for h in last5:
            role = "You" if h.get("role") == "user" else "Claude"
            text = h.get("text", "")[:80]
            lines.append(f"{role}: {text}")
        self._reply("\n".join(lines))

    def _cmd_sessions(self) -> None:
        try:
            result = subprocess.run(
                ["zsh", "-l", "-c", "claude --resume list 2>&1 | head -10"],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout.strip() if result.returncode == 0 else "Could not list sessions."
            self._reply(output or "No sessions found.")
        except Exception as e:
            self._reply(f"Error: {str(e)[:60]}")

    def _cmd_dirs(self) -> None:
        dirs = self.config.get("directories", {})
        lines = []
        for alias, path in dirs.items():
            marker = " (active)" if path == self.active_session_cwd else ""
            lines.append(f"{alias}: {path}{marker}")
        self._reply("\n".join(lines))

    def _cmd_switch(self, alias: str) -> None:
        if self._busy:
            self._reply("Busy. Wait or /cancel first.")
            return
        alias_lower = alias.lower()
        dirs = self.config.get("directories", {})
        if alias_lower not in dirs:
            available = ", ".join(dirs.keys())
            self._reply(f"Unknown: {alias}. Available: {available}")
            return
        new_cwd = dirs[alias_lower]
        if not os.path.isdir(new_cwd):
            self._reply(f"Directory not found: {new_cwd}")
            return

        self._pending_switch_cwd = new_cwd
        self._pending_switch_alias = alias_lower

        if self.active_session_id:
            self._awaiting_keep_end = True
            self._reply("End current session or keep? (end/keep)")
        else:
            # No active session — go straight to listing
            self._show_sessions_for_switch()

    def _handle_keep_end_reply(self, reply: str) -> None:
        """Process 'end' or 'keep' reply during /switch flow."""
        self._awaiting_keep_end = False
        if reply in ("end", "e"):
            self.active_session_id = None
            self.state["active_session_id"] = None
            self.state["message_history"] = []
            save_state(STATE_PATH, self.state)
            log.info("Session ended during /switch")
        elif reply in ("keep", "k"):
            log.info("Session kept during /switch")
        else:
            self._reply("Didn't understand. Say 'end' or 'keep'.")
            self._awaiting_keep_end = True
            return

        self._show_sessions_for_switch()

    def _show_sessions_for_switch(self) -> None:
        """Query adapter for sessions in target directory and show picker."""
        cwd = self._pending_switch_cwd
        alias = self._pending_switch_alias
        if not cwd:
            return

        # Update cwd
        self.active_session_cwd = cwd
        self.state["active_session_cwd"] = cwd
        save_state(STATE_PATH, self.state)

        tool = self.config.get("cli_tool", "claude")
        try:
            adapter = get_adapter(tool)
            sessions = adapter.list_sessions(cwd, self.config)
        except Exception:
            sessions = []

        if not sessions:
            self._pending_switch_cwd = None
            self._pending_switch_alias = None
            self.active_session_id = None
            self.state["active_session_id"] = None
            save_state(STATE_PATH, self.state)
            self._reply(f"No sessions in {alias}. Send a message to start one.")
            return

        # Special case: wasabi auto-resume
        if tool == "wasabi":
            self._pending_switch_cwd = None
            self._pending_switch_alias = None
            self._save_active_session("auto", cwd)
            self._reply(f"Switched to {alias}. Wasabi auto-resumes.")
            return

        # Show numbered list
        self._picker_sessions = sessions
        self._picker_mode = True
        lines = [f"Sessions in {alias}:"]
        for i, s in enumerate(sessions, 1):
            preview = s.get("preview", "")[:50]
            lines.append(f"  {i}. {preview}")
        lines.append('Reply with number, or "new" for fresh.')
        self._reply("\n".join(lines))

        # 30s timeout → auto-resume latest
        self._picker_timeout_thread = threading.Timer(30.0, self._picker_timeout)
        self._picker_timeout_thread.daemon = True
        self._picker_timeout_thread.start()

    def _handle_picker_reply(self, reply: str) -> None:
        """Process numbered session pick or 'new' during /switch."""
        # Cancel timeout
        if self._picker_timeout_thread:
            self._picker_timeout_thread.cancel()
            self._picker_timeout_thread = None

        self._picker_mode = False
        cwd = self._pending_switch_cwd or self.active_session_cwd
        alias = self._pending_switch_alias or "unknown"
        self._pending_switch_cwd = None
        self._pending_switch_alias = None

        if reply.lower() == "new":
            self.active_session_id = None
            self.state["active_session_id"] = None
            save_state(STATE_PATH, self.state)
            self._reply(f"Fresh start in {alias}. Send a message to begin.")
            return

        try:
            idx = int(reply) - 1
            if 0 <= idx < len(self._picker_sessions):
                session = self._picker_sessions[idx]
                sid = session.get("id", "auto")
                self._save_active_session(sid, cwd)
                preview = session.get("preview", "")[:40]
                self._reply(f'Resumed "{preview}" in {alias}.')
            else:
                self._reply(f"Invalid number. Resuming latest.")
                if self._picker_sessions:
                    sid = self._picker_sessions[0].get("id", "auto")
                    self._save_active_session(sid, cwd)
        except ValueError:
            self._reply(f"Didn't understand. Resuming latest in {alias}.")
            if self._picker_sessions:
                sid = self._picker_sessions[0].get("id", "auto")
                self._save_active_session(sid, cwd)

        self._picker_sessions = []

    def _picker_timeout(self) -> None:
        """Auto-resume latest session after 30s timeout."""
        if not self._picker_mode:
            return
        self._picker_mode = False
        alias = self._pending_switch_alias or "unknown"
        cwd = self._pending_switch_cwd or self.active_session_cwd
        self._pending_switch_cwd = None
        self._pending_switch_alias = None

        if self._picker_sessions:
            sid = self._picker_sessions[0].get("id", "auto")
            self._save_active_session(sid, cwd)
            self._reply(f"Timeout. Auto-resumed latest in {alias}.")
        self._picker_sessions = []

    def _cmd_queue(self, prompt: str) -> None:
        if not prompt:
            if self._task_queue:
                lines = [f"{i+1}. {t[:50]}" for i, t in enumerate(self._task_queue)]
                self._reply("Queue:\n" + "\n".join(lines))
            else:
                self._reply("Queue empty.")
            return
        self._task_queue.append(prompt)
        self._reply(f"Queued ({len(self._task_queue)} total).")

    def _cmd_tool(self, arg: str) -> None:
        """Switch CLI tool or show current."""
        if not arg:
            current = self.config.get("cli_tool", "claude")
            available = list_adapters()
            self._reply(f"Current: {current}. Available: {', '.join(available)}")
            return
        name = arg.lower()
        try:
            adapter = get_adapter(name)
            if not adapter.is_available():
                self._reply(f"{name} not found in PATH.")
                return
            self.config["cli_tool"] = name
            save_config(CONFIG_PATH, self.config)
            self._reply(f"Switched to {name}.")
        except KeyError as e:
            self._reply(str(e))

    def _cmd_eta(self, args: str) -> None:
        """Show task progress, ETA, or configure stuck detection."""
        if args.startswith("interval "):
            seconds = self._parse_time(args[9:].strip())
            if seconds:
                self.config["eta_auto_interval"] = seconds
                save_config(CONFIG_PATH, self.config)
                self._reply(f"Auto-update interval: {args[9:].strip()}")
            else:
                self._reply("Bad format. Use: /eta interval 5m")
            return

        if args.startswith("stuck "):
            val = args[6:].strip()
            if val == "off":
                self.config["stuck_threshold"] = 0
                save_config(CONFIG_PATH, self.config)
                self._reply("Stuck detection disabled.")
                return
            seconds = self._parse_time(val)
            if seconds:
                self.config["stuck_threshold"] = seconds
                save_config(CONFIG_PATH, self.config)
                self._reply(f"Stuck threshold: {val}")
            else:
                self._reply("Bad format. Use: /eta stuck 2h or /eta stuck off")
            return

        if args == "stuck":
            threshold = self.config.get("stuck_threshold", 5400)
            if threshold == 0:
                self._reply("Stuck detection: disabled")
            else:
                mins = int(threshold // 60)
                self._reply(f"Stuck threshold: {mins}min. Max alerts: {self.config.get('stuck_max_alerts', 3)}")
            return

        if not self._busy or not self._progress_tracker:
            self._reply("Nothing running.")
            return

        msg = self._progress_tracker.format_eta_message()
        self._reply(msg)

    def _cmd_remind(self, args: str) -> None:
        parts = args.split(None, 1)
        if len(parts) < 2:
            self._reply("Usage: /remind <time> <message>\nTime: 5m, 1h, 30s")
            return
        time_str, message = parts
        seconds = self._parse_time(time_str)
        if seconds is None:
            self._reply("Bad time format. Use: 5m, 1h, 30s, 2h30m")
            return
        fire_at = time.time() + seconds
        self._reminders.append({"fire_at": fire_at, "message": message})
        self._reply(f"Reminder set for {time_str}.")
        log.info(f"Reminder in {seconds}s: {message[:40]}")

    @staticmethod
    def _parse_time(s: str) -> Optional[float]:
        """Parse time string like 5m, 1h, 30s, 2h30m into seconds."""
        import re
        total = 0
        pattern = re.findall(r"(\d+)\s*([hms])", s.lower())
        if not pattern:
            return None
        for val, unit in pattern:
            val = int(val)
            if unit == "h":
                total += val * 3600
            elif unit == "m":
                total += val * 60
            elif unit == "s":
                total += val
        return total if total > 0 else None

    def _reminder_loop(self) -> None:
        """Background thread that fires reminders."""
        while self.running:
            now = time.time()
            fired = []
            for r in self._reminders:
                if now >= r["fire_at"]:
                    self._reply(f"Reminder: {r['message']}")
                    fired.append(r)
            for r in fired:
                self._reminders.remove(r)
            time.sleep(5)

    # --- Session Handlers ---

    def _save_active_session(self, session_id: str, cwd: str) -> None:
        self.active_session_id = session_id
        self.active_session_cwd = cwd
        self.state["active_session_id"] = session_id
        self.state["active_session_cwd"] = cwd
        save_state(STATE_PATH, self.state)

    def _track_history(self, role: str, text: str) -> None:
        """Track message in session history for /history command."""
        history = self.state.setdefault("message_history", [])
        history.append({"role": role, "text": text[:200], "ts": time.time()})
        # Keep last 20
        if len(history) > 20:
            self.state["message_history"] = history[-20:]
        save_state(STATE_PATH, self.state)

    def _process_queue(self) -> None:
        """Process next item in queue if any."""
        if not self._task_queue:
            return
        prompt = self._task_queue.pop(0)
        log.info(f"Processing queued task: {prompt[:60]}")
        self._reply(f"Next queued: {prompt[:50]}")
        parsed = parse_prefix(prompt)
        if parsed and parsed["action"] == "spawn":
            self._handle_spawn(parsed)
        elif parsed:
            self._handle_continue(parsed)

    def _handle_spawn(self, parsed: dict) -> None:
        alias = parsed["directory_alias"]
        prompt = parsed["prompt"]
        cwd = self.config["directories"].get(alias, self.config["directories"]["default"])

        if not os.path.isdir(cwd):
            self._reply(f"Directory not found: {cwd}")
            return

        if self.active_session_id:
            log.info(f"Ending previous session for new session")
            self.state["message_history"] = []

        short = prompt[:60] + ("..." if len(prompt) > 60 else "")
        self._busy = True
        self._current_task = short
        self._reply("On it.")
        tool = self.config.get("cli_tool", "claude")
        log.info(f"Spawning {tool} in {cwd}: {short}")
        self._track_history("user", prompt)

        try:
            tool = self.config.get("cli_tool", "claude")
            adapter = get_adapter(tool)

            # Start progress tracker (Claude Code only)
            if tool == "claude":
                self._progress_tracker = ProgressTracker(session_id=self.active_session_id)
                self._start_auto_updates()

            result = adapter.spawn(
                prompt=prompt,
                cwd=cwd,
                timeout=self.config.get("claude_p_timeout", 18000),
                process_holder=self,
                config=self.config,
            )

            if result["success"]:
                if result.get("session_id"):
                    self._save_active_session(result["session_id"], cwd)
                    log.info(f"Active session: {result['session_id']}")
                elif not self.active_session_id:
                    self._save_active_session("auto", cwd)
                self._track_history("assistant", result['output'])
                # Append completion summary if tracker active
                output = result['output']
                if self._progress_tracker:
                    summary = self._progress_tracker.format_completion_summary()
                    output = f"{output}\n\n{summary}"
                self._reply(output)
            else:
                self._reply(f"Failed: {result['error'][:80]}")
        finally:
            self._busy = False
            self._current_task = None
            self._active_process = None
            self._progress_tracker = None
            if self._stuck_detector:
                self._stuck_detector.reset()
            self._stuck_detector = None
            self._process_queue()

    def _handle_continue(self, parsed: dict) -> None:
        prompt = parsed["prompt"]

        if not self.active_session_id:
            self._reply("No session. Send new:<dir>: <prompt> to start.")
            return

        cwd = self.active_session_cwd or self.config["directories"]["default"]
        short = prompt[:60] + ("..." if len(prompt) > 60 else "")
        self._busy = True
        self._current_task = short
        self._reply("On it.")
        log.info(f"Continuing session {self.active_session_id}: {short}")
        self._track_history("user", prompt)

        try:
            tool = self.config.get("cli_tool", "claude")
            adapter = get_adapter(tool)

            if tool == "claude":
                self._progress_tracker = ProgressTracker(session_id=self.active_session_id)
                self._start_auto_updates()

            result = adapter.spawn(
                prompt=prompt,
                cwd=cwd,
                timeout=self.config.get("claude_p_timeout", 18000),
                resume_session_id=self.active_session_id,
                process_holder=self,
                config=self.config,
            )

            if result["success"]:
                if result.get("session_id"):
                    self._save_active_session(result["session_id"], cwd)
                self._track_history("assistant", result['output'])
                output = result['output']
                if self._progress_tracker:
                    summary = self._progress_tracker.format_completion_summary()
                    output = f"{output}\n\n{summary}"
                self._reply(output)
            else:
                self._reply(f"Failed: {result['error'][:80]}")
        finally:
            self._busy = False
            self._current_task = None
            self._active_process = None
            self._progress_tracker = None
            if self._stuck_detector:
                self._stuck_detector.reset()
            self._stuck_detector = None
            self._process_queue()

    # --- Auto-Updates & Stuck Detection ---

    def _start_auto_updates(self) -> None:
        """Start background threads for auto-progress updates and stuck detection."""
        interval = self.config.get("eta_auto_interval", 900)
        if interval > 0:
            threading.Thread(target=self._auto_update_loop, args=(interval,), daemon=True).start()

        threshold = self.config.get("stuck_threshold", 5400)
        if threshold > 0 and self._active_process:
            self._stuck_detector = StuckDetector(
                pid=self._active_process.pid,
                config=self.config,
            )
            threading.Thread(target=self._stuck_check_loop, daemon=True).start()

    def _auto_update_loop(self, interval: float) -> None:
        """Send periodic progress updates via iMessage."""
        while self._busy and self._progress_tracker:
            time.sleep(interval)
            if self._busy and self._progress_tracker:
                try:
                    msg = self._progress_tracker.format_eta_message()
                    self._reply(f"[Auto] {msg}")
                except Exception as e:
                    log.warning(f"Auto-update failed: {e}")

    def _stuck_check_loop(self) -> None:
        """Check for stuck tasks every 60s."""
        while self._busy and self._stuck_detector:
            time.sleep(60)
            if not self._busy or not self._stuck_detector:
                break
            try:
                diag = self._stuck_detector.check()
                if diag:
                    diagnosis = self._get_stuck_diagnosis(diag)
                    msg = self._stuck_detector.format_stuck_alert(diag, diagnosis)
                    self._reply(msg)
                    log.warning(f"Stuck alert #{diag['alert_number']}: {diag.get('child_commands', [])}")
            except Exception as e:
                log.warning(f"Stuck check failed: {e}")

    def _get_stuck_diagnosis(self, diag: dict) -> str:
        """Ask Claude to self-diagnose why it's stuck. Returns diagnosis text."""
        if not self.active_session_id or self.config.get("cli_tool") != "claude":
            return ""
        try:
            child_cmds = ", ".join(diag.get("child_commands", [])[:2])
            elapsed_min = int(diag["elapsed"] // 60)
            from adapters.base import get_login_shell_env
            env = get_login_shell_env()
            result = subprocess.run(
                ["zsh", "-i", "-c",
                 f'claude -p "You have been running for {elapsed_min} minutes. '
                 f'Your child process ({child_cmds}) has been unchanged for '
                 f'{int(diag["stale_minutes"])} minutes. Why are you stuck? '
                 f'What is blocking? Reply in 2 plain text sentences." '
                 f'--output-format json --dangerously-skip-permissions --effort low '
                 f'--resume {self.active_session_id}'],
                capture_output=True, text=True, timeout=30,
                cwd=self.active_session_cwd or "/tmp",
                env=env,
            )
            if result.returncode == 0:
                import json as _json
                data = _json.loads(result.stdout)
                return data.get("result", "")[:200]
        except Exception as e:
            log.debug(f"Self-diagnosis failed: {e}")
        return ""

    # --- Main Loop ---

    def poll(self) -> None:
        try:
            rows = self.chatdb.poll(self.state["watermark"])
        except Exception as e:
            log.warning(f"Poll query failed: {e}")
            return

        for msg in rows:
            self.state["watermark"] = msg["rowid"]
            save_state(STATE_PATH, self.state)
            self._handle_message(msg)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        interval = self.config.get("poll_interval", 1.0)
        while self.running:
            self.poll()
            time.sleep(interval)

        self.chatdb.close()
        log.info("Daemon stopped.")

    def stop(self) -> None:
        self.running = False


if __name__ == "__main__":
    daemon = Daemon()
    daemon.run()
