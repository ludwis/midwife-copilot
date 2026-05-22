# KB Firebase Pipeline — Phase 1: Modify Import Endpoint

Refactor `backend/api/admin/kb/imports.py` to upload the chat export file to GCS
before writing the Firestore doc, instead of running extraction as a BackgroundTask.
The Firestore `document.create` event will trigger the Firebase Function (Phase 2).

- [x] In `backend/api/admin/kb/imports.py`, add a GCS upload helper and update the `create_import` endpoint:
  - Add `from google.cloud import storage` import
  - Add `KB_IMPORTS_BUCKET_NAME` env var constant and a lazy `_gcs_client` singleton (`_get_gcs()`)
  - Add `_extension_for_format(source_format)` → `.txt` for `whatsapp_txt`, `.json` for `messenger_json`
  - Add `_upload_import_file(content, import_id, filename_hash, source_format) -> str` that uploads bytes to `gs://{KB_IMPORTS_BUCKET_NAME}/imports/{import_id}/{filename_hash}{ext}` and returns the `gs://` URI. Raise `RuntimeError` if the env var is not set.
  - In `create_import`: allocate `doc_ref` (and thus `import_id`) **before** the GCS upload so the path can embed the ID. Upload file to GCS first — if that raises, return HTTP 500 before any Firestore write. Then call `doc_ref.set(...)` with the new `gcs_path` field added to the existing fields. Remove `BackgroundTasks` from the function signature and remove the `background_tasks.add_task(...)` call entirely.
  - Remove `_run_pipeline` function (lines 96–202) and all imports that were only used by it: `asyncio`, `tempfile`, `extract_qa_pairs`, `parse_messenger`, `parse_whatsapp`, `strip_pii`, `stage_chunks`

- [x] Verify the modified endpoint works correctly:
  - Run `cd backend && python -m pytest tests/ -k "not integration" -x -q` to confirm no import errors or unit test regressions
  - Confirm `_run_pipeline` is gone and `BackgroundTasks` is no longer imported
  - Confirm `gcs_path` field is written to the Firestore doc in the `create_import` logic
