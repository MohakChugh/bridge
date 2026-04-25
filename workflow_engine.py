"""Workflow DAG executor — runs workflows as single-session conversations.

Supports: start, prompt, branch (conditional + parallel), merge, delay,
approval (human gate), notify (iMessage/Slack), end.

Persists runs to workflow_runs.json so history survives daemon restarts.
Orphaned runs (daemon died mid-execution) are marked as failed on load.
"""

from __future__ import annotations
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

from event_bus import get_event_bus

log = logging.getLogger("workflow_engine")

RUNS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow_runs.json")


@dataclass
class NodeState:
    status: str = "pending"
    output: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class WorkflowRun:
    id: str
    workflow_id: str
    workflow_name: str
    status: str = "pending"
    node_states: dict[str, NodeState] = field(default_factory=dict)
    session_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    params: dict = field(default_factory=dict)
    schedule_label: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "node_states": {nid: ns.to_dict() for nid, ns in self.node_states.items()},
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "params": self.params,
            "schedule_label": self.schedule_label,
        }

    @staticmethod
    def from_dict(d: dict) -> "WorkflowRun":
        r = WorkflowRun(
            id=d["id"],
            workflow_id=d["workflow_id"],
            workflow_name=d.get("workflow_name", ""),
            status=d.get("status", "completed"),
            session_id=d.get("session_id"),
            started_at=d.get("started_at", 0),
            completed_at=d.get("completed_at"),
            params=d.get("params", {}),
            schedule_label=d.get("schedule_label"),
        )
        for nid, ns_d in d.get("node_states", {}).items():
            ns = NodeState(
                status=ns_d.get("status", "pending"),
                output=ns_d.get("output"),
                error=ns_d.get("error"),
                started_at=ns_d.get("started_at"),
                completed_at=ns_d.get("completed_at"),
            )
            r.node_states[nid] = ns
        return r


