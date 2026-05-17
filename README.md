# Stilla — Midwife Co-pilot Knowledge Platform

Stilla converts midwife expertise from conversational chat histories (WhatsApp, Messenger) into a structured, searchable, auditable knowledge base. A midwife uploads chat exports, an AI pipeline extracts question-and-answer knowledge pairs, and a review interface lets her approve, edit, or discard each pair before it is promoted to a production search index that powers a retrieval-augmented AI assistant.

**Phase 1 scope:** Knowledge ingestion, PII stripping, Gemini-powered Q&A extraction, staged review workflow, production Vertex AI Search index, append-only audit trail.

---

## Architecture

```
Admin uploads chat export
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│         Cloud Run — stilla-backend (europe-west1)       │
│                                                         │
│  /api/admin/**   Admin REST API (Firebase ID token auth) │
│  /internal/**    Pipeline worker (OIDC auth)            │
│                                                         │
│  Static serving: Vue PWA (frontend/dist/)               │
└──────┬──────────────────────────────┬───────────────────┘
       │ POST /api/admin/kb/imports   │ POST /internal/kb/process-import/{id}
       │ creates kb_imports doc       │ accepts (202) + runs pipeline in background
       ▼                              ▲
┌─────────────────┐        ┌──────────────────────────────┐
│   Firestore     │        │  Cloud Workflow               │
│  kb_imports doc │        │  kb-import-pipeline           │
│  (status=       │───────▶│  OIDC auth, retry×3           │
│   processing)   │        └──────────────────────────────┘
└─────────────────┘                   ▲
         │                            │ invokes workflow
         │ document.v1.created        │
         ▼                            │
┌─────────────────────────────────────┴───────────────────┐
│      Eventarc trigger — kb-import-created               │
│      Filter: kb_imports/{importId} created (eur3)       │
└─────────────────────────────────────────────────────────┘

Pipeline (runs in Cloud Run background task, no timeout limit):
  1. Download file from GCS (KB_IMPORTS_BUCKET_NAME)
  2. Parse WhatsApp .txt or Messenger .json → conversation turns
  3. Strip PII from each turn (spaCy NER + phone/email/PESEL regex)
  4. Call Gemini 2.0 Flash in parallel overlapping windows → Q&A pairs
  5. Dedup (exact SHA-256 hash + cosine similarity near-duplicate flagging)
  6. Write kb_chunks docs to Firestore (status=staged)
  7. Update kb_imports doc with final status + counts
  8. Emit audit events (Cloud Logging + GCS JSONL)
  9. Delete the temporary GCS upload file
```

---

## Directory structure

```
stilla-app/
├── backend/                      # All Python backend code
├── workflows/
│   └── kb-import-pipeline.yaml   # Cloud Workflow: Eventarc → Cloud Run trigger
│   ├── api/                      # Cloud Run FastAPI service
│   │   ├── main.py               # App factory, lifespan (spaCy load), router mounts
│   │   ├── auth.py               # Firebase ID token auth (frontend) + X-Admin-Token (legacy)
│   │   ├── admin/kb/             # Frontend-facing API
│   │   │   ├── imports.py        # POST/GET /imports — upload & status polling
│   │   │   ├── chunks.py         # GET/PATCH /chunks — list & review actions
│   │   │   └── production.py     # GET /production/query — Vertex AI Search test
│   │   └── internal/             # Service-to-service API (Cloud Tasks → Cloud Run)
│   │       ├── auth.py           # OIDC token validation
│   │       └── kb_pipeline.py    # POST /internal/kb/process-import/{id}
│   ├── bot/kb/                   # KB extraction pipeline business logic
│   │   ├── parsers/              # whatsapp.py, messenger.py
│   │   ├── pii_stripper.py
│   │   ├── extractor.py          # Gemini Q&A extraction (async parallel windows)
│   │   ├── deduplicator.py       # Cosine similarity near-duplicate detection
│   │   ├── staging.py            # Write chunks to Firestore (batched)
│   │   └── promotion.py          # Promote chunks to Vertex AI Search
│   ├── core/audit.py             # Dual-write: Cloud Logging + GCS JSONL
│   ├── tests/
│   │   ├── unit/                 # Parser, PII stripper, deduplicator (no GCP)
│   │   └── integration/          # Firestore emulator + VCR Gemini cassettes
│   ├── Dockerfile                # Cloud Run container (entrypoint: api/main.py)
│   └── requirements.txt          # Cloud Run deps
├── frontend/                     # Vue 3 PWA admin app
│   ├── src/
│   │   ├── pages/                # LoginPage.vue, KbReviewPage.vue
│   │   ├── stores/               # auth.ts (Firebase Auth), kb.ts (chunk state)
│   │   ├── router/index.ts
│   │   └── services/api.ts       # Typed fetch wrapper
│   ├── package.json
│   └── vite.config.ts            # Dev proxy /api → localhost:8000
├── docs/                         # Compliance, privacy policy
├── specs/                        # Feature specs, data model, research notes
├── firebase.json                 # Functions source: backend/functions/
├── cloudbuild.yaml               # GCP Cloud Build CI/CD pipeline
└── .firebaserc                   # Firebase project alias → midwife-copilot
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12 | `brew install python@3.12` |
| Node.js | 20+ | `brew install node@20` |
| Google Cloud SDK | latest | `brew install google-cloud-sdk` |
| Firebase CLI | latest | `npm install -g firebase-tools` |

---

## Local development

### 1. GCP authentication

```bash
gcloud auth login
gcloud config set project midwife-copilot
gcloud auth application-default login
```

### 2. Backend

```bash
cd backend

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp ../.env.example .env
# Edit .env — see Environment variables section below
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Start everything

