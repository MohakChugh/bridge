"""AI workflow generator — natural language → DAG nodes + edges."""

from __future__ import annotations
import json
import logging
import shlex
import subprocess
from typing import Optional

from adapters.base import get_login_shell_env

log = logging.getLogger("workflow_generator")

GENERATE_PROMPT = """You are a workflow DAG designer. Given a natural language description, generate a workflow as JSON.

Available node types:
- start: entry point. Always exactly one. data: {{}}
- prompt: executes a prompt on the CLI tool. data: {{"prompt": "the detailed instruction"}}
- branch: conditional split based on previous output. data: {{"branch_type": "conditional", "condition": "yes/no question about previous output"}}
- merge: waits for all incoming branches before continuing. data: {{}}
- delay: pause execution. data: {{"seconds": N}}
- approval: pauses workflow, waits for human to click Continue. data: {{"message": "what needs approval"}}
- notify: sends notification via iMessage/Slack. The message field is a PROMPT that the LLM will use to compose the notification from conversation context. data: {{"channel": "imessage", "message": "describe what to notify about", "wait_for_ack": false}}
- end: terminal node. Always exactly one. data: {{}}

Rules:
1. Every workflow MUST start with exactly one "start" node and end with exactly one "end" node
2. Every branch node MUST have a corresponding merge node downstream that collects the paths
3. Branch edges MUST have "label": "yes" or "label": "no" for conditional branches
4. Node IDs should be descriptive: "check-pipelines", "diagnose-failure", etc.
5. Generate realistic, detailed prompt text for each prompt node — not just summaries
6. If the user mentions notifications/alerts, use notify nodes (not prompt nodes)
7. If the user mentions waiting for approval, use approval nodes

User request: {user_text}
Tool to use: {tool}

Reply with ONLY valid JSON, no other text:
{{"name": "workflow name", "description": "brief description", "nodes": [...], "edges": [...]}}"""


def generate_workflow(text: str, tool: str = "wasabi", cwd: str = "/tmp") -> Optional[dict]:
    env = get_login_shell_env()
    prompt = GENERATE_PROMPT.format(user_text=text, tool=tool)

    cmd = (
        "claude -p " + shlex.quote(prompt)
        + " --output-format json --dangerously-skip-permissions --effort low"
    )

    try:
        result = subprocess.run(
            ["zsh", "-i", "-c", cmd],
            capture_output=True, text=True, timeout=60, env=env,
        )
        if result.returncode != 0:
            log.warning(f"Workflow generation failed: {result.stderr[:200]}")
            return None

        raw = result.stdout.strip()
        try:
            outer = json.loads(raw)
            if isinstance(outer, dict) and "result" in outer:
                raw = outer["result"]
        except json.JSONDecodeError:
            pass

        if isinstance(raw, str):
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]
            wf = json.loads(raw)
        else:
            wf = raw

        if not isinstance(wf, dict) or "nodes" not in wf or "edges" not in wf:
            log.warning(f"Invalid workflow JSON structure")
            return None

        wf.setdefault("name", "AI Generated Workflow")
        wf.setdefault("description", text[:200])
        wf["tool"] = tool
        wf["cwd"] = cwd

        return wf

    except subprocess.TimeoutExpired:
        log.warning("Workflow generation timed out")
        return None
    except json.JSONDecodeError as e:
        log.warning(f"Failed to parse workflow JSON: {e}")
        return None
    except Exception as e:
        log.warning(f"Workflow generation error: {e}")
        return None
