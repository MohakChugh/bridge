# Bridge — Control Claude Code from Anywhere

Chat with Claude Code, Wasabi, and Kiro CLI from your **phone, Slack, or a beautiful web dashboard**. Persistent sessions, parallel execution, watch mode, scheduled tasks, smart reminders — all with real-time updates across every channel.

## What is this?

A multi-channel daemon that lets you drive Amazon's internal AI CLIs from any device:

- **Web dashboard** (localhost:7777) — React + TailwindCSS admin panel with chat, session tabs, live activity feed, and full CRUD for reminders/schedules/watches
- **iMessage** — self-chat from your iPhone, Apple Watch, or any Apple device
- **Slack DM** — DM your bot from anywhere (laptop, dev desktop, phone)

All channels route through the same daemon with shared session state, parallel execution, and cumulative memory across conversations.

## Demo

### Starting a session and getting responses
![Demo 1](assets/demo-1.gif)

### Multi-turn conversation
![Demo 2](assets/demo-2.gif)

## How It Works

```
┌─────────┐  ┌────────┐  ┌────────────┐
│ iPhone  │  │ Slack  │  │ Web (:7777)│
└────┬────┘  └───┬────┘  └──────┬─────┘
     │          │              │
     ▼          ▼              ▼
┌────────────────────────────────────────┐
│   Python Daemon (macOS / Linux)        │
│                                         │
│   SessionManager (parallel, per-sess)  │
│   EventBus (pub/sub for live updates)  │
│   FastAPI Gateway (REST + WebSocket)   │
│                                         │
│   Channels: iMessage poll · Slack WS   │
│   Adapters: Claude · Wasabi · Kiro     │
└────────────────────────────────────────┘
```

Python daemon runs as launchd/systemd service. Polls iMessage `chat.db` every second. Connects to Slack via Socket Mode WebSocket. Serves a React dashboard on `localhost:7777`. Routes every message through `SessionManager` which spawns the right CLI adapter with proper session state. Sends replies back on the same channel.

## Features

### Web Dashboard (NEW)

- **Multi-session tabs** — run multiple conversations in parallel, switch instantly
- **Stats overview** — sessions running, reminders upcoming, schedules active, watches alerting
- **Live activity feed** — last 15 messages across all sessions, role-coded
- **Full CRUD admin** — create/pause/resume/delete reminders, schedules, watches via UI
- **Natural-language parse** — type "tomorrow 9am check deploy" → LLM parses → you confirm → saved
- **Tool picker buttons** — select Claude / Wasabi / Kiro per session
- **WebSocket live updates** — session state, new messages, completion events push in real time
- **Dark theme** — polished shadcn-style UI, 75KB gzipped bundle

### Slack Integration (NEW)

- **Socket Mode** — no public URL needed, runs via outbound WebSocket
- **Bare commands** — `status`, `help`, `tool wasabi` (no slash, since Slack eats `/`)
- **Thread-aware replies** — bot replies stay in message thread
- **Emoji reactions** — ⚡ on acknowledgment, cleaner than "On it." text
- **Same commands as iMessage** — every feature works identically

### Multi-Tool Support

- **Claude Code** — persistent sessions, `--resume`, `--effort max`
- **Wasabi** — Amazon internal AI, **conversational memory** injected via prompt history (non-interactive mode resets context otherwise)
- **Kiro CLI** — session management, custom agent support
- Switch instantly: `tool claude` / `tool wasabi` / `tool kiro`

### Parallel Execution (NEW)

- Up to 4 sessions running concurrently by default (configurable)
- Per-session lock prevents double-execution within a session
- Global semaphore prevents CPU saturation
- Each channel sees live status for all running sessions

### Watch Mode (Real-Time Monitoring)

- Monitor pipelines, tickets, alarms for state changes
- Natural language: `watch all my pipelines`
- Auto-diagnose + suggest fix on alert
- Dashboard, mute, snooze, pause/resume
- 30min cooldown prevents alert spam
- Persists across restarts

### Scheduled Tasks

