#!/usr/bin/env python3
"""Backfill claude-mem from existing Claude Code session JSONL files.

Reads all session files from ~/.claude/projects/*/sessions/*.jsonl,
extracts sessions, user prompts, and observations (tool calls),
then imports them via the claude-mem worker API at localhost:37777.

Usage:
    python3 backfill_claude_mem.py [--dry-run] [--batch-size 50] [--max-sessions 0]
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from glob import glob
from pathlib import Path

WORKER_URL = "http://localhost:37777"
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

# Tools worth capturing as observations (skip noise like thinking blocks)
INTERESTING_TOOLS = {
    "Read", "Write", "Edit", "Bash", "Grep", "Glob",
    "Agent", "Skill", "WebFetch", "WebSearch",
    "NotebookEdit", "mcp__",  # prefix match for MCP tools
}

# Skip subagent files — they're fragments, not full sessions
SKIP_PATTERNS = ["/subagents/"]


def is_interesting_tool(name: str) -> bool:
    if not name:
        return False
    for t in INTERESTING_TOOLS:
        if name.startswith(t):
            return True
    return False


def extract_text_content(content) -> str:
    """Extract text from message.content which can be str or list of blocks."""
    if isinstance(content, str):
        return content[:2000]
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", "")[:500])
        return "\n".join(parts)[:2000]
    return ""


def extract_tool_uses(content) -> list:
    """Extract tool_use blocks from assistant message content."""
    tools = []
    if not isinstance(content, list):
        return tools
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "")
            if is_interesting_tool(name):
                inp = block.get("input", {})
                # Truncate large inputs
                inp_str = json.dumps(inp) if isinstance(inp, dict) else str(inp)
                if len(inp_str) > 1000:
                    inp_str = inp_str[:1000] + "..."
                tools.append({
                    "id": block.get("id", ""),
                    "name": name,
                    "input": inp_str,
                })
    return tools


def derive_project_name(filepath: str) -> str:
    """Derive project name from file path.
    e.g. /Users/x/.claude/projects/-Users-x/session.jsonl -> -Users-x
    """
    parts = filepath.split("/projects/")
    if len(parts) > 1:
        # Get the directory name after projects/
        remainder = parts[1]
        project_dir = remainder.split("/")[0]
        return project_dir
    return "unknown"


def parse_session(filepath: str) -> dict | None:
    """Parse a single JSONL session file into import-ready data."""
    session_id = None
    cwd = None
    first_prompt = None
    prompts = []
    observations = []
    timestamps = []
    entry_count = 0

    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_count += 1
                entry_type = entry.get("type", "")
                ts = entry.get("timestamp", "")
                sid = entry.get("sessionId", "")
                entry_cwd = entry.get("cwd", "")

                if sid and not session_id:
                    session_id = sid
                if entry_cwd and not cwd:
                    cwd = entry_cwd
                if ts:
                    timestamps.append(ts)

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role", "")
                content = msg.get("content", "")

                # User messages → prompts
                if entry_type == "user" and role == "user":
                    text = extract_text_content(content)
                    if text and len(text) > 5:
                        if not first_prompt:
                            first_prompt = text[:200]
                        prompts.append({
                            "text": text,
                            "timestamp": ts,
                        })

                # Assistant messages → extract tool uses as observations
                elif entry_type == "assistant" and role == "assistant":
                    tools = extract_tool_uses(content)
                    for tool in tools:
                        observations.append({
                            "tool_name": tool["name"],
                            "tool_input": tool["input"],
                            "timestamp": ts,
                        })

    except Exception as e:
        print(f"  Error parsing {filepath}: {e}", file=sys.stderr)
        return None

    if not session_id or entry_count < 3:
        return None

    project = derive_project_name(filepath)
    started_at = timestamps[0] if timestamps else ""
    completed_at = timestamps[-1] if timestamps else ""

    return {
        "session_id": session_id,
        "project": project,
        "cwd": cwd or "",
        "first_prompt": first_prompt or "(no prompt)",
        "started_at": started_at,
        "completed_at": completed_at,
        "prompts": prompts,
        "observations": observations,
        "entry_count": entry_count,
    }


def format_import_batch(sessions: list[dict]) -> dict:
    """Convert parsed sessions into the /api/import format."""
    import_sessions = []
    import_observations = []
    import_prompts = []

    for s in sessions:
        # Parse timestamps to epoch
        started_epoch = ts_to_epoch(s["started_at"])
        completed_epoch = ts_to_epoch(s["completed_at"]) if s["completed_at"] else None

        import_sessions.append({
            "content_session_id": s["session_id"],
            "memory_session_id": f"backfill-{s['session_id']}",
            "project": s["project"],
            "platform_source": "claude",
            "user_prompt": s["first_prompt"],
            "started_at": s["started_at"],
            "started_at_epoch": started_epoch,
            "completed_at": s.get("completed_at"),
            "completed_at_epoch": completed_epoch,
            "status": "completed",
        })

        # Build observations from tool uses
        for i, obs in enumerate(s["observations"][:50]):  # Cap at 50 per session
            obs_epoch = ts_to_epoch(obs["timestamp"]) if obs["timestamp"] else started_epoch
            # Build a narrative from tool name + input
            narrative = f"Used {obs['tool_name']}"
            tool_input = obs.get("tool_input", "")
            if tool_input and len(tool_input) < 200:
                narrative += f": {tool_input}"

            import_observations.append({
                "memory_session_id": f"backfill-{s['session_id']}",
                "project": s["project"],
                "text": narrative[:500],
                "type": "tool_observation",
                "title": obs["tool_name"],
                "subtitle": tool_input[:100] if tool_input else "",
                "narrative": narrative[:1000],
                "created_at": obs["timestamp"] or s["started_at"],
                "created_at_epoch": obs_epoch,
            })

        # Build prompts
        for pi, p in enumerate(s["prompts"][:10]):  # Cap at 10 per session
            p_epoch = ts_to_epoch(p["timestamp"]) if p["timestamp"] else started_epoch
            import_prompts.append({
                "content_session_id": s["session_id"],
                "memory_session_id": f"backfill-{s['session_id']}",
                "project": s["project"],
                "prompt_text": p["text"],
                "prompt_number": pi + 1,
                "created_at": p["timestamp"] or s["started_at"],
                "created_at_epoch": p_epoch,
            })

    return {
        "sessions": import_sessions,
        "observations": import_observations,
        "prompts": import_prompts,
    }


def ts_to_epoch(ts: str) -> int:
    """Convert ISO timestamp to epoch milliseconds."""
    if not ts:
        return int(time.time() * 1000)
    try:
        # Handle "2026-04-18T06:02:20.296Z"
        clean = ts.replace("Z", "+00:00")
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(clean)
        return int(dt.timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def post_import(batch: dict) -> dict:
    """POST batch to /api/import."""
    data = json.dumps(batch).encode("utf-8")
    req = urllib.request.Request(
        f"{WORKER_URL}/api/import",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_worker() -> bool:
    """Check if claude-mem worker is healthy."""
    try:
        req = urllib.request.Request(f"{WORKER_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Backfill claude-mem from Claude Code sessions")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't import")
    parser.add_argument("--batch-size", type=int, default=50, help="Sessions per import batch")
    parser.add_argument("--max-sessions", type=int, default=0, help="Max sessions to process (0=all)")
    args = parser.parse_args()

    # Check worker
    if not args.dry_run and not check_worker():
        print("ERROR: claude-mem worker not running at localhost:37777")
        print("Start it: npx claude-mem start")
        sys.exit(1)

    # Find all session JSONL files
    pattern = os.path.join(PROJECTS_DIR, "**", "*.jsonl")
    all_files = sorted(glob(pattern, recursive=True))

    # Filter out subagent files
    files = [f for f in all_files if not any(skip in f for skip in SKIP_PATTERNS)]
    print(f"Found {len(files)} session files ({len(all_files) - len(files)} subagent files skipped)")

    if args.max_sessions > 0:
        files = files[:args.max_sessions]
        print(f"Processing first {args.max_sessions} sessions")

    # Parse all sessions
    parsed = []
    skipped = 0
    for i, filepath in enumerate(files):
        if (i + 1) % 100 == 0:
            print(f"  Parsing {i + 1}/{len(files)}...")
        result = parse_session(filepath)
        if result:
            parsed.append(result)
        else:
            skipped += 1

    total_obs = sum(len(s["observations"]) for s in parsed)
    total_prompts = sum(len(s["prompts"]) for s in parsed)
    print(f"\nParsed: {len(parsed)} sessions, {total_obs} observations, {total_prompts} prompts ({skipped} skipped)")

    if args.dry_run:
        print("\n[DRY RUN] Would import the above. Run without --dry-run to execute.")
        # Show sample
        if parsed:
            s = parsed[0]
            print(f"\nSample session: {s['session_id'][:20]}...")
            print(f"  Project: {s['project']}")
            print(f"  CWD: {s['cwd']}")
            print(f"  Prompt: {s['first_prompt'][:80]}")
            print(f"  Observations: {len(s['observations'])}")
            print(f"  Entries: {s['entry_count']}")
        return

    # Import in batches
    batch_size = args.batch_size
    total_imported = {"sessions": 0, "observations": 0, "prompts": 0}

    for i in range(0, len(parsed), batch_size):
        batch = parsed[i:i + batch_size]
        import_data = format_import_batch(batch)

        print(f"\nImporting batch {i // batch_size + 1} ({len(batch)} sessions, "
              f"{len(import_data['observations'])} obs, {len(import_data['prompts'])} prompts)...")

        try:
            result = post_import(import_data)
            stats = result.get("stats", {})
            total_imported["sessions"] += stats.get("sessionsImported", 0)
            total_imported["observations"] += stats.get("observationsImported", 0)
            total_imported["prompts"] += stats.get("promptsImported", 0)
            print(f"  Imported: {stats.get('sessionsImported', 0)} sessions, "
                  f"{stats.get('observationsImported', 0)} obs, "
                  f"{stats.get('promptsImported', 0)} prompts "
                  f"(skipped: {stats.get('sessionsSkipped', 0)}s/{stats.get('observationsSkipped', 0)}o)")
        except Exception as e:
            print(f"  ERROR: {e}")

        # Small delay between batches to not overload worker
        if i + batch_size < len(parsed):
            time.sleep(0.5)

    print(f"\n=== BACKFILL COMPLETE ===")
    print(f"Sessions: {total_imported['sessions']}")
    print(f"Observations: {total_imported['observations']}")
    print(f"Prompts: {total_imported['prompts']}")


if __name__ == "__main__":
    main()
