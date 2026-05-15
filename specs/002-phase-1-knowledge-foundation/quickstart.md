# Quickstart: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Branch**: `002-phase-1-knowledge-foundation`
**Updated**: 2026-05-15

This guide walks a developer through setting up the Phase 1 pipeline locally: parsing chat exports, running extraction, reviewing chunks via the admin API, and promoting them to the production index.

Phase 1 is entirely backend + admin UI — no WhatsApp webhook or client-facing code is involved.

---

## Prerequisites

Same as the [001 MVP quickstart](../../001-midwife-copilot-mvp/quickstart.md), plus:

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12 | `pyenv install 3.12` |
| Node.js | 20 LTS | `nvm install 20` |
| Docker | 24+ | For combined image build |
| gcloud CLI | latest | `brew install google-cloud-sdk` |
| Firebase CLI | latest | `npm install -g firebase-tools` |

spaCy multilingual model (downloaded once):

```bash
pip install spacy
python -m spacy download xx_ent_wiki_sm
```

---

## 1. Clone & Configure

```bash
git clone <repo-url> stilla-app
cd stilla-app
git checkout 002-phase-1-knowledge-foundation

cp .env.example .env
# Fill in the Phase 1 specific vars (see section 2 below)
```

---

## 2. Environment Variables (Phase 1 additions)

These extend the base `.env` from the 001 quickstart:

```bash
# Vertex AI Search — data store IDs (eu region, pre-created in GCP)
VERTEX_SEARCH_DATASTORE_PRODUCTION=midwife-production
VERTEX_SEARCH_DATASTORE_STAGING=midwife-staging
VERTEX_SEARCH_LOCATION=eu

# GCP project
GCP_PROJECT_ID=your-project-id
GCP_REGION=europe-west1

# Admin API auth (shared with Phase 2+)
ADMIN_TOKEN=a_long_random_secret_for_the_PWA

# Audit log GCS bucket (created in step 5 below)
AUDIT_BUCKET_NAME=midwife-bot-audit-dev

# Firestore emulator (set for local dev)
FIRESTORE_EMULATOR_HOST=localhost:8080

# Gemini extraction model
GEMINI_MODEL=gemini-2.0-flash-001

# PII stripping
SPACY_MODEL=xx_ent_wiki_sm

# Near-duplicate threshold (0.0–1.0; default 0.90)
DUPLICATE_SIMILARITY_THRESHOLD=0.90
```

---

## 3. GCP Setup (One-Time)

### Enable required APIs

```bash
gcloud services enable \
  discoveryengine.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  logging.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com
```

### Create Vertex AI Search data stores

```bash
# Production data store (eu region, unstructured with metadata)
gcloud alpha discovery-engine data-stores create \
  --project=$GCP_PROJECT_ID \
  --location=eu \
  --display-name="Midwife KB Production" \
  --data-store-id=midwife-production \
  --content-config=CONTENT_REQUIRED

# Staging data store
gcloud alpha discovery-engine data-stores create \
  --project=$GCP_PROJECT_ID \
  --location=eu \
  --display-name="Midwife KB Staging" \
  --data-store-id=midwife-staging \
  --content-config=CONTENT_REQUIRED
```

### Create audit GCS bucket (dev — no retention lock)

```bash
gsutil mb -l europe-west1 gs://midwife-bot-audit-dev
```

For production (irreversible — only run once on production project):

```bash
gsutil mb -l europe-west1 gs://midwife-bot-audit-prod
gsutil retention set 7y gs://midwife-bot-audit-prod
gsutil retention lock gs://midwife-bot-audit-prod   # IRREVERSIBLE
```

---

## 4. Backend Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Authenticate with GCP
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

### Start Firestore Emulator

```bash
firebase init emulators   # select Firestore; accept default port 8080
firebase emulators:start --only firestore
```

### Run the Backend

```bash
uvicorn api.main:app --reload --port 8000
```

API available at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

---

## 5. Frontend Setup (KB Review UI)

```bash
cd frontend
npm install
npm run dev
```

Vite dev server at `http://localhost:5173`. `/api` is proxied to `:8000`.

Navigate to `http://localhost:5173/kb` to access the KB Review interface.

