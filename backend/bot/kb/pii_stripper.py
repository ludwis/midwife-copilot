"""PII stripping module.

strip_pii(text: str) -> tuple[str, bool]

  Pass 1 — spaCy NER (model: xx_ent_wiki_sm, loaded once):
    PERSON → [IMIĘ],  LOC → [ADRES],  ORG → [FIRMA]

  Pass 2 — regex (per research.md §3):
    phone      → [TELEFON]
    email      → [EMAIL]
    PESEL      → [PESEL]
    NIP        → [NIP]

  Post-strip rescan: if any digit sequence >6 digits remains → flag=True.

  Returns (stripped_text, needs_review_flag).
"""
from __future__ import annotations

import re

try:
    import spacy

    _nlp = spacy.load("xx_ent_wiki_sm")
except (ImportError, OSError):
    _nlp = None  # type: ignore[assignment]

# NER label → Polish placeholder
_NER_MAP: dict[str, str] = {
    "PERSON": "[IMIĘ]",
    "LOC": "[ADRES]",
    "ORG": "[FIRMA]",
}

# Regex patterns for structured PII (applied after NER, per research.md §3)
_PHONE_RE = re.compile(
    r"(\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}"
)
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
_PESEL_RE = re.compile(r"\b\d{11}\b")
_NIP_RE = re.compile(r"\b\d{3}-\d{3}-\d{2}-\d{2}\b|\b\d{10}\b")

# Post-strip rescan: flag if any digit sequence longer than 6 digits remains
_LONG_DIGIT_RE = re.compile(r"\d{7,}")


def strip_pii(text: str) -> tuple[str, bool]:
    """Strip PII from *text* and return ``(stripped_text, needs_review)``."""
    # Pass 1 — spaCy NER; replace spans in reverse order to preserve offsets
    doc = _nlp(text)
    result = text
    for ent in sorted(doc.ents, key=lambda e: e.start_char, reverse=True):
        placeholder = _NER_MAP.get(ent.label_)
        if placeholder:
            result = result[: ent.start_char] + placeholder + result[ent.end_char :]

    # Pass 2 — regex patterns for structured identifiers.
    # PESEL (11 digits) and NIP (10 digits) are applied first so the phone
    # regex does not consume digit sequences that should become [PESEL]/[NIP].
    result = _PESEL_RE.sub("[PESEL]", result)
    result = _NIP_RE.sub("[NIP]", result)
    result = _PHONE_RE.sub("[TELEFON]", result)
    result = _EMAIL_RE.sub("[EMAIL]", result)

    # Post-strip rescan: flag remaining digit sequences longer than 6 digits
    flag = bool(_LONG_DIGIT_RE.search(result))

    return result, flag
