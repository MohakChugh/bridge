"""Wasabi CLI adapter."""

from __future__ import annotations
from typing import Optional
import json
import logging
import re
import shlex
import subprocess

from .base import BaseAdapter, get_login_shell_env

log = logging.getLogger(__name__)

# Noise patterns in wasabi JSON log output to skip
SKIP_PATTERNS = [
    "Initializing", "Press ESC", "Prompt:", "Tokens used:",
    "Waiting for response", "Responding...", "Thinking...",
    "loading_state", "<thinking>", "Auto-approved",
    "Executing tool", "model is asking", "Restoring previous",
    "End workflow", "Reading file", "MCP server",
    "Passing context", "Compacting", "Cache prediction",
    "disable-continue disables restore", "Memory Reset",
    "hooks finished", "Tool response:", "Passing --disable",
]

BRIEF_PREFIX = (
    "CAVEMAN MODE. Terse like smart caveman. "
    "Drop articles, filler, pleasantries. Fragments OK. Short synonyms. "
    "No markdown. Plain text only. Extremely brief. "
)


def _format_history_for_prompt(history: list) -> str:
    """Render prior messages as plain-text context prefix.
    history: list of {role, text, timestamp} — newest last.
    Drops the final entry (that's the current user prompt, already included).
    """
    if not history or len(history) < 2:
        return ""
    # Keep last N turns to stay under context window
    recent = history[-10:-1]  # exclude final user entry (current prompt)
    if not recent:
        return ""
    lines = ["PREVIOUS CONVERSATION (for context):"]
    for msg in recent:
        role = msg.get("role", "")
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        # Truncate long responses
        if len(text) > 800:
            text = text[:800] + "..."
        if role == "user":
            lines.append(f"User: {text}")
        elif role == "assistant":
            lines.append(f"You: {text}")
    lines.append("---")
    lines.append("CURRENT MESSAGE:")
    return "\n".join(lines) + "\n\n"


def _is_tool_output(msg: str) -> bool:
    """Detect raw tool output that wasabi dumps as INFO messages.
    These are command results (ls, cat, grep) — not model responses.
    """
    lines = msg.strip().split("\n")
    if len(lines) < 3:
        return False
    # ls -la output: lines starting with permissions pattern
    perm_lines = sum(1 for l in lines if re.match(r'^[drwx\-lst@+]{10}', l.strip()))
    if perm_lines > 2:
        return True
    # total N at start of ls output
    if lines[0].strip().startswith("total ") and perm_lines > 0:
        return True
    return False


