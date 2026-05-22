# Quickstart: Midwife Co-pilot MVP

**Branch**: `001-midwife-copilot-mvp`  
**Updated**: 2026-05-14

This guide gets a developer to a working local environment for both the FastAPI backend and the Vue 3 PWA frontend.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12 | `pyenv install 3.12` |
| Node.js | 20 LTS | `nvm install 20` |
| Docker | 24+ | [docs.docker.com](https://docs.docker.com) |
| gcloud CLI | latest | `brew install google-cloud-sdk` |
| Firebase CLI | latest | `npm install -g firebase-tools` |

Google Cloud project with the following APIs enabled:

```bash
gcloud services enable \
  run.googleapis.com \
  discoveryengine.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  logging.googleapis.com \
  storage.googleapis.com
```

---

## 1. Clone & Configure

```bash
git clone <repo-url> stilla-app
cd stilla-app
git checkout 001-midwife-copilot-mvp

cp .env.example .env
# Edit .env — see Environment Variables section below
```

---

## 2. Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# GCP
GCP_PROJECT_ID=your-project-id
GCP_REGION=europe-west1

# WhatsApp Cloud API (Meta)
WHATSAPP_TOKEN=EAAxxxxx...
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=a_random_string_you_choose

# Admin API auth
ADMIN_TOKEN=a_long_random_secret_for_the_PWA

# Vertex AI Search data store IDs
VERTEX_SEARCH_DATASTORE_PRODUCTION=midwife-production
VERTEX_SEARCH_DATASTORE_STAGING=midwife-staging
VERTEX_SEARCH_LOCATION=eu

# VAPID keys (generate once with: npx web-push generate-vapid-keys)
VAPID_PUBLIC_KEY=BxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxA=
VAPID_PRIVATE_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Audit log GCS bucket
AUDIT_BUCKET_NAME=midwife-bot-audit-dev

# Firestore (auto-detected from ADC; set if needed)
# FIRESTORE_EMULATOR_HOST=localhost:8080  # set this for local dev
```

---

## 3. Backend Setup (FastAPI)

```bash
# Create virtualenv
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with GCP (for Vertex AI, Firestore, etc.)
gcloud auth application-default login
gcloud config set project $GCP_PROJECT_ID
```

### Start Firestore Emulator

For local development, use the Firebase Firestore emulator instead of a real Firestore instance:

```bash
firebase init emulators  # select Firestore; port 8080
firebase emulators:start --only firestore
```

Set in `.env`:
```bash
FIRESTORE_EMULATOR_HOST=localhost:8080
```

### Run the Backend

```bash
uvicorn api.main:app --reload --port 8000
```

API will be available at `http://localhost:8000`. The backend serves the built PWA from `./static/` — for local dev, use the Vite dev server instead (see below).

---

## 4. Frontend Setup (Vue 3 PWA)

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://localhost:5173`. It proxies `/api` requests to `http://localhost:8000` (configured in `vite.config.ts`).

### Build the PWA

```bash
npm run build
# Output → frontend/dist/
```

---

## 5. WhatsApp Webhook (Local Dev)

WhatsApp needs a public HTTPS URL to deliver webhooks. Use [ngrok](https://ngrok.com) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps):

```bash
ngrok http 8000
# Copy the https URL, e.g. https://abc123.ngrok.io
```

Register the webhook in Meta Developer Portal:
- **Webhook URL**: `https://abc123.ngrok.io/webhook`
- **Verify Token**: value of `WHATSAPP_VERIFY_TOKEN` from `.env`
- **Subscribe to**: `messages`

---

## 6. Knowledge Base — Initial Seed

Before the system can generate useful drafts, the production Vertex AI Search index must be seeded from the midwife's existing chat exports.

```bash
# Parse WhatsApp export (.txt format)
python ingestion/parse_whatsapp.py \
  --input path/to/export.txt \
  --output ingestion/structured.jsonl

# Extract Q&A chunks via Gemini
python ingestion/extract_knowledge.py \
  --input ingestion/structured.jsonl \
  --output ingestion/chunks.jsonl

# Review chunks manually — delete bad ones from chunks.jsonl
# (expect to discard 30–50% — this is non-negotiable for KB quality)

# Index to staging first, review, then promote to production
python ingestion/index_to_vertex.py \
  --input ingestion/chunks.jsonl \
  --datastore $VERTEX_SEARCH_DATASTORE_STAGING

# After reviewing in the PWA KB Review screen, promote items to production:
python ingestion/index_to_vertex.py \
  --input ingestion/approved_chunks.jsonl \
  --datastore $VERTEX_SEARCH_DATASTORE_PRODUCTION
```

---

## 7. Docker Build (Combined Image)

```bash
docker build -t stilla-midwife-bot:dev .

docker run --env-file .env -p 8080:8080 stilla-midwife-bot:dev
```

Visit `http://localhost:8080` — the FastAPI backend serves the built Vue PWA.

---

## 8. VAPID Key Generation (One-Time)

```bash
npx web-push generate-vapid-keys
# Copy public + private keys into .env and Secret Manager
```

---

## 9. Running Tests

```bash
# Backend unit tests (no emulator needed)
pytest tests/unit/ -v

# Backend integration tests (requires Firestore emulator running)
FIRESTORE_EMULATOR_HOST=localhost:8080 pytest tests/integration/ -v

# Frontend tests
cd frontend && npm run test
```

---

## 10. Deploy to Cloud Run

All production deployments go via Cloud Build:

```bash
gcloud builds submit --config cloudbuild.yaml .
```

The `cloudbuild.yaml` builds the Docker image, pushes to Artifact Registry, and deploys to Cloud Run with `min-instances=1` in `europe-west1`.

Manual deploy (emergency hotfix only — document in incident log):

```bash
gcloud run deploy midwife-bot \
  --image gcr.io/$GCP_PROJECT_ID/midwife-bot:latest \
  --region europe-west1 \
  --min-instances 1 \
  --memory 1Gi \
  --set-secrets "WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,..."
```

---

## 11. GCP Audit Bucket Setup (One-Time)

```bash
# Create audit bucket with 7-year retention lock
gsutil mb -l europe-west1 gs://midwife-bot-audit-prod
gsutil retention set 7y gs://midwife-bot-audit-prod
gsutil retention lock gs://midwife-bot-audit-prod  # IRREVERSIBLE

# Dev bucket (no retention lock — allows cleanup)
gsutil mb -l europe-west1 gs://midwife-bot-audit-dev
```

---

## Key URLs (Local Dev)

| Service | URL |
|---------|-----|
| FastAPI backend | `http://localhost:8000` |
| API docs (Swagger) | `http://localhost:8000/docs` |
| Vue PWA (dev server) | `http://localhost:5173` |
| Firestore emulator UI | `http://localhost:4000` |
| ngrok tunnel | `https://<id>.ngrok.io` |
