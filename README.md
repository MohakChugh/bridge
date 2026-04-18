# iMessage Bridge for Claude Code

Control Claude Code, Wasabi, and Kiro CLI from your iPhone via iMessage. Text yourself a prompt, get a response back as a text message. Persistent sessions, voice memos, scheduled tasks, multi-tool switching — all from your phone.

## Demo

### Starting a session and getting responses
![Demo 1](assets/demo-1.gif)

### Multi-turn conversation
![Demo 2](assets/demo-2.gif)

## How It Works

A Python daemon runs on your Mac and watches `~/Library/Messages/chat.db` for new self-chat messages (you texting yourself). When a message arrives, it routes to your chosen CLI tool and sends the response back via iMessage.

```
iPhone → iMessage (self-chat) → chat.db → Daemon → CLI tool → response → iMessage back
```

No server, no cloud relay. Everything runs locally on your Mac.

## Features

### Multi-Tool Support
- **Claude Code** — with persistent sessions, `--resume`, `--effort max`
- **Wasabi** — Amazon's internal AI tool, auto-resumes per directory
- **Kiro CLI** — with session management, custom agent support
- Switch between tools instantly via `/tool <name>`

### Session Management
- Persistent sessions with full conversation context
- Sessions survive daemon restarts and laptop reboots
- `/switch <dir>` — switch directory with session picker (numbered list)
- Multi-turn conversations — just type normally after starting

### Voice Memos
- Send a voice memo from your phone → auto-transcribed locally
- **Parakeet V3** (Apple Silicon optimized) as primary STT
- **OpenAI Whisper** as fallback
- Shows transcription for confirmation before executing

### Scheduled Tasks
- Natural language: `/schedule every morning check pipeline status`
- LLM parses schedule → you confirm → runs on cron
- Persists forever across restarts
- Full management: list, cancel, pause, resume

### Smart Reminders
- Natural language: `/remind tomorrow 9am check deploy`
- LLM parses time → you confirm
- Also supports relative: `/remind 5m check build`
- Persists across restarts, list/cancel support

### Progress Tracking (Claude Code only)
- `/eta` — real-time progress, task list, ETA estimate
- Auto-progress updates every 15 minutes (configurable)
- Stuck detection: alerts if task hangs for 90+ minutes
- Self-diagnosis: asks Claude why it's stuck

### Productivity
- Task queue — stack tasks while one is running
- Directory aliases for instant project switching
- Background threading — commands work while tasks run

## Requirements

- macOS (Ventura 13+ recommended)
- Python 3.10+ (`brew install python`)
- Claude Code CLI installed and authenticated
- iMessage signed in on your Mac
- Full Disk Access granted to Python

### Optional
- Wasabi CLI (for `/tool wasabi`)
- Kiro CLI (for `/tool kiro`)
- ffmpeg (`brew install ffmpeg`) — for voice memo conversion
- parakeet-mlx (`pip3 install parakeet-mlx`) — Parakeet V3 STT
- openai-whisper (`pip3 install openai-whisper`) — Whisper STT fallback

## Quick Setup

### 1. Clone

```bash
git clone https://github.com/MohakChugh/imessage-claude-bridge.git ~/.claude/imessage-bridge
```

### 2. Install dependencies

```bash
pip3 install --break-system-packages mcp pytest
pip3 install --break-system-packages parakeet-mlx openai-whisper  # For voice
brew install ffmpeg  # For voice memo conversion
```

### 3. Configure

Edit `~/.claude/imessage-bridge/config.json`:

```json
{
  "poll_interval": 1.0,
  "directories": {
    "default": "/path/to/workspace",
    "home": "/Users/yourusername/",
    "project1": "/path/to/project1"
  },
  "self_addresses": [],
  "reply_chat_guid": null,
  "claude_p_timeout": 18000,
  "cli_tool": "claude",
  "adapters": {
    "claude": { "effort": "max" },
    "wasabi": { "account": "YOUR_ACCOUNT_ID", "model": "global.anthropic.claude-opus-4-6-v1:1m" },
    "kiro": { "model": "claude-opus-4.7" }
  }
}
```

- `directories` — your project paths (keys become aliases)
- `self_addresses` — leave empty, auto-detected on first run
- `cli_tool` — default tool: `claude`, `wasabi`, or `kiro`
- `adapters` — per-tool configuration

### 4. Run the installer

```bash
cd ~/.claude/imessage-bridge && python3 install.py
```

### 5. Grant Full Disk Access

System Settings > Privacy & Security > Full Disk Access > add your Python binary (`/opt/homebrew/bin/python3`)

### 6. Text yourself

Open Messages on your iPhone. Text yourself:

```
new:home: hello, what can you help me with?
```

## Commands Reference

### Session

| Command | Description |
|---------|-------------|
| `new:<dir>: <prompt>` | Start new session in directory |
| *(just type)* | Continue current session |
| `/status` | What's happening now |
| `/end` | End current session |
| `/cancel` | Kill running task |
| `/history` | Last 5 messages |
| `/sessions` | List saved sessions |

### Navigation

