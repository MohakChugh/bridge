"""Kiro CLI adapter."""

from __future__ import annotations
from typing import Optional
import json
import os
import re
import subprocess

from .base import BaseAdapter

BRIEF_INSTRUCTION = (
    "You are replying via iMessage text. Respond like a WhatsApp text message "
    "— casual, short, plain text. No markdown ever (no backticks, asterisks, hashes, "
    "bullets, code blocks). Just natural conversational text. Keep it brief but complete."
)

# Kiro agent config for iMessage bridge
IMESSAGE_AGENT_CONFIG = {
    "name": "imessage-bridge",
    "description": "iMessage bridge assistant — responds in plain text, casual style",
    "prompt": BRIEF_INSTRUCTION,
    "tools": ["read", "write", "shell"],
    "allowedTools": ["read", "write", "shell"],
    "resources": [],
}


class KiroAdapter(BaseAdapter):
    def name(self) -> str:
        return "kiro"

    def is_available(self) -> bool:
        known_paths = [
            os.path.expanduser("~/.toolbox/bin/kiro-cli"),
            "/opt/homebrew/bin/kiro-cli",
            "/usr/local/bin/kiro-cli",
        ]
        for p in known_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return True
        try:
            r = subprocess.run(["which", "kiro-cli"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def _ensure_agent_config(self, cwd: str) -> None:
        """Create imessage-bridge agent config if not present."""
        # Use global agent dir so it works in all directories
        agent_dir = os.path.expanduser("~/.kiro/agents")
        agent_file = os.path.join(agent_dir, "imessage-bridge.json")
        if os.path.exists(agent_file):
            return
        os.makedirs(agent_dir, exist_ok=True)
        with open(agent_file, "w") as f:
            json.dump(IMESSAGE_AGENT_CONFIG, f, indent=2)

    @staticmethod
    def _find_kiro_path() -> str:
        for p in [
            os.path.expanduser("~/.toolbox/bin/kiro-cli"),
            "/opt/homebrew/bin/kiro-cli",
            "/usr/local/bin/kiro-cli",
        ]:
            if os.path.isfile(p):
                return p
        return "kiro-cli"

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
            adapter_cfg = cfg.get("adapters", {}).get("kiro", {})
            model = adapter_cfg.get("model", "claude-opus-4.7")

            self._ensure_agent_config(cwd)

            kiro_bin = self._find_kiro_path()
            cmd = [
                kiro_bin, "chat",
                "--model", model,
                "--trust-all-tools",
                "--no-interactive",
                "--wrap", "never",
                "--agent", "imessage-bridge",
            ]
            if resume_session_id and resume_session_id not in ("auto", "none"):
                cmd.extend(["--resume-id", resume_session_id])
            elif resume_session_id == "auto":
                cmd.append("--resume")

            cmd.append(prompt)

            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if process_holder and hasattr(process_holder, "_active_process"):
                process_holder._active_process = proc

            stdout, stderr = proc.communicate(timeout=timeout)

            if proc.returncode == 0:
                response = self._extract_response(stdout)
                session_id = self._extract_session_id(stderr, cwd)
                if response:
                    return {"success": True, "output": response, "error": "", "session_id": session_id}
                else:
                    return {"success": True, "output": "(no response)", "error": "", "session_id": session_id}
            else:
                error = self._extract_error(stderr) or f"exit code {proc.returncode}"
                return {"success": False, "output": "", "error": error[:200], "session_id": None}

        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            return {"success": False, "output": "", "error": f"Timed out after {timeout}s", "session_id": None}
        except FileNotFoundError:
            return {"success": False, "output": "", "error": "kiro-cli not found", "session_id": None}

    def list_sessions(self, cwd: str, config: Optional[dict] = None) -> list:
        """List Kiro sessions for a directory."""
        try:
            kiro_bin = self._find_kiro_path()
            result = subprocess.run(
                [kiro_bin, "chat", "--list-sessions"],
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
            sessions = []
            lines = result.stdout.split("\n")
            for i, line in enumerate(lines):
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
                if "Chat SessionId:" in clean:
                    sid = clean.split("Chat SessionId:")[-1].strip()
                    # Next line has age + preview
                    preview = ""
                    if i + 1 < len(lines):
                        next_clean = re.sub(r'\x1b\[[0-9;]*m', '', lines[i + 1]).strip()
                        preview = next_clean[:60]
                    sessions.append({"id": sid, "preview": preview, "age": "", "messages": 0})
            return sessions[:10]
        except Exception:
            return []

    def clear_session(self, cwd: str, config: Optional[dict] = None) -> None:
        """Delete all sessions for this directory."""
        try:
            kiro_bin = self._find_kiro_path()
            result = subprocess.run(
                [kiro_bin, "chat", "--list-sessions"],
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
            # Parse session IDs from text output
            for line in result.stdout.split("\n"):
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                if "Chat SessionId:" in clean:
                    sid = clean.split("Chat SessionId:")[-1].strip()
                    if sid:
                        subprocess.run(
                            [kiro_bin, "chat", "--delete-session", sid],
                            cwd=cwd, capture_output=True, timeout=10,
                        )
        except Exception:
            pass

    def _extract_response(self, stdout: str) -> str:
        """Extract response from stdout. Kiro puts response on stdout, noise on stderr."""
        # Strip ANSI escape codes
        text = re.sub(r'\x1b\[[0-9;]*[mGKHJ]', '', stdout)
        # Strip cursor hide/show
        text = re.sub(r'\x1b\[\?25[lh]', '', text)
        # Strip carriage returns and line clears
        text = re.sub(r'\r', '', text)
        text = re.sub(r'\x1b\[\d*[A-D]', '', text)
        # Remove "> " prefix kiro adds to responses
        text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
        # Remove tool execution artifacts
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('Creating:') or line.startswith('- Completed in'):
                continue
            if 'hooks finished' in line:
                continue
            lines.append(line)
        result = '\n'.join(lines).strip()
        return self.strip_markdown(result)

    @staticmethod
    def _extract_session_id(stderr: str, cwd: str) -> Optional[str]:
        """Try to extract session ID. Kiro doesn't return it directly;
        we get the most recent from --list-sessions after the run."""
        # For now, return None — daemon will use "auto" for --resume
        # which picks the most recent session in the directory
        return None

    @staticmethod
    def _extract_error(stderr: str) -> str:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', stderr)
        for line in clean.splitlines():
            if line.strip().startswith("error:"):
                return line.strip()
        return ""
