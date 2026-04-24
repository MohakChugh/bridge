# Web Dashboard + Multi-Session Support — Design Plan

**Date:** 2026-04-24
**Status:** Planning
**Scope:** MeshClaw-style UI + parallel execution + session tabs

---

## Goals

1. **Web dashboard** (MeshClaw-like) — React + shadcn/ui + FastAPI
2. **Chat with tool selection** — button-based tool picker (claude/wasabi/kiro)
3. **Parallel execution** — multiple sessions running concurrently
4. **Session tabs** — switch between active sessions without losing state
5. **At-a-glance overview** — reminders, schedules, watches, active work
6. **Lightweight + performant** — minimal bundle, fast loads

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  React SPA (Vite + shadcn/ui + TailwindCSS)              │
│  localhost:7777 (or SSH tunneled from remote-server)           │
│                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐  │
│  │ Session Tabs │ │ Chat View    │ │ Dashboard       │  │
│  │  (multiple)  │ │  + tool      │ │  (reminders,    │  │
│  │              │ │  selector    │ │  schedules,     │  │
│  │              │ │              │ │  watches)       │  │
│  └──────────────┘ └──────────────┘ └─────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ REST + WebSocket
                        ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI Backend (gateway.py — runs in daemon)           │
│                                                           │
│  REST: /api/sessions, /api/reminders, /api/schedules     │
│  WS:   /ws/sessions/<id>/stream  (live task updates)     │
│  WS:   /ws/dashboard  (global events)                    │
└───────────────────────┬─────────────────────────────────┘
                        │ Python in-process
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Daemon (refactored for multi-session)                   │
│                                                           │
│  SessionManager:                                          │
│    - sessions[sid] = Session(id, tool, cwd, status, ...) │
│    - execute(sid, prompt) — async, parallel-safe         │
│    - Replace self._busy / self._active_process           │
│      with per-session state                              │
│                                                           │
│  EventBus:                                                │
│    - Emit task.started, task.progress, task.complete     │
│    - FastAPI subscribes and pushes to WS clients         │
└─────────────────────────────────────────────────────────┘
```

---

## Phase 1: Daemon Refactor for Multi-Session

**Problem:** Current daemon has single-session state:
- `self._busy = False`
- `self._current_task = None`
- `self._active_process = None`
- `self.active_session_id / active_session_cwd`

**Solution:** Introduce `SessionManager` with per-session state.

### New class: `SessionManager`

```python
@dataclass
class Session:
    id: str                    # UUID
    title: str                 # Human label
    tool: str                  # claude / wasabi / kiro
    cwd: str
    status: str                # idle | busy | completed | failed
    tool_session_id: Optional[str]  # CLI-side session (for resume)
    created_at: float
    updated_at: float
    message_history: list[dict]
    current_task: Optional[str]
    active_process: Optional[subprocess.Popen]
    progress_tracker: Optional[ProgressTracker]
    lock: threading.Lock       # Per-session lock

class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, tool: str, cwd: str, title: str) -> Session: ...
    def get(self, sid: str) -> Optional[Session]: ...
    def list(self) -> list[Session]: ...
    def delete(self, sid: str) -> bool: ...
    def execute(self, sid: str, prompt: str) -> None:
        """Run task in thread, per-session lock, emit events."""
```

### Files to modify

| File | Change |
|------|--------|
| `session_manager.py` | **CREATE** — Session + SessionManager classes |
| `event_bus.py` | **CREATE** — pub/sub for task lifecycle events |
| `daemon.py` | **MODIFY** — replace `_busy`/`_active_process`/`active_session_*` with SessionManager calls. Channels still route via SessionManager |
| `slack_channel.py` | **MODIFY** — map Slack thread_ts → session_id (one session per thread) |
| `chatdb.py` | No change |

### Backward compat

- Single-user iMessage/Slack usage still works — each channel maps to a default session
- State.json schema migrates: `active_session_id` → `sessions: {<id>: {...}}`

### Tests

- `test_session_manager.py` — create, execute, concurrent executions, lock isolation
- Update existing `test_daemon_*.py` to use SessionManager
- Target: +30 tests, total ~290

---

## Phase 2: FastAPI Gateway

**Goal:** HTTP + WebSocket server running inside daemon process.

### New file: `gateway.py`

```python
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
# CORS only for localhost — no auth exposure

@app.get("/api/sessions")
def list_sessions(): ...

