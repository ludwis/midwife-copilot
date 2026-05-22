# backend/

Python backend for Stilla. Contains three independently deployable components in one codebase:

| Directory | Deployed as | Trigger |
|---|---|---|
| `api/` | Cloud Run FastAPI service | HTTP (admin + internal) |
| `bot/`, `core/` | Shared library (Cloud Run only) | — |

The Firestore → pipeline trigger is handled by a **Cloud Workflow** (`workflows/kb-import-pipeline.yaml` at the project root) invoked via an Eventarc trigger — no Firebase Function or Cloud Tasks queue required.

---

## Folder structure

```
backend/
├── api/                    # Cloud Run FastAPI service
│   ├── main.py             # App factory, lifespan startup, router mounts
│   ├── auth.py             # Firebase ID token + legacy X-Admin-Token auth
│   ├── admin/kb/           # /api/admin/kb/** — frontend-facing API
│   │   ├── imports.py      # Upload + status endpoints
│   │   ├── chunks.py       # Review (approve / discard) endpoints
│   │   └── production.py   # Vertex AI Search test query
│   └── internal/           # /internal/** — Cloud Workflow-facing API
│       ├── auth.py         # OIDC token validation
│       └── kb_pipeline.py  # Full extraction pipeline endpoint
│
├── bot/kb/                 # KB pipeline business logic
│   ├── parsers/            # WhatsApp .txt and Messenger JSON parsers
│   ├── extractor.py        # Gemini Q&A extraction (async parallel windows)
│   ├── pii_stripper.py     # spaCy NER + regex PII removal
│   ├── deduplicator.py     # SHA-256 + cosine similarity deduplication
│   ├── staging.py          # Firestore chunk writer (batched)
│   └── promotion.py        # Vertex AI Search promotion
│
├── core/
│   └── audit.py            # Dual-write: Cloud Logging + GCS JSONL
│
├── tests/
│   ├── unit/               # No GCP, no emulator required
│   └── integration/        # Firestore emulator + VCR cassettes
│
├── Dockerfile              # Cloud Run container (entrypoint: api/main.py)
└── requirements.txt        # Cloud Run deps (does NOT include firebase-functions)
```

---

## Setup

### 1. Virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

The spaCy model is installed automatically via the wheel URL in `requirements.txt` — no separate `python -m spacy download` step needed.

### 3. Authenticate with GCP

```bash
gcloud auth application-default login
gcloud config set project midwife-copilot
```

### 4. Configure environment

```bash
cp ../.env.example .env
# Edit .env with your values
```

---

## Environment variables

| Variable | Used by | Required | Description |
|---|---|---|---|
| `GCP_PROJECT_ID` | api/, bot/ | Yes | Google Cloud project ID |
| `ADMIN_TOKEN` | api/auth.py | No | Legacy static token for `X-Admin-Token` header (server-to-server scripts only) |
| `KB_IMPORTS_BUCKET_NAME` | api/, bot/ | Yes | GCS bucket for temporary chat export uploads |
| `AUDIT_BUCKET_NAME` | core/audit.py | Yes | GCS bucket for append-only JSONL audit logs |
| `VERTEX_SEARCH_DATASTORE_PRODUCTION` | bot/kb/ | Yes | Vertex AI Search production data store ID |
| `VERTEX_SEARCH_DATASTORE_STAGING` | bot/kb/ | Yes | Vertex AI Search staging data store ID |
| `VERTEX_SEARCH_LOCATION` | bot/kb/ | Yes | `eu` |
| `CLOUD_RUN_SERVICE_URL` | api/internal/auth.py | Yes | This service's URL (OIDC audience) — also injected into the Cloud Workflow at deploy time |
| `WORKFLOW_SA_EMAIL` | api/internal/auth.py | Yes | Workflow SA email (OIDC email claim to accept) — set to `kb-pipeline-invoker@...` |
| `GEMINI_MODEL` | bot/kb/extractor.py | No | Gemini model ID (default: `gemini-2.0-flash-001`) |
| `SPACY_MODEL` | api/main.py | No | spaCy model (default: `xx_ent_wiki_sm`) |
| `DUPLICATE_SIMILARITY_THRESHOLD` | bot/kb/deduplicator.py | No | Near-dup threshold (default: `0.92`) |
| `FIRESTORE_EMULATOR_HOST` | Dev only | No | `localhost:8080` when using the emulator |

---

## Running locally

```bash
# Start Firestore emulator (separate terminal)
firebase emulators:start --only firestore

# Start FastAPI
FIRESTORE_EMULATOR_HOST=localhost:8080 uvicorn api.main:app --reload --port 8000
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

---

## Running tests

```bash
# Unit tests — no external services
pytest tests/unit/ -v

# Integration tests — requires Firestore emulator
FIRESTORE_EMULATOR_HOST=localhost:8080 pytest tests/integration/ -v

# Full suite
FIRESTORE_EMULATOR_HOST=localhost:8080 pytest tests/ -v

# Live Vertex AI / Gemini tests (real GCP credentials required)
INTEGRATION=true pytest tests/integration/test_vertex_search.py -v
```

VCR cassettes in `tests/integration/cassettes/` replay pre-recorded Gemini responses so CI runs without live API calls.

---

## Deployment

Each component deploys independently. See the root [`README.md`](../README.md) for the full Cloud Build pipeline.

```bash
# Full deployment (Cloud Run + Workflow + Eventarc trigger)
gcloud builds submit --config cloudbuild.yaml --project midwife-copilot
```

For `api/` service details see [`api/README.md`](api/README.md).
