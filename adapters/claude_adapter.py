"""Claude Code CLI adapter."""

from __future__ import annotations
from typing import Optional
import json
import os
import shlex
import subprocess

from .base import BaseAdapter, get_login_shell_env

BRIEF_INSTRUCTION = (
    "CAVEMAN MODE ACTIVE. Respond terse like smart caveman. "
    "Drop articles (a/an/the), filler, pleasantries, hedging. "
    "Fragments OK. Short synonyms. Technical terms exact. "
    "Pattern: [thing] [action] [reason]. "
    "No markdown ever — no backticks, asterisks, hashes, bullets, code blocks. "
    "Plain text only. Like WhatsApp text message. "
    "Keep extremely brief. Code/commands inline as plain text."
)


class ClaudeAdapter(BaseAdapter):
    def name(self) -> str:
        return "claude"

    def is_available(self) -> bool:
        try:
            r = subprocess.run(["zsh", "-l", "-c", "which claude"], capture_output=True, text=True, timeout=10)
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
            adapter_cfg = cfg.get("adapters", {}).get("claude", {})
            effort = adapter_cfg.get("effort", "max")

            cmd = (
                "claude -p " + shlex.quote(prompt)
                + " --output-format json --dangerously-skip-permissions"
                + f" --effort {shlex.quote(effort)}"
            )
            if not cfg.get("_parsing_mode"):
                cmd += " --append-system-prompt " + shlex.quote(BRIEF_INSTRUCTION)
            if resume_session_id:
                cmd += " --resume " + shlex.quote(resume_session_id)

            env = get_login_shell_env()
            proc = subprocess.Popen(
                ["zsh", "-i", "-c", cmd],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            if process_holder and hasattr(process_holder, "_active_process"):
                process_holder._active_process = proc

            stdout, stderr = proc.communicate(timeout=timeout)

            if proc.returncode == 0:
                summary = self._extract_response(stdout)
                session_id = self._extract_session_id(stdout)
                return {"success": True, "output": summary, "error": "", "session_id": session_id}
            else:
                return {
                    "success": False, "output": "",
                    "error": stderr[:200] or f"exit code {proc.returncode}",
                    "session_id": None,
                }
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
        except FileNotFoundError:
            return {"success": False, "output": "", "error": "claude CLI not found", "session_id": None}

    def list_sessions(self, cwd: str, config: Optional[dict] = None) -> list:
        """List Claude Code sessions. Returns empty — Claude's --resume list is unreliable in non-interactive mode."""
        # Claude --resume list requires interactive mode and often errors with
        # "requires a valid session ID". Return empty to trigger "No sessions" path.
        return []

    def clear_session(self, cwd: str, config: Optional[dict] = None) -> None:
        # Claude sessions are cleared by removing session_id from state
        pass

    def _extract_response(self, output: str) -> str:
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "result" in data:
                text = data["result"]
            elif isinstance(data, dict) and "content" in data:
                text = data["content"]
            else:
                text = str(data)
        except (json.JSONDecodeError, TypeError):
            text = output
        return self.strip_markdown(text)

    @staticmethod
    def _extract_session_id(output: str) -> Optional[str]:
        try:
            data = json.loads(output)
            if isinstance(data, dict):
                return data.get("session_id")
        except (json.JSONDecodeError, TypeError):
            pass
        return None
