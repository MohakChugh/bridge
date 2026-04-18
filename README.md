# iMessage Bridge for Claude Code

Control Claude Code from your iPhone via iMessage. Text yourself a prompt, get a response back as a text message. Persistent sessions, task queuing, directory switching — all from your phone.

## Demo

### Starting a session and getting responses
![Demo 1](assets/demo-1.gif)

### Multi-turn conversation
![Demo 2](assets/demo-2.gif)

## How It Works

A Python daemon runs on your Mac and watches `~/Library/Messages/chat.db` for new self-chat messages (you texting yourself). When a message arrives, it routes to Claude Code via `claude -p` and sends the response back via iMessage through AppleScript.

```
iPhone → iMessage (self-chat) → chat.db → Daemon → claude -p → response → AppleScript → iMessage back to you
```

No server, no cloud relay, no external dependencies. Everything runs locally on your Mac.

## Features

- Text yourself from any device to trigger Claude Code
- Persistent sessions with full conversation context (`--resume`)
- Directory aliases for quick project switching
- Task queue — stack tasks while one is running
- Timed reminders
- Status checks while tasks are running
- MCP server for Claude-initiated iMessage replies
- Auto-starts at login via launchd
- Restarts automatically on crash

## Requirements

- macOS (Ventura 13+ recommended)
- Python 3.10+ (homebrew: `brew install python`)
- tmux (`brew install tmux`)
- Claude Code CLI installed and authenticated
- iMessage signed in on your Mac
- Full Disk Access granted to Python

## Quick Setup

### 1. Clone the repository

```bash
git clone https://github.com/MohakChugh/imessage-claude-bridge.git ~/.claude/imessage-bridge
```

If you already have files at `~/.claude/imessage-bridge/`, back them up first or clone elsewhere and copy.

### 2. Install dependencies

```bash
brew install tmux
pip3 install --break-system-packages mcp pytest
```

### 3. Configure

Edit `~/.claude/imessage-bridge/config.json`:

```json
{
  "poll_interval": 1.0,
  "directories": {
    "default": "/path/to/your/default/workspace",
    "project1": "/path/to/project1",
    "project2": "/path/to/project2",
    "home": "/Users/yourusername/"
  },
  "tmux_session": "claude-session",
  "self_addresses": [],
  "reply_chat_guid": null,
  "claude_p_timeout": 18000,
  "idle_stabilization_checks": 2,
  "idle_check_interval": 5,
  "max_poll_timeout": 600,
  "echo_window_seconds": 15
}
```

Key fields to customize:

| Field | What to change |
|-------|---------------|
| `directories` | Your project paths. Keys become aliases (e.g., `new:project1: do something`) |
| `self_addresses` | Leave empty — auto-detected on first run from your iMessage account |
| `reply_chat_guid` | Leave null — auto-detected on first run |
| `claude_p_timeout` | Max seconds for a single Claude task (default: 18000 = 5 hours) |

### 4. Update the install script

Edit `install.py` and update these paths if they differ on your machine:

- Line with `/opt/homebrew/bin/python3` — path to your homebrew Python
- Line with `HOME` — your home directory
- Line with `BedrockProfile` — your AWS profile (if using Bedrock auth)

If you use **Claude.ai auth** (not Bedrock), remove the Bedrock-specific environment variables from the plist template in `install.py`:
- `CLAUDE_CODE_USE_BEDROCK`
- `AWS_REGION`
- `AWS_PROFILE`
- `ANTHROPIC_MODEL`

If you use **API key auth**, add to the plist template:
```xml
<key>ANTHROPIC_API_KEY</key>
<string>sk-ant-your-key-here</string>
```

### 5. Run the installer

```bash
cd ~/.claude/imessage-bridge
python3 install.py
```

This will:
- Create a launchd plist (auto-starts daemon at login)
- Register the MCP server in `~/.claude/.mcp.json`
- Add a tmux alias to `~/.zshrc`
- Add iMessage Bridge instructions to `~/.claude/CLAUDE.md`