class WasabiAdapter(BaseAdapter):
    def name(self) -> str:
        return "wasabi"

    def is_available(self) -> bool:
        import os
        # Check known paths directly — toolbox doesn't always appear in zsh -l PATH
        known_paths = [
            os.path.expanduser("~/.toolbox/bin/wasabi"),
            "/opt/homebrew/bin/wasabi",
            "/usr/local/bin/wasabi",
        ]
        for p in known_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return True
        try:
            r = subprocess.run(["zsh", "-l", "-c", "which wasabi"], capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False

    def spawn(
        self,
        prompt: str,
        cwd: str,
        timeout: int = 18000,
        resume_session_id: Optional[str] = None,
        process_holder: object = None,
        config: Optional[dict] = None,
        history: Optional[list] = None,
    ) -> dict:
        proc = None
        try:
            cfg = config or {}
            adapter_cfg = cfg.get("adapters", {}).get("wasabi", {})
            account = adapter_cfg.get("account", "YOUR_ACCOUNT_ID")
            model = adapter_cfg.get("model", "global.anthropic.claude-opus-4-6-v1:1m")

            if account in ("YOUR_ACCOUNT_ID", "test", ""):
                return {"success": False, "output": "", "error": f"Wasabi account not configured (got '{account}'). Set adapters.wasabi.account in config.json", "session_id": None}
            if model in ("test-model", ""):
                return {"success": False, "output": "", "error": f"Wasabi model not configured (got '{model}'). Set adapters.wasabi.model in config.json", "session_id": None}

            # Wasabi resets memory between non-interactive calls ("End workflow. Memory Reset").
            # Inject prior conversation into the prompt ourselves to maintain continuity.
            history_block = _format_history_for_prompt(history or [])

            # Skip caveman prefix in parsing mode — need clean JSON output
            if cfg.get("_parsing_mode"):
                full_prompt = prompt
            else:
                full_prompt = BRIEF_PREFIX + history_block + prompt

            # Use full path — toolbox may not be in launchd's PATH
            wasabi_bin = self._find_wasabi_path()
            parts = [
                wasabi_bin,
                "--disable-initial-workspace-summary",
                "--auto-accept-edits",
                "--dangerously-accept-all-prompts",
                f"--model-arn={shlex.quote(model)}",
                "--skip-git-safety-check",
                f"--account {shlex.quote(account)}",
                "--non-interactive",
            ]
            if not resume_session_id or resume_session_id == "none":
                parts.append("--disable-continue")
            parts.append(f"--prompt {shlex.quote(full_prompt)}")
            # Use text mode with no-color for cleanest output
            # (json mode in wasabi is just as noisy)
            wasabi_cmd = " ".join(parts)

            env = get_login_shell_env()
            proc = subprocess.Popen(
                ["zsh", "-i", "-c", wasabi_cmd],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            if process_holder and hasattr(process_holder, "_active_process"):
                process_holder._active_process = proc

            stdout, stderr = proc.communicate(timeout=timeout)


            response = self._extract_response(stdout, skip_markdown_strip=bool(cfg.get("_parsing_mode")))
            has_error = self._has_error(stdout)

            if response and not has_error:
                # Return "auto" as session_id — signals manager that subsequent calls
                # should NOT pass --disable-continue (wasabi auto-resumes per cwd).
                return {"success": True, "output": response, "error": "", "session_id": "auto"}
            elif has_error:
                error_msg = self._extract_error(stdout) or "Unknown error"
                return {"success": False, "output": "", "error": error_msg[:200], "session_id": None}
            else:
                rc = proc.returncode
                stderr_hint = stderr.strip()[-200:] if stderr.strip() else ""
                stdout_hint = stdout.strip()[-200:] if stdout.strip() else "(empty stdout)"
                err_msg = f"No response from wasabi (rc={rc})"
                if stderr_hint:
                    err_msg += f" stderr: {stderr_hint}"
                elif not stdout.strip():
                    err_msg += " — wasabi produced no output at all. Check account/model config."
                else:
                    err_msg += f" — output filtered empty. Raw tail: {stdout_hint}"
                log.warning(f"Wasabi empty response: rc={rc}, stdout={len(stdout)}b, stderr={len(stderr)}b")
                return {
                    "success": False,
                    "output": "",
                    "error": err_msg[:500],
                    "session_id": "auto",
                }

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
                proc.wait()
            return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
        except FileNotFoundError:
            return {"success": False, "output": "", "error": "wasabi CLI not found", "session_id": None}
        except Exception as exc:
            if proc is not None:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
            return {"success": False, "output": "", "error": str(exc)[:200], "session_id": None}

    def list_sessions(self, cwd: str, config: Optional[dict] = None) -> list:
        """Wasabi auto-resumes per directory — return single 'auto' entry."""
        return [{"id": "auto", "preview": "Auto-resume session (wasabi)", "age": "auto", "messages": 0}]

    def clear_session(self, cwd: str, config: Optional[dict] = None) -> None:
        """Clear wasabi session by running with --disable-continue."""
        cfg = config or {}
        adapter_cfg = cfg.get("adapters", {}).get("wasabi", {})
        account = adapter_cfg.get("account", "YOUR_ACCOUNT_ID")
        model = adapter_cfg.get("model", "global.anthropic.claude-opus-4-6-v1:1m")
        try:
            env = get_login_shell_env()
            subprocess.run(
                ["zsh", "-i", "-c",
                 f"wasabi --disable-initial-workspace-summary --auto-accept-edits "
                 f"--dangerously-accept-all-prompts --model-arn={shlex.quote(model)} "
                 f"--skip-git-safety-check --account {shlex.quote(account)} "
                 f"--non-interactive --disable-continue --prompt '/clear'"],
                cwd=cwd, capture_output=True, text=True, timeout=30, env=env,
            )
        except Exception:
            pass

    @staticmethod
    def _find_wasabi_path() -> str:
        """Find wasabi binary path."""
        import os
        for p in [
            os.path.expanduser("~/.toolbox/bin/wasabi"),
            "/opt/homebrew/bin/wasabi",
            "/usr/local/bin/wasabi",
        ]:
            if os.path.isfile(p):
                return p
        return "wasabi"  # fallback to PATH lookup

    def _extract_response(self, raw_output: str, skip_markdown_strip: bool = False) -> str:
        """Extract actual response from wasabi's noisy output.

        Strategy: only collect messages that appear AFTER the "Prompt:" line.
        This skips restored conversation context entirely. Then filter out
        tool execution noise, keeping only the model's text responses.

        Args:
            raw_output: Raw stdout from wasabi process.
            skip_markdown_strip: When True, skip strip_markdown() to preserve
                code blocks (e.g. JSON wrapped in ```json ... ```). ANSI codes
                are still removed. Used by parsing_mode to keep structured output.
        """
        response_lines = []
        filtered_count = 0
        seen_prompt = False
        in_tool_block = False

        for line in raw_output.strip().split("\n"):
            line = line.replace("\x1b[K", "").strip()
            if not line:
                continue
            if "Shell cwd was reset" in line:
                continue

            try:
                obj = json.loads(line)
                msg = obj.get("message", "")
                level = obj.get("level", "")
                msg_type = obj.get("type", "")

                if msg.startswith("Prompt:"):
                    seen_prompt = True
                    continue

                if not seen_prompt:
                    filtered_count += 1
                    continue

                if level in ("WARN", "ERROR"):
                    filtered_count += 1
                    continue
                if msg_type == "loading_state":
                    filtered_count += 1
                    continue
                if msg.startswith("{") and "loading_state" in msg:
                    filtered_count += 1
                    continue
                if any(skip in msg for skip in SKIP_PATTERNS):
                    filtered_count += 1
                    continue
                if msg.startswith("<thinking>") or msg.endswith("</thinking>"):
                    filtered_count += 1
                    continue
                if not msg.strip():
                    filtered_count += 1
                    continue

                # Tool execution noise
                if msg.startswith("────"):
                    in_tool_block = not in_tool_block
                    filtered_count += 1
                    continue
                if in_tool_block:
                    filtered_count += 1
                    continue
                if msg.startswith("Command:") and len(msg) < 200:
                    filtered_count += 1
                    continue
                if msg.startswith("✓ Auto-approved"):
                    filtered_count += 1
                    continue
                if msg.startswith("Tokens used:"):
                    filtered_count += 1
                    continue
                if "disable-continue disables restore" in msg:
                    filtered_count += 1
                    continue
                if msg.startswith("End workflow"):
                    filtered_count += 1
                    continue
                if "Memory Reset" in msg:
                    filtered_count += 1
                    continue

                # Tool output is dumped as raw INFO — detect by structure
                # (ls output, file contents, etc. appear between tool calls)
                # Only keep lines that don't look like raw command output
                if _is_tool_output(msg):
                    filtered_count += 1
                    continue

                response_lines.append(msg)
            except json.JSONDecodeError:
                if not seen_prompt:
                    continue
                if line and not line.startswith("[") and not line.startswith("<system"):
                    response_lines.append(line)

        text = "\n".join(response_lines)
        if skip_markdown_strip:
            # Parsing mode: preserve code blocks (JSON etc.) but still strip ANSI
            result = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
        else:
            result = self.strip_markdown(text)

        # Last-resort fallback: normal extraction produced empty but stdout has
        # content after "Prompt:". Strip obvious noise, return a best-effort
        # cleaned version. Log memory-reset markers so the user sees WHY output
        # was empty.
        if not result:
            if "Prompt:" in raw_output:
                after_prompt = raw_output.split("Prompt:", 1)[1]
                lines = []
                for line in after_prompt.split("\n"):
                    s = line.replace("\x1b[K", "").strip()
                    if not s:
                        continue
                    # Skip tool blocks, timestamps, loading indicators
                    if s.startswith(("[Tool:", "[Loading", "Loading ", "───", "▲ ", "▼ ")):
                        continue
                    if "Memory Reset" in s or "End workflow" in s:
                        log.info(f"Wasabi memory reset detected: {s[:80]}")
                        continue
                    lines.append(s)
                if lines:
                    fallback = "\n".join(lines)
                    log.info(f"Wasabi extraction used last-resort fallback ({len(fallback)} chars)")
                    return fallback

        return result

    @staticmethod
    def _has_error(raw_output: str) -> bool:
        for line in raw_output.strip().split("\n"):
            line = line.replace("\x1b[K", "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("level") == "ERROR":
                    return True
            except json.JSONDecodeError:
                if "Authentication Failed" in line:
                    return True
        return False

    @staticmethod
    def _extract_error(raw_output: str) -> str:
        for line in raw_output.strip().split("\n"):
            line = line.replace("\x1b[K", "").strip()
            try:
                obj = json.loads(line)
                if obj.get("level") == "ERROR":
                    return obj.get("message", "Unknown error")
            except json.JSONDecodeError:
                if "Authentication Failed" in line:
                    return "Authentication failed"
        return "Unknown error"
