"""Generic LLM parser — routes through adapter system instead of direct claude -p.

Replaces all hardcoded `claude -p` calls for structured parsing (reminders,
schedules, watches, workflow generation). Works with ANY registered adapter.

Uses config["parsing_tool"] to determine which tool handles parsing.
Falls back to config["cli_tool"], then first available adapter.
"""

from __future__ import annotations
import json
import logging
from typing import Optional

log = logging.getLogger("llm_parser")


def parse_with_llm(prompt: str, config: dict, timeout: int = 120) -> Optional[str]:
    """Send prompt to the configured parsing tool and return raw output.

    Routes through the adapter system — works with claude, wasabi, kiro,
    or any future adapter.
    """
    from adapters import get_adapter, list_adapters

    tool = _resolve_parsing_tool(config)
    if not tool:
        log.warning("No parsing tool available")
        return None

    try:
        adapter = get_adapter(tool)
    except KeyError:
        log.warning(f"Parsing tool '{tool}' not registered")
        return None

    try:
        result = adapter.spawn(
            prompt=prompt,
            cwd="/tmp",
            timeout=timeout,
            config=config,
        )
        if result.get("success") and result.get("output"):
            return result["output"]
        log.warning(f"LLM parse failed with {tool}: {result.get('error', 'no output')}")
        return None
    except Exception as e:
        log.warning(f"LLM parse error with {tool}: {e}")
        return None


def parse_json_with_llm(prompt: str, config: dict, timeout: int = 120) -> Optional[dict]:
    """Send prompt and extract JSON from response.

    Handles tools that don't support --output-format json by extracting
    the first JSON object from text output.
    """
    raw = parse_with_llm(prompt, config, timeout=timeout)
    if not raw:
        return None
    return extract_json(raw)


def extract_json(text: str) -> Optional[dict]:
    """Extract first JSON object from text. Handles wrapped JSON."""
    if not text:
        return None

    # Try direct parse first (Claude with --output-format json)
    try:
        data = json.loads(text.strip())
        if isinstance(data, dict):
            # Claude wraps in {"result": "..."} — unwrap
            if "result" in data and isinstance(data["result"], str):
                inner = extract_json(data["result"])
                if inner:
                    return inner
            return data
    except json.JSONDecodeError:
        pass

    # Find first { ... } in text (wasabi/kiro text output)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _resolve_parsing_tool(config: dict) -> Optional[str]:
    """Determine which tool to use for LLM parsing."""
    from adapters import list_adapters

    # 1. Explicit parsing_tool config
    tool = config.get("parsing_tool")
    if tool:
        return tool

    # 2. Fall back to cli_tool
    tool = config.get("cli_tool")
    if tool:
        return tool

    # 3. First available adapter
    available = list_adapters()
    return available[0] if available else None