def _load_runs(path: str = RUNS_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_runs(runs: list[dict], path: str = RUNS_PATH) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(runs, f, separators=(",", ":"))
    os.replace(tmp, path)


class WorkflowEngine:
    def __init__(self, session_manager, config_provider: Callable, daemon_ref: Any = None):
        self._session_manager = session_manager
        self._config_provider = config_provider
        self._daemon_ref = daemon_ref
        self._bus = get_event_bus()
        self._runs: dict[str, WorkflowRun] = {}
        self._approval_events: dict[str, threading.Event] = {}
        self._abort_flags: dict[str, bool] = {}
        self._persist_lock = threading.Lock()
        self._load_history()

    def _load_history(self) -> None:
        for rd in _load_runs():
            r = WorkflowRun.from_dict(rd)
            if r.status in ("running", "paused", "pending"):
                r.status = "failed"
                r.completed_at = r.completed_at or time.time()
                for ns in r.node_states.values():
                    if ns.status == "running":
                        ns.status = "failed"
                        ns.error = "Daemon restarted"
                        ns.completed_at = ns.completed_at or time.time()
            self._runs[r.id] = r
        log.info(f"Loaded {len(self._runs)} workflow run(s) from history")

    def _persist(self) -> None:
        with self._persist_lock:
            all_runs = [r.to_dict() for r in self._runs.values()]
            all_runs.sort(key=lambda r: r.get("started_at", 0), reverse=True)
            _save_runs(all_runs[:200])

    def run(self, workflow: dict, params: Optional[dict] = None, schedule_label: Optional[str] = None) -> WorkflowRun:
        from variable_resolver import resolve_variables
        resolved_params = resolve_variables(workflow.get("variables", []), params or {})

        run_id = str(uuid.uuid4())
        wf_run = WorkflowRun(
            id=run_id,
            workflow_id=workflow["id"],
            workflow_name=workflow.get("name", "Untitled"),
        )
        wf_run.params = resolved_params
        wf_run.schedule_label = schedule_label
        for node in workflow.get("nodes", []):
            wf_run.node_states[node["id"]] = NodeState()

        self._runs[run_id] = wf_run
        self._abort_flags[run_id] = False
        self._persist()

        thread = threading.Thread(
            target=self._execute_dag,
            args=(wf_run, workflow),
            daemon=True,
        )
        thread.start()
        return wf_run

    def approve(self, run_id: str) -> bool:
        evt = self._approval_events.get(run_id)
        if evt:
            evt.set()
            return True
        return False

    def abort(self, run_id: str) -> bool:
        wf_run = self._runs.get(run_id)
        if not wf_run:
            return False
        self._abort_flags[run_id] = True
        evt = self._approval_events.get(run_id)
        if evt:
            evt.set()
        if wf_run.session_id:
            self._session_manager.cancel(wf_run.session_id)
        wf_run.status = "aborted"
        wf_run.completed_at = time.time()
        self._persist()
        self._bus.publish("workflow.run.completed", wf_run.to_dict())
        return True

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self._runs.get(run_id)

    def list_runs(self, workflow_id: Optional[str] = None) -> list[WorkflowRun]:
        if workflow_id:
            return [r for r in self._runs.values() if r.workflow_id == workflow_id]
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)

    def _execute_dag(self, wf_run: WorkflowRun, workflow: dict) -> None:
        wf_run.status = "running"
        self._persist()
        self._bus.publish("workflow.run.started", wf_run.to_dict())

        nodes = {n["id"]: n for n in workflow.get("nodes", [])}
        edges = workflow.get("edges", [])

        children = defaultdict(list)
        parents = defaultdict(list)
        for edge in edges:
            children[edge["source"]].append((edge, edge["target"]))
            parents[edge["target"]].append(edge["source"])

        tool = workflow.get("tool", self._config_provider().get("cli_tool", "wasabi"))
        cwd = workflow.get("cwd", self._config_provider()["directories"].get("default", "/tmp"))
        session = self._session_manager.create(tool=tool, cwd=cwd, title=f"WF: {workflow.get('name', '')}")
        wf_run.session_id = session.id

        start_nodes = [nid for nid, n in nodes.items() if n.get("type") == "start"]
        if not start_nodes:
            wf_run.status = "failed"
            wf_run.completed_at = time.time()
            self._persist()
            self._bus.publish("workflow.run.completed", wf_run.to_dict())
            return

        try:
            self._walk(wf_run, nodes, children, parents, start_nodes[0], session.id)
            if wf_run.status == "running":
                wf_run.status = "completed"
        except Exception as e:
            log.exception(f"Workflow execution error: {e}")
            wf_run.status = "failed"
        finally:
            wf_run.completed_at = time.time()
            self._persist()
            self._bus.publish("workflow.run.completed", wf_run.to_dict())

    def _walk(self, wf_run, nodes, children, parents, node_id, session_id):
        if self._abort_flags.get(wf_run.id):
            return

        node = nodes.get(node_id)
        if not node:
            return

        ns = wf_run.node_states.get(node_id)
        if not ns or ns.status in ("completed", "failed", "skipped"):
            return

        parent_ids = [pid for pid in parents.get(node_id, []) if pid in nodes]
        for pid in parent_ids:
            ps = wf_run.node_states.get(pid)
            if ps and ps.status not in ("completed", "skipped"):
                return

        ns.status = "running"
        ns.started_at = time.time()
        self._persist()
        self._bus.publish("workflow.node.started", {
            "run_id": wf_run.id, "node_id": node_id, "node_type": node["type"],
        })

        try:
            self._execute_node(wf_run, node, session_id)
            if ns.status == "running":
                ns.status = "completed"
            ns.completed_at = time.time()
            self._persist()
            self._bus.publish("workflow.node.completed", {
                "run_id": wf_run.id, "node_id": node_id, "output": ns.output,
            })
        except Exception as e:
            ns.status = "failed"
            ns.error = str(e)
            ns.completed_at = time.time()
            self._persist()
            self._bus.publish("workflow.node.failed", {
                "run_id": wf_run.id, "node_id": node_id, "error": str(e),
            })
            wf_run.status = "failed"
            return

        if self._abort_flags.get(wf_run.id):
            return

        outgoing = children.get(node_id, [])
        node_type = node.get("type")

        if node_type == "branch":
            branch_type = node.get("data", {}).get("branch_type", "conditional")
            if branch_type == "parallel":
                self._parallel_branch(wf_run, nodes, children, parents, outgoing, session_id)
            else:
                self._conditional_branch(wf_run, nodes, children, parents, outgoing, session_id, node)
        else:
            for edge, target_id in outgoing:
                self._walk(wf_run, nodes, children, parents, target_id, session_id)

    def _execute_node(self, wf_run, node, session_id):
        ns = wf_run.node_states[node["id"]]
        node_type = node.get("type", "")
        data = node.get("data", {})

        if node_type in ("start", "end", "merge"):
            ns.output = ""
            return

        if node_type == "prompt":
            from variable_resolver import substitute_variables
            prompt = substitute_variables(data.get("prompt", ""), wf_run.params)
            if not prompt:
                ns.output = "(empty prompt)"
                return
            output = self._run_prompt(session_id, prompt)
            ns.output = output

        elif node_type == "branch":
            ns.output = "(branch evaluated)"

        elif node_type == "delay":
            seconds = data.get("seconds", 0)
            time.sleep(seconds)
            ns.output = f"Waited {seconds}s"

        elif node_type == "notify":
            self._execute_notify(wf_run, node, ns)

        elif node_type == "approval":
            self._execute_approval(wf_run, node, ns)

    def _execute_notify(self, wf_run, node, ns):
        from variable_resolver import substitute_variables
        data = node.get("data", {})
        channel = data.get("channel", "imessage")
        prompt = substitute_variables(data.get("message", "Summarize what happened"), wf_run.params)
        wait_for_ack = data.get("wait_for_ack", False)

        # Run the message text as a prompt against the session's LLM.
        # The LLM has full conversation context from prior nodes —
        # it can compose a meaningful notification with failure details,
        # root causes, suggested fixes, etc.
        composed = prompt
        if wf_run.session_id:
            try:
                composed = self._run_prompt(
                    wf_run.session_id,
                    f"Compose a brief notification message for the following request. "
                    f"Use the conversation context above. Keep under 500 chars. "
                    f"Request: {prompt}"
                )
            except Exception as e:
                log.warning(f"Notify LLM compose failed, using raw message: {e}")
                composed = prompt

        notification = f"[WF: {wf_run.workflow_name}] {composed}"
        sent_to = []

        if channel in ("imessage", "both"):
            if self._daemon_ref and hasattr(self._daemon_ref, '_imessage_enabled') and self._daemon_ref._imessage_enabled:
                try:
                    from sender import send_imessage
                    guid = self._daemon_ref.config.get("reply_chat_guid")
                    if guid:
                        send_imessage(guid, notification)
                        sent_to.append("iMessage")
                except Exception as e:
                    log.warning(f"Notify iMessage failed: {e}")

        if channel in ("slack", "both"):
            if self._daemon_ref and hasattr(self._daemon_ref, '_slack_channel') and self._daemon_ref._slack_channel:
                try:
                    slack_cfg = self._daemon_ref.config.get("slack", {})
                    allowed = slack_cfg.get("allowed_users", [])
                    if allowed:
                        for uid in allowed:
                            try:
                                result = self._daemon_ref._slack_channel.app.client.conversations_open(users=uid)
                                dm_channel = result["channel"]["id"]
                                self._daemon_ref._slack_channel.app.client.chat_postMessage(
                                    channel=dm_channel,
                                    text=f"*{notification}*",
                                )
                                sent_to.append("Slack")
                                break
                            except Exception as e:
                                log.warning(f"Notify Slack DM failed for {uid}: {e}")
                except Exception as e:
                    log.warning(f"Notify Slack failed: {e}")

        ns.output = f"Sent to: {', '.join(sent_to) or 'none'}\n\n{composed}"
        self._bus.publish("workflow.notify.sent", {
            "run_id": wf_run.id,
            "node_id": node["id"],
            "channel": channel,
            "message": composed,
            "sent_to": sent_to,
        })

        if wait_for_ack:
            wf_run.status = "paused"
            evt = threading.Event()
            self._approval_events[wf_run.id] = evt
            self._persist()
            self._bus.publish("workflow.approval_needed", {
                "run_id": wf_run.id,
                "node_id": node["id"],
                "message": f"Notification sent. Waiting for acknowledgment.",
                "workflow_name": wf_run.workflow_name,
            })
            evt.wait()
            del self._approval_events[wf_run.id]
            if self._abort_flags.get(wf_run.id):
                ns.status = "failed"
                ns.error = "Aborted"
                raise Exception("Aborted by user")
            wf_run.status = "running"
            ns.output += " (acknowledged)"

    def _execute_approval(self, wf_run, node, ns):
        data = node.get("data", {})
        message = data.get("message", "Approval required")
        wf_run.status = "paused"
        evt = threading.Event()
        self._approval_events[wf_run.id] = evt
        self._persist()
        self._bus.publish("workflow.approval_needed", {
            "run_id": wf_run.id,
            "node_id": node["id"],
            "message": message,
            "workflow_name": wf_run.workflow_name,
        })
        log.info(f"Workflow paused at approval node: {message}")
        evt.wait()
        del self._approval_events[wf_run.id]
        if self._abort_flags.get(wf_run.id):
            ns.status = "failed"
            ns.error = "Aborted by user"
            raise Exception("Aborted by user")
        wf_run.status = "running"
        ns.output = "Approved"

    def _run_prompt(self, session_id: str, prompt: str) -> str:
        session = self._session_manager.get(session_id)
        if not session:
            return "(session not found)"

        done = threading.Event()
        result_holder = [None]

        def on_complete(sess, result):
            result_holder[0] = result
            done.set()

        self._session_manager.execute(session_id, prompt, on_complete=on_complete)
        done.wait(timeout=18000)

        result = result_holder[0]
        if result and result.get("success"):
            return result.get("output", "")
        elif result:
            raise Exception(result.get("error", "Prompt execution failed"))
        else:
            raise Exception("Timeout waiting for prompt execution")

    def _conditional_branch(self, wf_run, nodes, children, parents, outgoing, session_id, branch_node):
        condition = branch_node.get("data", {}).get("condition", "")
        if not condition:
            for edge, target_id in outgoing:
                self._walk(wf_run, nodes, children, parents, target_id, session_id)
            return

        answer = self._run_prompt(
            session_id,
            f"Based on the above conversation, answer ONLY 'yes' or 'no': {condition}"
        ).strip().lower()

        is_yes = answer.startswith("yes")
        for edge, target_id in outgoing:
            label = (edge.get("label") or "").lower()
            if (is_yes and label in ("yes", "true", "")) or (not is_yes and label in ("no", "false")):
                self._walk(wf_run, nodes, children, parents, target_id, session_id)
            else:
                ns = wf_run.node_states.get(target_id)
                if ns:
                    ns.status = "skipped"

    def _parallel_branch(self, wf_run, nodes, children, parents, outgoing, session_id):
        threads = []
        for edge, target_id in outgoing:
            t = threading.Thread(
                target=self._walk,
                args=(wf_run, nodes, children, parents, target_id, session_id),
                daemon=True,
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