Open three terminal tabs:

```bash
# Tab 1 — Firestore emulator
firebase emulators:start --only firestore

# Tab 2 — Backend API (http://localhost:8000)
cd backend && source .venv/bin/activate
FIRESTORE_EMULATOR_HOST=localhost:8080 uvicorn api.main:app --reload --port 8000

# Tab 3 — Frontend dev server (http://localhost:5173)
cd frontend && npm run dev
```

Swagger UI: http://localhost:8000/docs

> **Note:** The Cloud Workflow and Eventarc trigger are not emulated locally. To test the full end-to-end pipeline in development, call `POST /internal/kb/process-import/{import_id}` directly after temporarily disabling the OIDC auth check in `api/internal/auth.py`.

---

## Environment variables

### `backend/.env` (Cloud Run)

| Variable | Required | Description | Example |
|---|---|---|---|
| `GCP_PROJECT_ID` | Yes | Google Cloud project ID | `midwife-copilot` |
| `GCP_REGION` | No | GCP region (default: `europe-west1`) | `europe-west1` |
| `ADMIN_TOKEN` | No | Legacy static secret for `X-Admin-Token` header (server-to-server scripts only) | 64-char hex string |
| `KB_IMPORTS_BUCKET_NAME` | Yes | GCS bucket for temporary chat export uploads | `midwife-copilot-kb-imports-dev` |
| `AUDIT_BUCKET_NAME` | Yes | GCS bucket for append-only JSONL audit logs | `midwife-bot-audit-dev` |
| `VERTEX_SEARCH_DATASTORE_PRODUCTION` | Yes | Vertex AI Search production data store ID | `knowledge_production` |
| `VERTEX_SEARCH_DATASTORE_STAGING` | Yes | Vertex AI Search staging data store ID | `knowledge_staging` |
| `VERTEX_SEARCH_LOCATION` | Yes | Vertex AI Search region | `eu` |
| `CLOUD_RUN_SERVICE_URL` | Yes | This service's own URL (used for OIDC audience validation) | `https://stilla-backend-xxx-ew.a.run.app` |
| `WORKFLOW_SA_EMAIL` | No | Workflow invoker service account email (informational) | `kb-pipeline-invoker@midwife-copilot.iam.gserviceaccount.com` |
| `GEMINI_MODEL` | No | Gemini model ID (default: `gemini-2.0-flash-001`) | `gemini-2.0-flash-001` |
| `SPACY_MODEL` | No | spaCy model name (default: `xx_ent_wiki_sm`) | `xx_ent_wiki_sm` |
| `DUPLICATE_SIMILARITY_THRESHOLD` | No | Cosine similarity threshold (default: `0.92`) | `0.92` |
| `FIRESTORE_EMULATOR_HOST` | Dev only | Firestore emulator address | `localhost:8080` |

### Cloud Workflow env var (set at workflow deploy time)

