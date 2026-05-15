# Data Model: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Phase**: 1 — Design & Contracts
**Date**: 2026-05-15
**Storage**: Firestore (europe-west1) — mutable state; Vertex AI Search `eu` — two KB indexes; GCS (europe-west1) + Cloud Logging — append-only audit log

---

## Entity Overview

```
ChatExport (kb_imports) ──── produces many ──── KnowledgeChunk (kb_chunks)
                                                        │
                                              status: staged → promoted
                                                        │          │
                                                 staging index  production index
                                               (Vertex AI Search)  (Vertex AI Search)

KnowledgeChunk ──── generates ──── AuditEvent (Cloud Logging + GCS)
ChatExport     ──── generates ──── AuditEvent

AuditEvent (append-only, 7-year retention lock)
```

**Relationship to 001 data model**: The 001 plan's `kb_staging` collection was designed for chunks originating from midwife-approved conversation replies (Phase 2 flow). Phase 1 introduces the _import_ origin. Both flows produce `KnowledgeChunk` documents in `kb_chunks`; the `source_type` field distinguishes them. The `kb_staging` name from 001 is superseded by `kb_chunks` with a `status` field — more general and forward-compatible.

---

## Firestore Collections

### Collection: `kb_imports`

Tracks each chat export file submitted for processing.

