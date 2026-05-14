# Midwife Bot — Phase 1: Knowledge Foundation & Compliance Skeleton

Reference plan: `midwife-assistant-bot-mvp-v4.md` in the project root.

The project root is `/Users/ad4m/Library/Mobile Documents/com~apple~CloudDocs/Projects/stilla-app`.
All source files for the backend live directly in this directory following the repo structure from the plan:
`ingestion/`, `api/`, `bot/`, `adapters/`, `config/`, `frontend/`, `Dockerfile`, etc.

---

- [ ] Scaffold the project: create `pyproject.toml` (or `requirements.txt`) with all Python dependencies needed for the full MVP: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `google-cloud-aiplatform`, `google-cloud-discoveryengine`, `google-cloud-firestore`, `google-cloud-logging`, `google-cloud-storage`, `google-cloud-secret-manager`, `pywebpush`, `httpx`, `pytest`, `pytest-asyncio`, `pytest-mock`. Also create `.env.example` listing every required environment variable: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `ADMIN_TOKEN`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `GCP_PROJECT_ID`, `GCP_REGION` (default `europe-west1`), `VERTEX_SEARCH_STAGING_DATASTORE`, `VERTEX_SEARCH_PROD_DATASTORE`, `FIRESTORE_DATABASE`, `AUDIT_BUCKET`. Create `README.md` with a brief project description and setup steps. Create an empty `tests/` directory with a `conftest.py` that sets `PYTHONPATH` so imports resolve from the project root.

- [ ] Create `config/settings.py` using `pydantic-settings` (`BaseSettings`). It must expose all environment variables listed in `.env.example` as typed fields with sensible defaults where applicable (e.g. `GCP_REGION = "europe-west1"`). Load from a `.env` file when present. Write `tests/test_settings.py` that instantiates `Settings` with mock env vars and asserts each field type and default value is correct. Run `pytest tests/test_settings.py` and confirm it passes.

- [ ] Create `ingestion/parse_whatsapp.py`. It must parse WhatsApp `.txt` export files into a list of structured exchange dicts: `{"timestamp": str, "sender": str, "text": str}`. Handle multi-line messages (continuation lines have no timestamp prefix). Skip system messages (e.g. "Messages and calls are end-to-end encrypted"). Expose a `parse_file(path: str) -> list[dict]` function. Write `tests/ingestion/test_parse_whatsapp.py` with at least 5 test cases: normal message, multi-line message, system message filtered out, group message with contact name, empty file. Include fixture `.txt` snippets inline as string constants. Run `pytest tests/ingestion/test_parse_whatsapp.py` and confirm all pass.

- [ ] Create `ingestion/parse_messenger.py`. It must parse Facebook Messenger `.json` export files (the `messages_1.json` format) into the same list-of-dicts structure as `parse_whatsapp.py`: `{"timestamp": str, "sender": str, "text": str}`. Skip non-text messages (photos, reactions, shares). Expose a `parse_file(path: str) -> list[dict]` function. Write `tests/ingestion/test_parse_messenger.py` with at least 4 test cases: text message, photo message skipped, reaction skipped, empty messages list. Use inline JSON fixtures. Run `pytest tests/ingestion/test_parse_messenger.py` and confirm all pass.

- [ ] Create `ingestion/extract_knowledge.py`. It must take a list of parsed exchange dicts and use Vertex AI Gemini 2.0 Flash to batch-extract Q&A knowledge chunks. Each chunk output should be: `{"question": str, "answer": str, "source": str, "tags": list[str]}`. The system prompt must instruct the model to only extract generalizable knowledge (not patient-specific advice), group related exchanges, and produce clean standalone Q&A pairs. Expose `extract_chunks(exchanges: list[dict], project: str, location: str) -> list[dict]`. Abstract the Gemini API call behind a `_call_gemini(prompt: str) -> str` helper so it can be mocked in tests. Write `tests/ingestion/test_extract_knowledge.py` with at least 3 test cases using `pytest-mock` to mock `_call_gemini`: normal extraction returning valid JSON, model returning malformed JSON (must raise `ValueError`), empty exchanges list returning empty list. Run `pytest tests/ingestion/test_extract_knowledge.py` and confirm all pass.

- [ ] Create `ingestion/index_to_vertex.py`. It must push knowledge chunks to either the staging or production Vertex AI Search data store. Expose `index_chunks(chunks: list[dict], datastore_id: str, project: str, location: str, index: str = "staging") -> None`. Use the `google-cloud-discoveryengine` client. Include a CLI entrypoint (`if __name__ == "__main__"`) that accepts `--input` (path to JSON file of chunks), `--index` (`staging` or `production`), and reads GCP config from `Settings`. Write `tests/ingestion/test_index_to_vertex.py` with at least 2 test cases using `pytest-mock` to mock the Discovery Engine client: successful index of 3 chunks, empty chunks list (no-op, no API call). Run `pytest tests/ingestion/test_index_to_vertex.py` and confirm all pass.

- [ ] Create `bot/audit.py`. It must write append-only audit events to Cloud Logging with a structured JSON payload. Every event must include: `event_type` (one of: `inbound`, `draft_generated`, `outbound_approved`, `outbound_edited`, `outbound_original`), `conversation_id`, `client_phone`, `timestamp` (ISO 8601 UTC), `payload` (the message text or draft text). Use the `google-cloud-logging` client. Expose `log_event(event_type: str, conversation_id: str, client_phone: str, payload: str, extra: dict | None = None) -> None`. Abstract the Cloud Logging write call behind a `_write_log(entry: dict) -> None` helper for testability. Write `tests/bot/test_audit.py` with at least 3 test cases using `pytest-mock` to mock `_write_log`: inbound event logs correct fields, outbound_approved event includes `"AI-drafted, midwife-approved"` tag in extra, missing required field raises `ValueError`. Run `pytest tests/bot/test_audit.py` and confirm all pass.

- [ ] Run the full test suite with `pytest tests/ -v` from the project root. Fix any import errors, missing `__init__.py` files, or test failures. All tests from tasks above must be green. Output the final pytest summary showing counts of passed/failed/skipped tests.

---

**Manual steps after Phase 1 (do not checkbox — human required):**

- Enable required GCP APIs: `run.googleapis.com`, `discoveryengine.googleapis.com`, `aiplatform.googleapis.com`, `firestore.googleapis.com`, `secretmanager.googleapis.com`, `cloudbuild.googleapis.com`, `logging.googleapis.com`, `storage.googleapis.com`
- Create Firestore database in `europe-west1`
- Create two Vertex AI Search data stores: `midwife-bot-staging` and `midwife-bot-production` (both EU region, unstructured document type)
- Create GCS audit bucket with 7-year retention lock: `gs://midwife-bot-audit-prod`
- Populate GCP secrets: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `ADMIN_TOKEN`, `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`
- Kick off Meta Business verification (async — takes weeks)
- Run ingestion pipeline against first batch of existing WhatsApp/Messenger chat exports, manually review 20 extracted chunks, promote approved ones to production index
