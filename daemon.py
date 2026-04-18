#!/usr/bin/env python3
"""iMessage Bridge Daemon — polls chat.db, routes to Claude Code sessions."""

from __future__ import annotations
from typing import Optional
import logging
import logging.handlers
import os
import signal
import sys
import time

# Add project directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chatdb import ChatDB
from config import load_config, save_config, load_state, save_state
from echo_filter import EchoFilter
from parser import parse_prefix
from router import inject_into_session, spawn_claude_session
from sender import send_imessage

BASE_DIR = os.path.expanduser("~/.claude/imessage-bridge")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
LOG_PATH = os.path.join(BASE_DIR, "logs", "daemon.log")
CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

# Logging with rotation (5MB max, keep 3 backups)
# Only use file handler — launchd already captures stderr to the same file,
# so a StreamHandler would duplicate every line.
os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3),
    ],
)
log = logging.getLogger("imessage-bridge")


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

        # Detect self addresses — include both message.account emails AND
        # handle IDs (phone numbers) from the self-chat conversation
        if not self.config.get("self_addresses") or len(self.config["self_addresses"]) <= 1:
            addrs = set(self.chatdb.self_addresses)
            # Also add handles from self-chat (phone number may differ from email)
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

        # Active session tracking for persistent conversations
        self.active_session_id = self.state.get("active_session_id")
        self.active_session_cwd = self.state.get("active_session_cwd")
        if self.active_session_id:
            log.info(f"Resuming active session: {self.active_session_id}")

        log.info(f"Daemon started. Watching chat.db (watermark={self.state['watermark']})")

    def _try_notify_fda_error(self):
        """Try to send an iMessage about FDA error. May also fail."""
        try:
            cfg = load_config(CONFIG_PATH)
            guid = cfg.get("reply_chat_guid")
            if guid:
                send_imessage(guid, "iMessage Bridge: Cannot read chat.db. Grant Full Disk Access.")
        except Exception:
            pass

    def _reply(self, text: str) -> None:
        """Send an iMessage reply to self-chat."""
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
        """Check if the handle belongs to the user (self-chat)."""
        if not handle_id:
            return False
        return handle_id.lower() in {a.lower() for a in self.config.get("self_addresses", [])}

    def _handle_message(self, msg: dict) -> None:
        """Process a single new message."""
        if msg["is_from_me"]:
            return

        if not self._is_self_chat(msg["handle_id"]):
            return

        text = msg["text"]
        if not text or not text.strip():
            return

        chat_guid = msg["chat_guid"]
        if self.echo_filter.is_echo(chat_guid, text):
            return

        log.info(f"New message: {text[:80]}...")

        # Handle /end command — ends active session
        if text.strip().lower() == "/end":
            self._handle_end()
            return

        parsed = parse_prefix(text)
        if parsed is None:
            return

        if parsed["action"] == "spawn":
            self._handle_spawn(parsed)
        elif parsed["action"] == "inject":
            # "inject" = no prefix. If active session exists, continue it.
            # If no active session, tell user to start one.
            self._handle_continue(parsed)

    def _handle_end(self) -> None:
        """End the active persistent session."""
        if self.active_session_id:
            log.info(f"Ending session: {self.active_session_id}")
            self.active_session_id = None
            self.active_session_cwd = None
            self.state["active_session_id"] = None
            self.state["active_session_cwd"] = None
            save_state(STATE_PATH, self.state)
            self._reply("Session ended.")
        else:
            self._reply("No active session to end.")

    def _save_active_session(self, session_id: str, cwd: str) -> None:
        """Save active session to state for persistence across daemon restarts."""
        self.active_session_id = session_id
        self.active_session_cwd = cwd
        self.state["active_session_id"] = session_id
        self.state["active_session_cwd"] = cwd
        save_state(STATE_PATH, self.state)

    def _handle_spawn(self, parsed: dict) -> None:
        """Spawn a new claude -p session (ends any existing session)."""
        alias = parsed["directory_alias"]
        prompt = parsed["prompt"]
        cwd = self.config["directories"].get(alias, self.config["directories"]["default"])

        if not os.path.isdir(cwd):
            self._reply(f"Directory not found: {cwd}")
            return

        # End any existing session before starting new one
        if self.active_session_id:
            log.info(f"Ending previous session {self.active_session_id} for new session")

        self._reply(f"Starting new session in {alias}...")
        log.info(f"Spawning claude -p in {cwd}: {prompt[:60]}")

        result = spawn_claude_session(
            prompt=prompt,
            cwd=cwd,
            timeout=self.config.get("claude_p_timeout", 600),
        )

        if result["success"]:
            if result.get("session_id"):
                self._save_active_session(result["session_id"], cwd)
                log.info(f"Active session: {result['session_id']}")
            self._reply(f"Done: {result['output']}")
        else:
            self._reply(f"Error: {result['error']}")

    def _handle_continue(self, parsed: dict) -> None:
        """Continue the active persistent session, or report no session."""
        prompt = parsed["prompt"]

        if not self.active_session_id:
            self._reply("No active session. Use 'new:' prefix to start one, or /end to stop.")
            return

        cwd = self.active_session_cwd or self.config["directories"]["default"]
        log.info(f"Continuing session {self.active_session_id}: {prompt[:60]}")
        self._reply("Processing...")

        result = spawn_claude_session(
            prompt=prompt,
            cwd=cwd,
            timeout=self.config.get("claude_p_timeout", 600),
            resume_session_id=self.active_session_id,
        )

        if result["success"]:
            # Update session_id in case it changed
            if result.get("session_id"):
                self._save_active_session(result["session_id"], cwd)
            self._reply(f"{result['output']}")
        else:
            self._reply(f"Error: {result['error']}")

    def poll(self) -> None:
        """Single poll cycle — check for new messages."""
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
        """Main loop."""
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