---

## 6. Running an Import (End-to-End)

### Step 1 — Upload a chat export file

```bash
curl -X POST http://localhost:8000/api/admin/kb/imports \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -F "file=@/path/to/WhatsApp Chat.txt" \
  -F "source_format=whatsapp_txt"
```

Response:

```json
{
  "import_id": "imp_abc123",
  "status": "processing",
  "submitted_at": "2026-05-15T09:00:00.000Z"
}
```

### Step 2 — Poll for completion

```bash
curl http://localhost:8000/api/admin/kb/imports/imp_abc123 \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

Wait for `"status": "completed"` (or `"no_pairs_found"` if the export had no Q&A pairs).

### Step 3 — Review staged chunks

Open `http://localhost:5173/kb` and work through the review queue. For each chunk:
- **Approve**: accept as-is → immediately promoted to production
- **Edit & Approve**: correct content → promotes corrected version to production
- **Discard**: chunk is removed from the queue and never reaches production

Or via curl:

```bash
# Approve a chunk (promotes to production immediately)
curl -X PATCH http://localhost:8000/api/admin/kb/chunks/chk_xyz789 \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'

# Edit and approve
curl -X PATCH http://localhost:8000/api/admin/kb/chunks/chk_xyz790 \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "edit_approve",
    "question": "Is pelvic pressure normal at 36 weeks?",
    "answer": "Yes, it is common as the baby descends into the pelvis."
  }'
```

### Step 4 — Validate the production index (SC-007)

```bash
curl "http://localhost:8000/api/admin/kb/production/query?q=pelvic+pressure+36+weeks" \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

Confirm that promoted chunks are returned and the snippets are relevant. Run at least 5 representative midwifery questions to satisfy SC-007.

---

## 7. Running Tests

```bash
# Unit tests (no emulator or GCP needed)
pytest tests/unit/ -v

# Integration tests (requires Firestore emulator running on :8080)
FIRESTORE_EMULATOR_HOST=localhost:8080 pytest tests/integration/ -v

# Acceptance test with golden dataset
pytest tests/integration/test_kb_pipeline.py::test_golden_dataset -v

# Vertex AI Search / Gemini integration tests (requires real GCP creds)
INTEGRATION=true pytest tests/integration/test_vertex_search.py -v
```

---

## 8. Handling Duplicate-Flagged Chunks

When extraction detects a near-duplicate, the chunk appears in the review queue with a warning badge. The review UI shows the candidate alongside the similar existing chunk. The reviewer must explicitly approve or discard — the system never auto-deduplicates (FR-012).

For exact duplicates (`duplicate_flag: exact`): the system surfaces the chunk but the reviewer is expected to discard in most cases. The audit log records the decision either way.

---

## 9. Compliance Framework

Before Phase 3 begins, produce and review `docs/compliance-framework.md`. The document must cover:

1. Exact consent message text (Polish + English)
2. AI disclosure language (onboarding + per-message badge)
3. Data retention periods with legal basis
4. Right-to-erasure procedure

Template is available at `.specify/templates/compliance-framework-template.md`. Review with a GDPR-aware advisor and mark as reviewed in the document before Phase 3 kick-off (SC-005).

---

## 10. Messaging Channel Registration

Initiate WhatsApp Business API registration with Meta now — do not wait for Phase 2 or 3.

Required steps:
1. Create a Meta Business Suite account for the practice
2. Submit business verification documents (healthcare practice registration)
3. Apply for WhatsApp Cloud API — select "Health / Wellness"
4. Register the bot phone number (must not be a personal WhatsApp number)
5. Complete phone number verification

Track the application status. If Meta approval is delayed beyond Phase 3's start date, activate the Telegram adapter fallback (hexagonal architecture supports this without core code changes).

---

## Key URLs (Local Dev)

| Service | URL |
|---------|-----|
| FastAPI backend | `http://localhost:8000` |
| API docs (Swagger) | `http://localhost:8000/docs` |
| Vue PWA (dev server) | `http://localhost:5173` |
| KB Review UI | `http://localhost:5173/kb` |
| Firestore emulator UI | `http://localhost:4000` |