- Natural language: `schedule every morning check pipeline status`
- LLM parses schedule → you confirm → runs on cron
- Full management: list, cancel, pause, resume
- Runs in separate process (doesn't block)
- **Create via UI or text**

### Smart Reminders

- Natural language: `remind tomorrow 9am check deploy`
- Also supports relative: `remind 5m check build`
- List, cancel, persists across restarts
- **Create via UI or text**

### Progress Tracking (Claude Code)

- `eta` — elapsed time, current action, task progress, ETA
- Auto-progress updates (configurable interval)
- Stuck detection: alerts if task hangs 90+ minutes
- Self-diagnosis: asks Claude why it's stuck

### Session Management

- Persistent sessions with full conversation context
- `switch <dir>` — switch directory with session picker
- Multi-turn conversations — just type normally
- Survives daemon restarts and laptop reboots
- **Web UI: click tab to switch, + button for new, X to delete**

## Requirements

- macOS 13+ (Ventura) **OR** Linux (Amazon Linux / Ubuntu)
- Python 3.10+ (`brew install python` / `yum install python3`)
- Node.js 18+ (for dashboard build, optional)
- Claude Code CLI installed and authenticated
- **macOS only:** iMessage signed in, Full Disk Access granted
- **Linux:** Slack-only mode (iMessage gracefully disabled)

### Optional

- Wasabi CLI (for Wasabi adapter)
- Kiro CLI (for Kiro adapter)

## Quick Setup

### 1. Clone

```bash
git clone https://github.com/MohakChugh/imessage-claude-bridge.git ~/bridge
cd ~/bridge
```

### 2. Install dependencies

```bash
pip3 install --break-system-packages mcp pytest slack-bolt slack-sdk fastapi uvicorn
```

### 3. Configure

```bash
cp config.example.json config.json
# Edit: set directories, self_addresses (macOS), slack tokens (optional)
```

Config highlights:

```json
{
  "directories": {
    "default": "/path/to/workspace",
    "home": "/Users/you/",
    "centralis": "/workspace/Centralis/..."
  },
  "cli_tool": "wasabi",
  "max_parallel_sessions": 4,
  "gateway": { "enabled": true, "port": 7777 },
  "slack": {
    "enabled": true,
    "bot_token": "xoxb-...",
    "app_token": "xapp-...",
    "allowed_users": ["U01XXXXX"]
  }
}
```

### 4. Build the dashboard (optional)

```bash
cd web && npm install && npm run build && cd ..
```

### 5. Run the daemon

**macOS (launchd):**
```bash
python3 install.py
```

**Linux (systemd):**
```bash
# See docs/dev-desktop-setup.md
systemctl --user enable --now bridge
```

**Foreground (both):**
```bash
python3 daemon.py
```

### 6. Access your dashboard

Open http://localhost:7777 — create sessions, chat, manage automation.

## Slack Setup

1. Go to api.slack.com/apps → Create New App → From manifest
2. Use the manifest from `docs/slack-manifest.json`
3. Add `opus-amazon-prod` as collaborator (Amazon Slack only)
4. Install to workspace → get `xoxb-` bot token
5. Enable Socket Mode → generate `xapp-` app token
6. Paste both into `config.json` under `"slack"`, set `"enabled": true`
7. Reload daemon, DM the bot — `hi` should respond

**Only one Socket Mode connection per app token.** If you run on multiple machines, create separate Slack apps or stop the other instance.

## iMessage Setup (macOS only)

1. Sign in to iMessage on your Mac with the same Apple ID as your iPhone
2. Send a test message to yourself in iMessage first (creates self-chat)
3. System Settings → Privacy & Security → Full Disk Access → add `/opt/homebrew/bin/python3`
4. Start the daemon
5. Text yourself: `new:home: hello, what can you help me with?`

## Commands

All commands work via iMessage (`/cmd`), Slack (`cmd` — no slash), or the dashboard.

### Session
| Command | Description |
|---------|-------------|
| `status` | What's happening now (works while busy) |
| `end` | End session, clear context |
| `cancel` | Kill running task immediately |
| `history` | Last 5 messages |
| `sessions` | List saved sessions |
| `queue <prompt>` | Run after current task |

### Navigation
| Command | Description |
|---------|-------------|
| `switch <dir>` | Switch directory + pick session |
| `dirs` | Show directory aliases |
| `tool` | Show current CLI tool |
| `tool <name>` | Switch tool (claude/wasabi/kiro) |

### Progress (Claude Code)
| Command | Description |
|---------|-------------|
| `eta` | Progress: elapsed, action, todos, ETA |
| `eta interval 5m` | Auto-update interval |
| `eta stuck 2h` | Stuck alert threshold |

### Watch
| Command | Description |
|---------|-------------|
| `watch` | Dashboard: watches + alerts + status |
| `watch <text>` | Create watch (LLM parses) |
| `watch list` | Show all watches |
| `watch stop <N>` | Stop watch |
| `watch stop all` | Stop all |
| `watch pause <N>` | Pause watch |
| `watch resume <N>` | Resume watch |
| `watch mute <time>` | Silence all watches |
| `watch snooze <N>` | Snooze 30min |

Examples:
```
watch all my pipelines
watch new high sev tickets on MyTeam-Resolver
watch pipeline MyBackendService
```

### Schedule
| Command | Description |
|---------|-------------|
| `schedule <text>` | Create recurring task (LLM parses) |
| `schedule list` | Show schedules |
| `schedule cancel <N>` | Cancel |
| `schedule pause <N>` | Pause |
| `schedule resume <N>` | Resume |

Examples:
```
schedule every morning check pipeline status
schedule daily 9am open ticket report
schedule every friday oncall report
```

### Remind
| Command | Description |
|---------|-------------|
| `remind <text>` | Set reminder (LLM parses) |
| `remind 5m msg` | Quick relative time |
| `remind list` | Show reminders |
| `remind cancel <N>` | Cancel |

Examples:
```
remind tomorrow 9am check deploy
remind in 30 minutes call John
remind friday 5pm submit report
```

### Start Session (iMessage/Slack)
```
new:<dir>: <prompt>    Start in directory
new:home: hello        Example
new:centralis: fix bug Example
(just type normally)   Continue session
```

In the web dashboard, click **New session** → pick tool + directory.

## Architecture

```
~/bridge/
├── daemon.py              # Main daemon — channels, routing, command handlers
├── session_manager.py     # Parallel multi-session state
├── event_bus.py           # Pub/sub for live UI updates
├── gateway.py             # FastAPI REST + WebSocket (port 7777)
├── slack_channel.py       # Slack Socket Mode listener
├── watcher.py             # Watch mode — checkers, classification, alerts
├── scheduler.py           # Cron scheduler for schedule command
├── progress_tracker.py    # ETA progress tracking + stuck detection
├── parser.py              # Message prefix parsing
├── chatdb.py              # SQLite reader for chat.db (macOS)
├── sender.py              # iMessage via AppleScript (macOS)
├── echo_filter.py         # Prevents echo loops
├── config.py              # Config and state management
├── mcp_server.py          # MCP server (imessage_reply + imessage_history)
├── adapters/
│   ├── base.py            # Abstract adapter + env capture
│   ├── claude_adapter.py  # Claude Code
│   ├── wasabi_adapter.py  # Wasabi (history injection for memory)
│   └── kiro_adapter.py    # Kiro CLI
├── web/                   # React dashboard
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── Dashboard.tsx      # Stats + activity feed + quick actions
│   │   │   ├── ChatView.tsx       # Session tabs + chat
│   │   │   ├── NewSessionDialog.tsx
│   │   │   ├── CreateDialog.tsx   # Reminder/Schedule/Watch creation
│   │   │   ├── SimpleList.tsx     # Reminders/Schedules/Watches lists
│   │   │   └── ui.tsx             # Button/Card/Badge/Input primitives
│   │   ├── api/
│   │   │   ├── client.ts          # REST wrapper
│   │   │   └── ws.ts              # WebSocket hook
│   │   └── stores/sessionStore.ts # Zustand UI state
│   └── dist/              # Built bundle (served by gateway)
├── config.json            # User configuration
├── state.json             # Runtime state (sessions, reminders, etc.)
└── tests/                 # 256 tests
```

### Key Design Decisions

**Adapter pattern**: Each CLI tool is a separate adapter. Adding a new tool = drop a Python file in `adapters/`.

**Channel abstraction**: iMessage, Slack, and Web all route through the same `_reply()` path via context threading. Same commands work everywhere.

**Parallel-safe SessionManager**: Per-session lock serializes prompts within a session; global semaphore caps concurrent sessions. Subprocess.Popen is thread-safe, so multiple adapters can run in parallel.

**EventBus + WebSocket**: Backend publishes events (`session.busy`, `message.appended`, etc.); frontend subscribes via WebSocket and invalidates affected TanStack Query caches. No polling.

**Wasabi history injection**: Wasabi emits "End workflow. Memory Reset" after each non-interactive call. SessionManager passes `message_history` to the adapter; adapter prepends it to the prompt as plain-text context. Last 9 turns maintained, truncated at 800 chars each.

**Self-chat only (iMessage)**: Only processes messages from your own Apple ID.

**Zero-width space marker**: Outbound iMessage messages include invisible U+200B marker — prevents echo loops.

**Login shell env**: Captures full `zsh -i` environment for subprocesses. Tools like brazil-build, ada, cargo all work.

**Watch alerts on change only**: Never alerts on same state twice. ID-set comparison for tickets, flag comparison for pipelines. 30min cooldown prevents spam.

**Cross-platform**: iMessage skipped on non-macOS. Linux/dev-desktop runs Slack + web dashboard only.

## Dev Desktop Setup (Amazon Linux)

```bash
# 1. Clone
git clone https://github.com/MohakChugh/imessage-claude-bridge.git ~/bridge
cd ~/bridge

# 2. Dependencies
pip3 install slack-bolt slack-sdk fastapi uvicorn

# 3. Ensure wasabi is installed
toolbox install wasabi

# 4. Config — Slack-only mode, skip iMessage
cp config.example.json config.json
# Edit: set directories to /workplace/$USER/..., paste Slack tokens

# 5. Run (foreground or systemd)
python3 daemon.py
```

**Access dashboard via SSH tunnel:**
```bash
ssh -L 7777:localhost:7777 remote-server
open http://localhost:7777
```

## Troubleshooting

### Daemon not starting
```bash
launchctl list | grep imessage-bridge        # macOS
systemctl --user status bridge               # Linux
tail -20 logs/daemon.log
```

### Dashboard not loading
```bash
curl -s http://127.0.0.1:7777/api/health
# Check gateway started:
grep "Gateway started" logs/daemon.log
# Rebuild UI:
cd web && npm run build
```

### Slack not responding
```bash
# Verify Socket Mode connected:
grep "Bolt app is running" logs/daemon.log
# Verify allowed_users matches your Slack member ID
```

### Wasabi doesn't remember earlier messages
Already fixed — history injection is automatic. If still broken:
```bash
# Verify history param is passed:
grep "history" session_manager.py | head -3
```

### "authorization denied" (macOS)
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
python3 -c "
from chatdb import ChatDB; import json
cdb = ChatDB('$HOME/Library/Messages/chat.db')
json.dump({'watermark': cdb.get_max_rowid()}, open('state.json','w'))
"
launchctl load ~/Library/LaunchAgents/com.claude.imessage-bridge.plist
```

### Port 7777 conflict
Change in config.json:
```json
"gateway": { "enabled": true, "port": 8888 }
```

## Tests

```bash
cd ~/bridge && python3 -m pytest tests/ -v
```

256 tests covering daemon commands, message routing, adapters, config, parsing, echo filter, progress tracking, scheduling, watching, and integration.

## Plans & Design Docs

- `docs/plans/2026-04-24-web-dashboard-multi-session.md` — full dashboard + parallel execution plan
- `docs/superpowers/specs/2026-04-19-slack-integration-design.md` — Slack architecture

## License

MIT
