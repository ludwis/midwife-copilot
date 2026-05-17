# KB Cloud Tasks Migration — Phase 3: Internal FastAPI Pipeline Endpoint

Create the new `/internal/kb/process-import/{import_id}` FastAPI endpoint on Cloud Run.
This endpoint is the actual KB pipeline worker — it runs the full parse → PII strip →
Gemini extract → stage pipeline with a 3600s request timeout. It is called by Cloud Tasks
(not by the admin UI) and authenticated via Google OIDC tokens.

Project: `/Users/ad4m/Projects/stilla-app`
GCP project: `midwife-copilot`, region: `europe-west1`

**Context:**
- The FastAPI app lives in `backend/api/main.py` (factory with `lifespan`)
- The existing admin routes are under `backend/api/admin/` and use `X-Admin-Token` auth
- The current pipeline logic is in `backend/bot/kb/` (extractor, staging, deduplicator, pii_stripper, parsers)
- The pipeline body used to live in `backend/main.py` (now replaced by the enqueue stub in Phase 2)
- Cloud Tasks sends a POST with an `Authorization: Bearer <oidc-token>` header
- New env vars needed: `CLOUD_RUN_SERVICE_URL`, `TASKS_SA_EMAIL` (same values as in the Function)

**Firestore status state machine for `kb_imports` docs:**
- `processing` → doc is in the queue, not yet picked up
- `extracting` → endpoint has started the pipeline (set at the start of the endpoint)
- `completed` → pipeline finished successfully
- `failed` → unrecoverable error (check `error_message` field)
- `no_pairs_found` → parse succeeded but 0 Q&A pairs extracted

**Error handling rules for Cloud Tasks retries:**
- Fatal errors (e.g. document not found, unsupported format): write `status=failed` to
  Firestore, return **HTTP 200** (do NOT let Cloud Tasks retry a broken import)
- Transient errors (e.g. `google.api_core.exceptions.ServiceUnavailable`, network timeouts
  hitting Gemini/Vertex): return **HTTP 503** (lets Cloud Tasks retry with backoff)
- Always write `status=failed` before returning any error response, so the import is not
  stuck in `extracting` forever

- [x] Create `backend/api/internal/__init__.py` as an empty package init:
  - File content: just a single blank line or a module docstring `"""Internal service-to-service endpoints."""`

