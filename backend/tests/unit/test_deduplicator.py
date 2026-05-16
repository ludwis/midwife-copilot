"""Unit tests for the near-duplicate detector.

TDD: These tests are written before the implementation (T030).
They define the contract that ``check_duplicate`` must satisfy.

check_duplicate(question, chunk_id, existing_hashes) -> DedupResult:
  Pass 1: SHA-256 of normalized question (lower, collapsed whitespace).
          If hash found in existing_hashes → DedupResult(flag="exact",
          duplicate_of_chunk_id=<the matched chunk's id>).
  Pass 2: Vertex AI embedding cosine similarity vs _embedding_cache.
          If max similarity > 0.90 → DedupResult(flag="near",
          similarity=<score>, duplicate_of_chunk_id=<matched chunk_id>).
  Else: DedupResult(flag=None).

Interface note — existing_hashes parameter
------------------------------------------
T030 specifies ``existing_hashes: set[str]``, but the T024 requirement
("correct ``duplicate_of_chunk_id``") implies a hash → chunk_id mapping so
the caller can know *which* chunk is the duplicate.  This test file defines
``existing_hashes`` as ``dict[str, str]`` (content_hash → chunk_id).  T030
must reconcile this when implementing.

Embedding mock strategy
-----------------------
Tests that exercise pass 2 patch ``bot.kb.deduplicator._get_embedding`` to
return a pre-computed unit vector and directly set
``bot.kb.deduplicator._embedding_cache`` with a known cached vector.

Two-element unit vectors are used so cosine similarity can be computed
analytically:
  cached vector  : [1.0, 0.0]
  sim ≈ 0.95 vec : [0.95,  0.31225]   (cos θ ≈ 0.95,  sin θ ≈ 0.31225)
  sim ≈ 0.85 vec : [0.85,  0.52678]   (cos θ ≈ 0.85,  sin θ ≈ 0.52678)

SHA-256 normalisation
---------------------
Pass 1 normalises the question with ``.lower()`` + collapse whitespace before
hashing.  Tests pre-compute the expected hash to verify the implementation
uses the correct normalisation.

Coverage
--------
- Same SHA-256 hash as existing chunk → ``exact`` flag + correct
  ``duplicate_of_chunk_id``
- Mocked embedding cosine similarity 0.95 → ``near`` flag
- Mocked cosine similarity 0.85 → no flag (below 0.90 threshold)
- Empty cache → no flags for any input
"""
from __future__ import annotations

import hashlib
import re
from unittest.mock import patch

import pytest

from bot.kb.deduplicator import DedupResult, check_duplicate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Mirror the normalisation that pass 1 must apply before hashing."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# Two-element unit vectors for analytic cosine similarity control.
_CACHED_VEC = [1.0, 0.0]
_SIM_095_VEC = [0.95, 0.31225]   # cosine([1,0], this) ≈ 0.95
_SIM_085_VEC = [0.85, 0.52678]   # cosine([1,0], this) ≈ 0.85

_EXISTING_CHUNK_ID = "chunk_existing_001"
_NEW_CHUNK_ID = "chunk_new_002"
_QUESTION = "Czy ból w okolicy miednicy jest normalny w 36. tygodniu?"


# ---------------------------------------------------------------------------
# Pass 1 — exact hash match
# ---------------------------------------------------------------------------

