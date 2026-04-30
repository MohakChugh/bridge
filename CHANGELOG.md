# Changelog

All notable changes to Bridge are documented here.

---

## [Unreleased] — 2026-04-30

### Added
- **Reinforcement Memory (self-learning)** — New `reinforcement_memory.py` with separate `reinforcement.db`. Detects user corrections, extracts behavioral lessons via LLM, injects as "BEHAVIORAL GUIDANCE" into future sessions. Completely isolated from knowledge base — never touches `shared-memory.db`.
- **Git-isolated agent execution** — Agent tasks now run in isolated git worktrees (`git worktree add` per task). Each task gets its own branch `agent/{task_id}`, cleaned up on completion. Prevents parallel tasks from interfering.
- **Event-driven triggers (webhooks)** — New `webhook_triggers.py` with `TriggerManager`. Create triggers that match event patterns + data filters → fire sessions, workflows, or notifications. API: GET/POST/DELETE `/api/triggers`, POST `/api/webhooks/event` for external webhook ingestion.
- **Proactive heartbeat loop** — New `_heartbeat_loop()` in daemon. Configurable via `heartbeat` config key. Checks for stuck sessions (>30min), recent watch alerts, failed schedules. Publishes `heartbeat.alerts` event. Optionally spawns diagnostic session on alert. Default interval: 5 minutes.
- **Agent checkpoint resume** — Agent tasks save full checkpoint (messages, turn count, timestamp) before each LLM call. On daemon restart, orphaned tasks with checkpoints auto-resume from last good state instead of failing.
- **Model selector mid-session** — New `POST /api/sessions/{sid}/set-tool` endpoint + `session_manager.set_tool()`. Switch LLM tool (wasabi/kiro/claude) on idle sessions without creating new session. Frontend `api.sessions.setTool()` client method added.
- **Slack full integration** — Added `get_thread_context()` (fetch full thread history), `upload_file()` (share files in threads), `send_blocks()` (Block Kit rich messages) to SlackChannel.
- **Dynamic workspace discovery** — `/api/directories` now scans Brazil workspaces, git repos, and CR workspaces automatically instead of relying on hardcoded config
- **KB context injection in AI Code Review** — AI Review searches shared_memory for top 10 relevant chunks based on package names + file paths, injects as review context
- **KB context injection in Doc Studio** — AI Generate and AI Edit Selection search shared_memory for top 7 relevant chunks with source attribution (collection name + relevance score)
- **Latest revision only for CR comments** — fetch-comments prompt now explicitly requests highest revision number only and skips bot comments (CoverlayWorker, AutoSDE, GoodCopWorker)
- **fetchCommentsStatus persisted** — comment fetch status survives page reload, prevents duplicate fetch sessions

### Fixed
- **P0: Tiptap editor crash corrupting ALL navigation** — `SafeEditorContent` accessed `editor.view.dom` without null guards on unmount; added `?.` guards, `isDestroyed` checks, try/catch in cleanup, onSelectionUpdate, and auto-save timer
- **P0: AI Review showing no comments** — `strip_markdown()` destroyed JSON structure in session outputs; added `preserve_output` meta flag on CR sessions that sets `_parsing_mode=True` in adapter config
- **P1: CR comment fetch returning 0 comments** — `_extract_json()` failed on wasabi's line-wrapped JSON with `│ json` prefix; added 3-tier fallback: direct parse → newline escape → join all lines
- **P1: AI Review JSON parsing failure** — Frontend regex for ```` ```json ``` ```` didn't match wasabi's pipe-prefix format; added cleanup for `│ json` prefix and line-joined JSON fallback
- **P1: Raw JSON dumped as inline comment** — When JSON parse failed, garbled output stored as comment content; fallback now sends to Review Chat instead
- **Chat text rendering** — Removed `text-xs` constraint on assistant messages, wrapped in `chat-markdown text-sm` for proper markdown rendering
- **Comment count badge** — Now shows "No CR comments" (gray) or "X CR comments" (cyan) after fetch completes, not just when comments exist
- **Port changed** — Gateway moved from 7777 to 7776

### Changed
- RAG limits tuned: `RAG_PRIMARY_LIMIT=7`, `RAG_MAX_RESULTS=7`, `RAG_MIN_SCORE=0.15` (was 8/10/0.0)
- Context chunks now include source attribution: `[Source 1: collection-name (relevance: 78%)]`

---

## [1.0.0] — 2026-04-28 (commit `11ee240`)

### Added — Doc Studio
- Tiptap WYSIWYG editor with full markdown round-trip (tiptap-markdown)
- **AI Generate** — LLM-powered content generation with RAG context from knowledge base, typewriter streaming via WebSocket
- **AI Edit Selection** — Select text, provide feedback, AI rewrites only that block preserving surrounding content
- Auto-save with 3-state indicator (Saved / Saving... / Unsaved)
- Image upload via drag-drop and paste
- **Save to Memory** — One-click index document into knowledge base
- Mermaid diagram rendering via ProseMirror Plugin + Decoration.widget
- Document tree sidebar with folders, create/delete/rename
- Keyboard shortcuts: Cmd+S (save), Cmd+/ (AI Generate), Cmd+E (AI Edit Selection)

### Added — Code Review
- CR diff viewer with side-by-side and inline modes
- File tree sidebar with package tabs and +/- line count badges
- **AI Review** — One-click automated code review generating file-level comments with severity and suggestions
- **Review Chat** — Ask questions about CR with full repo context
- Inline commenting — click any diff line to ask AI about it
- Existing CR comment fetching via wasabi ReadInternalWebsites
- Step-by-step loading progress indicator (4 steps with progress bar and timer)
- Comment count badge after fetch completes
- Error state with diagnostic steps and manual command copy
- Syntax highlighting for Java, TypeScript, Python, Kotlin, Go, JSON, YAML, Smithy, and more

