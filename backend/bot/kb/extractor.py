"""Gemini 2.0 Flash Q&A extractor for KB knowledge pairs.

extract_qa_pairs(turns: list[dict]) -> list[ChunkDraft]:
  - Batches conversation turns into windows of 50 with 10-turn overlap when the
    estimated token count exceeds 8,000 tokens.
  - Calls Gemini 2.0 Flash with a constrained JSON-output extraction prompt
    (research.md §4).
  - Parses the response as list[ChunkDraft] via Pydantic.
  - Retries up to 2× on ValidationError or JSONDecodeError.
  - Returns a flat list of ChunkDraft objects (empty list = no_pairs_found).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini model configuration
# ---------------------------------------------------------------------------

# Override via GEMINI_MODEL env var if needed; default to Gemini 2.0 Flash.
import os

GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# Estimated average characters per token (conservative; covers Polish text).
_CHARS_PER_TOKEN: int = 4

# Batch window parameters (research.md §4).
_WINDOW_SIZE: int = 50   # turns per batch
_OVERLAP: int = 10       # overlap between consecutive windows
_TOKEN_THRESHOLD: int = 8_000  # switch to windowed batching above this limit

# Extraction prompt (verbatim from research.md §4).
_EXTRACTION_PROMPT = """\
You are processing a chat conversation between a midwife and a client.
The conversation has been stripped of personal identifiers.

Your task: extract discrete question-and-answer knowledge pairs that represent \
general midwifery knowledge — advice, explanations, and guidance that would be \
useful to answer similar questions from other clients.

Rules:
- Include only exchanges where the client asks a substantive question and the \
midwife provides a substantive answer.
- Do NOT include scheduling, administrative, or purely social exchanges.
- Each pair must be standalone — no references to "you" (client-specific context).
- Detect the primary language of each pair and include it as an ISO 639-1 code \
(e.g. "pl" for Polish, "en" for English).
- Output as a JSON array of objects: {{"question": "...", "answer": "...", "language": "..."}}
- If no qualifying pairs exist, output: []

Conversation:
{conversation_turns}"""

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class ChunkDraft(BaseModel):
    """A single extracted Q&A pair before staging."""

    question: str
    answer: str
    language: str = "unknown"  # ISO 639-1 code detected by Gemini (e.g. "pl", "en")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_turns(turns: list[dict[str, Any]]) -> str:
    """Convert parsed message dicts to a plain-text conversation string."""
    lines: list[str] = []
    for t in turns:
        sender = t.get("sender", "Unknown")
        content = t.get("content", "")
        lines.append(f"{sender}: {content}")
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _build_windows(turns: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Slice *turns* into overlapping windows of _WINDOW_SIZE with _OVERLAP."""
    if not turns:
        return []
    windows: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(turns):
        end = start + _WINDOW_SIZE
        windows.append(turns[start:end])
        if end >= len(turns):
            break
        start = end - _OVERLAP
    return windows


def _call_gemini(prompt: str) -> str:
    """Call Gemini via the google-genai SDK and return the raw text response."""
    from google import genai  # type: ignore[import]
    from google.genai import types  # type: ignore[import]

    project = os.environ.get("GCP_PROJECT_ID", "")
    client = genai.Client(vertexai=True, project=project, location="global")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return response.text


def _parse_response(raw: str) -> list[ChunkDraft]:
    """Parse a raw Gemini response string into validated ChunkDraft objects.

    Raises JSONDecodeError or ValidationError on bad output — the caller
    handles retries.
    """
    # Strip markdown code fences if Gemini wraps the JSON in them.
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.IGNORECASE)

    data = json.loads(cleaned)

    # Validate each item; raises ValidationError if schema is wrong.
    from pydantic import TypeAdapter

    adapter = TypeAdapter(list[ChunkDraft])
    return adapter.validate_python(data)


def _extract_from_turns(
    turns: list[dict[str, Any]],
    *,
    max_retries: int = 2,
) -> list[ChunkDraft]:
    """Run the extraction prompt for one batch of turns; retry on parse failure."""
    conversation_text = _format_turns(turns)
    prompt = _EXTRACTION_PROMPT.format(conversation_turns=conversation_text)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = _call_gemini(prompt)
            return _parse_response(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_exc = exc
            logger.warning(
                "Gemini response parse failure (attempt %d/%d): %s",
                attempt + 1,
                max_retries + 1,
                exc,
            )

    logger.error(
        "Gemini extraction failed after %d attempts: %s", max_retries + 1, last_exc
    )
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_qa_pairs(turns: list[dict[str, Any]]) -> list[ChunkDraft]:
    """Extract Q&A pairs from *turns* using Gemini 2.0 Flash.

    Parameters
    ----------
    turns:
        Output from a WhatsApp or Messenger parser — each dict has at minimum
        ``sender`` and ``content`` keys.

    Returns
    -------
    list[ChunkDraft]
        Validated question/answer pairs ready for PII stripping and staging.
        An empty list means no qualifying pairs were found (``no_pairs_found``).
    """
    if not turns:
        return []

    conversation_text = _format_turns(turns)
    token_estimate = _estimate_tokens(conversation_text)

    if token_estimate <= _TOKEN_THRESHOLD:
        batches = [turns]
    else:
        batches = _build_windows(turns)

    results: list[ChunkDraft] = []
    seen: set[tuple[str, str]] = set()

    for batch in batches:
        for draft in _extract_from_turns(batch):
            key = (draft.question.strip(), draft.answer.strip())
            if key not in seen:
                seen.add(key)
                results.append(draft)

    return results
