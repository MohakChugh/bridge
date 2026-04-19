# iMessage Bridge for Claude Code

Control Claude Code, Wasabi, and Kiro CLI from your iPhone via iMessage. Text yourself a prompt, get a response back. Persistent sessions, watch mode, scheduled tasks, smart reminders — all from your phone.

## Demo

### Starting a session and getting responses
![Demo 1](assets/demo-1.gif)

### Multi-turn conversation
![Demo 2](assets/demo-2.gif)

## How It Works

```
iPhone → iMessage (self-chat) → chat.db → Daemon → CLI tool → response → iMessage back
```

Python daemon on your Mac polls `~/Library/Messages/chat.db` every second. Detects new self-chat messages, routes to your chosen CLI tool, sends response back via AppleScript. No server, no cloud relay — everything local.

## Features

### Multi-Tool Support
- **Claude Code** — persistent sessions, `--resume`, `--effort max`
- **Wasabi** — Amazon internal AI, auto-resumes per directory
- **Kiro CLI** — session management, custom agent support
- Switch instantly: `/tool claude`, `/tool wasabi`, `/tool kiro`

### Watch Mode (Real-Time Monitoring)
- Monitor pipelines, tickets, alarms for state changes
- Natural language: `/watch all my pipelines`
- Auto-diagnose + suggest fix on alert
- Dashboard, mute, snooze, pause/resume
- 30min cooldown prevents alert spam
- Persists across restarts

