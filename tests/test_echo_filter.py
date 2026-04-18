import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from echo_filter import EchoFilter


def test_track_and_consume():
    ef = EchoFilter(window_seconds=15)
    ef.track("chat1", "Hello world")
    assert ef.is_echo("chat1", "Hello world") is True
    assert ef.is_echo("chat1", "Hello world") is False


def test_different_chat_not_consumed():
    ef = EchoFilter(window_seconds=15)
    ef.track("chat1", "Hello world")
    assert ef.is_echo("chat2", "Hello world") is False


def test_different_text_not_consumed():
    ef = EchoFilter(window_seconds=15)
    ef.track("chat1", "Hello world")
    assert ef.is_echo("chat1", "Goodbye world") is False


def test_normalize_strips_signature():
    ef = EchoFilter(window_seconds=15)
    ef.track("chat1", "Hello world\nSent by Claude")
    assert ef.is_echo("chat1", "Hello world") is True


def test_normalize_collapses_whitespace():
    ef = EchoFilter(window_seconds=15)
    ef.track("chat1", "Hello   world")
    assert ef.is_echo("chat1", "Hello world") is True


def test_expired_echo_not_consumed():
    ef = EchoFilter(window_seconds=0.1)
    ef.track("chat1", "Hello")
    time.sleep(0.2)
    assert ef.is_echo("chat1", "Hello") is False


def test_prune_removes_old_entries():
    ef = EchoFilter(window_seconds=0.1)
    ef.track("chat1", "msg1")
    ef.track("chat1", "msg2")
    time.sleep(0.2)
    ef.track("chat1", "msg3")
    assert len(ef._echoes) == 1
