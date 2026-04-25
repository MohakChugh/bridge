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


def parse_with_llm(prompt: str, config: dict, timeout: int = 180) -> Optional[str]:
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
        # Override config to disable caveman mode for parsing — we need clean JSON output
        parse_config = dict(config)
        parse_config["_parsing_mode"] = True

        result = adapter.spawn(
            prompt=prompt,
            cwd="/tmp",
            timeout=timeout,
            config=parse_config,
        )
        if result.get("success") and result.get("output"):
            return result["output"]
        log.warning(f"LLM parse failed with {tool}: {result.get('error', 'no output')}")
        return None
    except Exception as e:
        log.warning(f"LLM parse error with {tool}: {e}")
        return None


def parse_json_with_llm(prompt: str, config: dict, timeout: int = 180) -> Optional[dict]:
    """Send prompt and extract JSON from response.

    Handles tools that don't support --output-format json by extracting
    the first JSON object from text output. Retries once with stronger
    JSON instruction if first attempt fails.
    """
    # Ensure prompt emphasizes JSON-only output
    if "Reply ONLY with" not in prompt and "ONLY with valid JSON" not in prompt:
        prompt = prompt.rstrip() + "\n\nIMPORTANT: Reply with ONLY valid JSON. No explanations, no markdown, no text before or after the JSON."

    raw = parse_with_llm(prompt, config, timeout=timeout)
    if not raw:
        return None

    result = extract_json(raw)
    if result:
        return result

    # Retry with stronger instruction
    log.info("JSON extraction failed on first attempt, retrying with stronger prompt")
    retry_prompt = (
        "Your previous response was not valid JSON. "
        "Reply with ONLY a JSON object. No text, no explanation, no code blocks. "
        "Just the raw JSON starting with { and ending with }.\n\n"
        + prompt
    )
    raw2 = parse_with_llm(retry_prompt, config, timeout=timeout)
    if raw2:
        return extract_json(raw2)
    return None


def extract_json(text: str) -> Optional[dict]:
    """Extract first JSON object from text — bulletproof across all tools.

    Handles:
    - Direct JSON string
    - Claude {"result": "..."} wrapper
    - JSON buried in text/prose
    - JSON inside markdown code blocks (```json ... ```)
    - JSON with leading/trailing whitespace and newlines
    - Multiple JSON objects (returns first valid one)
    - Escaped quotes in text surrounding JSON
    """
    if not text:
        return None

    text = text.strip()

    # 1. Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], str):
                inner = extract_json(data["result"])
                if inner:
                    return inner
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Strip markdown code blocks: ```json ... ``` or ``` ... ```
    import re
    code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if code_block:
        try:
            data = json.loads(code_block.group(1).strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Find all { ... } candidates and try each (handles noise before/after)
    candidates = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
                start = -1

    # Try longest candidate first (most likely to be the full JSON)
    for candidate in sorted(candidates, key=len, reverse=True):
        # Try as-is first
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Fix common LLM JSON issues: literal newlines in strings, trailing commas
        cleaned = candidate.replace("\n", " ").replace("\r", " ")
        cleaned = re.sub(r',\s*}', '}', cleaned)  # trailing comma
        cleaned = re.sub(r',\s*]', ']', cleaned)  # trailing comma in arrays
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            continue

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
