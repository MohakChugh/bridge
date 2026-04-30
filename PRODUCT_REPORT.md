# Bridge — Product & Architecture Report

## Executive Summary

Bridge is a **personal AI engineering copilot** that turns iMessage into a command interface for Claude, Wasabi, and Kiro — then wraps it in a full web IDE at `localhost:7777` with 15 pages, 139 API endpoints, 40+ real-time WebSocket events, and a local vector knowledge base. It's the single pane of glass for an Amazon SDE's daily workflow: sessions, code reviews, document writing, workflow automation, knowledge management, and autonomous agent tasks.

---

## 1. Platform Inventory

| Metric | Count |
|--------|-------|
| Frontend pages | 18 (15 sidebar + 3 hidden) |
| REST endpoints | 139 |
| WebSocket event types | 40+ |
| Zustand stores | 9 |
| Backend modules | 20+ |
| LLM adapters | 3 (Claude, Wasabi, Kiro) |
| Background daemon threads | 9 |
| Keyboard shortcuts | 16 |

---

## 2. Feature Capabilities

### 2.1 Multi-Session AI Chat
- Run unlimited parallel Claude/Wasabi/Kiro sessions from browser or phone
- Each session maintains full conversation history with tool context
- Sessions auto-ingest their outputs into the knowledge base
- Archive, resume, delete sessions
- Queue messages when session is busy — no dropped requests

**Why top-notch:** No other tool lets you run 400 concurrent LLM sessions across 3 different AI backends from a single interface, with automatic knowledge capture.

### 2.2 AI Code Review
- Paste any CR ID → auto-pulls workspace, extracts git diff, renders side-by-side or inline
- One-click AI Review: parallel analysis sessions generate file-level comments with severity
- Review Chat: ask questions about the CR with full repo context
- Inline commenting: click any diff line to ask AI about it
- Existing CR comments fetched and displayed at correct file/line positions
- Multi-package CR support (separate tabs per package)

**Why top-notch:** Combines diff viewer + AI reviewer + interactive Q&A in one screen. The AI doesn't just summarize — it finds regex edge cases, ordering bugs, and missing error handling that humans miss.

### 2.3 Document Studio (Doc Writer)
- Tiptap WYSIWYG editor with full markdown round-trip
- AI Generate: describe what you want → LLM writes it with RAG context from your knowledge base
- AI Edit Selection: select text → provide feedback → AI rewrites only that block
- Mermaid diagram rendering inline
- Image drag-drop and paste
- Auto-save with 3-state indicator
- Save to Memory: one-click index into knowledge base for future RAG
- Folder tree organization

**Why top-notch:** The selection-aware editing is rare — most AI doc tools replace everything. The RAG integration means generated content references YOUR actual systems, not generic training data.

### 2.4 Knowledge Base & Memory
- Local vector database (SQLite + all-MiniLM-L6-v2 embeddings, 384 dims)
- Multi-source ingestion: files, wikis, Quip docs, code repos, web pages
- AST-aware code chunking (Python, Java, TypeScript function extraction)
- LLM-powered summarization and auto-tagging per chunk
- Knowledge graph with edges linking related concepts
- 3D interactive graph visualization
- AI-powered knowledge discovery: describe a topic → AI finds and ingests relevant docs
- Parallel bulk refresh with controlled concurrency
- Tag-based search filtering

**Why top-notch:** This is a personal knowledge graph that grows automatically. Every session output, every document, every CR gets ingested. Over time, Bridge knows your entire service landscape.

### 2.5 Workflow Automation Engine
- Visual DAG editor with drag-and-drop nodes (ReactFlow)
- 10 node types: Prompt, Branch (conditional + parallel), Merge, Delay, Approval, Notify, Discover, Ingest, Memory Search, Start/End
- AI workflow generation: describe what you want → LLM builds the DAG
- AI workflow refinement: give feedback → LLM modifies specific nodes
- Cron scheduling with natural language parsing
- Human-in-the-loop approval gates
- Retry logic with configurable attempts and delays
- Variable substitution (date, env, previous outputs)
- Artifact saving per run
- Analytics dashboard: success rate, avg duration, failure reasons, parameter distribution

**Why top-notch:** This turns any repeatable SDE task into an automated pipeline. Weekly oncall reports, pipeline diagnosis, bulk code analysis — all become scheduled workflows with approval gates.