### Scheduled Tasks
- Natural language: `/schedule every morning check pipeline status`
- LLM parses schedule → you confirm → runs on cron
- Full management: list, cancel, pause, resume
- Runs in separate process (doesn't block)

### Smart Reminders
- Natural language: `/remind tomorrow 9am check deploy`
- Also supports relative: `/remind 5m check build`
- List, cancel, persists across restarts

### Progress Tracking (Claude Code)
- `/eta` — elapsed time, current action, task progress, ETA
- Auto-progress updates (configurable interval)
- Stuck detection: alerts if task hangs 90+ minutes
- Self-diagnosis: asks Claude why it's stuck

### Session Management
- Persistent sessions with full conversation context
- `/switch <dir>` — switch directory with session picker
- Multi-turn conversations — just type normally
- Survives daemon restarts and laptop reboots

## Requirements

- macOS (Ventura 13+)
- Python 3.10+ (`brew install python`)
- Claude Code CLI installed and authenticated
- iMessage signed in on your Mac
- Full Disk Access granted to Python

### Optional
- Wasabi CLI (for `/tool wasabi`)
- Kiro CLI (for `/tool kiro`)

## Quick Setup

### 1. Clone

```bash
git clone https://github.com/MohakChugh/imessage-claude-bridge.git ~/.claude/imessage-bridge
```

### 2. Install dependencies

```bash
pip3 install --break-system-packages mcp pytest
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

### 4. Run installer

```bash
cd ~/.claude/imessage-bridge && python3 install.py
```

### 5. Grant Full Disk Access

System Settings > Privacy & Security > Full Disk Access > add `/opt/homebrew/bin/python3`

### 6. Text yourself

```
new:home: hello, what can you help me with?
```

## Commands

### Session
| Command | Description |
|---------|-------------|
| `/status` | What's happening now (works while busy) |
| `/end` | End session, clear context |
| `/cancel` | Kill running task immediately |
| `/history` | Last 5 messages |
| `/sessions` | List saved sessions |
| `/queue <prompt>` | Run after current task |

### Navigation
| Command | Description |
|---------|-------------|
| `/switch <dir>` | Switch directory + pick session |
| `/dirs` | Show directory aliases |
| `/tool` | Show current CLI tool |
| `/tool <name>` | Switch tool (claude/wasabi/kiro) |

### Progress (Claude Code)
| Command | Description |
|---------|-------------|
| `/eta` | Progress: elapsed, action, todos, ETA |
| `/eta interval 5m` | Auto-update interval |
| `/eta stuck 2h` | Stuck alert threshold |

### Watch
| Command | Description |
|---------|-------------|
| `/watch` | Dashboard: watches + alerts + status |
| `/watch <text>` | Create watch (LLM parses) |
| `/watch list` | Show all watches |
| `/watch stop <N>` | Stop watch |
| `/watch stop all` | Stop all |
| `/watch pause <N>` | Pause watch |
| `/watch resume <N>` | Resume watch |
| `/watch mute <time>` | Silence all watches |
| `/watch snooze <N>` | Snooze 30min |

Examples:
```
/watch all my pipelines
/watch new high sev tickets on MyTeam-Resolver
/watch pipeline MyBackendService
```

### Schedule
| Command | Description |
|---------|-------------|
| `/schedule <text>` | Create recurring task (LLM parses) |
| `/schedule list` | Show schedules |
| `/schedule cancel <N>` | Cancel |
| `/schedule pause <N>` | Pause |
| `/schedule resume <N>` | Resume |

Examples:
```
/schedule every morning check pipeline status
/schedule daily 9am open ticket report
/schedule every friday oncall report
```

### Remind
| Command | Description |
|---------|-------------|
| `/remind <text>` | Set reminder (LLM parses) |
| `/remind 5m msg` | Quick relative time |
| `/remind list` | Show reminders |
| `/remind cancel <N>` | Cancel |

Examples:
```
/remind tomorrow 9am check deploy
/remind in 30 minutes call John
/remind friday 5pm submit report
```

### Start Session
```
new:<dir>: <prompt>    Start in directory
new:home: hello        Example
new:centralis: fix bug Example
(just type normally)   Continue session
```

## Architecture

```
~/.claude/imessage-bridge/
├── daemon.py              # Main daemon — polls chat.db, routes messages
├── watcher.py             # Watch mode — checkers, classification, alerts
├── scheduler.py           # Cron scheduler for /schedule
├── progress_tracker.py    # /eta progress tracking + stuck detection
├── parser.py              # Message prefix parsing
├── chatdb.py              # SQLite reader for chat.db
├── sender.py              # iMessage via AppleScript
├── echo_filter.py         # Prevents echo loops
├── config.py              # Config and state management
├── mcp_server.py          # MCP server (imessage_reply + imessage_history)
├── adapters/
│   ├── base.py            # Abstract adapter + env capture
│   ├── claude_adapter.py  # Claude Code
│   ├── wasabi_adapter.py  # Wasabi
│   └── kiro_adapter.py    # Kiro CLI
├── config.json            # User configuration
├── state.json             # Runtime state
└── tests/                 # 256 tests
```

### Key Design Decisions

**Adapter pattern**: Each CLI tool is a separate adapter. Adding a new tool = drop a Python file in `adapters/`.

**Self-chat only**: Only processes messages from your own Apple ID.

**Zero-width space marker**: Outbound messages include invisible U+200B marker — prevents echo loops.

**Login shell env**: Captures full `zsh -i` environment for subprocesses. Tools like brazil-build, ada, cargo all work.

**Watch: alert on change only**: Never alerts on same state twice. ID-set comparison for tickets, flag comparison for pipelines. 30min cooldown prevents spam.

**Background threading**: Tasks, watches, schedules, reminders all run in daemon threads. Commands respond instantly.

## Troubleshooting

### Daemon not starting
```bash
launchctl list | grep imessage-bridge
tail -20 ~/.claude/imessage-bridge/logs/daemon.log
```

### "authorization denied"
Add Python to Full Disk Access in System Settings.

### Tools not found (brazil-build, ada)
Restart daemon — it captures login shell env at startup:
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

## Tests

```bash
cd ~/.claude/imessage-bridge && python3 -m pytest tests/ -v
```

256 tests covering daemon commands, message routing, adapters, config, parsing, echo filter, progress tracking, scheduling, watching, and integration.

## License

MIT