- [x] Create `backend/api/internal/auth.py` — OIDC token validation FastAPI dependency:
  - This dependency validates the `Authorization: Bearer <token>` header on internal routes
  - The token is a Google-signed OIDC JWT issued by Cloud Tasks for the `TASKS_SA_EMAIL` service account
  - Read `CLOUD_RUN_SERVICE_URL` and `TASKS_SA_EMAIL` from `os.environ` at module level
  - Implement a FastAPI dependency `require_tasks_oidc(request: Request)`:
    ```python
    import os
    import google.auth.transport.requests
    import google.oauth2.id_token
    from fastapi import Request, HTTPException

    CLOUD_RUN_SERVICE_URL = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    TASKS_SA_EMAIL = os.environ.get("TASKS_SA_EMAIL", "")

    def require_tasks_oidc(request: Request) -> None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=403, detail="Missing OIDC token")
        token = auth_header[len("Bearer "):]
        try:
            idinfo = google.oauth2.id_token.verify_oauth2_token(
                token,
                google.auth.transport.requests.Request(),
                audience=CLOUD_RUN_SERVICE_URL,
            )
        except Exception as exc:
            raise HTTPException(status_code=403, detail=f"Invalid OIDC token: {exc}") from exc
        if idinfo.get("email") != TASKS_SA_EMAIL:
            raise HTTPException(status_code=403, detail="Token email does not match expected SA")
    ```
  - Import `google-auth` is already available (it's a transitive dep of `google-cloud-*`)

- [x] Create `backend/api/internal/kb_pipeline.py` — the full KB pipeline as a FastAPI POST route:
  - Read these files for full context on what each module does before writing:
    - `backend/bot/kb/extractor.py` (Gemini extraction, `extract_qa_pairs(turns)`)
    - `backend/bot/kb/staging.py` (Firestore + Vertex AI staging, `stage_chunks(chunks, import_id, client)`)
    - `backend/bot/kb/deduplicator.py` (dedup check)
    - `backend/bot/kb/pii_stripper.py` (`strip_pii(text)`)
    - `backend/bot/kb/parsers/whatsapp.py` (`parse_whatsapp(text)`)
    - `backend/bot/kb/parsers/messenger.py` (`parse_messenger(data)`)
    - `backend/core/audit.py` (`write_event(event_type, payload)`)
    - The old `backend/main.py` pipeline body (before Phase 2 replaced it) to confirm the exact call sequence
  - Create an `APIRouter` and implement `POST /kb/process-import/{import_id}`:

  ```python
  from fastapi import APIRouter, Depends, HTTPException
  from fastapi.responses import JSONResponse
  from .auth import require_tasks_oidc
  # ... other imports

  router = APIRouter()

  @router.post("/kb/process-import/{import_id}", dependencies=[Depends(require_tasks_oidc)])
  async def process_import(import_id: str) -> JSONResponse:
      ...
  ```

  - **Step 1 — Idempotency guard (Firestore transaction):**
    - Read the `kb_imports/{import_id}` Firestore doc
    - If the doc does not exist: return `JSONResponse({"status": "skipped", "reason": "not_found"}, status_code=200)`
    - If `doc.get("status") != "processing"`: return `JSONResponse({"status": "skipped", "reason": doc.get("status")}, status_code=200)`
    - Use a Firestore transaction to atomically flip `status: processing → extracting` and set `started_at` to current timestamp
    - If the transaction fails (doc was claimed by another invocation): return `JSONResponse({"status": "skipped", "reason": "concurrent_claim"}, status_code=200)`

  - **Step 2 — Download from GCS:**
    - Read env vars `KB_IMPORTS_BUCKET_NAME` and `GCP_PROJECT_ID`
    - Use `google.cloud.storage.Client()` to download the file from `imports/{import_id}/` prefix
    - List blobs under that prefix and download the first match
    - If no file found: write `status=failed`, `error_message="GCS file not found"` to Firestore; return `JSONResponse({"status": "failed"}, 200)`

  - **Step 3 — Parse:**
    - Read `source_format` from the Firestore doc
    - `whatsapp_txt`: decode bytes as UTF-8, call `parse_whatsapp(text)` → `list[dict]`
    - `messenger_json`: `json.loads(bytes)`, call `parse_messenger(data)` → `list[dict]`
    - Other: write `status=failed`; return 200
    - Write `turns_parsed: len(turns)` to Firestore doc (progress field, best-effort)

  - **Step 4 — PII stripping:**
    - For each turn, apply `strip_pii(turn["content"])` and replace the content in-place
    - (spaCy is already loaded in the FastAPI lifespan; no reloading needed)

  - **Step 5 — Gemini extraction:**
    - Call `extract_qa_pairs(turns)` from `bot.kb.extractor` (sync, use `asyncio.to_thread` to avoid blocking the event loop)
    - Write `windows_total` to Firestore if the extractor exposes it (best-effort)
    - If result is empty list: write `status=no_pairs_found`, emit `kb_import_completed` audit event; return `JSONResponse({"status": "no_pairs_found"}, 200)`

  - **Step 6 — Stage chunks:**
    - Call `stage_chunks(chunks, import_id, client=None)` from `bot.kb.staging` (wrap in `asyncio.to_thread` if sync)
    - Returns `list[str]` of chunk_ids

  - **Step 7 — Count duplicates and update Firestore:**
    - Query Firestore for `kb_chunks` where `import_id == import_id` and `duplicate_flag == True`
    - Update `kb_imports/{import_id}` doc:
      - `status = "completed"`
      - `completed_at = now`
      - `chunks_extracted = len(chunk_ids)`
      - `chunks_flagged_duplicate = count`

  - **Step 8 — Audit event + GCS cleanup:**
    - Call `write_event("kb_import_completed", {...})` from `core.audit`
    - Delete the GCS file (swallow exceptions)

  - **Top-level error handling:** Wrap the entire pipeline body in `try/except Exception`. On any uncaught exception:
    - Determine if it's transient (`google.api_core.exceptions.ServiceUnavailable`, `google.api_core.exceptions.DeadlineExceeded`, `ConnectionError`, `TimeoutError`)
    - Transient: raise `HTTPException(status_code=503, detail=str(e))` — Cloud Tasks will retry
    - Fatal: write `status=failed`, `error_message=str(e)[:500]`, `completed_at=now` to Firestore; log the full traceback; return `JSONResponse({"status": "failed"}, 200)`

- [x] Mount the new internal router in `backend/api/main.py` and pre-warm the embedding cache:
  - Read `backend/api/main.py` to find: (a) the `lifespan` function, (b) existing `include_router` calls
  - Add import: `from .internal.kb_pipeline import router as pipeline_router`
  - Add `app.include_router(pipeline_router, prefix="/internal")` after the existing admin router mount
    - Do NOT add the `require_admin_token` dependency at the router level — auth is handled per-route via OIDC
  - In the `lifespan` function, after spaCy loads, add a deduplicator warm-up:
    ```python
    import bot.kb.deduplicator  # triggers GCS embedding cache download at startup
    logger.info("Embedding cache pre-warmed")
    ```
    - This ensures the first pipeline request does not pay the GCS cold-start penalty
  - Verify: `cd backend && python -c "from api.main import app"` exits cleanly (no import errors)
