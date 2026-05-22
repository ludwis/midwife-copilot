# KB Firebase Pipeline — Phase 4: Update Tests

Split the now-invalid `test_import_flow.py` into two focused tests:
one for the POST intake endpoint (GCS mocked) and one for the Firebase
Function handler (called directly, OIDC and GCS mocked).

- [x] Create `backend/tests/integration/test_post_intake.py` — tests the POST `/api/admin/kb/imports` endpoint in isolation:
  - Copy the `admin_client`, `firestore_client`, and `captured_audit_events` fixtures from the existing `conftest.py` (or import them)
  - Add a `mock_gcs_upload` fixture that monkeypatches `api.admin.kb.imports._upload_import_file` to return `"gs://test-bucket/imports/test-id/abc123.txt"` without actually calling GCS
  - Add env var `KB_IMPORTS_BUCKET_NAME=test-kb-imports` to the fixture setup via `monkeypatch.setenv`
  - Test `test_post_returns_202`: POST with the golden WhatsApp export, assert 202, assert response body has `import_id`, `status=processing`, `submitted_at`
  - Test `test_post_writes_firestore_doc`: assert the Firestore `kb_imports` doc exists with `status=processing`, `gcs_path` set to the mocked URI, `source_format=whatsapp_txt`, `filename_hash` non-empty
  - Test `test_post_emits_audit_event`: assert `kb_import_started` audit event was captured with correct `import_id` and `source_format`
  - Test `test_post_no_backgroundtask_runs`: assert no `kb_import_completed` event was emitted (pipeline does not run inline)
  - Test `test_post_invalid_format_400`: POST with `source_format=invalid` → 400
  - Test `test_post_empty_file_400`: POST with empty file → 400
  - Test `test_post_gcs_failure_500`: monkeypatch `_upload_import_file` to raise `RuntimeError`, assert 500 response and no Firestore doc created

- [x] Create `backend/tests/integration/test_extract_function.py` — tests the Firebase Function handler directly:
  - Import `extract_kb_import` from `backend/functions/main` (adjust sys.path as needed)
  - Add a `mock_event` fixture that creates a fake `firestore_fn.Event` object with `params={"importId": "<id>"}` and a mock `DocumentSnapshot` — use `unittest.mock.MagicMock` for the event
  - Add a `mock_gcs_download` fixture that monkeypatches the GCS `Client().bucket().blob().download_as_bytes()` call to return the golden WhatsApp export bytes
  - Mark tests with `@pytest.mark.vcr` using the same VCR cassette as the old `test_import_flow.py` (path: `cassettes/test_import_flow/test_post_upload_and_poll_until_completed.yaml`) — or copy and rename it
  - Test `test_extract_function_success`: pre-seed Firestore emulator with a `kb_imports` doc (`status=processing`, `gcs_path`, `source_format=whatsapp_txt`), call `extract_kb_import(mock_event)` directly, assert Firestore doc transitions to `status=completed`, `chunks_extracted > 0`
  - Test `test_extract_function_creates_chunks`: assert `kb_chunks` docs exist in Firestore with `status=staged`, no PII in question/answer (check against phone/email/PESEL regex patterns)
  - Test `test_extract_function_emits_audit_events`: assert `kb_import_completed` and `kb_chunk_staged` events captured
  - Test `test_extract_function_idempotency`: pre-seed Firestore doc with `status=completed`, call function, assert it returns immediately without modifying anything
  - Test `test_extract_function_no_pairs`: pre-seed with a doc pointing to a GCS file containing only system messages (no extractable Q&A), assert Firestore transitions to `status=no_pairs_found`

- [x] Delete or skip `backend/tests/integration/test_import_flow.py`:
  - Add `@pytest.mark.skip(reason="Replaced by test_post_intake.py and test_extract_function.py")` to the existing test class/function, OR delete the file entirely
  - Confirm no other test file imports from `test_import_flow.py`

- [x] Run the full test suite and confirm it passes:
  - `cd backend && python -m pytest tests/ -x -q 2>&1 | tail -30`
  - All new tests must pass; no previously-passing tests may regress
