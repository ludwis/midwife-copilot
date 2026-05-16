"""INTEGRATION=true-gated Vertex AI Search tests (T049).

Tests real Discovery Engine API calls against a live GCP dev project.
All tests are skipped unless ``INTEGRATION=true`` is set in the environment.

Required env vars (when INTEGRATION=true):
    GOOGLE_CLOUD_PROJECT          — GCP project ID (dev project)
    VERTEX_STAGING_DATA_STORE     — Discovery Engine staging data store ID
                                    (defaults to 'midwife-staging')
    VERTEX_PRODUCTION_DATA_STORE  — Discovery Engine production data store ID
                                    (defaults to 'midwife-production')
    VERTEX_LOCATION               — Discovery Engine location (defaults to 'eu')

What the tests verify:
    1. Staging ingest + retrieval: a document can be created in the staging data
       store and retrieved by ID; the schema matches data-model.md.
    2. Production ingest + retrieval: a document can be created in the production
       data store and retrieved by ID; the schema matches data-model.md.
    3. Document schema completeness: all required structData fields (per
       data-model.md §Vertex AI Search Documents) are present and correct.

Why get_document() instead of search(): the Search API indexes asynchronously
after ingestion; get_document() is synchronous and tests ingestion correctness
without introducing a nondeterministic wait.  The document-ID contract
(chunk_id == Vertex AI document ID) is the referential guarantee that matters
for the Phase 2 RAG pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import pytest

# ---------------------------------------------------------------------------
# Module-level skip guard — all tests in this file require INTEGRATION=true
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION") != "true",
    reason="Skipped: set INTEGRATION=true to run against real GCP dev project",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed test document — distinct enough to avoid collisions with real data.
_TEST_CHUNK_ID = "test-vertex-search-t049"
_TEST_QUESTION = "Is pelvic pressure normal at 36 weeks? (T049 integration test)"
_TEST_ANSWER = "Yes, pelvic pressure is common in the third trimester. (T049 test)"
_TEST_IMPORT_ID = "test-import-t049"
_TEST_STAGED_AT = "2026-05-16"
_TEST_PROMOTED_AT = "2026-05-16"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_hash(question: str, answer: str) -> str:
    """SHA-256 of question + newline + answer — per data-model.md §kb_chunks."""
    return hashlib.sha256((question + "\n" + answer).encode()).hexdigest()


def _get_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _client_options():  # type: ignore[return]
    """Return ClientOptions with regional endpoint for non-global Discovery Engine locations."""
    from google.api_core.client_options import ClientOptions  # type: ignore[import]

    location = _get_env("VERTEX_LOCATION", "eu")
    if location and location != "global":
        return ClientOptions(api_endpoint=f"{location}-discoveryengine.googleapis.com")
    return None


def _staging_branch_path() -> str:
    project = _get_env("GOOGLE_CLOUD_PROJECT", "")
    location = _get_env("VERTEX_LOCATION", "eu")
    data_store = _get_env("VERTEX_STAGING_DATA_STORE", "midwife-staging")
    return (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection"
        f"/dataStores/{data_store}/branches/default_branch"
    )


def _production_branch_path() -> str:
    project = _get_env("GOOGLE_CLOUD_PROJECT", "")
    location = _get_env("VERTEX_LOCATION", "eu")
    data_store = _get_env("VERTEX_PRODUCTION_DATA_STORE", "midwife-production")
    return (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection"
        f"/dataStores/{data_store}/branches/default_branch"
    )


def _document_name(branch_path: str, doc_id: str) -> str:
    return f"{branch_path}/documents/{doc_id}"


async def _create_staging_document(
    chunk_id: str,
    question: str,
    answer: str,
    import_id: str,
    content_hash: str,
    staged_at: str,
) -> None:
    """Write a document to the Vertex AI staging data store.

    Schema matches data-model.md §Vertex AI Search Documents (staging fields).
    """
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]
    from google.protobuf import struct_pb2  # type: ignore[import]

    parent = _staging_branch_path()
    text_content = f"Q: {question}\nA: {answer}"

    struct_data = struct_pb2.Struct()
    struct_data.update(
        {
            "question": question,
            "answer": answer,
            "source_type": "export",
            "import_id": import_id,
            "content_hash": content_hash,
            "staged_at": staged_at,
        }
    )

    client = discoveryengine.DocumentServiceAsyncClient(client_options=_client_options())
    request = discoveryengine.CreateDocumentRequest(
        parent=parent,
        document=discoveryengine.Document(
            id=chunk_id,
            content=discoveryengine.Document.Content(
                mime_type="text/plain",
                raw_bytes=text_content.encode("utf-8"),
            ),
            struct_data=struct_data,
        ),
        document_id=chunk_id,
    )
    await client.create_document(request)


async def _create_production_document(
    chunk_id: str,
    question: str,
    answer: str,
    content_hash: str,
    promoted_at: str,
) -> None:
    """Write a document to the Vertex AI production data store.

    Schema matches data-model.md §Vertex AI Search Documents (production fields).
    Note: production documents do not include import_id or staged_at — those are
    staging-only fields that are not relevant after promotion.
    """
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]
    from google.protobuf import struct_pb2  # type: ignore[import]

    parent = _production_branch_path()
    text_content = f"Q: {question}\nA: {answer}"

    struct_data = struct_pb2.Struct()
    struct_data.update(
        {
            "question": question,
            "answer": answer,
            "source_type": "export",
            "content_hash": content_hash,
            "promoted_at": promoted_at,
        }
    )

    client = discoveryengine.DocumentServiceAsyncClient(client_options=_client_options())
    request = discoveryengine.CreateDocumentRequest(
        parent=parent,
        document=discoveryengine.Document(
            id=chunk_id,
            content=discoveryengine.Document.Content(
                mime_type="text/plain",
                raw_bytes=text_content.encode("utf-8"),
            ),
            struct_data=struct_data,
        ),
        document_id=chunk_id,
    )
    await client.create_document(request)


async def _get_document(doc_name: str):  # type: ignore[return]
    """Retrieve a document by name from Discovery Engine (synchronous get, not search)."""
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]

    client = discoveryengine.DocumentServiceAsyncClient(client_options=_client_options())
    return await client.get_document(name=doc_name)


async def _delete_document(doc_name: str) -> None:
    """Delete a document by name — best-effort; silently ignores failures."""
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]

    try:
        client = discoveryengine.DocumentServiceAsyncClient(client_options=_client_options())
        await client.delete_document(name=doc_name)
    except Exception:  # noqa: BLE001
        pass  # Best-effort cleanup; failure here must not mask test failures.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_staging_document_ingest_and_retrieval() -> None:
    """Ingest a test document to the staging data store and assert it is retrievable.

    Verifies:
    - The document can be created via DocumentServiceAsyncClient.create_document()
    - The document is retrievable by ID (chunk_id == Vertex AI document ID contract)
    - Document schema matches data-model.md §Vertex AI Search Documents:
        id, content.mimeType, content.text, structData.question, answer,
        source_type, import_id, content_hash, staged_at

    Why get_document() over search(): search indexing is asynchronous and
    would make this test nondeterministically flaky.  The document-by-ID
    retrieval tests ingestion correctness without waiting for indexing.
    """
    content_hash = _content_hash(_TEST_QUESTION, _TEST_ANSWER)

    staging_doc_name = _document_name(_staging_branch_path(), _TEST_CHUNK_ID)

    try:
        # Ingest document into staging data store
        asyncio.run(
            _create_staging_document(
                chunk_id=_TEST_CHUNK_ID,
                question=_TEST_QUESTION,
                answer=_TEST_ANSWER,
                import_id=_TEST_IMPORT_ID,
                content_hash=content_hash,
                staged_at=_TEST_STAGED_AT,
            )
        )

        # Query staging — assert document retrievable by ID
        doc = asyncio.run(_get_document(staging_doc_name))

        # Document ID must equal the chunk_id (per data-model.md referential contract)
        assert doc.id == _TEST_CHUNK_ID, (
            f"Document ID mismatch: expected {_TEST_CHUNK_ID!r}, got {doc.id!r}"
        )

        # Content schema: mimeType must be text/plain, text must be "Q: ...\nA: ..."
        assert doc.content.mime_type == "text/plain", (
            f"content.mimeType: expected 'text/plain', got {doc.content.mime_type!r}"
        )
        expected_text = f"Q: {_TEST_QUESTION}\nA: {_TEST_ANSWER}"
        actual_text = doc.content.raw_bytes.decode("utf-8")
        assert actual_text == expected_text, (
            f"content.text mismatch:\n  expected: {expected_text!r}\n  got:      {actual_text!r}"
        )

        # structData schema — all staging fields must be present per data-model.md
        # doc.struct_data is a proto-plus MapComposite (dict-like), not a protobuf Struct.
        fields = dict(doc.struct_data)
        required_staging_fields = {
            "question", "answer", "source_type", "import_id", "content_hash", "staged_at"
        }
        missing = required_staging_fields - set(fields.keys())
        assert not missing, (
            f"structData missing required staging fields: {missing!r}\n"
            f"Present fields: {set(fields.keys())!r}"
        )

        # Verify field values
        assert fields["question"] == _TEST_QUESTION
        assert fields["answer"] == _TEST_ANSWER
        assert fields["source_type"] == "export"
        assert fields["import_id"] == _TEST_IMPORT_ID
        assert fields["content_hash"] == content_hash
        assert fields["staged_at"] == _TEST_STAGED_AT

    finally:
        asyncio.run(_delete_document(staging_doc_name))


def test_production_document_ingest_and_retrieval() -> None:
    """Ingest a test document to the production data store and assert it is retrievable.

    Verifies:
    - The document can be created via DocumentServiceAsyncClient.create_document()
    - The document is retrievable by ID (chunk_id == Vertex AI document ID contract)
    - Document schema matches data-model.md §Vertex AI Search Documents:
        id, content.mimeType, content.text, structData.question, answer,
        source_type, content_hash, promoted_at
    - The production data store uses promoted_at (not staged_at or import_id)

    Why get_document() over search(): same reason as the staging test — search
    indexing latency is nondeterministic.
    """
    content_hash = _content_hash(_TEST_QUESTION, _TEST_ANSWER)

    production_doc_name = _document_name(_production_branch_path(), _TEST_CHUNK_ID)

    try:
        # Ingest document into production data store
        asyncio.run(
            _create_production_document(
                chunk_id=_TEST_CHUNK_ID,
                question=_TEST_QUESTION,
                answer=_TEST_ANSWER,
                content_hash=content_hash,
                promoted_at=_TEST_PROMOTED_AT,
            )
        )

        # Query production — assert document retrievable by ID
        doc = asyncio.run(_get_document(production_doc_name))

        # Document ID must equal the chunk_id (per data-model.md referential contract)
        assert doc.id == _TEST_CHUNK_ID, (
            f"Document ID mismatch: expected {_TEST_CHUNK_ID!r}, got {doc.id!r}"
        )

        # Content schema: mimeType must be text/plain, text must be "Q: ...\nA: ..."
        assert doc.content.mime_type == "text/plain", (
            f"content.mimeType: expected 'text/plain', got {doc.content.mime_type!r}"
        )
        expected_text = f"Q: {_TEST_QUESTION}\nA: {_TEST_ANSWER}"
        actual_text = doc.content.raw_bytes.decode("utf-8")
        assert actual_text == expected_text, (
            f"content.text mismatch:\n  expected: {expected_text!r}\n  got:      {actual_text!r}"
        )

        # structData schema — all production fields must be present per data-model.md
        # doc.struct_data is a proto-plus MapComposite (dict-like), not a protobuf Struct.
        fields = dict(doc.struct_data)
        required_production_fields = {
            "question", "answer", "source_type", "content_hash", "promoted_at"
        }
        missing = required_production_fields - set(fields.keys())
        assert not missing, (
            f"structData missing required production fields: {missing!r}\n"
            f"Present fields: {set(fields.keys())!r}"
        )

        # Verify field values
        assert fields["question"] == _TEST_QUESTION
        assert fields["answer"] == _TEST_ANSWER
        assert fields["source_type"] == "export"
        assert fields["content_hash"] == content_hash
        assert fields["promoted_at"] == _TEST_PROMOTED_AT

    finally:
        asyncio.run(_delete_document(production_doc_name))
