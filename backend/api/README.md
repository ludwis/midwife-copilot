# backend/api/

Cloud Run FastAPI service — `stilla-backend`.

Serves two distinct route namespaces on the same container:

| Namespace | Auth | Caller | Purpose |
|---|---|---|---|
| `/api/admin/**` | Firebase ID token (`Authorization: Bearer`) | Frontend (Vue PWA) | KB review workflow |
| `/internal/**` | Google OIDC token | Cloud Workflow | KB extraction pipeline |

Static files (compiled Vue PWA) are served from `frontend/dist/` at the root path when present.

---

## Startup behaviour

On container startup the `lifespan` function in `main.py`:

1. Initialises Firebase Admin SDK (uses Cloud Run ADC credentials automatically)
2. Initialises Vertex AI (`google-cloud-aiplatform`)
3. Loads the spaCy NER model into a module-level singleton (avoids reloading per-request)

---

## Route reference

### Admin API — `/api/admin/kb/`

All routes require `Authorization: Bearer <firebase-id-token>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/admin/kb/imports` | Upload a WhatsApp `.txt` or Messenger `.json` export (max 10 MB). Stores in GCS, creates `kb_imports` doc (`status=processing`). Returns `202 {"import_id": "..."}`. |
| `GET` | `/api/admin/kb/imports` | List imports, newest first. Optional `?status=` filter. |
| `GET` | `/api/admin/kb/imports/{id}` | Get import status, counts, and error message. |
| `GET` | `/api/admin/kb/chunks` | List chunks. Filters: `?status=staged`, `?import_id=`, `?duplicate_flag=exact\|near`. Cursor-paginated. |
| `GET` | `/api/admin/kb/chunks/{id}` | Get full chunk detail including edit history and duplicate reference. |
| `PATCH` | `/api/admin/kb/chunks/{id}` | Review action: `{"action": "approve" \| "edit_approve" \| "discard", "question": "...", "answer": "..."}`. Approve/edit-approve promotes the chunk to Vertex AI Search immediately. |
| `GET` | `/api/admin/kb/production/query` | Test query against the production Vertex AI Search index. `?q=<query>&limit=5`. |

### Internal API — `/internal/`

Called exclusively by Cloud Workflow. Authenticated via Google-signed OIDC JWT issued by the `WORKFLOW_SA_EMAIL` service account (`kb-pipeline-invoker`). Requests without a valid token return `403`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/kb/process-import/{import_id}` | Run the full KB extraction pipeline for one import. Idempotent — skips if status is not `processing`. |

**Pipeline stages (inside `/internal/kb/process-import`):**

1. Idempotency guard — Firestore transaction claims `processing → extracting`
2. Download from GCS
3. Parse (WhatsApp `.txt` or Messenger `.json`)
4. PII stripping (spaCy NER + regex)
5. Gemini Q&A extraction (async parallel windows, `max_concurrent_windows=4`)
6. Deduplication (exact SHA-256 + cosine similarity)
7. Write `kb_chunks` to Firestore (batched writes)
8. Update `kb_imports` status + counts
9. Emit audit events, delete GCS file

**Error response contract:**

| Error type | HTTP status | Cloud Workflow behaviour |
|---|---|---|
| Fatal (bad format, not found) | `200` | No retry — import marked `status=failed` |
| Transient (quota, network) | `503` | Cloud Workflow retries with backoff (max 3×); status reset to `processing` |

---

## Files

| File | Description |
|---|---|
| `main.py` | FastAPI app factory, `lifespan` startup, router mounts |
| `auth.py` | `require_firebase_token` (Firebase ID token) + `require_admin_token` (legacy X-Admin-Token) |
| `admin/kb/imports.py` | Upload and status endpoints |
| `admin/kb/chunks.py` | Chunk listing and review action endpoints |
| `admin/kb/production.py` | Vertex AI Search test query endpoint |
| `internal/__init__.py` | Package init |
| `internal/auth.py` | `require_tasks_oidc` OIDC token validation (Cloud Workflow requests) |
| `internal/kb_pipeline.py` | Full pipeline as a FastAPI POST route |

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GCP_PROJECT_ID` | Yes | Google Cloud project ID |
| `ADMIN_TOKEN` | No | Legacy static token for `X-Admin-Token` header (server-to-server scripts only) |
| `KB_IMPORTS_BUCKET_NAME` | Yes | GCS bucket for temporary chat export uploads |
| `AUDIT_BUCKET_NAME` | Yes | GCS bucket for audit JSONL logs |
| `VERTEX_SEARCH_DATASTORE_PRODUCTION` | Yes | Vertex AI Search production data store ID |
| `VERTEX_SEARCH_DATASTORE_STAGING` | Yes | Vertex AI Search staging data store ID |
| `VERTEX_SEARCH_LOCATION` | Yes | `eu` |
| `CLOUD_RUN_SERVICE_URL` | Yes | This service's own URL — used as the OIDC token audience |
| `WORKFLOW_SA_EMAIL` | Yes | Cloud Workflow invoker SA email — validated against the OIDC token `email` claim |
| `GEMINI_MODEL` | No | Gemini model (default: `gemini-2.0-flash-001`) |
| `SPACY_MODEL` | No | spaCy model (default: `xx_ent_wiki_sm`) |
| `DUPLICATE_SIMILARITY_THRESHOLD` | No | Near-dup cosine threshold (default: `0.92`) |
| `FIRESTORE_EMULATOR_HOST` | Dev only | `localhost:8080` when using the emulator |

---

## Running locally

```bash
cd backend
source .venv/bin/activate

# Start Firestore emulator (separate terminal)
firebase emulators:start --only firestore

# Start the API
FIRESTORE_EMULATOR_HOST=localhost:8080 uvicorn api.main:app --reload --port 8000
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

**Testing the pipeline endpoint locally:** The `/internal/` routes use OIDC auth which requires real Google tokens. For local testing, temporarily disable the `require_tasks_oidc` dependency in `kb_pipeline.py` and revert before committing.

---

## Deployment

The service is built and deployed via Cloud Build:

```bash
# Full pipeline
gcloud builds submit --config cloudbuild.yaml --project midwife-copilot

# Manual deploy (after pushing the image)
gcloud run deploy stilla-backend \
  --image europe-west1-docker.pkg.dev/midwife-copilot/stilla/backend:latest \
  --region europe-west1 \
  --timeout=3600 \
  --concurrency=1 \
  --min-instances=1
```

`--timeout=3600` — allows pipeline requests up to 60 minutes.
`--concurrency=1` — one pipeline job per container instance; Cloud Run scales out for concurrent imports.

---

## Container

Built from `backend/Dockerfile`. Key settings:

- Base: `python:3.12-slim`
- Entrypoint: `uvicorn api.main:app`
- Workers: `1` (horizontal scaling via Cloud Run instances)
- `--timeout-keep-alive 75` — prevents uvicorn from closing long-lived connections
- `--timeout-keep-alive 75` keeps long-lived connections open; no worker timeout flag (uvicorn doesn't support it)

---

## Monitoring

- **Cloud Logging:** Filter `resource.type="cloud_run_revision" resource.labels.service_name="stilla-backend"`
- **Cloud Run Console:** Services → `stilla-backend` → Logs, Metrics, Revisions
- **Import status:** Query Firestore `kb_imports` collection — `status=extracting` docs older than 2 hours indicate a stuck pipeline
