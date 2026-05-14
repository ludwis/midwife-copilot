# Midwife Bot — Phase 4: Hardening, Deployment & Pilot

Reference plan: `midwife-assistant-bot-mvp-v4.md` in the project root.
Depends on Phases 1–3 being complete and all tests green.

Project root: `/Users/ad4m/Library/Mobile Documents/com~apple~CloudDocs/Projects/stilla-app`

---

## Part A — 24h Window Hardening

- [ ] Harden the 24h service window handling in `bot/conversation.py`. The function `is_window_open(conversation_id: str, db) -> bool` must already exist from Phase 2. Now ensure: (1) `record_outbound()` calls `update_window_timestamp()` so the window clock resets only on client inbound (not midwife outbound) — verify that `last_client_inbound_at` is set on `record_inbound()` and NOT touched by `record_outbound()`; (2) add `get_window_age(conversation_id: str, db) -> timedelta | None` returning time since last client inbound (or None if never). Update `api/routes/admin.py` `POST /api/admin/conversations/{id}/reply` to call `is_window_open()` before sending and return `409 {"error": "window_closed", "message": "24h window has expired. Use a re-engagement template to reopen."}`. Write `tests/bot/test_conversation_window.py` with at least 5 test cases: `is_window_open` returns True at 23h59m, False at 24h01m, False when never messaged, `get_window_age` returns correct timedelta, `record_outbound` does NOT update `last_client_inbound_at`. Run `pytest tests/bot/test_conversation_window.py` and confirm all pass.

- [ ] Add `PAUSED` and `HUMAN_ONLY` side-state handling to `_handle_inbound()` in `api/routes/webhook.py`. When a message arrives from an ACTIVE client: (1) check if message text is "STOP" (case-insensitive) → transition to `PAUSED`, send acknowledgment "You've been unsubscribed. Message RESTART to resume."; (2) check if message text is "HUMAN" → transition to `HUMAN_ONLY`, send acknowledgment "Noted. Your midwife will reply directly."; (3) if state is `PAUSED` and message is "RESTART" → transition back to `ACTIVE`; (4) if state is `PAUSED` (but not RESTART) → ignore message, no draft, no notification; (5) if state is `HUMAN_ONLY` → draft IS still generated and shown to midwife, but with a `human_only_flag: true` field on the inbox item so the midwife sees the client's preference. Write `tests/api/test_webhook_side_states.py` with at least 5 test cases (all mocked): STOP → PAUSED + ack sent, HUMAN → HUMAN_ONLY + ack sent, PAUSED + RESTART → ACTIVE, PAUSED + other message → no draft no notification, HUMAN_ONLY → draft generated with human_only_flag. Run `pytest tests/api/test_webhook_side_states.py` and confirm all pass.

---

## Part B — Integration Tests

- [ ] Write `tests/integration/test_onboarding_flow.py` — an end-to-end integration test for the full onboarding flow using `httpx.AsyncClient` with the real FastAPI app (but mocked GCP services: Firestore mock, Vertex AI mock, WhatsApp API mock). Test the complete sequence: (1) `POST /api/admin/clients` → receive wa.me link with token; (2) simulate inbound WhatsApp message containing the token → verify consent prompt is "sent" to mock WhatsApp adapter; (3) simulate client replying "YES" → verify state transitions to ACTIVE in mock Firestore; (4) simulate client sending a question → verify safety triage called, draft generated, audit log written, push notification sent. Assert each step's side effects. Run `pytest tests/integration/test_onboarding_flow.py -v` and confirm all pass.

- [ ] Write `tests/integration/test_reply_flow.py` — an end-to-end integration test for the midwife review + send flow using the same mock infrastructure. Test: (1) `GET /api/admin/conversations` returns the pending draft item; (2) `GET /api/admin/conversations/{id}` returns full thread with draft and citations; (3) `POST /api/admin/conversations/{id}/reply` with `source: "approved"` → verify WhatsApp adapter called with correct text, audit log records "outbound_approved", window timestamp updated; (4) `POST /api/admin/conversations/{id}/reply` after simulating 25h elapsed → verify 409 window_closed response; (5) `POST /api/admin/conversations/{id}/tag_kb` → verify chunk queued to staging datastore. Run `pytest tests/integration/test_reply_flow.py -v` and confirm all pass.

- [ ] Write `tests/integration/test_kb_review_flow.py` — integration test for the KB staging → production pipeline. Test: (1) `GET /api/admin/kb/staging` returns staged chunks; (2) `POST /api/admin/kb/staging/{id}/promote` calls production Vertex AI Search index and updates Firestore status to `promoted`; (3) `POST /api/admin/kb/staging/{id}/edit` with new question/answer then promotes with updated content; (4) `POST /api/admin/kb/staging/{id}/discard` updates status without indexing. Run `pytest tests/integration/test_kb_review_flow.py -v` and confirm all pass.