**Document ID**: Auto-generated Firestore ID (`import_id`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filename_hash` | string | ✅ | SHA-256 of the original filename (PII-safe identifier; never store the real filename) |
| `source_format` | enum | ✅ | `whatsapp_txt` or `messenger_json` |
| `submitted_at` | timestamp | ✅ | UTC; when the file was uploaded |
| `submitted_by` | string | ✅ | Actor identity (Phase 1: always `"midwife"`) |
| `status` | enum | ✅ | `processing`, `completed`, `failed`, `no_pairs_found` |
| `completed_at` | timestamp | conditional | Set when extraction finishes (success or failure) |
| `chunks_extracted` | integer | conditional | Number of Q&A pairs sent to staging |
| `chunks_flagged_duplicate` | integer | conditional | Number flagged as exact or near-duplicate |
| `error_message` | string | conditional | Set on `failed` status |

**Validation rules**:
- `source_format` must be one of the two enum values
- `status` transitions: `processing` → `completed` | `failed` | `no_pairs_found`
- Document is created before extraction begins; updated atomically on completion

---

### Collection: `kb_chunks`

The central entity for Phase 1. Tracks every extracted Q&A pair from extraction through staging to promotion or discard.

**Document ID**: Auto-generated Firestore ID (`chunk_id`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | ✅ | Extracted question text (PII-stripped) |
| `answer` | string | ✅ | Extracted answer text (PII-stripped) |
| `content_hash` | string | ✅ | SHA-256 of `question + "\n" + answer` (normalized); used for deduplication and audit provenance |
| `source_type` | enum | ✅ | `export` (Phase 1) or `conversation_reply` (Phase 2+) |
| `import_id` | string | conditional | Present when `source_type == "export"`; reference to `kb_imports` doc |
| `status` | enum | ✅ | See state machine below |
| `duplicate_flag` | enum | optional | `exact` or `near` if deduplication flagged this chunk |
| `duplicate_of_chunk_id` | string | optional | Reference to the similar existing chunk (if flagged) |
| `similarity_score` | float | optional | Cosine similarity score (0.0–1.0) if `near` duplicate |
| `staged_at` | timestamp | ✅ | When the chunk entered staging |
| `reviewed_at` | timestamp | conditional | When the midwife took a review action |
| `reviewed_by` | string | conditional | Actor who reviewed |
| `content_hash_before_edit` | string | conditional | Set if chunk was edited before approval; preserves original for audit |
| `production_vertex_id` | string | conditional | Set on promotion: the document ID in the Vertex AI Search production data store |
| `promoted_at` | timestamp | conditional | Set on promotion |
| `vertex_embedding_id` | string | optional | ID of the stored embedding in the deduplication cache |

**KnowledgeChunk Status State Machine**:

| Status | Description | Transition In | Transition Out |
|--------|-------------|---------------|----------------|
| `staged` | Awaiting midwife review | Created by extraction | Reviewed (→ `approved` or `discarded`) |
| `approved` | Midwife approved, awaiting promotion | Review action: approve or edit | Promotion (→ `promoted`) or discard-after-approve (→ `discarded`) |
| `promoted` | In the production Vertex AI Search index | Explicit promote action | No outbound transition (terminal for production) |
| `discarded` | Rejected by midwife, will not reach production | Review action: discard | No outbound transition (terminal) |

**Note**: The `approved` status is an intermediate state between review and promotion. In Phase 1, approval and promotion happen in a single UI action ("Approve & Promote to Production"). The `approved` status is preserved in the data model for forward-compatibility with a scenario where bulk review precedes a separate batch promotion step.

**Validation rules**:
- `question` and `answer` must be non-empty after PII stripping
- `content_hash` must be computed before the document is written (never computed from the DB)
- Status transitions must be written via Firestore transactions to prevent concurrent review races
- `production_vertex_id` must be set before status transitions to `promoted`

---

## Audit Log Schema (Cloud Logging + GCS)

Phase 1 extends the 001 audit log with knowledge-event types. Written to the same GCS path: `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl`.

All events share these base fields:

```json
{
  "event_type": "...",
  "timestamp": "ISO-8601 UTC",
  "actor": "midwife",
  "session_id": "optional trace ID"
}
```

### Event: `kb_import_started`

```json
{
  "event_type": "kb_import_started",
  "timestamp": "2026-05-15T09:00:00.000Z",
  "actor": "midwife",
  "import_id": "imp_abc123",
  "source_format": "whatsapp_txt",
  "filename_hash": "sha256(WhatsApp Chat with Client.txt)"
}
```

### Event: `kb_import_completed`

```json
{
  "event_type": "kb_import_completed",
  "timestamp": "2026-05-15T09:00:47.123Z",
  "actor": "midwife",
  "import_id": "imp_abc123",
  "status": "completed",
  "chunks_extracted": 12,
  "chunks_flagged_duplicate": 2,
  "duration_ms": 47123
}
```

### Event: `kb_chunk_staged`

```json
{
  "event_type": "kb_chunk_staged",
  "timestamp": "2026-05-15T09:00:35.000Z",
  "actor": "midwife",
  "import_id": "imp_abc123",
  "chunk_id": "chk_xyz789",
  "content_hash": "sha256(question+answer)",
  "duplicate_flag": null
}
```

### Event: `kb_chunk_approved`

```json
{
  "event_type": "kb_chunk_approved",
  "timestamp": "2026-05-15T10:15:00.000Z",
  "actor": "midwife",
  "chunk_id": "chk_xyz789",
  "content_hash": "sha256(question+answer)"
}
```

### Event: `kb_chunk_edited`

```json
{
  "event_type": "kb_chunk_edited",
  "timestamp": "2026-05-15T10:16:00.000Z",
  "actor": "midwife",
  "chunk_id": "chk_xyz790",
  "content_hash_before": "sha256(original)",
  "content_hash_after": "sha256(edited)"
}
```

### Event: `kb_chunk_discarded`

```json
{
  "event_type": "kb_chunk_discarded",
  "timestamp": "2026-05-15T10:17:00.000Z",
  "actor": "midwife",
  "chunk_id": "chk_xyz791"
}
```

### Event: `kb_chunk_promoted`

```json
{
  "event_type": "kb_chunk_promoted",
  "timestamp": "2026-05-15T10:18:00.000Z",
  "actor": "midwife",
  "chunk_id": "chk_xyz789",
  "content_hash": "sha256(question+answer)",
  "production_vertex_id": "kb_prod_0001"
}
```

### Event: `kb_query_test`

```json
{
  "event_type": "kb_query_test",
  "timestamp": "2026-05-15T11:00:00.000Z",
  "actor": "midwife",
  "query_text": "Is it normal to feel pelvic pressure at 36 weeks?",
  "result_count": 3
}
```

---

## Vertex AI Search Documents (Knowledge Base)

Both staging and production data stores use the same document schema. Staging is NOT queryable by the Phase 2 RAG pipeline — only the production data store is.

### Staging and Production document schema

```json
{
  "id": "chk_xyz789",
  "content": {
    "mimeType": "text/plain",
    "text": "Q: Is it normal to feel pelvic pressure at 36 weeks?\nA: Yes, pelvic pressure is common in the third trimester as the baby descends into the pelvis. This is called engagement or 'lightening' and is a normal sign that your body is preparing for birth."
  },
  "structData": {
    "question": "Is it normal to feel pelvic pressure at 36 weeks?",
    "answer": "Yes, pelvic pressure is common in the third trimester...",
    "source_type": "export",
    "import_id": "imp_abc123",
    "content_hash": "sha256(...)",
    "staged_at": "2026-05-15",
    "promoted_at": "2026-05-15"
  }
}
```

**Document ID** in Vertex AI Search: same as `chunk_id` from Firestore — ensures referential consistency without a join table.

---

## State Transition Summary

```
Upload file → kb_imports: status=processing
Extraction complete → kb_imports: status=completed | failed | no_pairs_found

Per extracted pair:
  kb_chunks created → status=staged
  staged → (approve without edit) → status=approved
  staged → (edit + approve)       → status=approved, content_hash updated, content_hash_before_edit set
  staged → (discard)              → status=discarded
  approved → (promote to prod)    → status=promoted, production_vertex_id set

Deduplication flags (set at staging time, surfaced in review UI):
  staged → duplicate_flag=exact   (same hash as existing chunk)
  staged → duplicate_flag=near    (similarity > 0.90)
```