| Command | Description |
|---------|-------------|
| `/switch <dir>` | Switch directory (shows session picker) |
| `/dirs` | Show directory aliases |
| `/tool <name>` | Switch CLI tool (claude/wasabi/kiro) |
| `/tool` | Show current tool |

### Progress (Claude Code only)

| Command | Description |
|---------|-------------|
| `/eta` | Task progress, todos, ETA |
| `/eta interval 5m` | Change auto-update interval (default 15m) |
| `/eta stuck 2h` | Change stuck alert threshold (default 90m) |
| `/eta stuck off` | Disable stuck alerts |

### Schedule

| Command | Description |
|---------|-------------|
| `/schedule <natural language>` | Create recurring task (LLM parses) |
| `/schedule list` | Show active schedules |
| `/schedule cancel <N>` | Cancel by number |
| `/schedule cancel all` | Cancel all |
| `/schedule pause <N>` | Pause schedule |
| `/schedule resume <N>` | Resume paused schedule |

### Reminders

| Command | Description |
|---------|-------------|
| `/remind <natural language>` | Set reminder (LLM parses time) |
| `/remind 5m check build` | Quick relative time (backward compat) |
| `/remind list` | Show pending reminders |
| `/remind cancel <N>` | Cancel by number |
| `/remind cancel all` | Cancel all |

### Voice

Send a voice memo from your phone — auto-detected, transcribed locally (Parakeet V3 / Whisper), shown for confirmation before executing.

### Other

| Command | Description |
|---------|-------------|
| `/queue <prompt>` | Run after current task finishes |
| `/help` | Show all commands |

## Architecture

```
~/.claude/imessage-bridge/
├── daemon.py              # Main daemon — polls chat.db, routes messages
├── parser.py              # Message prefix parsing + attributedBody extraction
├── chatdb.py              # SQLite reader for ~/Library/Messages/chat.db
├── sender.py              # Sends iMessages via AppleScript
├── echo_filter.py         # Prevents daemon from processing its own replies
├── config.py              # Config and state management
├── router.py              # Legacy spawn (backward compat)
├── progress_tracker.py    # /eta progress tracking + stuck detection
├── scheduler.py           # Cron scheduler for /schedule
├── transcriber.py         # Voice memo transcription (Parakeet V3 / Whisper)
├── mcp_server.py          # MCP server (imessage_reply + imessage_history)
├── install.py             # One-time installer
├── adapters/
│   ├── base.py            # Abstract adapter + login shell env capture
│   ├── claude_adapter.py  # Claude Code CLI adapter
│   ├── wasabi_adapter.py  # Wasabi CLI adapter
│   └── kiro_adapter.py    # Kiro CLI adapter
├── config.json            # User configuration
├── state.json             # Runtime state (sessions, reminders, schedules)
└── tests/                 # 225 tests
```

### Key Design Decisions

**Adapter pattern**: Each CLI tool (Claude/Wasabi/Kiro) is a separate adapter file. Adding a new tool = drop a Python file in `adapters/`.

**Self-chat only**: Only processes messages from your own Apple ID. Other texts silently ignored.

**Zero-width space marker**: Outbound messages include invisible U+200B marker. Daemon skips any inbound containing it — prevents echo loops.

**Login shell environment**: Captures full `zsh -i` environment once, passes to all subprocesses. Tools like brazil-build, ada, cargo all work.

**Persistent sessions**: Session IDs stored in `state.json`. Survive daemon restarts and laptop reboots. Claude uses `--resume`, Kiro uses `--resume-id`, Wasabi auto-resumes per directory.

**Background threading**: Tasks run in daemon threads. Commands (`/status`, `/cancel`, `/eta`) respond instantly while tasks run.

**Stuck detection**: Monitors child PIDs. If unchanged for 10+ minutes past threshold, sends escalating alerts with self-diagnosis.

## Troubleshooting

### Daemon not starting

```bash
launchctl list | grep imessage-bridge
tail -20 ~/.claude/imessage-bridge/logs/daemon.log
python3 ~/.claude/imessage-bridge/daemon.py  # Manual debug
```

### "authorization denied"

Add Python to Full Disk Access in System Settings.

### "Not logged in"

Auth env vars missing from launchd plist. Check:
```bash
grep -A1 "ANTHROPIC\|CLAUDE\|AWS" ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

### Tools not found (brazil-build, ada)

Daemon captures login shell env at startup. If tools were installed after daemon started, restart:
```bash
launchctl unload ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
launchctl load ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

### Echo loop

```bash
launchctl unload ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
cd ~/.claude/imessage-bridge && python3 -c "
from chatdb import ChatDB; import json
cdb = ChatDB('$HOME/Library/Messages/chat.db')
json.dump({'watermark': cdb.get_max_rowid()}, open('state.json','w'))
"
launchctl load ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

## Running Tests

```bash
cd ~/.claude/imessage-bridge
python3 -m pytest tests/ -v
```

225 tests covering daemon commands, message routing, adapters, config, parsing, echo filter, progress tracking, scheduling, and end-to-end integration.

## License

MIT