---

## Part C — Docker & Deployment

- [ ] Write the multi-stage `Dockerfile`. Stage 1 (builder): `FROM node:20-alpine AS builder`, copy `frontend/`, run `npm ci && npm run build`. Stage 2 (runtime): `FROM python:3.12-slim`, install Python dependencies from `requirements.txt`, copy `api/`, `bot/`, `adapters/`, `config/`, `ingestion/`, copy `--from=builder /app/frontend/dist ./frontend/dist`. Set `CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]`. Expose port 8080. Build the image locally with `docker build -t midwife-bot:local .` and verify it succeeds with no errors. Run `docker run --rm -e ADMIN_TOKEN=test midwife-bot:local uvicorn --version` to confirm the runtime works. Output the build and run results.

- [ ] Write `cloudbuild.yaml` for Google Cloud Build. It must: (1) build the Docker image and tag it `gcr.io/$PROJECT_ID/midwife-bot:$COMMIT_SHA`; (2) push the image; (3) deploy to Cloud Run with `--region=europe-west1`, `--min-instances=1`, `--memory=1Gi`, `--port=8080`, `--set-secrets` for all 6 secrets (WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN, ADMIN_TOKEN, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY). Also write a `Makefile` with targets: `make test` (runs pytest + vitest), `make build` (docker build), `make deploy` (gcloud builds submit). Verify `cloudbuild.yaml` is valid YAML by parsing it with Python: `python3 -c "import yaml; yaml.safe_load(open('cloudbuild.yaml'))"`. Output the result.

---

## Part D — Observability & Safety Nets

- [ ] Add structured logging throughout the backend. In `api/main.py`, add a startup event that logs `{"event": "startup", "version": git_sha_or_unknown}`. In `api/routes/webhook.py`, log every inbound webhook receipt with `message_id` and `from_number` (no PII in message text). In `api/routes/admin.py` reply endpoint, log every send with `conversation_id`, `source`, and `urgency`. All logs must use Python's `logging` module with a JSON formatter (create `config/logging.py` with a `setup_logging()` function). Add `setup_logging()` call to `api/main.py`. Write `tests/config/test_logging.py`: assert `setup_logging()` installs a JSON-format handler, assert log output is valid JSON. Run `pytest tests/config/test_logging.py` and confirm pass.

- [ ] Add a health check endpoint and basic observability to `api/main.py`. Expand `GET /health` (already returning `{"status": "ok"}`) to also return: `{"status": "ok", "version": str, "firestore": "ok"|"error", "vertex_search": "ok"|"error"}` by doing a lightweight probe of each dependency (Firestore: fetch a non-existent doc and confirm no exception; Vertex AI Search: confirm the client can be instantiated with current credentials). If any dependency probe fails, return `{"status": "degraded", ...}` with HTTP 200 (not 500 — Cloud Run health checks should not fail on partial degradation). Write `tests/api/test_health.py`: assert healthy response structure, assert degraded response when Firestore mock raises, assert HTTP status is always 200. Run `pytest tests/api/test_health.py` and confirm pass.

---

## Part E — Final Validation

- [ ] Run the complete backend test suite: `pytest tests/ -v --tb=short` from project root. Fix any failures. All tests across Phases 1–4 must be green. Output the final pytest summary with total passed/failed/skipped counts and elapsed time.

- [ ] Run the complete frontend test suite: `npx vitest run --reporter=verbose` from `frontend/`. Fix any failures. All Vitest tests must be green. Output the final summary.

- [ ] Run `npm run build` in `frontend/` and confirm the production bundle is generated in `frontend/dist/` with no TypeScript errors or Vite build warnings. Run `docker build -t midwife-bot:final .` and confirm the multi-stage build succeeds. Output both results.

---

**Manual steps after Phase 4 (human required — do not checkbox):**

- Deploy to Cloud Run: `gcloud builds submit --config cloudbuild.yaml`
- Configure WhatsApp webhook URL in Meta Developer Console to `https://{cloud-run-url}/webhook`
- Install the PWA on the pilot midwife's phone (Chrome/Safari → Add to Home Screen) and confirm Web Push notifications are received
- End-to-end smoke test with two real phones: midwife phone + test client phone
  - Generate invite link via PWA → share → client taps link → consent → send test question → midwife receives push → approves draft → client receives reply
- Confirm audit log entries appear in Cloud Logging
- Pilot midwife onboards 2–3 trusted clients