### Added — Knowledge Base
- Local vector database (SQLite + all-MiniLM-L6-v2, 384 dimensions)
- Multi-source ingestion: files, wikis, Quip docs, code repos, web pages
- AST-aware code chunking (Python, Java, TypeScript function extraction)
- LLM-powered summarization and auto-tagging per chunk
- Knowledge graph with edges linking related concepts
- 3D interactive graph visualization (ForceGraph3D)
- AI-powered knowledge discovery with workflow generation
- Parallel bulk refresh with controlled concurrency
- Tag-based search filtering across 2000+ tags

### Added — Workflow Engine
- Visual DAG editor with ReactFlow canvas
- 10 node types: Prompt, Branch, Merge, Delay, Approval, Notify, Discover, Ingest, Memory Search, Start/End
- AI workflow generation from natural language
- AI workflow refinement with feedback
- Cron scheduling with natural language parsing
- Human-in-the-loop approval gates
- Retry logic, variable substitution, artifact saving
- Analytics dashboard: success rate, avg duration, failure reasons

### Added — Autonomous Agent
- Task creation with natural language descriptions
- Reasoning loop: think → call tools → observe → repeat
- Tool registry: sessions, memory search, workflows, filesystem (sandboxed)
- Safe and Yellow modes with approval gates
- Pause, resume, cancel mid-execution
- Full audit trail

### Added — Core Platform
- Multi-session AI chat (400 concurrent sessions across Claude/Wasabi/Kiro)
- iMessage and Slack integration
- Watches, Schedules, Reminders with natural language creation
- Calendar view with .ics export
- Dashboard with unified stats
- Operations dashboard with real-time workflow/session monitoring
- Structured logging with SQLite, correlation IDs, real-time streaming
- RAG Chat (Ask Bridge) — global Cmd+K overlay on all pages
- Settings page with tool selection
- Todo list (client-side, persisted)
- 15 sidebar pages, 139 REST endpoints, 40+ WebSocket event types

### Fixed — Doc Studio Bugs
- Doc switch crash — Tiptap `useEditor` incompatible with React `key={}`, replaced with `loadedDocIdRef` tracking
- AI Edit overwriting entire doc — `selectedText` cleared by focus loss when CommandPalette opened, now captured into ref before palette opens
- Paste intercepting text as image — browsers include `image/png` for rich text, now checks text MIME types first
- Doc content empty on switch — `contentInitializedRef` race condition, replaced with `loadedDocIdRef` approach
- Delete doc leaving stale editor — `activeDocId` not cleared on delete

### Fixed — Adapter Bugs
- Kiro adapter `strip_markdown()` in parsing mode — destroyed markdown formatting in doc generation output; added `preserve_markdown` flag (wasabi and claude already had this)

---

## [0.9.0] — 2026-04-20

### Added
- Knowledge ingestion pipeline with AST analysis and parallel refresh
- Knowledge base system with document registry, graph, tags, rich UI
- Shared memory with auto-ingest, workflow nodes, personas
- Local vector DB with named collections and auto-inject into sessions
- Comprehensive integration test suite (74+ tests)

---

## [0.8.0] — 2026-04-15

### Added
- Configurable default tools + settings page + generic LLM parser
- Retry on failure + output artifacts + workflow analytics
- Workflow variables — parameterized execution + multi-schedule
- Past session persistence + resume from history
- Copy to New workflow button

### Fixed
- Bulletproof JSON extraction for cross-tool parsing
- Claude parse returning empty — strip_markdown killed JSON code blocks
- Reminder/schedule parse timeout 30s → 120s

---

## [0.7.0] — 2026-04-10

### Added
- Visual workflow creator — DAG builder + execution engine
- Notify node + run persistence + Operations dashboard
- Workflow scheduling with cron-based auto-execution
- AI-generated workflows from natural language
- Interactive AI feedback loop for workflow refinement

---

## [0.6.0] — 2026-04-05

### Added
- Web dashboard + multi-session backend + parallel execution
- Full CRUD admin UI
- Slack channel + cross-platform support (Linux/macOS)
- Caveman mode on all adapters (~75% token reduction)

---

## [0.5.0] — 2026-03-28

### Added
- Watch mode — pipeline/ticket/URL monitoring with auto-diagnosis
- Comprehensive /help with examples for all 17+ commands
- Watcher system with classifiers and alert formatting

---

## [0.4.0] — 2026-03-20

### Added
- Kiro CLI adapter with custom agent support
- ProgressTracker + StuckDetector
- /eta command with progress tracking
- /schedule (recurring tasks)
- Natural language reminders with LLM parsing + persistence
- Enhanced /switch with session picker

---

## [0.3.0] — 2026-03-12

### Added
- CLI adapter pattern with Wasabi integration
- Background thread execution for non-blocking operation
- /cancel /help /queue /remind /sessions /dirs /switch /history commands
- WhatsApp-style conversational text replies

---

## [0.2.0] — 2026-03-05

### Added
- Persistent sessions with --resume
- Brief plain-text replies, no markdown
- Invisible marker echo-prevention for self-chat

---

## [0.1.0] — 2026-02-28

### Added
- Initial release: core daemon, iMessage polling, Claude Code integration
- MCP server for imessage_reply tool
- LaunchD auto-start with Python 3.14 compatibility
- 41 passing tests
