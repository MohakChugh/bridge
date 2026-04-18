"""Parse iMessage text: prefix routing and attributedBody extraction."""

KNOWN_ALIASES = {"centralis", "frontend", "nexus", "home", "default"}


def parse_prefix(text: str) -> dict | None:
    """Parse message text into routing action.

    Returns:
        None if text is empty/whitespace
        {"action": "inject", "prompt": str, "directory_alias": None}
        {"action": "spawn", "prompt": str, "directory_alias": str}
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()
    lower = stripped.lower()

    if not lower.startswith("new:"):
        return {"action": "inject", "prompt": stripped, "directory_alias": None}

    remainder = stripped[4:].strip()

    colon_pos = remainder.find(":")
    if colon_pos > 0:
        candidate = remainder[:colon_pos].strip().lower()
        if candidate in KNOWN_ALIASES:
            prompt = remainder[colon_pos + 1:].strip()
            return {"action": "spawn", "prompt": prompt, "directory_alias": candidate}

    return {"action": "spawn", "prompt": remainder, "directory_alias": "default"}


def parse_attributed_body(blob: bytes | None) -> str | None:
    """Extract plain text from NSAttributedString binary blob.

    macOS Ventura+ stores message text in attributedBody when the text column
    is NULL. The blob is a typedstream containing an NSAttributedString.
    """
    if not blob:
        return None

    buf = bytes(blob) if not isinstance(blob, bytes) else blob
    marker = b"NSString"
    idx = buf.find(marker)
    if idx < 0:
        return None

    idx += len(marker)
    while idx < len(buf) and buf[idx] != 0x2B:
        idx += 1
    if idx >= len(buf):
        return None
    idx += 1

    if idx >= len(buf):
        return None
    b = buf[idx]
    idx += 1

    if b == 0x81:
        if idx >= len(buf):
            return None
        length = buf[idx]
        idx += 1
    elif b == 0x82:
        if idx + 1 >= len(buf):
            return None
        length = int.from_bytes(buf[idx:idx + 2], "little")
        idx += 2
    elif b == 0x83:
        if idx + 2 >= len(buf):
            return None
        length = int.from_bytes(buf[idx:idx + 3], "little")
        idx += 3
    else:
        length = b

    if idx + length > len(buf):
        return None

    return buf[idx:idx + length].decode("utf-8", errors="replace")