### 2.6 Autonomous Agent
- Create tasks with natural language descriptions
- Agent runs in a reasoning loop: think → call tools → observe → repeat
- Tool registry: sessions, memory search, workflows, filesystem (sandboxed)
- Two modes: Safe (requires approval for dangerous ops) and Yellow (auto-approve most)
- Pause, resume, cancel mid-execution
- Full audit trail of every thought and tool call
- Max 3 concurrent tasks, configurable cost/time limits

**Why top-notch:** This is a personal SDE agent that can investigate issues, run commands, search knowledge, and build workflows — all while you watch and approve.

### 2.7 iMessage & Slack Integration
- Poll macOS chat.db for incoming messages
- Route commands: new sessions, continue conversations, reminders, watches, schedules
- Natural language parsing for all commands
- Echo-prevention (doesn't process its own messages)
- Slack Socket Mode as alternative channel

**Why top-notch:** Control your AI copilot from your phone. Stuck in a meeting? Text "check the pipeline for CentralisBackendService" and get a diagnosis without opening a laptop.

### 2.8 Operational Monitoring
- Watches: monitor pipelines, tickets, custom URLs at configurable intervals
- Schedules: cron-based recurring prompts with natural language creation
- Reminders: one-time future tasks with natural language time parsing
- Calendar view: month view of all scheduled events with .ics export
- Dashboard: unified stats across all subsystems
- Operations: real-time view of running workflows, busy sessions, active watches

### 2.9 Structured Logging
- SQLite-backed log storage with correlation IDs
- Three views: Logs, HTTP Requests, Event Bus events
- Filter by level, logger, source, time range, search query
- Frontend error capture (React error boundary → backend)
- Real-time log streaming via WebSocket

### 2.10 RAG Chat (Ask Bridge)
- Global overlay accessible from any page (Cmd+K)
- Searches knowledge base for context before answering
- Shows source badges with collection name and similarity score
- Suggests follow-up actions (navigate to pages, create sessions, refresh docs)
- Persistent across sessions

---

## 3. Cross-Feature Integration Map

These integrations are what make Bridge more than the sum of its parts:

| From | To | Integration |
|------|-----|-------------|
| **Doc Studio** | **Knowledge Base** | "Save to Memory" indexes document into vector DB for future RAG |
| **Knowledge Base** | **Workflows** | Refresh and discovery operations generate and execute workflow DAGs |
| **Workflows** | **Sessions** | Prompt nodes execute through session manager (LLM calls) |
| **Code Review** | **Sessions** | Every AI analysis, comment, and chat creates a tracked session |
| **Agent Brain** | **Sessions + Memory + Workflows** | Agent can create sessions, search memory, run workflows as tools |
| **Sessions** | **Knowledge Base** | Auto-ingest: completed session outputs stored in "sessions" collection |
| **RAG Chat** | **Knowledge Base** | Every question searches shared memory for context |
| **Watches** | **Sessions** | State change detected → diagnostic session auto-spawned |
| **Schedules** | **Workflows** | Cron triggers can run workflows (not just prompts) |
| **Calendar** | **Schedules** | Calendar events derived from all schedule types |
| **Agent Ingestor** | **All outputs** | Background worker auto-ingests session/workflow/task outputs |
| **Logs** | **All requests** | Every HTTP request logged with correlation ID, duration, body |
| **AI Generate** | **Knowledge Base** | Document generation uses RAG context from shared memory |
| **AI Edit Selection** | **Knowledge Base** | Selection editing retrieves relevant context for better rewrites |

---

## 4. User Journeys

### Journey 1: Morning Oncall Check (5 min)
1. Open Dashboard → see active sessions, upcoming schedules
2. Check Operations → view running workflows, watch alerts
3. If alert fired → click through to session with diagnosis
4. Ask Bridge (Cmd+K): "What happened with the pipeline overnight?"
5. RAG returns context from auto-ingested watch outputs

### Journey 2: Code Review (10-15 min)
1. Navigate to Code Review → enter CR-XXXXXXX
2. Loading progress shows 4 steps completing
3. File tree appears → click through files
4. Toggle Inline view for long Java files
5. Click "AI Review" → auto-review generates comments
6. Ask in Review Chat: "Is the DDB GSI projection correct for this query?"
7. Click "+" on a diff line → ask about specific change
8. All interactions tracked as sessions, auto-ingested

### Journey 3: Write Design Document (20 min)
1. Navigate to Docs → create "M3 Architecture"
2. Click AI Generate → "Write an overview of our event-driven investigation system"
3. AI writes content using RAG context from knowledge base (your actual services)
4. Select a paragraph → AI Edit Selection → "Add more detail about retry behavior"
5. Add mermaid diagram describing the flow
6. Click "Save to Memory" → indexed for future RAG queries

### Journey 4: Build Automation Workflow (15 min)
1. Navigate to Workflows → "Generate with AI"
2. Prompt: "Every Tuesday, check all my pipelines, diagnose any failures, and send me a summary"
3. AI builds DAG: Prompt → Branch (pass/fail) → Diagnose → Notify
4. Edit nodes, add approval gate before remediation
5. Schedule: "Every Tuesday at 11am IST"
6. View analytics after a few runs: success rate, avg duration

### Journey 5: Knowledge Base Building (ongoing)
1. Navigate to Memory → Documents → "Add Document"
2. Register team wiki, design docs, runbooks by URL
3. "Discover" tab: enter "Centralis Investigation Service" → AI finds related docs
4. Auto-ingest discovered documents
5. 3D Graph tab: visualize knowledge clusters
6. Every session output, every CR review, every doc automatically enriches the KB

### Journey 6: Phone-Based Control (anytime)
1. Text from phone: "new: check if the gamma deployment rolled back"
2. Bridge spawns a session, runs the check, replies with diagnosis
3. Text: "watch the pipeline every 30 minutes"
4. Bridge creates a watch, monitors, alerts on state change
5. Text: "remind me to merge the CR tomorrow at 10am"
6. Reminder fires at scheduled time

### Journey 7: Deep Investigation (30+ min)
1. Navigate to Agent → "New Task"
2. Describe: "Investigate why STS AssumeRole fails in the Nexus beta account. Check IAM policies, trust relationships, and CDK code."
3. Agent reasons through the problem, calls tools (search memory, create sessions, read files)
4. Watch the thought process in real-time
5. Approve/reject sensitive operations
6. Result: comprehensive investigation report with evidence

---

## 5. Architecture Highlights

### Event-Driven Real-Time Updates
Every action publishes to the event bus → WebSocket → instant UI update. No polling lag. 40+ event types cover sessions, workflows, agents, docs, knowledge, logs.

### Multi-Adapter LLM Routing
Three LLM backends (Claude Code, Wasabi/Bedrock, Kiro) with unified interface. Parsing operations route through `_parsing_mode` flag to preserve markdown. Each adapter handles its tool's quirks (JSON logs, ANSI codes, session management).

### Progressive Knowledge Accumulation
The `ContinuousIngestor` subscribes to all completion events. Every session output, workflow result, and agent task gets chunked, embedded, and stored. The knowledge base grows passively — after a month of use, Bridge knows your entire operational landscape.

### Hybrid Persistence
- Hot state: in-memory (Python dicts + Zustand stores)
- Warm state: JSON files (sessions, workflows, config)
- Cold state: SQLite (vector DB, logs, agent tasks)
- Frontend: localStorage (Zustand persist) survives browser refresh

---

## 6. What Makes This Different

| Capability | Generic AI Tools | Bridge |
|-----------|-----------------|--------|
| Context | None or manual | Auto-accumulating RAG from all interactions |
| Code Review | Copy-paste diff | Pull CR, render diff, AI review with repo context |
| Documents | Generic writing | RAG-aware generation referencing YOUR services |
| Automation | None | Visual DAG workflows with scheduling |
| Monitoring | Separate tools | Watches + schedules + reminders unified |
| Agent | Chat only | Autonomous reasoning loop with tool use + approval |
| Input | Browser only | iMessage + Slack + Web UI |
| Persistence | Session-only | Everything persists and cross-references |

---

## 7. Technical Stats

- **Total lines of Python backend**: ~15,000+
- **Total lines of TypeScript frontend**: ~12,000+
- **SQLite tables**: 8 (collections, memories, documents, edges, tags, memory_tags, agent_tasks, agent_audit)
- **Background threads**: 9 persistent daemon threads
- **Max concurrent sessions**: 400 (configurable)
- **Max concurrent agent tasks**: 3
- **Embedding model**: all-MiniLM-L6-v2 (384 dimensions)
- **Vector search**: Cosine similarity on SQLite (no external DB needed)
