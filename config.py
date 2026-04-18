"""Configuration and state management for iMessage Bridge."""

import json
import os

DEFAULT_CONFIG = {
    "poll_interval": 1.0,
    "directories": {
        "default": "/Volumes/workspace/",
        "centralis": "/Volumes/workspace/Nexus/MyBackendService/src",
        "frontend": "/Users/chumohak/workspace/Nexus/MyFrontendModule/src",
        "nexus": "/Volumes/workspace/Nexus/",
        "home": "/Users/chumohak/",
    },
    "tmux_session": "claude-session",
    "self_addresses": [],
    "reply_chat_guid": None,
    "claude_p_timeout": 18000,
    "idle_stabilization_checks": 2,
    "idle_check_interval": 5,
    "max_poll_timeout": 600,
    "echo_window_seconds": 15,
    "cli_tool": "claude",
    "adapters": {
        "claude": {"effort": "max"},
        "wasabi": {"account": "YOUR_ACCT_ID", "model": "global.anthropic.claude-opus-4-6-v1:1m"},
    },
}


def load_config(path: str) -> dict:
    """Load config from path, returning defaults if file missing or corrupt."""
    try:
        with open(path) as f:
            data = json.load(f)
        merged = {**DEFAULT_CONFIG, **data}
        merged["directories"] = {**DEFAULT_CONFIG["directories"], **data.get("directories", {})}
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(path: str, data: dict) -> None:
    """Atomically write config to path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.rename(tmp, path)


def load_state(path: str) -> dict:
    """Load persisted state (watermark, etc). Returns defaults if missing."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"watermark": 0}


def save_state(path: str, state: dict) -> None:
    """Atomically write state to path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
        f.write("\n")
    os.rename(tmp, path)
