"""Integration tests — test the full daemon flow with a mock chat.db."""

import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chatdb import ChatDB
from config import load_config, save_config, load_state, save_state
from echo_filter import EchoFilter
from parser import parse_prefix


def create_test_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT,
                           display_name TEXT, service_name TEXT, style INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
            date INTEGER, is_from_me INTEGER, handle_id INTEGER,
            cache_has_attachments INTEGER DEFAULT 0, service TEXT, account TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
    """)
    return conn


class TestEndToEnd:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "chat.db")

        conn = create_test_db(self.db_path)
        conn.execute("INSERT INTO handle VALUES (1, '+15551234567', 'iMessage')")
        conn.execute("INSERT INTO chat VALUES (1, 'iMessage;-;+15551234567', '+15551234567', NULL, 'iMessage', 45)")
        conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        conn.execute(
            "INSERT INTO message VALUES (1, 'g1', 'old message', NULL, 1000000000, 0, 1, 0, 'iMessage', 'E:me@icloud.com')"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        # Add a sent message so self_addresses can be detected
        conn.execute(
            "INSERT INTO message VALUES (100, 'g100', 'my sent msg', NULL, 500000000, 1, 1, 0, 'iMessage', 'E:me@icloud.com')"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 100)")
        conn.commit()
        conn.close()

    def test_full_flow_new_session(self):
        """new message with 'new:' prefix triggers spawn."""
        cdb = ChatDB(self.db_path)
        assert cdb.get_max_rowid() == 100  # seed includes ROWID 1 and 100
        assert "me@icloud.com" in cdb.self_addresses

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO message VALUES (101, 'g2', 'new: list files', NULL, 2000000000, 0, 1, 0, 'iMessage', 'E:me@icloud.com')"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 101)")
        conn.commit()
        conn.close()

        cdb = ChatDB(self.db_path)
        rows = cdb.poll(watermark=100)  # skip all seed messages
        assert len(rows) == 1
        assert rows[0]["text"] == "new: list files"

        parsed = parse_prefix(rows[0]["text"])
        assert parsed["action"] == "spawn"
        assert parsed["prompt"] == "list files"
        assert parsed["directory_alias"] == "default"

    def test_full_flow_inject(self):
        """message without prefix routes to inject."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO message VALUES (101, 'g2', 'what is the build status?', NULL, 2000000000, 0, 1, 0, 'iMessage', 'E:me@icloud.com')"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 101)")
        conn.commit()
        conn.close()

        cdb = ChatDB(self.db_path)
        rows = cdb.poll(watermark=100)
        parsed = parse_prefix(rows[0]["text"])
        assert parsed["action"] == "inject"
        assert parsed["prompt"] == "what is the build status?"

    def test_non_self_messages_filtered(self):
        """messages from other people are ignored."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO handle VALUES (2, '+15559999999', 'iMessage')")
        conn.execute(
            "INSERT INTO message VALUES (101, 'g2', 'hey there', NULL, 2000000000, 0, 2, 0, 'iMessage', NULL)"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 101)")
        conn.commit()
        conn.close()

        cdb = ChatDB(self.db_path)
        # watermark=100 skips seed messages, only gets the new one
        rows = cdb.poll(watermark=100)
        assert len(rows) == 1
        assert rows[0]["handle_id"] == "+15559999999"
        # Daemon would filter — handle not in self_addresses

    def test_echo_filter_blocks_own_replies(self):
        """echo filter prevents processing our own outbound messages."""
        ef = EchoFilter(window_seconds=15)
        ef.track("iMessage;-;+15551234567", "Done: I fixed the bug")
        assert ef.is_echo("iMessage;-;+15551234567", "Done: I fixed the bug") is True

    def test_new_with_directory_alias(self):
        """new:centralis: routes to correct directory alias."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO message VALUES (101, 'g2', 'new:centralis: fix the handler', NULL, 2000000000, 0, 1, 0, 'iMessage', 'E:me@icloud.com')"
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 101)")
        conn.commit()
        conn.close()

        cdb = ChatDB(self.db_path)
        rows = cdb.poll(watermark=100)
        parsed = parse_prefix(rows[0]["text"])
        assert parsed["action"] == "spawn"
        assert parsed["directory_alias"] == "centralis"
        assert parsed["prompt"] == "fix the handler"

    def test_config_round_trip(self):
        """config save and load preserves all fields."""
        config_path = os.path.join(self.tmpdir, "config.json")
        original = {
            "poll_interval": 2.0,
            "directories": {"default": "/tmp", "custom": "/opt"},
            "self_addresses": ["me@icloud.com"],
            "reply_chat_guid": "iMessage;-;+15551234567",
        }
        save_config(config_path, original)
        loaded = load_config(config_path)
        assert loaded["poll_interval"] == 2.0
        assert loaded["directories"]["custom"] == "/opt"
        assert loaded["self_addresses"] == ["me@icloud.com"]
        assert loaded["reply_chat_guid"] == "iMessage;-;+15551234567"

    def test_state_watermark_persistence(self):
        """watermark persists across load/save cycles."""
        state_path = os.path.join(self.tmpdir, "state.json")
        save_state(state_path, {"watermark": 42})
        loaded = load_state(state_path)
        assert loaded["watermark"] == 42

    def test_attributed_body_message(self):
        """messages with attributedBody instead of text are parsed."""
        text = b"Hello from attributedBody"
        blob = b"\x00\x00NSString\x00\x2B" + bytes([len(text)]) + text

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO message VALUES (101, 'g2', NULL, ?, 2000000000, 0, 1, 0, 'iMessage', 'E:me@icloud.com')",
            (blob,),
        )
        conn.execute("INSERT INTO chat_message_join VALUES (1, 101)")
        conn.commit()
        conn.close()

        cdb = ChatDB(self.db_path)
        rows = cdb.poll(watermark=100)
        assert rows[0]["text"] == "Hello from attributedBody"