@app.post("/api/sessions")
def create_session(body: CreateSession): ...

@app.post("/api/sessions/{sid}/message")
def send_message(sid: str, body: SendMessage): ...

@app.get("/api/reminders")
def list_reminders(): ...

@app.get("/api/schedules")
def list_schedules(): ...

@app.get("/api/watches")
def list_watches(): ...

@app.get("/api/dashboard")
def dashboard_snapshot():
    """At-a-glance: active sessions, pending reminders, running watches."""

@app.websocket("/ws/sessions/{sid}/stream")
async def session_stream(ws: WebSocket, sid: str):
    """Live updates: progress, output, completion."""

@app.websocket("/ws/dashboard")
async def dashboard_stream(ws: WebSocket):
    """Global events — new session, reminder fired, alert, etc."""
```

### REST Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sessions` | List all (active + recent) |
| POST | `/api/sessions` | Create new session (tool, cwd, title) |
| GET | `/api/sessions/{sid}` | Session details + history |
| POST | `/api/sessions/{sid}/message` | Send prompt |
| POST | `/api/sessions/{sid}/cancel` | Kill running task |
| DELETE | `/api/sessions/{sid}` | End + clear |
| GET | `/api/tools` | Available tools (claude/wasabi/kiro) |
| GET | `/api/directories` | Directory aliases |
| GET | `/api/reminders` + POST/DELETE | /remind CRUD |
| GET | `/api/schedules` + POST/DELETE/pause/resume | /schedule CRUD |
| GET | `/api/watches` + POST/DELETE/pause/resume | /watch CRUD |
| GET | `/api/dashboard` | Snapshot for homepage |

### WebSocket Events

Published to `/ws/dashboard`:
- `session.created`, `session.completed`, `session.failed`
- `reminder.fired`, `schedule.fired`, `watch.alert`
- `progress.update` (ETA tracker)

Published to `/ws/sessions/{sid}/stream`:
- `message.appended` (new user/assistant message)
- `progress.tick` (current action, elapsed, ETA)
- `status.change` (idle → busy → completed)

### Security

- Bind to `127.0.0.1` only — no external access
- Local token in `~/.claude/imessage-bridge/state.json` → passed as `Authorization` header
- For remote-server: SSH tunnel `ssh -L 7777:localhost:7777 remote-server`

### Files

| File | Action |
|------|--------|
| `gateway.py` | CREATE |
| `daemon.py` | MODIFY — spawn gateway thread at startup |
| `requirements.txt` | ADD fastapi, uvicorn, websockets |

### Tests

- `test_gateway.py` — REST endpoints, WebSocket connect, event routing
- Target: +20 tests

---

## Phase 3: React Frontend

**Stack:** Vite + React 19 + TypeScript + TailwindCSS 4 + shadcn/ui + TanStack Query + Zustand

### Directory structure

```
~/.claude/imessage-bridge/web/
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── components.json          # shadcn config
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   ├── client.ts        # fetch wrapper
│   │   ├── sessions.ts      # TanStack queries
│   │   └── ws.ts            # WebSocket hook
│   ├── components/
│   │   ├── ui/              # shadcn primitives
│   │   ├── SessionTabs.tsx
│   │   ├── ChatView.tsx
│   │   ├── ToolSelector.tsx
│   │   ├── Dashboard.tsx
│   │   ├── ReminderList.tsx
│   │   ├── ScheduleList.tsx
│   │   ├── WatchList.tsx
│   │   └── ProgressBadge.tsx
│   ├── stores/
│   │   └── sessionStore.ts  # Zustand — local UI state
│   └── lib/
│       └── utils.ts
└── dist/                    # built static assets
```

### Layout

```
┌────────────────────────────────────────────────────────────┐
│  Header: logo · breadcrumb · [+ new session] · user       │
├────────────┬───────────────────────────────────────────────┤
│            │                                                │
│ Sidebar    │  Main view                                     │
│            │                                                │
│ · Chat     │  ┌────────────────────────────────────────┐   │
│ · Tasks    │  │ Session Tabs: [centralis] [home] [+]   │   │
│ · Remind   │  ├────────────────────────────────────────┤   │
│ · Schedule │  │                                         │   │
│ · Watch    │  │  Chat messages                         │   │
│ · Dashboard│  │                                         │   │
│            │  ├────────────────────────────────────────┤   │
│            │  │ Tool: [claude ▼] [wasabi] [kiro]       │   │
│            │  │ Dir:  [centralis ▼]                     │   │
│            │  │ ┌─────────────────────────────────┐    │   │
│            │  │ │ type prompt...              [>] │    │   │
│            │  │ └─────────────────────────────────┘    │   │
│            │  └────────────────────────────────────────┘   │
│            │                                                │
└────────────┴───────────────────────────────────────────────┘
```