### 6. Grant Full Disk Access

The daemon reads `~/Library/Messages/chat.db` which is protected by macOS TCC.

1. Open **System Settings** > **Privacy & Security** > **Full Disk Access**
2. Click **+**
3. Navigate to `/opt/homebrew/bin/` (press Cmd+Shift+G to type the path)
4. Select `python3` (or `python3.14` — whichever your homebrew installed)
5. Toggle it ON

If you're unsure which Python binary to add, run:
```bash
which python3
```

### 7. Grant Automation Permission

The first time the daemon sends an iMessage reply, macOS will prompt:

> "Terminal wants to control Messages"

Click **OK**. If you miss the prompt, go to **System Settings** > **Privacy & Security** > **Automation** and enable it manually.

### 8. Text yourself

Open Messages on your iPhone. Start a conversation with yourself (your own phone number or Apple ID). Send:

```
new:home: hello, what can you help me with?
```

You should get a response back within 10-30 seconds.

### 9. Restart your terminal

To pick up the tmux alias:

```bash
source ~/.zshrc
```

Now typing `claude` in your terminal opens Claude Code inside a tmux session, which enables the inject feature for messages without a prefix.

## Usage

### Starting a session

```
new:home: what files are in my home directory?
new:project1: run the tests and tell me if they pass
new: do something in the default workspace
```

Format: `new:<directory_alias>: <your prompt>`

### Continuing a conversation

Just type normally — no prefix needed. The session persists.

```
You: new:home: what's in .zshrc?
Claude: [shows zshrc contents]

You: add an alias for ll
Claude: [adds the alias]

You: actually make it ls -lah instead
Claude: [updates the alias]
```

### Commands

| Command | What it does |
|---------|-------------|
| `/status` | Shows what Claude is working on right now |
| `/end` | Ends the current session |
| `/cancel` | Kills a running task immediately |
| `/switch <dir>` | Switch directory without ending session |
| `/history` | Shows last 5 messages in current session |
| `/sessions` | Lists saved Claude sessions you can resume |
| `/dirs` | Shows all directory aliases and which is active |
| `/queue <prompt>` | Queue a task to run after the current one finishes |
| `/remind <time> <msg>` | Set a timed reminder (e.g., `/remind 30m check the deploy`) |
| `/help` | Shows all available commands |

### Time formats for /remind

- `30s` — 30 seconds
- `5m` — 5 minutes
- `1h` — 1 hour
- `2h30m` — 2 hours 30 minutes

### Task queue example

```
You: new:project1: run the full test suite
Claude: On it.

You: /queue fix any failing tests
You: /queue run the tests again after fixing

Claude: [finishes first task]
Claude: Next queued: fix any failing tests
Claude: On it.
[...]
Claude: Next queued: run the tests again after fixing
Claude: On it.
```

## Architecture

```
~/.claude/imessage-bridge/
├── daemon.py          # Main daemon — polls chat.db, routes messages
├── parser.py          # Message prefix parsing + attributedBody extraction
├── chatdb.py          # SQLite reader for ~/Library/Messages/chat.db
├── router.py          # Spawns claude -p sessions, manages tmux injection
├── sender.py          # Sends iMessages via AppleScript
├── echo_filter.py     # Prevents daemon from processing its own replies
├── config.py          # Config and state management
├── mcp_server.py      # MCP server (imessage_reply + imessage_history tools)
├── install.py         # One-time installer
├── config.json        # User configuration
├── state.json         # Runtime state (watermark, active session)
└── tests/             # 49 unit + integration tests
```

### Key design decisions

**Self-chat only**: The daemon only processes messages from your own Apple ID addresses. Other people's texts are silently ignored. No pairing, no allowlists — single-user system.

**Zero-width space marker**: All outbound messages include an invisible Unicode marker (U+200B). The daemon checks for this on inbound and skips — preventing the self-chat echo loop.

