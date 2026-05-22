# KB Firebase Pipeline — Phase 2: Firebase Cloud Function

Create the Firebase Cloud Function that is triggered by `kb_imports/{importId}` document
creation and runs the full extraction pipeline (parse → PII strip → Gemini extract →
stage chunks → update Firestore → delete GCS file).

The function lives in `backend/functions/` and is a separate deployment unit from the
FastAPI backend. It shares the `bot/kb/` module code by including it in its source tree
or via a shared package path (see implementation note below).

- [x] Create `backend/functions/requirements.txt` with all dependencies the function needs:
  ```
  firebase-functions>=0.1.0
  firebase-admin>=6.0.0
  google-cloud-firestore>=2.19.0
  google-cloud-storage>=3.0.0
  google-cloud-aiplatform>=1.74.0
  google-genai>=1.0.0
  google-cloud-discoveryengine>=0.13.0
  google-cloud-logging>=3.10.0
  pydantic>=2.0.0
  spacy>=3.8.0
  python-dotenv>=1.0.0
  ```

- [x] Create `backend/functions/main.py` — the Firebase Cloud Function entry point:
  - Import `firebase_functions.firestore_fn` and `firebase_admin`
  - Call `firebase_admin.initialize_app()` at module level
  - Add sys.path manipulation to import from `backend/` sibling packages: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))` so that `bot.kb.*` and `core.*` modules resolve correctly
  - Load `.env` via `dotenv.load_dotenv` pointing at `../. env` (the backend `.env`)
  - Define `@firestore_fn.on_document_created(document="kb_imports/{importId}", region="europe-west1", memory=512, timeout_sec=3600)` function named `extract_kb_import(event)`
  - Inside the function:
    1. Extract `import_id = event.params["importId"]`
    2. Read the `kb_imports/{import_id}` doc from Firestore via `firebase_admin.firestore.client()`
    3. **Idempotency guard**: if doc doesn't exist or `status != "processing"`, log and return immediately
    4. Read `gcs_path` and `source_format` from the doc
    5. Download file bytes from GCS using `google.cloud.storage.Client()`
    6. Parse: `whatsapp_txt` → `parse_whatsapp(text)`, `messenger_json` → write tempfile, call `parse_messenger([path])`, unlink
    7. PII-strip each turn with `strip_pii(turn["content"])`
    8. Extract: `chunks = extract_qa_pairs(stripped_turns)` (sync, runs in Firebase Function thread — no `asyncio.to_thread` needed since this is not an asyncio context)
    9. If no chunks: update Firestore `status=no_pairs_found`, emit `kb_import_completed` audit event, delete GCS file, return
    10. `await stage_chunks(chunks, import_id, client=None)` — note: `stage_chunks` is async; since Firebase Functions Python runtime is sync, run it via `asyncio.run(stage_chunks(...))`
    11. Count duplicate chunks from Firestore
    12. Update Firestore: `status=completed`, `completed_at`, `chunks_extracted`, `chunks_flagged_duplicate`
    13. Emit `kb_import_completed` audit event
    14. Delete GCS file (best-effort, swallow exceptions, log warning)
  - Wrap the entire body in `try/except Exception`: on failure, update `status=failed`, `error_message`, `completed_at`, emit `kb_import_completed` with `status=failed`, attempt GCS cleanup, then re-raise (Firebase retries on uncaught exceptions)

- [x] Add a `_delete_gcs_file(gcs_uri: str) -> None` helper in `main.py`:
  - Parse `gs://bucket/path` from the URI
  - Call `storage.Client().bucket(bucket_name).blob(blob_path).delete()`
  - Swallow all exceptions and log a warning — never raises

- [x] Verify the function file is syntactically valid and imports resolve:
  - `cd backend/functions && python -c "import main"` (with `FIRESTORE_EMULATOR_HOST` and other env vars set or mocked)
  - Confirm no circular imports or missing modules
  - **Result**: `python3 -m py_compile main.py` → clean; `import functions.main` with mocked `firebase_admin`/`firebase_functions` → `Import OK` — no circular imports or missing modules from the backend venv.