### Key components (shadcn)

| Component | Used for |
|-----------|----------|
| `Tabs` | Session tabs |
| `Sheet` | Slide-in for reminder/schedule create |
| `Dialog` | New session modal |
| `Command` | ⌘K palette — switch tool, dir, session |
| `Card` | Dashboard tiles |
| `Badge` | Status (busy/idle/failed) |
| `Avatar` | Tool icon (claude/wasabi/kiro) |
| `Button` + `DropdownMenu` | Tool selector |
| `ScrollArea` | Chat messages |
| `Progress` | Task progress bar |
| `Toast` (sonner) | Notifications |
| `Skeleton` | Loading states |

### State management

- **TanStack Query** — server state (sessions, reminders, etc.) with WebSocket invalidation
- **Zustand** — UI state (active tab, theme, sidebar open/collapsed)
- **WebSocket hook** — auto-reconnect, invalidates affected queries on event

### Dashboard page (at-a-glance)

```
┌──────────────────────────────────────────────────────┐
│  Active Sessions (3)                        [View →] │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐   │
│  │ centralis   │ │ home        │ │ nexus        │   │
│  │ wasabi      │ │ claude      │ │ kiro         │   │
│  │ busy 2m     │ │ idle        │ │ busy 15s     │   │
│  │ Fixing CR.. │ │ --          │ │ Running te.. │   │
│  └─────────────┘ └─────────────┘ └──────────────┘   │
├──────────────────────────────────────────────────────┤
│  Upcoming (4)                                        │
│  · 9:00 AM  Schedule · pipeline status               │
│  · 10:30 AM Schedule · oncall report                 │
│  · 2h       Reminder · call John                     │
│  · Friday   Reminder · submit timesheet              │
├──────────────────────────────────────────────────────┤
│  Watches (2)                                         │
│  · MyTeam-Resolver · tickets (1m) · 0 alerts        │
│  · CentralisBackend · pipelines (5m) · 1 alert ⚠   │
└──────────────────────────────────────────────────────┘
```

### Performance targets

- Bundle < 300KB gzipped (Vite tree-shaking + lazy chat component)
- First paint < 500ms on localhost
- No polling — all updates via WebSocket

### Files

| File | Action |
|------|--------|
| `web/package.json` | CREATE — Vite + React + shadcn deps |
| `web/src/**` | CREATE — React app |
| `gateway.py` | MODIFY — serve `web/dist/` as static |
| `build.sh` | CREATE — `cd web && pnpm build` |

---

## Phase 4: Parallel Execution

**Requires Phase 1** (SessionManager).

### Changes

- Each Session has its own thread pool (1 worker — serial per session)
- Global thread pool (max_parallel_sessions, default 4) — prevents CPU saturation
- `adapter.spawn()` is already thread-safe (uses subprocess.Popen — no shared state)

### Config

```json
{
  "max_parallel_sessions": 4
}
```

### UI behavior

- User clicks "new session" → creates session, switches to its tab
- Each tab shows live status independently
- Can send prompt in session A while session B is running

### Gotchas

- **Claude-mem worker** — single process on port 37777, handles concurrent sessions via SQLite WAL. Already verified.
- **Wasabi** — separate `wasabi` subprocess per session, fine
- **Shared resources** — BEDROCK quota, ADA credentials (refreshed globally)
- **Log file** — single daemon.log, prefix with `[session_id]` for grep-ability

### Tests

- `test_parallel_execution.py` — spawn 3 sessions, verify isolation
- Target: +15 tests

---

## Phase 5: Dev Desktop Support

Since Phase 2 runs FastAPI, dev desktop needs:

1. Install deps: `pip3 install fastapi uvicorn websockets`
2. SSH tunnel: `ssh -L 7777:localhost:7777 remote-server`
3. Open `http://localhost:7777` on laptop
4. Optional: systemd service wraps daemon for 24/7 uptime

### Files

