"""Near-duplicate detector for KB chunks.

Implementation stub — see T030 for full implementation details.

check_duplicate(question, chunk_id, existing_hashes) -> DedupResult:
  Pass 1: SHA-256 of normalized question (lower, collapsed whitespace);
          if hash in existing_hashes → DedupResult(flag="exact", duplicate_of_chunk_id=...)
  Pass 2: Vertex AI textembedding-gecko-multilingual@001 cosine similarity;
          if max similarity > 0.90 → DedupResult(flag="near", ...)
  Else:   DedupResult(flag=None)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Module-level embedding cache: chunk_id → embedding vector.
# Loaded from GCS at startup (T030). Empty dict until implemented.
_embedding_cache: dict[str, list[float]] = {}


@dataclass
class DedupResult:
    """Result returned by check_duplicate."""

    flag: Optional[str]  # "exact", "near", or None
    duplicate_of_chunk_id: Optional[str] = None
    similarity_score: Optional[float] = None


def _get_embedding(text: str) -> list[float]:  # pragma: no cover
    """Return a Vertex AI embedding for *text*. Stub — raises until T030."""
    raise NotImplementedError("_get_embedding not yet implemented (T030)")


def check_duplicate(
    question: str,
    chunk_id: str,
    existing_hashes: dict[str, str],
) -> DedupResult:
    """Check whether *question* is an exact or near-duplicate of an existing chunk.

    Parameters
    ----------
    question:
        The question text to check (after PII stripping).
    chunk_id:
        The candidate chunk's own ID (used to skip self-comparison in cache).
    existing_hashes:
        Mapping of ``{content_hash: chunk_id}`` for all previously staged
        chunks.  Used for exact-match detection in pass 1.

    Returns
    -------
    DedupResult
        ``flag="exact"`` if the normalised hash is already present,
        ``flag="near"`` if cosine similarity > 0.90,
        ``flag=None`` otherwise.
    """
    raise NotImplementedError("check_duplicate not yet implemented (T030)")
