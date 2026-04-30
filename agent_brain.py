"""Agent Brain — autonomous reasoning loop with tool_use.

Manages tasks: decomposition, execution, approval flow, persistence.
Uses Anthropic tool_use protocol via wasabi/kiro/claude adapters.
"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Optional

from event_bus import get_event_bus

log = logging.getLogger("agent_brain")

_brain: Optional["AgentBrain"] = None
_brain_lock = threading.Lock()


def get_agent_brain() -> "AgentBrain":
    global _brain
    if _brain is None:
        raise RuntimeError("AgentBrain not initialized. Call init_agent_brain() first.")
    return _brain


def init_agent_brain(session_manager, config_provider, daemon_ref) -> "AgentBrain":
    global _brain
    with _brain_lock:
        if _brain is None:
            _brain = AgentBrain(session_manager, config_provider, daemon_ref)
    return _brain


class AgentBrain:
    def __init__(self, session_manager, config_provider, daemon_ref):
        self._sm = session_manager
        self._config = config_provider  # callable returning config dict
        self._daemon = daemon_ref
        self._bus = get_event_bus()

        from agent_store import get_agent_store
        self._store = get_agent_store()

        from agent_tools import build_tool_registry
        self._registry = build_tool_registry(session_manager, daemon_ref, config_provider, self._store)

        self._active_threads: dict[str, threading.Thread] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._pause_flags: dict[str, bool] = {}
        self._approval_events: dict[str, threading.Event] = {}
        self._approval_results: dict[str, bool] = {}  # True=approved, False=rejected
        self._mode = "safe"  # global default

        self._max_concurrent = 3
        self._running = True

        # Load config overrides
        agent_cfg = (config_provider() if callable(config_provider) else config_provider).get("agent", {})
        self._mode = agent_cfg.get("default_mode", "safe")
        self._max_concurrent = agent_cfg.get("max_concurrent_tasks", 3)

        # Cleanup orphaned tasks from previous runs
        self._cleanup_orphaned_tasks()

    def _cleanup_orphaned_tasks(self):
        for status in ("running", "waiting_approval", "paused", "pending"):
            orphans = self._store.list_tasks(status=status)
            for task in orphans:
                if task["id"] not in self._active_threads:
                    checkpoint = task.get("metadata", {}).get("checkpoint_turn", 0)
                    if checkpoint > 0 and task.get("messages"):
                        log.info("Resuming orphaned task %s from checkpoint turn %d", task["id"], checkpoint)
                        self._resume_from_checkpoint(task)
                    else:
                        task["status"] = "failed"
                        task["error"] = "Interrupted by daemon restart"
                        task["completed_at"] = time.time()
                        task["updated_at"] = time.time()
                        self._store.save_task(task)
                        log.info("Cleaned up orphaned task %s: %s", task["id"], task["title"])

    def _resume_from_checkpoint(self, task: dict):
        """Resume a task from its last checkpoint."""
        task_id = task["id"]
        task["status"] = "pending"
        task["error"] = None
        task["metadata"]["resumed_from_turn"] = task.get("metadata", {}).get("checkpoint_turn", 0)
        task["updated_at"] = time.time()
        self._store.save_task(task)

        self._cancel_flags[task_id] = False
        self._pause_flags[task_id] = False

        thread = threading.Thread(target=self._run_task_loop, args=(task_id,), daemon=True, name=f"agent-resume-{task_id}")
        self._active_threads[task_id] = thread
        thread.start()
        self._bus.publish("agent.task.resumed", {"task_id": task_id, "from_turn": task["metadata"]["resumed_from_turn"]})

    # ---- Git Worktree Isolation ----

    def _create_worktree(self, task_id: str, config: dict) -> Optional[str]:
        """Create a git worktree for isolated task execution.
        Returns worktree path or None if not in a git repo."""
        import subprocess
        bridge_dir = os.path.dirname(os.path.abspath(__file__))
        worktree_base = os.path.join(bridge_dir, ".agent-worktrees")
        worktree_path = os.path.join(worktree_base, f"task-{task_id}")

        # Find a suitable git repo to branch from
        default_dir = config.get("directories", {}).get("default", "/tmp")
        git_dir = self._find_git_root(default_dir) or self._find_git_root(bridge_dir)
        if not git_dir:
            log.debug("No git repo found for worktree, using default cwd")
            return None

        try:
            os.makedirs(worktree_base, exist_ok=True)
            branch_name = f"agent/{task_id}"
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, worktree_path, "HEAD"],
                cwd=git_dir, capture_output=True, text=True, timeout=30,
            )
            if os.path.isdir(worktree_path):
                log.info("Created worktree at %s for task %s", worktree_path, task_id)
                return worktree_path
        except Exception as e:
            log.warning("Worktree creation failed for task %s: %s", task_id, e)
        return None

    def _cleanup_worktree(self, worktree_path: str, task_id: str) -> None:
        """Remove a git worktree after task completes."""
        import subprocess, shutil
        try:
            parent_git = self._find_git_root(os.path.dirname(worktree_path.rstrip("/")))
            if parent_git:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", worktree_path],
                    cwd=parent_git, capture_output=True, text=True, timeout=15,
                )
            if os.path.isdir(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)
            branch_name = f"agent/{task_id}"
            if parent_git:
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    cwd=parent_git, capture_output=True, text=True, timeout=10,
                )
            log.info("Cleaned up worktree for task %s", task_id)
        except Exception as e:
            log.warning("Worktree cleanup failed for task %s: %s", task_id, e)

    @staticmethod
    def _find_git_root(path: str) -> Optional[str]:
        """Walk up to find .git directory."""
        current = os.path.abspath(path)
        for _ in range(10):
            if os.path.isdir(os.path.join(current, ".git")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return None

    # ---- Public API ----

    def create_task(self, title: str, description: str, mode: Optional[str] = None) -> dict:
        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "status": "pending",
            "mode": mode or self._mode,
            "messages": [],
            "turns": 0,
            "cost": 0.0,
            "result": None,
            "error": None,
            "progress_pct": 0,
            "progress_msg": "",
            "parent_id": None,
            "created_at": time.time(),
            "updated_at": time.time(),
            "completed_at": None,
            "metadata": {},
        }
        self._store.save_task(task)
        self._bus.publish("agent.task.created", {"task_id": task_id, "title": title, "mode": task["mode"]})

        self._cancel_flags[task_id] = False
        self._pause_flags[task_id] = False

        thread = threading.Thread(target=self._run_task_loop, args=(task_id,), daemon=True, name=f"agent-{task_id}")
        self._active_threads[task_id] = thread
        thread.start()

        return task

    def get_task(self, task_id: str) -> Optional[dict]:
        task = self._store.get_task(task_id)
        if task:
            task["audit"] = self._store.list_audit(task_id=task_id, limit=20)
        return task

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> list:
        return self._store.list_tasks(status=status, limit=limit)

    def approve(self, task_id: str) -> bool:
        evt = self._approval_events.get(task_id)
        if not evt:
            return False
        self._approval_results[task_id] = True
        evt.set()
        self._bus.publish("agent.approval.granted", {"task_id": task_id})
        return True

    def reject(self, task_id: str) -> bool:
        evt = self._approval_events.get(task_id)
        if not evt:
            return False
        self._approval_results[task_id] = False
        evt.set()
        self._bus.publish("agent.approval.rejected", {"task_id": task_id})
        return True

    def cancel(self, task_id: str) -> bool:
        self._cancel_flags[task_id] = True
        # Unblock if waiting for approval
        evt = self._approval_events.get(task_id)
        if evt:
            self._approval_results[task_id] = False
            evt.set()
        # Immediately mark as cancelled in DB so UI reflects it
        task = self._store.get_task(task_id)
        if task and task["status"] not in ("completed", "failed", "cancelled"):
            task["status"] = "cancelled"
            task["completed_at"] = time.time()
            task["updated_at"] = time.time()
            self._store.save_task(task)
            self._bus.publish("agent.task.cancelled", {"task_id": task_id})
        return True

    def pause(self, task_id: str) -> bool:
        self._pause_flags[task_id] = True
        task = self._store.get_task(task_id)
        if task and task["status"] == "running":
            task["status"] = "paused"
            self._store.save_task(task)
            self._bus.publish("agent.task.paused", {"task_id": task_id})
        return True

    def resume(self, task_id: str) -> bool:
        self._pause_flags[task_id] = False
        task = self._store.get_task(task_id)
        if task and task["status"] == "paused":
            task["status"] = "running"
            self._store.save_task(task)
            self._bus.publish("agent.task.resumed", {"task_id": task_id})
        return True

    def set_mode(self, mode: str):
        if mode not in ("safe", "yellow"):
            raise ValueError(f"Invalid mode: {mode}")
        self._mode = mode
        self._bus.publish("agent.mode.changed", {"mode": mode})

    def get_mode(self) -> str:
        return self._mode

    def shutdown(self):
        self._running = False
        # Cancel all active tasks
        for task_id in list(self._cancel_flags):
            self._cancel_flags[task_id] = True
            evt = self._approval_events.get(task_id)
            if evt:
                self._approval_results[task_id] = False
                evt.set()
        # Wait for threads to finish (with timeout)
        for task_id, thread in list(self._active_threads.items()):
            thread.join(timeout=5)
        self._active_threads.clear()

    # ---- Internal: The Loop ----

    def _run_task_loop(self, task_id: str):
        task = self._store.get_task(task_id)
        if not task:
            return

        config = self._config() if callable(self._config) else self._config
        agent_cfg = config.get("agent", {})
        max_turns = agent_cfg.get("max_turns", 50)
        max_cost = agent_cfg.get("max_cost_usd", 10.0)
        max_time = agent_cfg.get("max_time_seconds", 7200)

        task["status"] = "running"
        task["updated_at"] = time.time()
        self._store.save_task(task)
        self._bus.publish("agent.task.running", {"task_id": task_id})

        # Git-isolated worktree for this task
        worktree_path = self._create_worktree(task_id, config)
        if worktree_path:
            task["metadata"]["worktree"] = worktree_path
            self._store.save_task(task)

        start_time = time.time()
        messages = list(task.get("messages") or [])

        # Build system prompt
        from agent_prompt import build_system_prompt
        status_text = self._build_status_text()
        recent = self._store.list_tasks(status="completed", limit=5)
        system_prompt = build_system_prompt(
            mode=task["mode"],
            tool_descriptions=self._registry.describe_all(),
            system_status=status_text,
            recent_tasks=recent,
        )

        # Initialize messages if fresh
        if not messages:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task["description"]},
            ]

        tool_error_counts: dict[str, int] = {}

        try:
            while True:
                # Check termination conditions
                if self._cancel_flags.get(task_id):
                    task["status"] = "cancelled"
                    break

                while self._pause_flags.get(task_id):
                    time.sleep(1)
                    if self._cancel_flags.get(task_id):
                        break

                if task["turns"] >= max_turns:
                    task["status"] = "failed"
                    task["error"] = f"Max turns exceeded ({max_turns})"
                    break

                if task["cost"] >= max_cost:
                    task["status"] = "failed"
                    task["error"] = f"Cost limit exceeded (${max_cost})"
                    break

                elapsed = time.time() - start_time
                if elapsed >= max_time:
                    task["status"] = "failed"
                    task["error"] = f"Timeout ({int(max_time)}s)"
                    break

                # Checkpoint: persist full state so task can resume after crash
                task["messages"] = messages
                task["updated_at"] = time.time()
                task["metadata"]["checkpoint_turn"] = task["turns"]
                task["metadata"]["checkpoint_time"] = time.time()
                self._store.save_task(task)
                self._bus.publish("agent.progress", {
                    "task_id": task_id,
                    "msg": f"Turn {task['turns'] + 1}: calling LLM...",
                    "pct": min(95, int((task["turns"] / max_turns) * 100)),
                })

                # Call LLM
                response_text, tool_calls = self._call_llm(messages, task_id)
                task["turns"] += 1

                if response_text:
                    messages.append({"role": "assistant", "content": response_text})
                    self._bus.publish("agent.thought", {
                        "task_id": task_id,
                        "turn": task["turns"],
                        "text": response_text[:500],
                    })

                # No tool calls = task complete
                if not tool_calls:
                    task["status"] = "completed"
                    task["result"] = response_text
                    break

                # Execute tool calls
                for call in tool_calls:
                    if self._cancel_flags.get(task_id):
                        break

                    tool_name = call.get("name", "")
                    tool_input = call.get("input", {})
                    call_id = call.get("id", uuid.uuid4().hex[:8])

                    tool = self._registry.get(tool_name)
                    if not tool:
                        messages.append({
                            "role": "tool_result",
                            "tool_use_id": call_id,
                            "content": f"Error: Unknown tool '{tool_name}'",
                            "is_error": True,
                        })
                        continue

                    # Approval check
                    needs_approval = tool.always_confirm or (tool.needs_approval and task["mode"] == "safe")
                    if needs_approval:
                        approved = self._wait_for_approval(task_id, tool_name, tool_input)
                        if not approved:
                            messages.append({
                                "role": "tool_result",
                                "tool_use_id": call_id,
                                "content": "Action rejected by user.",
                                "is_error": True,
                            })
                            self._store.save_audit(task_id, tool_name, json.dumps(tool_input), "rejected", is_error=True, approved_by="user")
                            continue
                        approved_by = "user"
                    else:
                        approved_by = "yellow" if task["mode"] == "yellow" else "auto"

                    # Execute tool
                    self._bus.publish("agent.tool.start", {
                        "task_id": task_id, "tool": tool_name, "args": tool_input,
                    })

                    try:
                        result = self._registry.execute(tool_name, tool_input)
                        result_str = str(result)[:4000]
                        messages.append({
                            "role": "tool_result",
                            "tool_use_id": call_id,
                            "content": result_str,
                        })
                        self._bus.publish("agent.tool.result", {
                            "task_id": task_id, "tool": tool_name,
                            "success": True, "preview": result_str[:200],
                        })
                        self._store.save_audit(task_id, tool_name, json.dumps(tool_input), result_str[:1000], approved_by=approved_by)
                        tool_error_counts[tool_name] = 0
                    except Exception as e:
                        error_str = f"Error: {e}"
                        messages.append({
                            "role": "tool_result",
                            "tool_use_id": call_id,
                            "content": error_str,
                            "is_error": True,
                        })
                        self._bus.publish("agent.tool.result", {
                            "task_id": task_id, "tool": tool_name,
                            "success": False, "error": str(e),
                        })
                        self._store.save_audit(task_id, tool_name, json.dumps(tool_input), error_str, is_error=True, approved_by=approved_by)
                        tool_error_counts[tool_name] = tool_error_counts.get(tool_name, 0) + 1
                        if tool_error_counts[tool_name] >= 3:
                            messages.append({
                                "role": "tool_result",
                                "tool_use_id": call_id,
                                "content": f"Tool '{tool_name}' has failed 3 times. Skipping further calls to this tool.",
                                "is_error": True,
                            })

                # Persist state after each turn
                task["messages"] = messages
                task["updated_at"] = time.time()
                self._store.save_task(task)

        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            log.error(f"Agent task {task_id} failed: {e}")

        finally:
            task["completed_at"] = time.time()
            task["messages"] = messages
            task["updated_at"] = time.time()
            self._store.save_task(task)
            self._bus.publish(f"agent.task.{task['status']}", {
                "task_id": task_id,
                "result": task.get("result", "")[:500] if task.get("result") else None,
                "error": task.get("error"),
            })
            # Cleanup git worktree
            wt = task.get("metadata", {}).get("worktree")
            if wt:
                self._cleanup_worktree(wt, task_id)
            self._active_threads.pop(task_id, None)
            self._cancel_flags.pop(task_id, None)
            self._pause_flags.pop(task_id, None)

    def _call_llm(self, messages: list, task_id: str) -> tuple:
        """Call LLM with tool_use. Returns (text_response, tool_calls)."""
        from adapters import get_adapter

        config = self._config() if callable(self._config) else self._config
        agent_cfg = config.get("agent", {})
        tool_name = agent_cfg.get("reasoning_tool", config.get("cli_tool", "wasabi"))

        # Build the prompt: full conversation + tool definitions
        tool_defs = self._registry.to_tool_defs()

        # Compact messages if too long (keep system + last 30)
        compact_messages = messages
        if len(messages) > 40:
            compact_messages = messages[:1] + messages[-30:]

        # Format for the adapter: the adapter takes a single prompt string
        prompt = self._format_messages_for_adapter(compact_messages, tool_defs)

        adapter = get_adapter(tool_name)
        parse_config = dict(config)
        parse_config["_parsing_mode"] = True

        self._bus.publish("agent.thought", {
            "task_id": task_id,
            "turn": 0,
            "text": f"Calling {tool_name}...",
        })

        try:
            task = self._store.get_task(task_id)
            task_cwd = (task or {}).get("metadata", {}).get("worktree") or config.get("directories", {}).get("default", "/tmp")
            result = adapter.spawn(
                prompt=prompt,
                cwd=task_cwd,
                timeout=agent_cfg.get("step_timeout_seconds", 600),
                config=parse_config,
            )
        except Exception as e:
            log.error(f"LLM call failed for task {task_id}: {e}")
            return f"LLM call failed: {e}", []

        if not result.get("success") or not result.get("output"):
            error_msg = result.get("error", "No response from LLM")
            log.warning(f"LLM returned no output for task {task_id}: {error_msg}")
            return f"LLM error: {error_msg}", []

        output = result["output"]

        # Parse tool calls from output
        tool_calls = self._extract_tool_calls(output)

        # If tool calls found, strip them from text
        if tool_calls:
            text = self._strip_tool_blocks(output)
        else:
            text = output

        return text, tool_calls

    def _format_messages_for_adapter(self, messages: list, tool_defs: list) -> str:
        """Format conversation + tools into a single prompt string for the adapter."""
        parts = []

        # System message first
        for m in messages:
            if m.get("role") == "system":
                parts.append(m["content"])
                break

        # Tool definitions
        parts.append("\n\nAVAILABLE TOOLS (use >>>TOOL_CALL blocks to invoke):")
        for td in tool_defs:
            params = json.dumps(td["input_schema"].get("properties", {}), indent=2)
            required = td["input_schema"].get("required", [])
            parts.append(f"\n### {td['name']}\n{td['description']}\nParameters: {params}\nRequired: {required}")

        parts.append("\n\nTo call a tool, output:\n>>>TOOL_CALL\nname: tool_name\ninput: {json_args}\n<<<TOOL_CALL\n")
        parts.append("You may call multiple tools. After tool results are returned, you continue reasoning.")

        # Conversation history
        parts.append("\n\n--- CONVERSATION ---")
        for m in messages:
            role = m.get("role", "")
            if role == "system":
                continue
            elif role == "user":
                parts.append(f"\nUSER: {m['content']}")
            elif role == "assistant":
                parts.append(f"\nASSISTANT: {m['content']}")
            elif role == "tool_result":
                is_err = m.get("is_error", False)
                prefix = "TOOL_ERROR" if is_err else "TOOL_RESULT"
                parts.append(f"\n{prefix} [{m.get('tool_use_id', '')}]: {m['content']}")

        parts.append("\n\nASSISTANT:")
        return "\n".join(parts)

    def _extract_tool_calls(self, text: str) -> list:
        """Extract >>>TOOL_CALL...<<<TOOL_CALL blocks from LLM output."""
        calls = []
        pattern = r'>>>TOOL_CALL\s*\n(.*?)\n<<<TOOL_CALL'
        for match in re.finditer(pattern, text, re.DOTALL):
            block = match.group(1).strip()
            name = ""
            input_json = {}
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    name = line[5:].strip()
                elif line.startswith("input:"):
                    raw = line[6:].strip()
                    # May span multiple lines — collect remaining
                    remaining = block[block.index(line) + len(line):].strip()
                    if remaining:
                        raw = raw + "\n" + remaining
                    try:
                        input_json = json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        try:
                            input_json = json.loads(line[6:].strip())
                        except (json.JSONDecodeError, ValueError):
                            input_json = {}
                    break
            if name:
                calls.append({
                    "id": uuid.uuid4().hex[:8],
                    "name": name,
                    "input": input_json,
                })
        return calls

    def _strip_tool_blocks(self, text: str) -> str:
        return re.sub(r'>>>TOOL_CALL\s*\n.*?\n<<<TOOL_CALL', '', text, flags=re.DOTALL).strip()

    def _wait_for_approval(self, task_id: str, tool_name: str, tool_input: dict) -> bool:
        """Block until user approves or rejects. Returns True if approved."""
        task = self._store.get_task(task_id)
        if task:
            task["status"] = "waiting_approval"
            self._store.save_task(task)

        self._bus.publish("agent.approval.needed", {
            "task_id": task_id,
            "tool": tool_name,
            "args": tool_input,
        })

        evt = threading.Event()
        self._approval_events[task_id] = evt
        evt.wait(timeout=3600)  # 1 hour max wait
        del self._approval_events[task_id]

        result = self._approval_results.pop(task_id, False)

        if task:
            task["status"] = "running"
            self._store.save_task(task)

        return result

    def _build_status_text(self) -> str:
        parts = []
        try:
            sessions = self._sm.list()
            busy = sum(1 for s in sessions if getattr(s, 'status', '') == 'busy')
            parts.append(f"Sessions: {len(sessions)} total, {busy} busy")
        except Exception:
            parts.append("Sessions: unavailable")

        try:
            state = self._daemon.state
            parts.append(f"Reminders: {len(state.get('reminders', []))}")
            active_schedules = [s for s in state.get('scheduled_tasks', []) if s.get('status') == 'active']
            parts.append(f"Schedules: {len(active_schedules)} active")
            active_watches = [w for w in state.get('watches', []) if w.get('status') == 'active']
            parts.append(f"Watches: {len(active_watches)} active")
        except Exception:
            pass

        try:
            active_tasks = self._store.list_tasks(status="running")
            parts.append(f"Agent tasks: {len(active_tasks)} running")
        except Exception:
            pass

        return "\n".join(parts)
