# Phase 06: User Story 4 — Audit Trail for Knowledge Events

Verify and complete the audit trail coverage across all knowledge management events: import started/completed, chunk staged, chunk approved/edited/discarded/promoted, and production query. Write integration tests that validate 100% event coverage. Document the GCS retention lock procedure. By the end of this phase, SC-003 (100% audit coverage) is verifiable.

**Priority**: P2. Depends on US1 + US2 being complete (all event types must exist to verify). Best run after Phase 04.

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md (§User Story 4, FR-007, FR-008, SC-003)
- **Plan:** specs/002-phase-1-knowledge-foundation/plan.md
- **Data Model:** specs/002-phase-1-knowledge-foundation/data-model.md (§Audit schema)

## Tasks

### Tests

- [x] T048 [P] [US4] Write integration test for audit log in `backend/tests/integration/test_audit_log.py` (Firestore emulator + mock GCS write capturing written lines; run import → review sequence; assert all 8 event types emitted: `kb_import_started`, `kb_import_completed`, `kb_chunk_staged`, `kb_chunk_approved`, `kb_chunk_edited`, `kb_chunk_discarded`, `kb_chunk_promoted`, `kb_query_test`; assert `kb_chunk_edited` includes `content_hash_before` and `content_hash_after`; assert every event has `event_type`, `timestamp`, and `actor` base fields; assert `kb_import_completed` includes `duration_ms`)
  <!-- Done: test_all_8_event_types_emitted_in_full_sequence covers the full sequence with mocked extractor/dedup/promotion/Discovery Engine. kb_chunk_promoted assertion is TDD-RED until T052 adds the missing write_event() call. -->
- [x] T049 [P] [US4] Write `INTEGRATION=true`-gated Vertex AI Search test in `backend/tests/integration/test_vertex_search.py` (skip unless `os.environ.get("INTEGRATION") == "true"`; ingest a test document to staging data store; query staging — assert document retrievable; ingest to production data store; query production — assert document retrievable; verify document schema matches data-model.md Vertex AI Search document structure)
  <!-- Done: two tests (test_staging_document_ingest_and_retrieval, test_production_document_ingest_and_retrieval) use pytestmark skipif guard; both use DocumentServiceAsyncClient.create_document() + get_document() to verify ingestion and schema without search-indexing latency; structData fields validated against data-model.md; best-effort cleanup via finally blocks; confirmed skips cleanly when INTEGRATION != "true". -->

### Implementation — Audit Event Verification

- [x] T050 [US4] Verify `kb_import_started` and `kb_import_completed` audit events are emitted in `backend/api/admin/kb/imports.py` (`kb_import_started`: fields `import_id`, `source_format`, `filename_hash`, `actor="midwife"`; `kb_import_completed`: fields `status`, `chunks_extracted`, `chunks_flagged_duplicate`, `duration_ms`; add any missing `audit.write_event()` calls; verify fields match data-model.md audit schema)
  <!-- Done: kb_import_started (line 245) and both successful kb_import_completed branches were complete. Added missing duration_ms to the failed-branch kb_import_completed call (line 194–200); all three kb_import_completed code paths now include duration_ms as required by data-model.md and test_audit_log.py assertions. -->
- [x] T051 [US4] Verify `kb_chunk_staged` audit event fields in `backend/bot/kb/staging.py` match data-model.md audit schema (`import_id`, `chunk_id`, `content_hash`, `duplicate_flag`; the call itself is implemented in T031 — this task confirms field completeness and that the event appears in `test_audit_log.py` output)
  <!-- Done: staging.py lines 203–210 emit all 4 required fields (import_id, chunk_id, content_hash, duplicate_flag) with actor="midwife" — exactly matching data-model.md §kb_chunk_staged. test_audit_log.py lines 396–407 assert all 4 fields plus import_id value equality. No changes were needed; field completeness confirmed. -->
- [ ] T052 [US4] Verify `kb_chunk_approved`, `kb_chunk_edited`, `kb_chunk_discarded`, `kb_chunk_promoted` are emitted in `backend/api/admin/kb/chunks.py` (`kb_chunk_edited` MUST include `content_hash_before` and `content_hash_after` per data-model.md; add any missing `audit.write_event()` calls for each action branch)
- [ ] T053 [US4] Verify `kb_query_test` audit event is emitted in `backend/api/admin/kb/production.py` (fields: `query_text`, `result_count`; add missing `audit.write_event()` call if absent)
- [ ] T054 [US4] Document production GCS retention lock procedure in `cloudbuild.yaml` as a commented-out step (commands: `gsutil mb -l europe-west1 gs://midwife-bot-audit-prod`, `gsutil retention set 7y`, `gsutil retention lock`; add `# IRREVERSIBLE — run once on production project only` warning; keep dev bucket creation as an active step for CI; add `AUDIT_BUCKET_NAME` substitution variable)

## Completion

- [ ] `pytest backend/tests/integration/test_audit_log.py` passes — all 8 event types asserted
- [ ] Run full extraction → approve 2 chunks → discard 1 → promote 1 to production; query GCS audit.jsonl and confirm all expected events appear with required fields
- [ ] `cloudbuild.yaml` contains the retention lock commented step with `# IRREVERSIBLE` warning
- [ ] `INTEGRATION=true pytest backend/tests/integration/test_vertex_search.py` passes (requires real GCP dev project)
- [ ] Run `/speckit-analyze` to verify consistency
