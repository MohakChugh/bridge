"""Wasabi CLI adapter."""

from __future__ import annotations
from typing import Optional
import json
import shlex
import subprocess

from .base import BaseAdapter, get_login_shell_env

# Noise patterns in wasabi JSON log output to skip
SKIP_PATTERNS = [
    "Initializing", "Press ESC", "Prompt:", "Tokens used:",
    "Waiting for response", "Responding...", "Thinking...",
    "loading_state", "<thinking>", "Auto-approved",
    "Executing tool", "model is asking", "Restoring previous",
    "End workflow", "Reading file", "MCP server",
    "Passing context", "Compacting", "Cache prediction",
]

BRIEF_PREFIX = (
    "Reply via iMessage text. Casual, short, plain text. "
    "No markdown (no backticks, asterisks, hashes, bullets, code blocks). "
    "Keep brief but complete. "
)


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
    ) -> dict:
        try:
            cfg = config or {}
            adapter_cfg = cfg.get("adapters", {}).get("wasabi", {})
            account = adapter_cfg.get("account", "YOUR_ACCT_ID")
            model = adapter_cfg.get("model", "global.anthropic.claude-opus-4-6-v1:1m")

            # Prepend brief instruction since wasabi has no --append-system-prompt
            full_prompt = BRIEF_PREFIX + prompt

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
                f"--prompt {shlex.quote(full_prompt)}",
            ]
            # Use text mode with no-color for cleanest output
            # (json mode in wasabi is just as noisy)
            wasabi_cmd = " ".join(parts)

            env = get_login_shell_env()
            proc = subprocess.Popen(
                ["zsh", "-c", wasabi_cmd],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            if process_holder and hasattr(process_holder, "_active_process"):
                process_holder._active_process = proc

            stdout, stderr = proc.communicate(timeout=timeout)

            response = self._extract_response(stdout)
            has_error = self._has_error(stdout)

            if response and not has_error:
                # Wasabi auto-resumes per cwd, no session_id needed
                return {"success": True, "output": response, "error": "", "session_id": None}
            elif has_error:
                error_msg = self._extract_error(stdout) or "Unknown error"
                return {"success": False, "output": "", "error": error_msg[:200], "session_id": None}
            else:
                return {"success": False, "output": "", "error": "No response from wasabi", "session_id": None}

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
        except FileNotFoundError:
            return {"success": False, "output": "", "error": "wasabi CLI not found", "session_id": None}

    def clear_session(self, cwd: str, config: Optional[dict] = None) -> None:
        """Clear wasabi session by running with --disable-continue."""
        cfg = config or {}
        adapter_cfg = cfg.get("adapters", {}).get("wasabi", {})
        account = adapter_cfg.get("account", "YOUR_ACCT_ID")
        model = adapter_cfg.get("model", "global.anthropic.claude-opus-4-6-v1:1m")
        try:
            env = get_login_shell_env()
            subprocess.run(
                ["zsh", "-c",
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

    def _extract_response(self, raw_output: str) -> str:
        """Extract actual response from wasabi's noisy output."""
        response_lines = []
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

                if level == "WARN":
                    continue
                if msg_type == "loading_state":
                    continue
                if msg.startswith("{") and "loading_state" in msg:
                    continue
                if any(skip in msg for skip in SKIP_PATTERNS):
                    continue
                if msg.startswith("<thinking>") or msg.endswith("</thinking>"):
                    continue
                if not msg.strip():
                    continue

                if level == "ERROR":
                    continue  # Errors handled separately

                response_lines.append(msg)
            except json.JSONDecodeError:
                # Non-JSON line — might be plain text response
                if line and not line.startswith("[") and not line.startswith("<system"):
                    response_lines.append(line)

        text = "\n".join(response_lines)
        return self.strip_markdown(text)

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
