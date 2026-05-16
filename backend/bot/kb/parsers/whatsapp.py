"""WhatsApp .txt export parser."""
import re
from typing import Any

# Handles two common WhatsApp export formats:
#   English/US:  12/31/2024, 20:07 - Sender: content
#   Polish/EU:   [31.12.2024, 20:07:02] Sender: content  (no dash, brackets present)
WHATSAPP_LINE_RE = re.compile(
    r"^\[?(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}),?\s(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s(?:[-–]\s)?(.+?):\s(.+)$"
)

# Matches lines that start with a timestamp prefix (but may not be full messages).
# Used to detect system-message lines that lack the "Sender: content" structure.
_TIMESTAMP_PREFIX_RE = re.compile(r"^\[?\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}")

# U+200E LEFT-TO-RIGHT MARK — WhatsApp prefixes system messages with this character
# in many locales (visible as ‎ in text editors).
_LTR_MARK = "\u200e"

# Known system message prefixes — exact matches or prefixes.
_SYSTEM_PREFIXES = (
    "Messages and calls are end-to-end encrypted",
    "You deleted this message",
    "This message was deleted",
    "Missed voice call",
    "Missed video call",
    # Polish locale system messages
    "Wiadomości i połączenia są w pełni zaszyfrowane",
    "Twoja wiadomość została usunięta",
    "Ta wiadomość została usunięta",
    "Nieodebrane połączenie głosowe",
    "Nieodebrane połączenie wideo",
)


def parse_whatsapp(text: str) -> list[dict[str, Any]]:
    """Parse a WhatsApp .txt export into a list of message dicts.

    Each dict has keys: ``timestamp``, ``sender``, ``content``.
    System messages are filtered out. Multi-line messages are merged.
    """
    if not text.strip():
        return []

    messages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in text.splitlines():
        m = WHATSAPP_LINE_RE.match(line)
        if m:
            date_str, time_str, sender, content = m.groups()
            # Strip leading LTR mark (U+200E) that WhatsApp prepends to system messages.
            content_stripped = content.lstrip(_LTR_MARK)
            # Filter messages whose content begins with a known system prefix.
            if any(content_stripped.startswith(prefix) for prefix in _SYSTEM_PREFIXES):
                if current is not None:
                    messages.append(current)
                    current = None
                continue
            if current is not None:
                messages.append(current)
            current = {
                "timestamp": f"{date_str} {time_str}",
                "sender": sender,
                "content": content_stripped,
            }
        elif _TIMESTAMP_PREFIX_RE.match(line):
            # Line has a timestamp prefix but no "Sender: content" structure —
            # it is a system-message line. Save the current message and skip.
            if current is not None:
                messages.append(current)
                current = None
        else:
            # Continuation line: append to the current message's content.
            if current is not None:
                current["content"] = current["content"] + "\n" + line

    if current is not None:
        messages.append(current)

    return messages
