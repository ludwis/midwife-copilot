# Backend — Stilla App (Phase 1: Knowledge Foundation)

FastAPI backend for the KB ingestion pipeline, admin review API, and audit logging.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12 | `pyenv install 3.12` |
| gcloud CLI | latest | `brew install google-cloud-sdk` |
| Firebase CLI | latest | `npm install -g firebase-tools` |

---

## Setup

### 1. Create virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Download spaCy model (one-time)

```bash
python -m spacy download xx_ent_wiki_sm
```

### 4. Authenticate with GCP

```bash
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

---

## Environment Variables

Copy `.env.example` from the repo root and fill in the Phase 1 variables:

```bash
cp ../.env.example ../.env
```

Key variables:

| Variable | Description |
|----------|-------------|
| `FIRESTORE_EMULATOR_HOST` | Set to `localhost:8080` for local dev |
| `GCP_PROJECT_ID` | Your GCP project ID |
| `ADMIN_TOKEN` | Long random secret for admin API auth |
| `VERTEX_SEARCH_DATASTORE_PRODUCTION` | Vertex AI Search data store ID (production) |
| `VERTEX_SEARCH_DATASTORE_STAGING` | Vertex AI Search data store ID (staging) |
| `VERTEX_SEARCH_LOCATION` | `eu` |
| `AUDIT_BUCKET_NAME` | GCS bucket for audit logs |
| `GEMINI_MODEL` | e.g. `gemini-2.0-flash-001` |
| `SPACY_MODEL` | `xx_ent_wiki_sm` |

---

## Start Firestore Emulator

```bash
# First-time only: initialise emulators (select Firestore, accept port 8080)
firebase init emulators

# Start the emulator
firebase emulators:start --only firestore
```

The emulator UI is available at `http://localhost:4000`.

---

## Run the Backend

```bash
uvicorn api.main:app --reload --port 8000
```

- API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

---

## Running Tests

```bash
# Unit tests (no emulator or GCP required)
pytest tests/unit/ -v

# Integration tests (requires Firestore emulator on localhost:8080)
FIRESTORE_EMULATOR_HOST=localhost:8080 pytest tests/integration/ -v

# Golden dataset acceptance test
pytest tests/integration/test_kb_pipeline.py::test_golden_dataset -v

# Vertex AI Search / Gemini tests (requires real GCP credentials)
INTEGRATION=true pytest tests/integration/test_vertex_search.py -v
```

---

## Project Structure

```
backend/
├── api/           # FastAPI app and routers
│   └── admin/kb/  # Admin endpoints: imports, chunks, production query
├── bot/           # KB ingestion pipeline (parsers, extractor, deduplication)
│   └── kb/
├── core/          # Shared utilities (audit logging, Firestore client)
├── tests/
│   ├── unit/
│   └── integration/
└── requirements.txt
```

---

## Key Admin Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/kb/imports` | Upload a chat export (WhatsApp `.txt`) |
| `GET` | `/api/admin/kb/imports/{id}` | Poll import status |
| `GET` | `/api/admin/kb/chunks` | List staged chunks awaiting review |
| `PATCH` | `/api/admin/kb/chunks/{id}` | Approve / edit-approve / discard a chunk |
| `GET` | `/api/admin/kb/production/query` | Query the production Vertex AI Search index |

All admin endpoints require `X-Admin-Token: <ADMIN_TOKEN>` header.

File upload limit: **10 MB**. Exceeding this returns `413` with `{"error": "File exceeds 10 MB limit"}`.
