"""Messenger .json export parser."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_messenger(file_paths: list[str | Path]) -> list[dict[str, Any]]:
    """Parse one or more Messenger message_N.json export files.

    Accepts a list of paths to ``message_N.json`` files from Facebook's
    "Download Your Information" tool.  Multiple files for the same
    conversation are merged by deduplicating on
    ``(sender_name, timestamp_ms, content)`` and sorting ascending by
    ``timestamp_ms``.

    Returns a list of dicts with keys:
        timestamp (str)  — ISO-8601 UTC
        sender    (str)  — sender display name
        content   (str)  — message text

    Entries without a ``content`` field (photos, stickers, reactions) are
    skipped.
    """
    seen: set[tuple[str, int, str]] = set()
    messages: list[dict[str, Any]] = []

    for path in file_paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for msg in data.get("messages", []):
            if "content" not in msg:
                continue
            sender = msg["sender_name"]
            ts_ms: int = msg["timestamp_ms"]
            content: str = msg["content"]
            key = (sender, ts_ms, content)
            if key in seen:
                continue
            seen.add(key)
            ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            messages.append({"timestamp": ts_iso, "sender": sender, "content": content})

    messages.sort(key=lambda m: m["timestamp"])
    return messages