| File | Action |
|------|--------|
| `docs/dev-desktop-setup.md` | CREATE |
| `scripts/install-remote-server.sh` | CREATE — one-shot installer |
| `scripts/slack-bridge.service` | CREATE — systemd unit |

---

## Phase 6: Polish + Features

Post-MVP items:

- **⌘K palette** — `Command` component for power users
- **Dark mode** — Tailwind `dark:` via class + theme toggle
- **Session history** — reopen past sessions from claude-mem database
- **Export chat** — markdown download
- **Notification** — browser Notification API when task completes (while tab inactive)
- **Keyboard shortcuts** — `cmd+t` new tab, `cmd+w` close, `cmd+1..9` switch
- **Interactive buttons** — approve/reject for confirm flows (Slack-style in UI too)

---

## Implementation Checklist

### Phase 1: Multi-Session Backend (est. 6-8h)

- [ ] Create `session_manager.py` with Session + SessionManager
- [ ] Create `event_bus.py` with pub/sub
- [ ] Refactor `daemon.py` to use SessionManager (no direct `_busy` etc.)
- [ ] Update channels (iMessage, Slack) to map to sessions
- [ ] State migration: single `active_session_id` → `sessions: {}`
- [ ] Update all adapters to handle concurrent spawns (verify thread safety)
- [ ] Tests: `test_session_manager.py` (create, execute, concurrent, cancel)
- [ ] Update `test_daemon_*.py` for new structure
- [ ] Verify all 256 existing tests still pass
- [ ] Manual: iMessage + Slack both work with new backend

### Phase 2: Gateway API (est. 4-5h)

- [ ] Create `gateway.py` (FastAPI app)
- [ ] Implement REST: sessions CRUD
- [ ] Implement REST: reminders/schedules/watches CRUD (proxy existing)
- [ ] Implement REST: dashboard snapshot
- [ ] Implement WS: `/ws/sessions/{sid}/stream`
- [ ] Implement WS: `/ws/dashboard`
- [ ] EventBus → WebSocket bridge
- [ ] Auth token (random UUID stored in state.json, required in header)
- [ ] CORS locked to 127.0.0.1
- [ ] Start gateway thread in daemon `__init__`
- [ ] Tests: `test_gateway.py` (all REST endpoints, WS echo)
- [ ] Manual: curl localhost:7777/api/sessions

### Phase 3: React Frontend (est. 12-16h)

- [ ] `pnpm create vite web --template react-ts`
- [ ] Install shadcn: `pnpm dlx shadcn@latest init`
- [ ] Install components: tabs, sheet, dialog, command, card, button, input, badge, avatar, dropdown-menu, scroll-area, progress, skeleton, toast (sonner)
- [ ] Install: TanStack Query, Zustand, React Router
- [ ] Layout: sidebar + main + header
- [ ] Component: `SessionTabs` (tabs = open sessions, + to create)
- [ ] Component: `ChatView` (messages + input + tool selector)
- [ ] Component: `ToolSelector` (buttons: claude/wasabi/kiro)
- [ ] Component: `DirectorySelector` (dropdown)
- [ ] Component: `Dashboard` (cards: active sessions, upcoming, watches)
- [ ] Component: `ReminderList`, `ScheduleList`, `WatchList` with CRUD
- [ ] Component: `ProgressBadge` (animated when busy)
- [ ] WebSocket hook — auto-reconnect, query invalidation
- [ ] Routing: `/`, `/chat/:sid`, `/reminders`, `/schedules`, `/watches`, `/settings`
- [ ] Build: `vite build` → `dist/`
- [ ] Gateway serves `dist/` as static
- [ ] Manual: visit http://localhost:7777, chat works

### Phase 4: Parallel Execution (est. 3-4h)

- [ ] Global semaphore in SessionManager (max_parallel_sessions)
- [ ] Per-session thread (1 worker)
- [ ] UI shows multiple busy badges simultaneously
- [ ] Config: `max_parallel_sessions`
- [ ] Log prefix: `[session_id]` for all per-session logs
- [ ] Tests: `test_parallel_execution.py` (spawn 3, verify order, verify isolation)
- [ ] Manual: create 3 sessions in UI, run prompts in parallel

### Phase 5: Dev Desktop (est. 2-3h)

- [ ] `docs/dev-desktop-setup.md` — step-by-step
- [ ] `scripts/install-remote-server.sh` — idempotent installer
- [ ] `scripts/slack-bridge.service` — systemd unit template
- [ ] Test on actual dev desktop — full Slack + UI flow
- [ ] Document SSH tunnel setup in README

