# Research: Midwife Co-pilot MVP

**Phase**: 0 — Outline & Research  
**Date**: 2026-05-14  
**Status**: Complete — all NEEDS CLARIFICATION items resolved

---

## 1. WhatsApp Cloud API — Webhook & Send Patterns

**Decision**: Use Meta's WhatsApp Cloud API (Graph API v18+) with a HTTPS webhook endpoint registered in Meta Developer Portal.

**Rationale**: The webhook delivers inbound messages as JSON POST bodies. Signature verification (`X-Hub-Signature-256`) is mandatory and must happen before any payload processing. WhatsApp expects a 200 response within 5 seconds or it retries — the response must be immediate; all async work happens after ACK.

**Best practice for FastAPI**:
```python
# In webhook.py POST handler:
# 1. Verify signature immediately (HMAC-SHA256 of raw body)
# 2. Return 200 OK with {} immediately (before any processing)
# 3. Dispatch processing to a BackgroundTask (FastAPI) or fire-and-forget coroutine
```

**Retry behavior**: WhatsApp retries with exponential backoff (up to ~24h for persistent failures). Idempotency key is the `message.id` field — use this as Firestore document ID to prevent duplicate processing.

**Alternatives considered**: Twilio WhatsApp sandbox (rejected — adds cost layer, breaks direct Meta billing).

---

## 2. Vertex AI Search (Discovery Engine) — RAG Integration

**Decision**: Use `google-cloud-discoveryengine` Python SDK with two separate data stores: `midwife-staging` and `midwife-production` (both in `eu` multi-region, closest supported to europe-west1).

**Note on region**: Vertex AI Search data stores use multi-region identifiers (`eu`, `us`, `global`). Choose `eu` for GDPR residency. The serving config is `projects/{project}/locations/eu/collections/default_collection/dataStores/{datastore_id}/servingConfigs/default_serving_config`.

**Query pattern**:
```python
from google.cloud import discoveryengine_v1alpha as discoveryengine

client = discoveryengine.SearchServiceClient()
request = discoveryengine.SearchRequest(
    serving_config=serving_config_path,
    query=user_message,
    page_size=5,
    content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
        extract_config=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
            max_extractive_answer_count=3
        )
    )
)
response = client.search(request)
```

**Ingestion**: Use `DocumentServiceClient` to upsert chunks. Each chunk: `{ id, content: { text }, structData: { question, answer, source_date } }`. Bulk ingest via `import_documents` from GCS JSON Lines for the initial KB seed.

**Alternatives considered**: Pinecone (rejected — external service, GDPR residency complex, adds cost); AlloyDB pgvector (rejected — introduces new GCP service requiring justification per constitution); native Gemini grounding (rejected — future work per MVP scope table, requires Vertex AI Search datastore to be linked at LLM level, not yet stable in EU).

---

## 3. Gemini 2.0 Flash — Draft Generation & Safety Classifier

**Decision**: Two separate Gemini calls per inbound message:
1. **Safety triage** (fast, cheap): classify urgency level before any retrieval.
2. **Draft generation** (only for non-urgent): RAG-grounded reply with citations.

**Urgency scale** (4 levels, as required by Constitution IV):
- `URGENT` — potential emergency (pain, bleeding, fetal movement concerns, fever)
- `HIGH` — time-sensitive but not emergency (e.g., strong contractions, vomiting)
- `NORMAL` — routine questions, reassurance-seeking
- `LOW` — admin / scheduling / non-clinical

Only `NORMAL` and `LOW` trigger draft generation. `URGENT` and `HIGH` go directly to midwife inbox with no draft and priority push notification.

**System prompt for draft generation**:
```
You are a knowledgeable midwifery assistant. Answer ONLY using the reference material provided below. 
Cite each piece of information with [Source N] markers matching the provided sources.
If the reference material does not contain sufficient information, say: 
"I don't have a clear reference for this — the midwife will reply directly."
Do not speculate or add information not present in the sources.
```

**SDK choice**: `google-cloud-aiplatform` (`vertexai` SDK), initialized with `vertexai.init(project=PROJECT_ID, location="europe-west1")`.

**Alternatives considered**: OpenAI GPT-4o (rejected — non-EU data residency, separate billing, constitution locks Vertex AI); Claude API (rejected — same reasons).

---

## 4. Firestore State Machine

**Decision**: Use Firestore native (not Datastore mode) in `europe-west1`. Each entity maps to a collection. Firestore transactions for state transitions to prevent race conditions (e.g., double-consent).

**Collections**:
- `clients` — client profiles + state
- `conversations` — one doc per client (holds message subcollection)
- `conversations/{id}/messages` — ordered messages
- `conversations/{id}/drafts` — current draft (overwritten per message cycle)
- `push_subscriptions` — VAPID endpoint registrations
- `kb_staging` — staged Q&A items

**State transitions use Firestore transactions**:
```python
@firestore.async_transactional
async def transition_to_active(transaction, client_ref, consent_data):
    client = await client_ref.get(transaction=transaction)
    if client.get("state") != "awaiting_consent":
        raise ValueError("Invalid transition")
    transaction.update(client_ref, {"state": "active", "consent": consent_data})
```

