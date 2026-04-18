#!/usr/bin/env python3
"""MCP server for iMessage Bridge — provides reply and history tools to Claude."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from chatdb import ChatDB
from config import load_config
from sender import send_imessage

BASE_DIR = os.path.expanduser("~/.claude/imessage-bridge")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CHAT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")

server = Server("imessage-bridge")


def _get_chat_guid(args: dict) -> str:
    """Get chat GUID from args or config default."""
    if "chat_guid" in args and args["chat_guid"]:
        return args["chat_guid"]
    config = load_config(CONFIG_PATH)
    guid = config.get("reply_chat_guid")
    if not guid:
        raise ValueError("No reply_chat_guid configured. Run daemon first to auto-detect.")
    return guid


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="imessage_reply",
            description=(
                "Send an iMessage reply. Used when a prompt arrived via [iMessage] prefix. "
                "Defaults to self-chat if chat_guid is omitted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message text to send"},
                    "chat_guid": {
                        "type": "string",
                        "description": "Optional chat GUID. Defaults to self-chat.",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="imessage_history",
            description=(
                "Read recent iMessage history from self-chat. "
                "Returns timestamped messages in chronological order."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "number",
                        "description": "Max messages to return (default 50, max 200)",
                    },
                    "chat_guid": {
                        "type": "string",
                        "description": "Optional chat GUID. Defaults to self-chat.",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "imessage_reply":
        text = arguments["text"]
        chat_guid = _get_chat_guid(arguments)
        err = send_imessage(chat_guid, text)
        if err:
            return [TextContent(type="text", text=f"Failed to send: {err}")]
        return [TextContent(type="text", text="sent")]

    elif name == "imessage_history":
        chat_guid = _get_chat_guid(arguments)
        limit = min(int(arguments.get("limit", 50)), 200)

        try:
            cdb = ChatDB(CHAT_DB_PATH)
        except Exception as e:
            return [TextContent(type="text", text=f"Cannot open chat.db: {e}")]

        history = cdb.get_history(chat_guid, limit=limit)
        cdb.close()

        if not history:
            return [TextContent(type="text", text="(no messages)")]

        lines = []
        for msg in history:
            who = "me" if msg["is_from_me"] else (msg["handle_id"] or "unknown")
            ts = msg["date_iso"][:16] if msg["date_iso"] else "?"
            lines.append(f"[{ts}] {who}: {msg['text']}")

        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