The workflow reads `CLOUD_RUN_SERVICE_URL` via `sys.get_env()`. This is injected automatically by `cloudbuild.yaml` using `--set-env-vars`. No manual configuration required after the first `gcloud builds submit`.

### `frontend/.env`

| Variable | Required | Description |
|---|---|---|
| `VITE_FIREBASE_API_KEY` | Yes | Firebase Web API key |
| `VITE_FIREBASE_AUTH_DOMAIN` | Yes | Firebase Auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Yes | GCP project ID |
| `VITE_FIREBASE_STORAGE_BUCKET` | Yes | Firebase Storage bucket |
| `VITE_FIREBASE_MESSAGING_SENDER_ID` | Yes | Firebase messaging sender ID |
| `VITE_FIREBASE_APP_ID` | Yes | Firebase app ID |
| `VITE_ADMIN_EMAIL` | No | Pre-filled email hint on login page |

---

## API reference

### Admin API — `/api/admin/kb/`

All endpoints require `Authorization: Bearer <firebase-id-token>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/imports` | Upload a WhatsApp `.txt` or Messenger `.json` export (max 10 MB). Stores file in GCS, creates `kb_imports` doc (`status=processing`). Returns `202`. |
| `GET` | `/imports` | List all import runs, newest first. Supports `?status=` filter. |
| `GET` | `/imports/{id}` | Get a single import run with status, counts, and error message if failed. |
| `GET` | `/chunks` | List knowledge chunks. Supports `?status=staged&import_id=&duplicate_flag=exact\|near`. Cursor-paginated. |
| `GET` | `/chunks/{id}` | Get full detail for one chunk including edit history and duplicate info. |
| `PATCH` | `/chunks/{id}` | Review a chunk. Body: `{"action": "approve" \| "edit_approve" \| "discard", "question": "...", "answer": "..."}`. `approve`/`edit_approve` promote to Vertex AI Search immediately. |
| `GET` | `/production/query` | Test query against the production Vertex AI Search index. `?q=<query>&limit=5` |

### Internal API — `/internal/`

Called by Cloud Workflow only. Authenticated via Google OIDC tokens — not accessible from the browser.

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/kb/process-import/{id}` | Run the full extraction pipeline for an import. Idempotent. |

---

## Running tests

```bash
cd backend
source .venv/bin/activate

# Unit tests (no GCP, no emulator)
python -m pytest tests/unit/ -v

# Integration tests (requires Firestore emulator on localhost:8080)
FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/integration/ -v

# All tests
FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/ -v
```

Integration tests use VCR cassettes (pre-recorded Gemini API responses) — no live Gemini calls during CI.

---

## Deployment

Deployment is managed by Cloud Build on push to `main`.

```bash
# Full deployment — tags image as 'latest'
gcloud builds submit --config cloudbuild.yaml --project midwife-copilot

# Full deployment — tag image with a specific git SHA
gcloud builds submit --config cloudbuild.yaml --project midwife-copilot \
  --substitutions=_IMAGE_TAG=$(git rev-parse --short HEAD)

# Deploy Cloud Run only (after docker build/push)
gcloud run deploy stilla-backend \
  --image europe-west1-docker.pkg.dev/midwife-copilot/stilla/backend:latest \
  --region europe-west1 --timeout=3600 --concurrency=1

# Deploy frontend to Firebase Hosting
cd frontend && npm run build
firebase deploy --only hosting --project midwife-copilot
```

### Cloud Build pipeline stages

1. **create-audit-bucket-dev** — Create `gs://midwife-bot-audit-dev` (idempotent)
2. **create-kb-imports-bucket** — Create `gs://midwife-copilot-kb-imports-dev` with 7-day lifecycle rule
3. **docker-build** — Build `backend/Dockerfile` → tagged with `$_IMAGE_TAG` and `latest`
4. **docker-push** — Push to `europe-west1-docker.pkg.dev/midwife-copilot/stilla/backend`
5. **cloud-run-deploy** — Deploy `stilla-backend` (`timeout=3600s`, `concurrency=1`)
6. **deploy-workflow** — Deploy `kb-import-pipeline` workflow with Cloud Run URL injected as env var
7. **grant-eventarc-receiver** — Grant `eventarc.eventReceiver` to `kb-pipeline-invoker` SA
8. **create-eventarc-trigger** — Create Firestore → Workflow Eventarc trigger in `eur3`
9. **grant-workflow-invoker** — Grant `workflows.invoker` to `kb-pipeline-invoker` SA