class TestExactDuplicate:
    """Same SHA-256 hash must yield flag='exact' with the correct chunk_id."""

    def test_exact_match_sets_exact_flag(self):
        """When the normalized question hash is in existing_hashes, flag must be 'exact'."""
        content_hash = _sha256(_normalise(_QUESTION))
        existing_hashes = {content_hash: _EXISTING_CHUNK_ID}

        with patch("bot.kb.deduplicator._get_embedding") as mock_embed:
            # Embedding must NOT be called when exact match is found in pass 1.
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, existing_hashes)

        assert result.flag == "exact"

    def test_exact_match_returns_correct_duplicate_of_chunk_id(self):
        """duplicate_of_chunk_id must identify the previously staged matching chunk."""
        content_hash = _sha256(_normalise(_QUESTION))
        existing_hashes = {content_hash: _EXISTING_CHUNK_ID}

        with patch("bot.kb.deduplicator._get_embedding"):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, existing_hashes)

        assert result.duplicate_of_chunk_id == _EXISTING_CHUNK_ID

    def test_exact_match_normalises_case_and_whitespace(self):
        """Normalisation (lower + collapse whitespace) must apply before hashing."""
        # Compute hash of the normalised canonical form.
        canonical = "czy ból w okolicy miednicy jest normalny w 36. tygodniu?"
        content_hash = _sha256(canonical)
        existing_hashes = {content_hash: _EXISTING_CHUNK_ID}

        # Supply equivalent question with different case and extra spaces.
        question_variant = "Czy  BÓL  w okolicy miednicy jest normalny w 36. tygodniu?"

        with patch("bot.kb.deduplicator._get_embedding"):
            result = check_duplicate(question_variant, _NEW_CHUNK_ID, existing_hashes)

        assert result.flag == "exact"

    def test_exact_match_does_not_call_embedding_api(self):
        """Pass 1 must short-circuit — no embedding call when exact match found."""
        content_hash = _sha256(_normalise(_QUESTION))
        existing_hashes = {content_hash: _EXISTING_CHUNK_ID}

        with patch("bot.kb.deduplicator._get_embedding") as mock_embed:
            check_duplicate(_QUESTION, _NEW_CHUNK_ID, existing_hashes)

        mock_embed.assert_not_called()


# ---------------------------------------------------------------------------
# Pass 2 — near-duplicate via cosine similarity
# ---------------------------------------------------------------------------

class TestNearDuplicate:
    """Cosine similarity above 0.90 must yield flag='near'."""

    def test_high_similarity_sets_near_flag(self):
        """When cosine similarity is 0.95 (> 0.90 threshold), flag must be 'near'."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_095_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.flag == "near"

    def test_high_similarity_returns_correct_chunk_id(self):
        """duplicate_of_chunk_id must be the cache key with the highest similarity."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_095_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.duplicate_of_chunk_id == _EXISTING_CHUNK_ID

    def test_high_similarity_populates_similarity_score(self):
        """similarity_score must be set and be greater than 0.90 on a near match."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_095_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.similarity_score is not None
        assert result.similarity_score > 0.90


# ---------------------------------------------------------------------------
# Pass 2 — below similarity threshold → no flag
# ---------------------------------------------------------------------------

class TestBelowThreshold:
    """Cosine similarity of 0.85 is below the 0.90 threshold; flag must be None."""

    def test_low_similarity_returns_no_flag(self):
        """Similarity of 0.85 must not trigger the near-duplicate flag."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_085_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.flag is None

    def test_low_similarity_chunk_id_is_none(self):
        """No duplicate_of_chunk_id when below threshold."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_085_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.duplicate_of_chunk_id is None

    def test_low_similarity_similarity_score_is_none(self):
        """similarity_score must not be populated when there is no near match."""
        cache = {_EXISTING_CHUNK_ID: _CACHED_VEC}

        with (
            patch("bot.kb.deduplicator._embedding_cache", cache),
            patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_085_VEC),
        ):
            result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.similarity_score is None


# ---------------------------------------------------------------------------
# Empty cache — no false positives
# ---------------------------------------------------------------------------

class TestEmptyCache:
    """With no existing chunks, check_duplicate must always return flag=None."""

    def test_empty_existing_hashes_returns_no_flag(self):
        """No exact-match flag when existing_hashes is empty."""
        with patch("bot.kb.deduplicator._embedding_cache", {}):
            with patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_095_VEC):
                result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.flag is None

    def test_empty_cache_no_duplicate_chunk_id(self):
        """No duplicate_of_chunk_id when cache is empty."""
        with patch("bot.kb.deduplicator._embedding_cache", {}):
            with patch("bot.kb.deduplicator._get_embedding", return_value=_SIM_095_VEC):
                result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert result.duplicate_of_chunk_id is None

    def test_empty_cache_return_type_is_dedup_result(self):
        """check_duplicate must always return a DedupResult instance."""
        with patch("bot.kb.deduplicator._embedding_cache", {}):
            with patch("bot.kb.deduplicator._get_embedding", return_value=[1.0, 0.0]):
                result = check_duplicate(_QUESTION, _NEW_CHUNK_ID, {})

        assert isinstance(result, DedupResult)