**zsh login shell**: `claude -p` runs inside `zsh -l -c` so it inherits your full terminal environment (PATH, aliases, env vars). Tools like brazil, ada, npm, cargo all work.

**Persistent sessions**: Session IDs are captured from `claude -p --output-format json` and stored in `state.json`. Subsequent messages use `--resume <session_id>` to continue the conversation with full context.

**Background threading**: Tasks run in daemon threads so the poll loop stays responsive. `/status`, `/cancel`, and other commands work instantly even while a task is running.

## MCP Server

The bridge includes a standard MCP server that gives Claude two tools:

- `imessage_reply` — Send an iMessage (used when Claude processes an `[iMessage]` prefixed prompt)
- `imessage_history` — Read recent message history from self-chat

Registered in `~/.claude/.mcp.json`. Available in all Claude Code sessions.

## Configuration Reference

### config.json

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `poll_interval` | float | 1.0 | Seconds between chat.db polls |
| `directories` | object | — | Alias-to-path mapping for `new:<alias>:` prefix |
| `tmux_session` | string | "claude-session" | tmux session name for inject mode |
| `self_addresses` | array | [] | Auto-detected Apple ID addresses (email + phone) |
| `reply_chat_guid` | string | null | Auto-detected self-chat GUID |
| `claude_p_timeout` | int | 18000 | Max seconds per task (5 hours) |
| `echo_window_seconds` | int | 15 | Echo filter window |

### Environment Variables (in launchd plist)

The installer writes these into the launchd plist. Edit `~/Library/LaunchAgents/com.claude.imessage-bridge.plist` to change:

| Variable | Required for |
|----------|-------------|
| `HOME` | All (Python needs this) |
| `PATH` | Finding claude, tmux, and other tools |
| `CLAUDE_CODE_USE_BEDROCK` | Bedrock auth only |
| `AWS_REGION` | Bedrock auth only |
| `AWS_PROFILE` | Bedrock auth only |
| `ANTHROPIC_MODEL` | Bedrock auth only |
| `ANTHROPIC_API_KEY` | API key auth only |

## Troubleshooting

### Daemon not starting

```bash
# Check if it's running
launchctl list | grep imessage-bridge

# Check logs
tail -20 ~/.claude/imessage-bridge/logs/daemon.log

# Manual start for debugging
python3 ~/.claude/imessage-bridge/daemon.py
```

### "authorization denied" error

Full Disk Access not granted. Add your Python binary to System Settings > Privacy & Security > Full Disk Access.

### "Not logged in" error

Claude CLI credentials not available in the launchd environment. Check that the correct auth environment variables are in the plist:

```bash
cat ~/Library/LaunchAgents/com.claude.imessage-bridge.plist | grep -A1 "ANTHROPIC\|CLAUDE\|AWS"
```

### Messages not being detected

```bash
# Check self_addresses in config
cat ~/.claude/imessage-bridge/config.json | python3 -m json.tool

# Verify your addresses include both email AND phone
# If not, delete self_addresses array and restart daemon to re-detect
```

### Echo loop (daemon responding to its own messages)

This should not happen with the zero-width space marker. If it does:

```bash
# Stop immediately
launchctl unload ~/Library/LaunchAgents/com.claude.imessage-bridge.plist

# Reset watermark to skip loop messages
python3 -c "
from chatdb import ChatDB; import json
cdb = ChatDB('$HOME/Library/Messages/chat.db')
json.dump({'watermark': cdb.get_max_rowid()}, open('state.json','w'))
"

# Restart
launchctl load ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

### Reload after code changes

```bash
launchctl unload ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
launchctl load ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

## Running Tests

```bash
cd ~/.claude/imessage-bridge
python3 -m pytest tests/ -v
```

49 tests covering config, parser, echo filter, chat.db reader, sender, router, and end-to-end integration.

## License

MIT
