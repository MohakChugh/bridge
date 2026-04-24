# Claude Code Plugin Research Report
**Date:** 2026-04-19  
**Focus:** Plugins for iMessage Bridge (non-interactive `claude -p` use case)

---

## 1. claude-mem (62.8K stars) ⭐⭐⭐⭐⭐
**GitHub:** https://github.com/thedotmack/claude-mem  
**Stars:** 62,800 (VERIFIED)

### What It Actually Does
Persistent memory system that automatically captures all Claude Code session activity, compresses it using Claude's agent-sdk, and injects relevant context into future sessions. Uses SQLite + Chroma vector DB for hybrid semantic + keyword search. Provides 3-tier progressive disclosure (indexed search → chronological context → full observations) with ~10x token savings.

### Installation
```bash
npx claude-mem install
# OR
/plugin marketplace add thedotmack/claude-mem
```

### Key Features
- 5 lifecycle hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd)
- Worker service on port 37777 with web viewer UI
- Privacy controls via `<private>` tags
- Citation system for referencing past observations
- MCP search tools for 3-layer memory retrieval

### Claude Code CLI Compatibility
✅ YES - Uses official Claude Code plugin hooks

### iMessage Bridge (`claude -p`) Compatibility
⚠️ MAYBE - Requires investigation:
- Worker service on port 37777 must stay running
- Hooks should work with non-interactive sessions
- Web UI is optional (daemon doesn't need it)
- **CONCERN:** Does it require interactive setup? Does the worker auto-start?

### Dependencies
- Node.js 18.0.0+
- Bun (auto-installed)
- SQLite 3 (bundled)
- Chroma DB

### Size/Complexity
Large - full worker service, web UI, vector DB

### Actively Maintained?
✅ YES - 1,751 commits, AGPL-3.0 license, last commit recent

### Star Count Accuracy
✅ VERIFIED: 62.8K stars

### MY RECOMMENDATION
**INVESTIGATE FURTHER** - Extremely powerful for persistent memory across sessions, but needs testing to confirm:
1. Does worker service auto-start in daemon mode?
2. Do hooks fire correctly with `claude -p`?
3. Can it run headless without the web UI?

If it works headless, this is a MUST-HAVE for iMessage bridge use case.

---

## 2. memsearch (1.3K stars) ⭐⭐⭐⭐
**GitHub:** https://github.com/zilliztech/memsearch  
**Stars:** 1,255 (NOT as advertised - no specific star count was given)

### What It Actually Does
Markdown-first memory system that works as a standalone library for any AI agent. Captures conversation summaries to daily markdown files, uses Milvus for semantic search with hybrid BM25 + vector embeddings. Live file watcher auto-indexes changes. Designed for multi-platform use (Claude Code, OpenClaw, OpenCode, Codex CLI).

### Installation
```bash
uv tool install memsearch
# OR
pipx install memsearch
# OR
pip install memsearch
```

Then enable in Claude Code and restart.

### Key Features
- Markdown files as source of truth (Milvus is shadow index)
- 3-layer progressive search (L1 semantic → L2 section expansion → L3 raw transcripts)
- Smart deduplication via SHA-256 hashing
- Multiple embedding providers (ONNX local default, or OpenAI/Google/Ollama)
- Python API + CLI for programmatic use

### Claude Code CLI Compatibility
✅ YES - Native integration via `/memory-recall [query]`

### iMessage Bridge (`claude -p`) Compatibility
✅ YES - Supports programmatic Python API:
```python
await mem.index()
await mem.search()
```
CLI commands work batch-style without interaction.

### Dependencies
- Python ≥3.10
- Milvus (Lite by default)
- ONNX or external embedding provider

### Size/Complexity
Medium - requires Python, Milvus, embedding models

### Actively Maintained?
✅ YES - 319 commits, MIT license, active development

### Star Count Accuracy
⚠️ INACCURATE - User claimed unknown count, actual is 1,255

### MY RECOMMENDATION
**INSTALL** - Excellent fit for iMessage bridge:
- Markdown-first means human-readable memory
- Python API supports non-interactive use
- Multi-platform means memories persist across tools
- Lighter than claude-mem (no worker service)

**CAVEAT:** Requires Python runtime + Milvus. Check if that's acceptable overhead.

---

## 3. arscontexta (3.2K stars) ⭐⭐⭐
**GitHub:** https://github.com/agenticnotetaking/arscontexta  
**Stars:** 3,165 (NOT as advertised - no specific star count was given)

### What It Actually Does
Generates individualized knowledge management systems through conversational setup (not templates). Answer 2-4 domain questions over ~20 min (token-intensive), get a complete markdown vault with wiki-linked knowledge graph, 16 generated processing commands, 4 automation hooks, and multi-level MOCs (Maps of Content).

### Installation
```bash
/plugin marketplace add agenticnotetaking/arscontexta
/plugin install arscontexta@agenticnotetaking
/arscontexta:setup
```

### Key Features
- 8 configuration dimensions deriving personalized architecture
- 249 research-backed methodology claims
- Wiki-linked knowledge graphs
- Quality enforcement hooks
- Semantic search via optional `qmd` tool

### Claude Code CLI Compatibility
✅ YES - Plugin-based system with generated commands

### iMessage Bridge (`claude -p`) Compatibility
❌ NO - Requires:
- Interactive 20-minute conversational setup
- Real-time Q&A for architecture derivation
- No mention of non-interactive or headless mode

This is explicitly conversational-first.

### Dependencies
- Claude Code v1.0.33+
- `tree` command
- `ripgrep` (rg)
- Optional: `qmd` for semantic search

### Size/Complexity
Medium - generates custom systems, but core is lightweight

### Actively Maintained?
✅ YES - v0.8.0, 10 commits, MIT license, multi-agent processing in progress

### Star Count Accuracy
Actual: 3,165

### MY RECOMMENDATION
**SKIP** - Beautiful concept for interactive knowledge building, but fundamentally incompatible with non-interactive `claude -p` use. The entire value prop is the conversational setup phase.

---

## 4. Claude Squad (81 stars) ⭐⭐⭐
**GitHub:** https://github.com/bijutharakan/multi-agent-squad  
**Stars:** 81 (VERIFIED - this is the top result, not a 1000+ star repo)

### What It Actually Does
Production-ready multi-agent orchestration framework that turns Claude Code into an AI dev team. Specialized agents, automated Git workflows (worktrees, commits), enterprise integrations (GitHub, Jira, Slack), and MCP server auto-configuration. Uses natural conversation to set up project structure and instantiate agents.

### Installation
```bash
git clone https://github.com/bijutharakan/multi-agent-squad.git && cd multi-agent-squad
claude
/project
```

"No installation process - Just clone and start"

### Key Features
- Conversational project setup (asks about structure, task tracking)
- Specialized AI agent instantiation
- Automated Git workflows (worktree manager, hooks)
- MCP server setup scripts
- GitHub CLI integration

### Claude Code CLI Compatibility
✅ YES - Primary interface is conversational through Claude Code

### iMessage Bridge (`claude -p`) Compatibility
❌ NO - Requires:
- Interactive conversational setup
- Real-time Q&A about project preferences
- Natural language control throughout
- No batch/non-interactive mode mentioned

### Dependencies
- Git (required)
- Claude Code (required)
- GitHub CLI `gh` (optional)
- Python 3.8+ (optional)
- Service API tokens (optional)

### Size/Complexity
Medium - shell scripts + Python helpers, but requires interactive setup

### Actively Maintained?
⚠️ MAYBE - 14 commits, 81 stars, 41 open issues (suggests active but young project)

### Star Count Accuracy
User implied higher star count, actual: 81

### MY RECOMMENDATION
**SKIP** - Interesting multi-agent system, but requires interactive setup and conversational control. Not compatible with daemon-driven `claude -p` execution.

---

## 5. Claude Swarm - RuFlo (32.4K stars) ⭐⭐⭐⭐
**GitHub:** https://github.com/ruvnet/ruflo  
**Stars:** 32,375 (VERIFIED)

### What It Actually Does
Enterprise-grade agent orchestration platform for deploying intelligent multi-agent swarms and autonomous workflows. Distributed swarm intelligence, RAG integration, native Claude Code/Codex integration, visual board views, and handoff workflows. Designed for large-scale agent coordination.

### Installation
Multiple methods:
- One-line install script (recommended)
- npm/npx install
- Install profiles for customization

### Key Features
- MCP (Model Context Protocol) integration
- Dual-mode CLI (Claude Code + Codex)
- Pre-built collaboration templates
- Visual board views
- Handoff workflows between agents
- Enterprise-grade architecture

### Claude Code CLI Compatibility
✅ YES - Native MCP integration + dual-mode CLI

### iMessage Bridge (`claude -p`) Compatibility
⚠️ UNKNOWN - Documentation mentions:
- "Dual-Mode CLI Commands" (but no explicit `-p` flag support)
- Interactive features emphasized (visual boards, handoffs)
- No explicit non-interactive or batch mode documentation

Likely **interactive-first** design.

### Dependencies
- Node.js ecosystem (primary)
- TypeScript (64.8% of codebase)
- JavaScript (22.2%)
- Python (8.3%)

### Size/Complexity
VERY LARGE - 6,067 commits, 1,470 releases, enterprise-scale project

### Actively Maintained?
✅ YES - Extremely active:
- v3.5.80 (April 11, 2026)
- 399 open issues, 70 PRs
- Comprehensive versioned documentation

### Star Count Accuracy
✅ VERIFIED: 32,375 stars

### MY RECOMMENDATION
**SKIP** - While powerful, this is an enterprise-scale orchestration platform designed for interactive workflows and visual management. Overkill for iMessage bridge use case, and likely doesn't support headless `claude -p` execution well.

Too heavyweight for daemon use.

---

## 6. Auto-Claude (ARIS) (7K stars) ⭐⭐⭐⭐⭐
**GitHub:** https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep  
**Stars:** 7,004 (VERIFIED)

### What It Actually Does
Lightweight markdown-only skills for autonomous ML research workflows. Orchestrates cross-model collaboration where Claude Code executes research while external LLMs (via MCP) provide critical review. Four core workflows: idea discovery → experiments → auto-review → paper writing → rebuttal. Zero dependencies, no framework lock-in.

### Installation
```bash
git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git
mkdir -p ~/.claude/skills/
cp -r Auto-claude-code-research-in-sleep/skills/* ~/.claude/skills/
```

Updates: `bash tools/smart_update.sh --apply`

### Key Features
- Plain markdown skills (no framework)
- Multi-model support (Claude Code, Codex, Cursor, Trae, Antigravity, any LLM)
- Research Wiki (persistent knowledge base)
- Cross-model review (adversarial pairing prevents blind spots)
- Direct skill invocation via CLI

### Claude Code CLI Compatibility
✅ YES - Skills system with direct invocation

### iMessage Bridge (`claude -p`) Compatibility
✅ YES - Non-interactive skill invocation works:
```bash
/idea-discovery "research direction"
/experiment-bridge
/auto-review-loop "paper topic"
/research-pipeline "full direction"  # End-to-end
```

Skills run autonomously without interaction required.

### Dependencies
- Claude Code (latest with skill support)
- Codex MCP: `npm install -g @openai/codex && codex setup`
- Optional: Zotero, Obsidian, Overleaf Premium

### Size/Complexity
LIGHTWEIGHT - Just markdown files copied to ~/.claude/skills/

### Actively Maintained?
✅ YES - Very active:
- v0.4.3 (April 17, 2026)
- Last update April 19, 2026 (2 days ago!)
- 62+ synchronized skills
- Regular community contributions

### Star Count Accuracy
✅ VERIFIED: 7,004 stars

### MY RECOMMENDATION
**INSTALL** (if research/ML use case relevant) - Excellent design principles:
- Zero framework lock-in (just markdown)
- Works non-interactively via skill invocation
- Lightweight (copy files, done)
- Actively maintained
- Multi-model support

**CAVEAT:** Designed for ML research workflows specifically. If your iMessage bridge is NOT for research tasks, the skills won't be relevant. But the ARCHITECTURE (markdown skills, cross-model review, autonomous execution) is a great reference.

---

## 7. claude-octopus (2.7K stars) ⭐⭐⭐⭐
**GitHub:** https://github.com/nyldn/claude-octopus  
**Stars:** 2,741 (VERIFIED)

### What It Actually Does
Coordinates up to 8 AI providers (Codex, Gemini, Copilot, Qwen, Ollama, Perplexity, OpenRouter, OpenCode) to catch blind spots through multi-model consensus and adversarial review. Four-phase workflow (Discover → Define → Develop → Deliver), 32 specialist personas, and 8 key commands. Consensus gates require 75% agreement to ship.

### Installation
```bash
claude plugin marketplace add https://github.com/nyldn/claude-octopus.git
claude plugin install octo@nyldn-plugins
# Then inside Claude Code:
/octo:setup
```

### Key Features
- Multi-model orchestration (parallel, sequential, adversarial modes)
- 32 auto-activating specialist personas
- Consensus gates (75% threshold)
- Reaction engine (auto-responds to CI failures, stuck agents)
- 8 commands: embrace, factory, debate, research, security, tdd, review, auto

### Claude Code CLI Compatibility
✅ YES - Plugin system with slash commands

### iMessage Bridge (`claude -p`) Compatibility
❌ NO - Explicitly stated:
- "Interactive-first, designed for Claude Code sessions"
- "Standard Claude CLI usage (`claude -p`) is unsupported"
- "Requires full Claude Code environment for slash commands and MCP tool integration"

There's a `bin/octopus` CLI for basic scripting, but primary workflows require interactive Claude Code.

### Dependencies
Multiple AI providers (authentication required):
- Claude (built-in)
- Codex, Gemini, Qwen, Copilot, Ollama, Perplexity, OpenRouter (optional)

Zero external providers needed to start (Claude built-in).

### Size/Complexity
LARGE - 951 commits, 146 tests, complex multi-model orchestration

### Actively Maintained?
✅ YES - Very active:
- v9.23.0
- Recent token compression features
- Requires Claude Code v2.1.83+
- MIT license

### Star Count Accuracy
✅ VERIFIED: 2,741 stars

### MY RECOMMENDATION
**SKIP** - Despite being powerful for interactive multi-model consensus, it explicitly does NOT support `claude -p` non-interactive mode. Designed for real-time orchestration in full Claude Code sessions.

Not compatible with iMessage bridge daemon use case.

---

## Summary Matrix

| Plugin | Stars | Non-Interactive? | iMessage Bridge Fit | Recommendation |
|--------|-------|------------------|---------------------|----------------|
| **claude-mem** | 62.8K | ⚠️ Maybe | ⚠️ Needs testing | **INVESTIGATE** |
| **memsearch** | 1.3K | ✅ Yes | ✅ Good fit | **INSTALL** |
| **arscontexta** | 3.2K | ❌ No | ❌ Interactive-only | **SKIP** |
| **Claude Squad** | 81 | ❌ No | ❌ Interactive-only | **SKIP** |
| **RuFlo (Swarm)** | 32.4K | ⚠️ Unknown | ⚠️ Likely interactive | **SKIP** |
| **ARIS (Auto-Claude)** | 7.0K | ✅ Yes | ✅ Good (if research use) | **INSTALL*** |
| **claude-octopus** | 2.7K | ❌ No | ❌ Explicitly unsupported | **SKIP** |

\* ARIS only if ML research workflows are relevant

---

## Final Recommendations for iMessage Bridge

### MUST INVESTIGATE
1. **claude-mem (62.8K stars)** - Persistent memory is crucial for context across iMessage sessions. Need to test if worker service runs headless and hooks fire with `claude -p`.

### INSTALL NOW
2. **memsearch (1.3K stars)** - Markdown-first memory, Python API, works non-interactively. Perfect fit for daemon use case.

### CONDITIONAL INSTALL
3. **ARIS / Auto-Claude (7K stars)** - Only if your iMessage bridge handles ML research tasks. Otherwise skip.

### SKIP ALL OTHERS
- arscontexta, Claude Squad, RuFlo, claude-octopus - All require interactive setup or explicitly don't support `claude -p`.

---

## Testing Plan for claude-mem

If proceeding with investigation:

1. Install: `npx claude-mem install`
2. Check if worker service auto-starts: `ps aux | grep claude-mem`
3. Test with `claude -p "test prompt"` - do hooks fire?
4. Check memory capture: `sqlite3 ~/.claude/claude-mem/data.db "SELECT * FROM observations LIMIT 5"`
5. Test memory retrieval with next `claude -p` call
6. Verify web UI is optional (disable port 37777 and test)

If hooks work + worker runs headless + no interactive setup required = **MUST HAVE**

---

## Key Insight: Most "Multi-Agent" Plugins Are Interactive-First

The research reveals that most highly-starred multi-agent orchestration plugins (Claude Squad, RuFlo, claude-octopus) are designed for **interactive Claude Code sessions** with:
- Real-time conversational setup
- Visual UIs and dashboards  
- Slash command interfaces
- Multi-model coordination requiring live orchestration

These are fundamentally incompatible with daemon-driven `claude -p` execution from iMessage.

The exceptions (memsearch, ARIS) succeed because they use:
- **File-based state** (markdown, SQLite)
- **CLI/API interfaces** (not just slash commands)
- **Background workers** or **batch processing** modes
- **Zero required interaction** after initial setup

For iMessage bridge use case, prioritize plugins with these architectural patterns.

---

**End of Report**
