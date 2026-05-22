"""Near-duplicate detector for KB chunks.

check_duplicate(question, chunk_id, existing_hashes) -> DedupResult:
  Pass 1: SHA-256 of normalized question (lower, collapsed whitespace);
          if hash in existing_hashes → DedupResult(flag="exact", duplicate_of_chunk_id=...)
  Pass 2: Vertex AI textembedding-gecko-multilingual@001 cosine similarity;
          if max similarity > 0.90 → DedupResult(flag="near", ...)
  Else:   DedupResult(flag=None)

GCS cache is loaded at module import from
  gs://midwife-bot-audit-{STILLA_ENV}/embeddings/cache.jsonl
where each line is {"chunk_id": "...", "embedding": [...]}.
If the bucket is unreachable (e.g. in tests), the cache starts empty.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level embedding cache: chunk_id → embedding vector.
# Loaded from GCS at startup; empty dict if GCS is unavailable.
# ---------------------------------------------------------------------------
_embedding_cache: dict[str, list[float]] = {}


def _load_gcs_cache() -> None:
    """Populate _embedding_cache from GCS JSONL file (best-effort)."""
    env = os.environ.get("STILLA_ENV", "dev")
    bucket = f"midwife-bot-audit-{env}"
    blob_path = "embeddings/cache.jsonl"

    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        bucket_obj = client.bucket(bucket)
        blob = bucket_obj.blob(blob_path)
        content = blob.download_as_text()
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            chunk_id = entry["chunk_id"]
            embedding = entry["embedding"]
            _embedding_cache[chunk_id] = embedding
        logger.info("Loaded %d embeddings from gs://%s/%s", len(_embedding_cache), bucket, blob_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("GCS embedding cache not loaded (%s); starting empty.", exc)


_load_gcs_cache()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DedupResult:
    """Result returned by check_duplicate."""

    flag: Optional[str]  # "exact", "near", or None
    duplicate_of_chunk_id: Optional[str] = None
    similarity_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace before hashing."""
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (returns 0.0 if either is zero-length)."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _get_embedding(text: str) -> list[float]:
    """Return a Vertex AI embedding for *text*.

    Uses textembedding-gecko-multilingual@001 in the eu region.
    """
    from vertexai.language_models import TextEmbeddingModel  # type: ignore

    model = TextEmbeddingModel.from_pretrained("textembedding-gecko-multilingual@001")
    embeddings = model.get_embeddings([text])
    return embeddings[0].values


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_NEAR_DUP_THRESHOLD = 0.90


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
    # Pass 1 — exact hash match (no embedding call).
    norm_hash = _sha256(_normalise(question))
    if norm_hash in existing_hashes:
        return DedupResult(
            flag="exact",
            duplicate_of_chunk_id=existing_hashes[norm_hash],
        )

    # Pass 2 — near-duplicate via cosine similarity.
    if _embedding_cache:
        embedding = _get_embedding(question)
        best_sim = 0.0
        best_id: Optional[str] = None
        for cached_id, cached_vec in _embedding_cache.items():
            if cached_id == chunk_id:
                continue
            sim = _cosine(embedding, cached_vec)
            if sim > best_sim:
                best_sim = sim
                best_id = cached_id

        if best_id is not None and best_sim > _NEAR_DUP_THRESHOLD:
            return DedupResult(
                flag="near",
                duplicate_of_chunk_id=best_id,
                similarity_score=best_sim,
            )

    return DedupResult(flag=None)
