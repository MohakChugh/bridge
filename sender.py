"""Send iMessages via AppleScript."""

from __future__ import annotations
from typing import Optional
import subprocess

SEND_SCRIPT = """on run argv
  tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run"""

# Zero-width space used as invisible marker on all outbound messages.
# The daemon checks for this marker on inbound and skips any message
# that contains it — this prevents the self-chat echo loop.
OUTBOUND_MARKER = "\u200b"


def send_imessage(chat_guid: str, text: str) -> Optional[str]:
    """Send text to a chat via osascript. Returns error string or None on success.

    Appends an invisible marker so the daemon can identify its own messages.
    """
    marked_text = text + OUTBOUND_MARKER
    result = subprocess.run(
        ["osascript", "-", marked_text, chat_guid],
        input=SEND_SCRIPT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return result.stderr.strip() or f"osascript exit {result.returncode}"
    return None
