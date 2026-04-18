"""Read-only interface to ~/Library/Messages/chat.db."""

from __future__ import annotations
from typing import Optional
import re
import sqlite3
from parser import parse_attributed_body

APPLE_EPOCH_MS = 978307200000


def _apple_date_iso(ns: int) -> str:
    """Convert Apple nanosecond timestamp to ISO 8601 string."""
    from datetime import datetime, timezone
    ts = ns / 1e6 + APPLE_EPOCH_MS
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()


class ChatDB:
    """Read-only interface to iMessage chat.db."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only = ON")
        self.self_addresses = self._detect_self_addresses()

    def _detect_self_addresses(self) -> set:
        """Detect the user's own addresses from sent messages."""
        rows = self.conn.execute(
            "SELECT DISTINCT account FROM message "
            "WHERE is_from_me = 1 AND account IS NOT NULL AND account != '' LIMIT 50"
        ).fetchall()
        addresses = set()
        for row in rows:
            addr = row["account"]
            if re.match(r"^[A-Za-z]:", addr):
                addr = addr[2:]
            addresses.add(addr.lower())
        return addresses

    def get_max_rowid(self) -> int:
        """Get current maximum ROWID in message table."""
        row = self.conn.execute("SELECT MAX(ROWID) AS max_id FROM message").fetchone()
        return row["max_id"] or 0

    def find_self_chat_guid(self) -> Optional[str]:
        """Find the chat GUID for self-chat (DM with yourself).

        Checks both self_addresses (from message.account) and handle addresses
        since self-chat handle may be phone while account is email.
        """
        # Collect all possible self identifiers: from message.account AND from
        # handles that appear on is_from_me=1 messages
        self_handles = set(self.self_addresses)
        rows = self.conn.execute(
            "SELECT DISTINCT LOWER(h.id) AS hid FROM handle h "
            "JOIN message m ON m.handle_id = h.ROWID "
            "WHERE m.is_from_me = 1 LIMIT 50"
        ).fetchall()
        for row in rows:
            if row["hid"]:
                self_handles.add(row["hid"])

        for addr in self_handles:
            rows = self.conn.execute(
                "SELECT DISTINCT c.guid FROM chat c "
                "JOIN chat_handle_join chj ON chj.chat_id = c.ROWID "
                "JOIN handle h ON h.ROWID = chj.handle_id "
                "WHERE c.style = 45 AND LOWER(h.id) = ?",
                (addr,),
            ).fetchall()
            for row in rows:
                return row["guid"]
        return None

    def poll(self, watermark: int) -> list:
        """Get all messages with ROWID > watermark, ordered ascending."""
        rows = self.conn.execute(
            """
            SELECT m.ROWID AS rowid, m.guid, m.text, m.attributedBody, m.date,
                   m.is_from_me, m.cache_has_attachments, m.service,
                   h.id AS handle_id, c.guid AS chat_guid, c.style AS chat_style
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE m.ROWID > ?
            ORDER BY m.ROWID ASC
            """,
            (watermark,),
        ).fetchall()

        result = []
        for r in rows:
            text = r["text"] or parse_attributed_body(r["attributedBody"])
            result.append({
                "rowid": r["rowid"],
                "guid": r["guid"],
                "text": text or "",
                "date": r["date"],
                "date_iso": _apple_date_iso(r["date"]) if r["date"] else None,
                "is_from_me": bool(r["is_from_me"]),
                "has_attachments": bool(r["cache_has_attachments"]),
                "service": r["service"],
                "handle_id": r["handle_id"],
                "chat_guid": r["chat_guid"],
                "chat_style": r["chat_style"],
            })
        return result

    def get_history(self, chat_guid: str, limit: int = 50) -> list:
        """Get recent messages for a chat, returned in chronological order."""
        rows = self.conn.execute(
            """
            SELECT m.ROWID AS rowid, m.text, m.attributedBody, m.date,
                   m.is_from_me, h.id AS handle_id
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE c.guid = ?
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (chat_guid, limit),
        ).fetchall()

        result = []
        for r in reversed(rows):
            text = r["text"] or parse_attributed_body(r["attributedBody"])
            result.append({
                "rowid": r["rowid"],
                "text": text or "",
                "date_iso": _apple_date_iso(r["date"]) if r["date"] else None,
                "is_from_me": bool(r["is_from_me"]),
                "handle_id": r["handle_id"],
            })
        return result

    def get_attachments(self, message_rowid: int) -> list:
        """Get attachments for a message."""
        rows = self.conn.execute(
            """
            SELECT a.filename, a.mime_type, a.uti, a.total_bytes
            FROM attachment a
            JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
            WHERE maj.message_id = ?
            """,
            (message_rowid,),
        ).fetchall()
        return [{"filename": r["filename"], "mime_type": r["mime_type"],
                 "uti": r["uti"], "bytes": r["total_bytes"]} for r in rows]

    def close(self):
        self.conn.close()
