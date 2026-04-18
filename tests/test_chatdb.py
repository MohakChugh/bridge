import os
import sys
import sqlite3
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from chatdb import ChatDB


def create_test_db(path: str) -> sqlite3.Connection:
    """Create a minimal chat.db schema for testing."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT,
                           display_name TEXT, service_name TEXT, style INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB,
            date INTEGER, is_from_me INTEGER, handle_id INTEGER,
            cache_has_attachments INTEGER DEFAULT 0, service TEXT,
            account TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
    """)
    return conn


def seed_self_chat(conn: sqlite3.Connection):
    """Seed a self-chat scenario."""
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567', 'iMessage')")
    conn.execute("INSERT INTO chat VALUES (1, 'iMessage;-;+15551234567', '+15551234567', NULL, 'iMessage', 45)")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    ns = 1000000000
    conn.execute(
        "INSERT INTO message VALUES (1, 'guid1', 'Hello Claude', NULL, ?, 0, 1, 0, 'iMessage', 'E:me@icloud.com')",
        (ns,),
    )
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (2, 'guid2', 'Response', NULL, ?, 1, 1, 0, 'iMessage', 'E:me@icloud.com')",
        (2 * ns,),
    )
    conn.execute("INSERT INTO chat_message_join VALUES (1, 2)")
    conn.commit()


def test_detect_self_addresses():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        assert "me@icloud.com" in cdb.self_addresses


def test_get_watermark():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        assert cdb.get_max_rowid() == 2


def test_poll_new_messages():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        rows = cdb.poll(watermark=0)
        assert len(rows) == 2
        assert rows[0]["rowid"] == 1
        assert rows[0]["text"] == "Hello Claude"
        assert rows[0]["chat_guid"] == "iMessage;-;+15551234567"


def test_poll_respects_watermark():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        rows = cdb.poll(watermark=1)
        assert len(rows) == 1
        assert rows[0]["rowid"] == 2


def test_detect_self_chat_guid():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        guid = cdb.find_self_chat_guid()
        assert guid == "iMessage;-;+15551234567"


def test_get_history():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "chat.db")
        conn = create_test_db(db_path)
        seed_self_chat(conn)
        conn.close()
        cdb = ChatDB(db_path)
        history = cdb.get_history("iMessage;-;+15551234567", limit=10)
        assert len(history) == 2
        assert history[0]["text"] == "Hello Claude"
