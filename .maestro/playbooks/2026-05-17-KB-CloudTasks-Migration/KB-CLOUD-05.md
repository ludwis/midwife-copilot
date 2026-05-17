# KB Cloud Tasks Migration — Phase 5: Tests for the New Architecture

Add integration tests for:
1. The new lightweight Firebase Function stub (should enqueue a Cloud Tasks task and return)
2. The new `/internal/kb/process-import/{import_id}` FastAPI endpoint (full pipeline)
3. The OIDC auth dependency (rejects requests with missing or wrong tokens)

The existing tests in `tests/integration/test_extract_function.py` test the old monolithic
Cloud Function. Update them to reflect that the function is now a stub. The full pipeline
tests move to a new test file for the internal endpoint.

Project: `/Users/ad4m/Projects/stilla-app`
Golden WhatsApp test fixture lives at: `backend/tests/integration/` (check for a `.txt` fixture file)
Firestore emulator is used for integration tests (see `conftest.py` for setup).

- [x] Update `backend/tests/integration/test_extract_function.py` to match the new stub behaviour:
  - Read the existing file fully before changing anything
  - The function was moved to `backend/functions/main.py` in Phase 0 — update the import:
    - Change `from main import extract_kb_import` (or `import main`) →
      `from functions.main import extract_kb_import`
    - Also check `backend/tests/integration/conftest.py` for any `import main` and update it
  - The tests currently expect the function to run the full pipeline and produce `kb_chunks` docs
  - The new function only enqueues a Cloud Tasks task — adapt tests accordingly:
    - Replace the pipeline-assertion tests with a single test `test_stub_enqueues_cloud_task`:
      - Mock `google.cloud.tasks_v2.CloudTasksClient` using `unittest.mock.patch`
      - Set env vars `CLOUD_TASKS_QUEUE`, `CLOUD_RUN_SERVICE_URL`, `TASKS_SA_EMAIL` via `monkeypatch.setenv`
      - Pre-seed Firestore emulator with a `kb_imports` doc (`status=processing`)
      - Call `extract_kb_import(mock_event)` directly
      - Assert `CloudTasksClient().create_task.call_count == 1`
      - Assert the task URL contains `/internal/kb/process-import/{import_id}`
      - Assert the task has `dispatch_deadline.seconds == 3600`
    - Add `test_stub_idempotency_not_needed`: the stub no longer needs to check Firestore status
      (idempotency is handled by the endpoint) — document this in a comment
  - Keep the existing `mock_event` fixture (already updated for the new import path above)
  - Run `cd backend && python -m pytest tests/integration/test_extract_function.py -x -q 2>&1 | tail -20`

- [x] Create `backend/tests/integration/test_kb_pipeline_endpoint.py` — tests for the new internal endpoint:
  - This tests `POST /internal/kb/process-import/{import_id}` via the FastAPI `TestClient`
  - Use the Firestore emulator fixtures from `conftest.py`
  - For OIDC auth: monkeypatch `api.internal.auth.google.oauth2.id_token.verify_oauth2_token`
    to return a valid idinfo dict `{"email": TASKS_SA_EMAIL}` — this avoids real Google token validation
  - Add a helper fixture `internal_client` that creates a `TestClient(app)` with a default
    `Authorization: Bearer fake-oidc-token` header and the monkeypatched OIDC validator

  **Tests to add:**

  - `test_process_import_success`:
    - Pre-seed Firestore with a `kb_imports` doc (`status=processing`, `gcs_path`, `source_format=whatsapp_txt`)
    - Mock GCS download to return the golden WhatsApp fixture bytes
    - Mock Gemini (`bot.kb.extractor.extract_qa_pairs` or `extract_qa_pairs_async`) to return 3 `ChunkDraft` objects
    - Mock Vertex AI embeddings in `deduplicator` to return zero similarity (no duplicates)
    - POST `/internal/kb/process-import/{import_id}`
    - Assert HTTP 200
    - Assert Firestore `kb_imports` doc has `status=completed`, `chunks_extracted=3`
    - Assert 3 `kb_chunks` docs exist in Firestore with `status=staged`

  - `test_process_import_idempotency_already_completed`:
    - Pre-seed Firestore doc with `status=completed`
    - POST the endpoint
    - Assert HTTP 200 with body `{"status": "skipped"}`
    - Assert no new `kb_chunks` docs were created

  - `test_process_import_idempotency_extracting`:
    - Pre-seed Firestore doc with `status=extracting` (concurrent claim scenario)
    - POST the endpoint
    - Assert HTTP 200 with body `{"status": "skipped"}`

  - `test_process_import_no_pairs_found`:
    - Mock Gemini to return empty list
    - POST the endpoint
    - Assert HTTP 200, Firestore doc `status=no_pairs_found`

  - `test_process_import_transient_gemini_error`:
    - Mock Gemini to raise `google.api_core.exceptions.ServiceUnavailable("quota")`
    - POST the endpoint
    - Assert HTTP 503 (Cloud Tasks will retry)
    - Assert Firestore doc still has `status=extracting` (not failed — it may succeed on retry)
    - Actually: reconsider — if it returns 503, Cloud Tasks retries, but the Firestore doc is
      `extracting` which breaks the idempotency guard. The endpoint should reset
      `status=processing` before returning 503 so the next attempt can claim it.
      Implement this reset-on-transient-error and assert it in the test.

  - `test_process_import_fatal_error`:
    - Mock GCS download to raise `RuntimeError("bucket not found")`
    - POST the endpoint
    - Assert HTTP 200
    - Assert Firestore doc has `status=failed`, `error_message` contains "bucket not found"

  - `test_process_import_missing_oidc_token`:
    - POST `/internal/kb/process-import/{id}` with no `Authorization` header (do not use the `internal_client` fixture)
    - Assert HTTP 403

  - `test_process_import_wrong_sa_email`:
    - Monkeypatch OIDC validator to return `{"email": "wrong@other.iam.gserviceaccount.com"}`
    - POST with a Bearer token
    - Assert HTTP 403

  - Run: `cd backend && python -m pytest tests/integration/test_kb_pipeline_endpoint.py -x -q 2>&1 | tail -30`

- [x] Run the full test suite and confirm no regressions:
  - `cd /Users/ad4m/Projects/stilla-app/backend && python -m pytest tests/ -x -q 2>&1 | tail -40`
  - All tests must pass
  - If any previously-passing test fails, fix the root cause (do not skip or delete tests)
  - Report the final test count in a comment at the bottom of this task

<!-- RESULT: 100 passed, 3 skipped, 0 failed (2026-05-17)
     New tests added: 2 (test_extract_function.py) + 8 (test_kb_pipeline_endpoint.py) = 10 new tests
     Pre-existing failures fixed: 5 (3×test_review_actions, test_audit_log, test_kb_pipeline)
     Source changes: kb_pipeline.py — transient errors reset status=processing; added duration_ms to audit event
-->
