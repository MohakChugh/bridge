"""Slack Socket Mode channel for iMessage bridge daemon.

Receives messages from Slack DMs, routes through the same command parser
as iMessage, sends replies back to Slack. Uses Socket Mode (WebSocket,
no public URL needed).
"""

from __future__ import annotations
import logging
import os
import re
import threading
from typing import Optional, Callable

log = logging.getLogger("slack_channel")


class SlackChannel:
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        allowed_users: list[str],
        message_callback: Callable[[str, "SlackChannel", dict], None],
    ):
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        self.bot_token = bot_token
        self.app_token = app_token
        self.allowed_users = set(allowed_users)
        self.callback = message_callback
        self._reply_context: Optional[dict] = None

        self.app = App(token=bot_token)

        @self.app.event("assistant_thread_started")
        def handle_assistant_thread_started(event, say):
            pass

        @self.app.event("assistant_thread_context_changed")
        def handle_assistant_context_changed(event, say):
            pass

        @self.app.event("app_home_opened")
        def handle_app_home_opened(event, say):
            pass

        @self.app.event("member_joined_channel")
        def handle_member_joined(event, say):
            pass

        @self.app.event("file_change")
        def handle_file_change(event, say):
            pass

        @self.app.event("app_mention")
        def handle_app_mention(event, say):
            user = event.get("user", "")
            if self.allowed_users and user not in self.allowed_users:
                return
            text = event.get("text", "").strip()
            text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
            if not text:
                return
            text = _normalize_slack_command(text)
            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts") or event.get("ts")
            ctx = {"channel": channel, "thread_ts": thread_ts, "user": user, "say": say}
            log.info(f"Slack mention from {user}: {text[:60]}")
            self.callback(text, self, ctx)

        @self.app.event("message")
        def handle_message(event, say):
            user = event.get("user", "")
            if self.allowed_users and user not in self.allowed_users:
                return

            subtype = event.get("subtype")
            if subtype in ("bot_message", "message_changed", "message_deleted"):
                return

            text = event.get("text", "").strip()
            if not text:
                return

            # Slack eats /commands — support without slash too
            text = _normalize_slack_command(text)

            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts") or event.get("ts")

            ctx = {
                "channel": channel,
                "thread_ts": thread_ts,
                "user": user,
                "say": say,
            }

            log.info(f"Slack message from {user}: {text[:60]}")
            self.callback(text, self, ctx)

        self._handler = SocketModeHandler(self.app, app_token)

    def start(self) -> None:
        log.info("Starting Slack Socket Mode channel")
        self._handler.start()

    def stop(self) -> None:
        log.info("Stopping Slack Socket Mode channel")
        try:
            self._handler.close()
        except Exception:
            pass

    def send(self, text: str, ctx: Optional[dict] = None) -> None:
        if not text:
            return

        text = _clean_for_slack(text)

        if ctx and ctx.get("say"):
            try:
                ctx["say"](text=text, thread_ts=ctx.get("thread_ts"))
                return
            except Exception as e:
                log.warning(f"say() failed, falling back to chat_postMessage: {e}")

        if ctx and ctx.get("channel"):
            try:
                self.app.client.chat_postMessage(
                    channel=ctx["channel"],
                    text=text,
                    thread_ts=ctx.get("thread_ts"),
                )
            except Exception as e:
                log.error(f"Slack send failed: {e}")

    def react(self, emoji: str, ctx: Optional[dict] = None) -> None:
        if not ctx:
            return
        try:
            self.app.client.reactions_add(
                channel=ctx.get("channel", ""),
                timestamp=ctx.get("thread_ts", ""),
                name=emoji,
            )
        except Exception as e:
            log.debug(f"React failed: {e}")


_SLASH_COMMANDS = {
    "end", "status", "cancel", "help", "history", "sessions", "dirs",
    "switch", "queue", "remind", "tool", "eta", "watch", "schedule",
}


def _normalize_slack_command(text: str) -> str:
    """Convert bare commands to /commands for daemon routing.
    'status' → '/status', 'tool wasabi' → '/tool wasabi'
    """
    first = text.split()[0].lower()
    if first in _SLASH_COMMANDS:
        return "/" + text
    return text


def _clean_for_slack(text: str) -> str:
    if len(text) > 3900:
        text = text[:3900] + "\n... (truncated)"
    return text
