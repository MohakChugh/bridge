import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import load_config, save_config, load_state, save_state, DEFAULT_CONFIG


def test_load_config_defaults_when_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        cfg = load_config(path)
        assert cfg["poll_interval"] == 1.0
        assert cfg["directories"]["default"] == "/path/to/workspace"
        assert cfg["cli_tool"] == "claude"


def test_load_config_reads_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        data = {"poll_interval": 2.0, "directories": {"default": "/tmp"}, "tmux_session": "test"}
        with open(path, "w") as f:
            json.dump(data, f)
        cfg = load_config(path)
        assert cfg["poll_interval"] == 2.0
        assert cfg["directories"]["default"] == "/tmp"


def test_save_config_atomic():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "config.json")
        data = {"poll_interval": 1.0, "directories": {"default": "/tmp"}}
        save_config(path, data)
        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["poll_interval"] == 1.0


def test_load_state_defaults_when_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        state = load_state(path)
        assert state["watermark"] == 0


def test_save_state_atomic():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        save_state(path, {"watermark": 12345})
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["watermark"] == 12345