### One-time IAM setup

Run once per GCP project (not part of Cloud Build):

```bash
PROJECT_ID=midwife-copilot

# Create the pipeline invoker service account (used by Eventarc + Workflow)
gcloud iam service-accounts create kb-pipeline-invoker \
  --project=$PROJECT_ID \
  --display-name="KB Pipeline Invoker"

# Allow the SA to invoke Cloud Run (used by Cloud Workflow HTTP step)
gcloud run services add-iam-policy-binding stilla-backend \
  --region=europe-west1 \
  --member="serviceAccount:kb-pipeline-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Allow all authenticated users to access Cloud Run
# (Firebase ID token verification is handled in-app; Cloud Run IAM allows unauthenticated)
gcloud run services add-iam-policy-binding stilla-backend \
  --region=europe-west1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

---

## Firestore data model

### `kb_imports`

Tracks each chat export upload and its extraction outcome.

| Field | Type | Description |
|---|---|---|
| `source_format` | string | `whatsapp_txt` or `messenger_json` |
| `filename_hash` | string | SHA-256 of original filename |
| `gcs_path` | string | `gs://` URI of the uploaded file |
| `status` | string | `processing` → `extracting` → `completed` / `no_pairs_found` / `failed` |
| `submitted_at` | timestamp | Upload time |
| `started_at` | timestamp | When Cloud Run claimed the import |
| `completed_at` | timestamp | Pipeline completion time |
| `turns_parsed` | number | Conversation turns found in the export |
| `chunks_extracted` | number | Count of staged chunks |
| `chunks_flagged_duplicate` | number | Count of near/exact duplicate chunks |
| `error_message` | string | Set only on `status=failed` |

**Status state machine:**

```
processing → extracting → completed
                       → no_pairs_found
                       → failed
```

### `kb_chunks`

Individual extracted Q&A pairs awaiting review.

| Field | Type | Description |
|---|---|---|
| `question` | string | Extracted question (PII-stripped) |
| `answer` | string | Extracted answer (PII-stripped) |
| `language` | string | ISO 639-1 language code detected by Gemini (e.g. `pl`, `en`) |
| `status` | string | `staged` → `promoted` / `discarded` |
| `source_type` | string | Always `export` in Phase 1 |
| `import_id` | string | Parent `kb_imports` document ID |
| `content_hash` | string | SHA-256 of `question\nanswer` |
| `staged_at` | timestamp | When the chunk was written |
| `duplicate_flag` | string | `exact`, `near`, or absent |
| `duplicate_of_chunk_id` | string | Reference to the original chunk if flagged |
| `similarity_score` | number | Cosine similarity (0–1) for near-duplicate flags |
| `reviewed_at` | timestamp | Set when action is taken |
| `production_vertex_id` | string | Vertex AI document ID after promotion |
| `promoted_at` | timestamp | Set on promotion |

---

## Compliance

- **PII stripping** is applied to every message before it reaches Gemini
- **Audit log** is append-only, dual-written to Cloud Logging and a 7-year retention-locked GCS bucket (`midwife-bot-audit-dev`)
- **Temporary upload files** in `KB_IMPORTS_BUCKET_NAME` are deleted immediately after extraction and have a 7-day lifecycle rule as a safety net
- **Data residency**: all GCP resources are provisioned in `europe-west1` (Belgium); Vertex AI Search index in the `eu` multi-region

See [`docs/compliance-framework.md`](docs/compliance-framework.md) and [`docs/privacy-policy.md`](docs/privacy-policy.md) for full policy documentation.

---

## GCP resources

| Resource | Name | Region |
|---|---|---|
| Cloud Run service | `stilla-backend` | `europe-west1` |
| Cloud Workflow | `kb-import-pipeline` | `europe-west1` |
| Eventarc trigger | `kb-import-created` | `eur3` |
| Artifact Registry | `europe-west1-docker.pkg.dev/midwife-copilot/stilla/backend` | `europe-west1` |
| GCS — audit logs | `midwife-bot-audit-dev` | `europe-west1` |
| GCS — temp uploads | `midwife-copilot-kb-imports-dev` | `europe-west1` |
| Vertex AI Search | `knowledge_production` | `eu` |
| Firebase project | `midwife-copilot` | — |