### Phase 6: Polish (est. 4-6h, optional post-MVP)

- [ ] ⌘K palette (shadcn Command)
- [ ] Dark mode toggle
- [ ] Browser notifications on task complete
- [ ] Keyboard shortcuts (cmd+t, cmd+w, cmd+1-9)
- [ ] Interactive confirm buttons (replace y/n text)
- [ ] Export chat to markdown
- [ ] Session history viewer (via claude-mem)

---

## Total Effort Estimate

| Phase | Hours | Tests |
|-------|-------|-------|
| 1: Multi-session backend | 6-8 | +30 |
| 2: Gateway API | 4-5 | +20 |
| 3: React frontend | 12-16 | +10 (E2E) |
| 4: Parallel execution | 3-4 | +15 |
| 5: Dev desktop support | 2-3 | 0 |
| 6: Polish (optional) | 4-6 | +5 |
| **Total (MVP: 1-5)** | **27-36h** | **+75** |
| **Total (full)** | **31-42h** | **+80** |

---

## Risks + Gotchas

| Risk | Mitigation |
|------|-----------|
| Breaking existing iMessage/Slack flows during refactor | Keep current behavior as default path; migrate incrementally; full test coverage before merging |
| Claude-mem hooks fire N times for parallel sessions → race conditions on worker | Already designed for concurrency (SQLite WAL); test with 5+ parallel sessions |
| Wasabi shared-state across sessions (sends restored context) | Already fixed with `--disable-continue` + session isolation per cwd |
| React bundle too large (shadcn has many deps) | Lazy-load routes, code-split, measure bundle on each build |
| FastAPI blocks daemon thread | Run uvicorn in separate thread; SessionManager uses its own threads |
| WebSocket reconnect storms | Exponential backoff + max 10 retry cap |
| Dev desktop doesn't have Node.js for build | Build on laptop, commit `dist/`, deploy built artifacts |
| Port 7777 conflict (MeshClaw uses same) | Make configurable: `gateway.port` in config.json |

---

## Decision Points for User

1. **Port:** 7777 (MeshClaw standard) or different? (if running both)
2. **Build strategy:** pnpm build on each machine, or commit `dist/` to repo?
3. **Auth:** localhost-only OR token-based (for future multi-user)?
4. **Schedule persistence:** what happens to running sessions when daemon restarts?
   Options: (a) kill all, (b) mark orphaned, (c) resume via adapter session_id
5. **Chat input parsing:** `new:<dir>:` prefix still required, or UI handles via buttons?
6. **Notification strategy:** browser-only, or also Slack/iMessage on completion?

---

## File Summary

### New files (~25)

```
session_manager.py
event_bus.py
gateway.py
scripts/install-remote-server.sh
scripts/slack-bridge.service
docs/dev-desktop-setup.md
web/package.json
web/vite.config.ts
web/tailwind.config.ts
web/components.json
web/src/main.tsx
web/src/App.tsx
web/src/api/client.ts
web/src/api/sessions.ts
web/src/api/ws.ts
web/src/components/SessionTabs.tsx
web/src/components/ChatView.tsx
web/src/components/ToolSelector.tsx
web/src/components/Dashboard.tsx
web/src/components/ReminderList.tsx
web/src/components/ScheduleList.tsx
web/src/components/WatchList.tsx
web/src/components/ProgressBadge.tsx
web/src/stores/sessionStore.ts
tests/test_session_manager.py
tests/test_gateway.py
tests/test_parallel_execution.py
```

### Modified files (~10)

```
daemon.py              — SessionManager integration
config.py              — new keys (gateway.port, max_parallel_sessions)
slack_channel.py       — thread_ts → session_id
adapters/*.py          — verify thread safety
tests/test_daemon_*.py — updated for SessionManager
requirements.txt       — fastapi, uvicorn, websockets
README.md              — document UI + dev desktop
config.example.json    — new config keys
```

---

## Ready to Start?

If approved, proceed in order:
1. Phase 1 (backend refactor — safest, all tests pass before moving on)
2. Phase 2 (API — verifiable with curl)
3. Phase 3 (UI — visible progress)
4. Phase 4 (parallel — needs 1 + 2 + 3)
5. Phase 5 (dev desktop — validates cross-platform)
6. Phase 6 (optional polish)
