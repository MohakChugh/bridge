"""Send iMessages via AppleScript."""

import subprocess

SEND_SCRIPT = """on run argv
  tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run"""


def send_imessage(chat_guid: str, text: str) -> str | None:
    """Send text to a chat via osascript. Returns error string or None on success."""
    result = subprocess.run(
        ["osascript", "-", text, chat_guid],
        input=SEND_SCRIPT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return result.stderr.strip() or f"osascript exit {result.returncode}"
    return None
