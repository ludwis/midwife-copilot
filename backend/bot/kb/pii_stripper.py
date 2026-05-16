"""PII stripping module — stub awaiting T028 implementation.

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

# Module-level NLP model reference.
# Real implementation (T028) loads spacy.load("xx_ent_wiki_sm") here.
# Tests mock this variable via @patch("bot.kb.pii_stripper._nlp").
_nlp = None


def strip_pii(text: str) -> tuple[str, bool]:
    """Strip PII from *text* and return ``(stripped_text, needs_review)``.

    Stub: raises NotImplementedError until T028.
    """
    raise NotImplementedError("strip_pii not yet implemented — awaiting T028")
