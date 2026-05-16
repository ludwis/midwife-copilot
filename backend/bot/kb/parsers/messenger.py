"""Messenger .json export parser — stub (T027 will implement this)."""
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

    Raises:
        NotImplementedError: T027 not yet implemented.
    """
    raise NotImplementedError("T027 not yet implemented")
