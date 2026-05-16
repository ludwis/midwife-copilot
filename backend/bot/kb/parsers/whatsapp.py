"""WhatsApp .txt export parser — stub (T026 will implement this)."""
import re
from typing import Any

WHATSAPP_LINE_RE = re.compile(
    r"^\[?(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}),?\s(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s[-–]\s(.+?):\s(.+)$"
)

# Known system message prefixes — exact matches or prefixes.
_SYSTEM_PREFIXES = (
    "Messages and calls are end-to-end encrypted",
    "You deleted this message",
    "This message was deleted",
    "Missed voice call",
    "Missed video call",
)


def parse_whatsapp(text: str) -> list[dict[str, Any]]:  # noqa: D103
    raise NotImplementedError("T026 not yet implemented")
