# Phase 04: User Story 2 — Staging-to-Production Knowledge Promotion

Implement the review-and-promotion pipeline: backend chunk promotion writer, GET/PATCH chunk endpoints, production query endpoint, frontend Pinia KB store, and the review queue UI. By the end of this phase a midwife can approve, edit-approve, or discard staged chunks, and promoted chunks are queryable from the production Vertex AI Search index.

**Priority**: P1 — MVP critical. Depends on Phase 03 (staged chunks must exist to review).

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md
- **Plan:** specs/002-phase-1-knowledge-foundation/plan.md
- **Data Model:** specs/002-phase-1-knowledge-foundation/data-model.md
- **Contracts:** specs/002-phase-1-knowledge-foundation/contracts/kb-review.yaml

## Tasks

### Tests (write before implementation)

- [x] T037 [US2] Write integration test for review actions in `backend/tests/integration/test_review_actions.py` (Firestore emulator; seed 3 `kb_chunks` docs with `status=staged`; test `approve`: PATCH → assert doc `status=promoted`, `production_vertex_id` set, `reviewed_at` set; test `edit_approve`: assert `content_hash` updated, `content_hash_before_edit` preserved, `status=promoted`; test `discard`: assert `status=discarded`; test 409 on second PATCH to already-actioned chunk via simulated concurrent request)
- [x] T038 [P] [US2] Write acceptance test for golden dataset end-to-end pipeline in `backend/tests/integration/test_kb_pipeline.py` (`test_golden_dataset`: load `golden_whatsapp_export.txt`, run full pipeline with VCR Gemini cassette, assert extracted and PII-stripped chunks match `golden_expected_chunks.json` structure and content; assert no digit sequence >6 digits in any chunk question or answer)

### Implementation

- [x] T039 [US2] Implement chunk promotion writer in `backend/bot/kb/promotion.py` (`promote_chunk(chunk_id: str, question: str, answer: str, content_hash: str)`: write document to Vertex AI production data store using Discovery Engine API with full schema per data-model.md §Vertex AI Search Documents; on success: Firestore transaction to update `kb_chunks` doc: `status=promoted`, `production_vertex_id`, `promoted_at`; update GCS embedding cache by appending new `{chunk_id, embedding}` entry to `embeddings/cache.jsonl`)
- [x] T040 [US2] Implement `GET /api/admin/kb/chunks` and `GET /api/admin/kb/chunks/{chunk_id}` in `backend/api/admin/kb/chunks.py` (`listChunks`: filter by `status`, `import_id`, `duplicate_flag` query params; cursor-based pagination using Firestore `start_after`; when `duplicate_flag` is set, fetch and embed `duplicate_of` ChunkSummary in each result; include `total_staged` count; `getChunk`: full `ChunkDetail` including `content_hash_before_edit`, `reviewed_by`, `production_vertex_id`)
- [x] T041 [US2] Implement `PATCH /api/admin/kb/chunks/{chunk_id}` in `backend/api/admin/kb/chunks.py` (Firestore `@firestore.transactional` to prevent concurrent review races; read chunk and assert `status=staged`, raise 409 if already actioned; `approve`: call `promotion.promote_chunk()`, update status; `edit_approve`: recompute `content_hash = SHA-256(new_question + "\n" + new_answer)`, set `content_hash_before_edit`, update question/answer, call `promotion.promote_chunk()`; `discard`: set `status=discarded`; emit corresponding audit event via `core.audit.write_event()`; return updated `ChunkDetail`; raise 400 if `edit_approve` missing question or answer)
- [x] T042 [US2] Implement `GET /api/admin/kb/production/query` in `backend/api/admin/kb/production.py` (require non-empty `q` param, raise 400 if missing; query Vertex AI Search production data store with Discovery Engine `SearchServiceClient`; map results to `QueryResult` array with extractive answer snippet; emit `kb_query_test` audit event with `query_text` and `result_count`; return typed response per kb-review.yaml)
- [ ] T043 [US2] Extend `frontend/src/services/api.ts` with review and query methods (`listChunks(params: {status?, importId?, duplicateFlag?, cursor?}): Promise<ChunksListResponse>`; `getChunk(id: string): Promise<ChunkDetail>`; `reviewChunk(id: string, action: ReviewAction): Promise<ChunkDetail>`; `queryProduction(q: string, limit?: number): Promise<QueryResponse>`; all typed per kb-review.yaml schemas)
- [ ] T044 [US2] Create `frontend/src/stores/kb.ts` (Pinia: `stagedChunks: ChunkSummary[]`, `nextCursor: string | null`, `imports: ImportSummary[]`; actions: `fetchStagedChunks()` with cursor pagination; `approveChunk(id)`, `editApproveChunk(id, question, answer)`, `discardChunk(id)` — each calls `api.reviewChunk()` then removes chunk from local `stagedChunks`; `queryProduction(q)` returns results; `fetchImports()`)
- [ ] T045 [US2] Implement review queue section in `frontend/src/pages/KbReviewPage.vue` (fetch and display `stagedChunks` from `kbStore`; per-chunk card: question text, answer text, `staged_at`, source badge; if `duplicate_flag` show warning badge with similarity score and link to similar chunk; action buttons: Approve (calls `kbStore.approveChunk()`), Edit & Approve (expands inline textarea for question/answer edit then `kbStore.editApproveChunk()`), Discard (calls `kbStore.discardChunk()`); load-more button for cursor pagination; production query test panel: text input + Search button + results list with snippets)

## Completion

- [ ] Integration tests pass: `pytest backend/tests/integration/test_review_actions.py backend/tests/integration/test_kb_pipeline.py`
- [ ] Seed 5 staged chunks; approve 2, edit-approve 1, discard 1; verify `GET /api/admin/kb/chunks?status=promoted` returns 3
- [ ] Query `GET /api/admin/kb/production/query?q=<midwifery question>` and confirm promoted chunks are returned
- [ ] 409 is returned on second PATCH to already-actioned chunk
- [ ] Run `/speckit-analyze` to verify consistency