**Alternatives considered**: PostgreSQL (rejected — requires Cloud SQL, adds a managed DB service not in constitution); Redis (rejected — not persistent, not justified).

---

## 5. VAPID Web Push — FastAPI Integration

**Decision**: Use `pywebpush` library for server-side VAPID push. Generate VAPID key pair once, store in Google Secret Manager.

**Flow**:
1. PWA calls `navigator.serviceWorker.pushManager.subscribe({ applicationServerKey: VAPID_PUBLIC_KEY, userVisibleOnly: true })`
2. PWA POSTs subscription object to `POST /api/admin/push/subscribe` → stored in `push_subscriptions` Firestore collection
3. Backend calls `webpush(subscription_info, message_body, vapid_private_key, vapid_claims)` from `pywebpush`

**Priority headers for urgent notifications**:
```python
webpush(
    subscription_info=sub,
    data=json.dumps(payload),
    vapid_private_key=VAPID_PRIVATE_KEY,
    vapid_claims={"sub": "mailto:admin@stilla.app"},
    headers={"Urgency": "high"}  # RFC 8030
)
```

**iOS caveat**: Web Push on iOS requires PWA installed to home screen (iOS 16.4+). Validate with pilot midwife in week 3. Android has no restriction.

**Alternatives considered**: Firebase Cloud Messaging (FCM) (rejected — requires Google account per device, adds complexity, VAPID is simpler for PWA-only use).

---

## 6. Single-Artifact Docker Build (Multi-Stage)

**Decision**: Multi-stage Dockerfile: Stage 1 builds the Vue 3 PWA (`node:20-alpine`), Stage 2 is the Python FastAPI runtime (`python:3.12-slim`). The built `frontend/dist/` is copied into the Python image and mounted as static files in FastAPI.

```dockerfile
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=frontend-build /app/frontend/dist ./static
COPY api/ bot/ adapters/ config/ ingestion/ ./
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

FastAPI serves static files via `StaticFiles("/static")` with a catch-all route returning `index.html` for client-side routing.

**Alternatives considered**: Separate Cloud Run service for frontend (rejected — violates Constitution VI).

---

## 7. 24-Hour Window Enforcement

**Decision**: Track `last_client_inbound_at` (UTC timestamp) on the `clients` Firestore document. On every `POST /api/admin/conversations/{id}/reply` call, the backend checks `(now - last_client_inbound_at) > 24h` before calling `send_message()`. If exceeded, return `HTTP 422` with body `{ "error": "window_closed", "last_inbound_at": "..." }`. Frontend displays the blocked state.

**Alternatives considered**: State machine `window_closed` state (considered, too coarse — the window re-opens on client inbound, so real-time check at send is cleaner than a cron-based state transition).

---

## 8. Audit Log Architecture

**Decision**: Dual write — Cloud Logging (structured JSON log entries) + GCS bucket (europe-west1, 7-year retention lock). Cloud Logging for real-time search/alerting; GCS for tamper-evident long-term storage.

**GCS write pattern**: Append a newline-delimited JSON record to a file per day (`YYYY/MM/DD/audit.jsonl`). Use GCS object versioning; object retention lock prevents deletion.

**Log record schema**:
```json
{
  "event_type": "inbound_message" | "ai_draft" | "outbound_message",
  "timestamp": "ISO-8601",
  "client_id": "...",
  "conversation_id": "...",
  "message_id": "...",
  "body": "...",
  "urgency": "...",        // inbound only
  "action_type": "...",   // outbound only: approved|edited|original
  "draft_id": "..."       // outbound only if AI-drafted
}
```

**Alternatives considered**: BigQuery for audit (rejected — introduces new GCP service without constitution justification; Cloud Logging + GCS is sufficient for compliance).

---

## 9. Testing Strategy

**Decision**: 
- **Integration tests** use `firebase-tools` Firestore emulator (`firebase emulators:start`) for all state-critical paths (state transitions, audit writes, 24h window). Required by constitution pre-merge gate.
- **Unit tests** for pure logic: urgency classifier prompts, state machine transition rules, window calculation.
- **No mocks for Firestore** — emulator only, per constitution and dev workflow gate.

**Vertex AI Search / Gemini tests**: Use recorded HTTP fixtures (VCR pattern via `pytest-recording`) for unit tests; real API calls in a dedicated integration suite guarded by `INTEGRATION=true` env flag.

---

## 10. Open Risks (from MVP doc — tracked, not resolved in code)

| Risk | Mitigation |
|------|-----------|
| Meta WhatsApp approval for healthcare | Start verification immediately (Week 1); have Telegram adapter as fallback plan |
| iOS PWA push reliability | Validate with pilot midwife device in Week 3 before hardening |
| KB quality from single export | Manual review of first 20 chunks (non-negotiable per MVP build sequence) |
| Regulatory gate (MDR/GDPR/EU AI Act) | Hard gate before public pilot — tracked in constitution governance |
| Bus factor (one midwife offline) | Out of MVP scope — post-MVP escalation path |
