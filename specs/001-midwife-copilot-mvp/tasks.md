# Tasks: Midwife Assistant Co-pilot Bot MVP

**Input**: Design documents from `/specs/001-midwife-copilot-mvp/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/admin-api.yaml ✅ quickstart.md ✅

**Tests**: Not requested in spec — test tasks are omitted. Integration tests using Firestore emulator are included as part of infra setup only (per research.md testing strategy).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. US1 is the MVP — all other stories extend it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- All file paths are relative to repository root

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create project skeleton, build tooling, and local dev infrastructure. No application logic yet.

- [ ] T001 Create full directory structure per plan.md: `api/routes/`, `bot/`, `adapters/`, `config/`, `ingestion/`, `frontend/src/{views,components,stores,pwa}/`, `tests/{unit,integration}/`
- [ ] T002 [P] Create `requirements.txt` with all Python backend dependencies: `fastapi`, `uvicorn[standard]`, `google-cloud-aiplatform`, `google-cloud-discoveryengine`, `google-cloud-firestore`, `google-cloud-logging`, `google-cloud-storage`, `pywebpush`, `httpx`, `pydantic-settings`, `pytest`, `pytest-asyncio`
- [ ] T003 [P] Initialize frontend: `frontend/package.json` with `vue@3`, `vite`, `vite-plugin-pwa`, `pinia`, `vue-router`, `tailwindcss`, `typescript`, `qrcode`, `@types/qrcode`; create `frontend/tsconfig.json` and `frontend/tailwind.config.ts`
- [ ] T004 [P] Create multi-stage `Dockerfile`: Stage 1 `node:20-alpine` builds Vue PWA from `frontend/`; Stage 2 `python:3.12-slim` installs deps, copies `api/ bot/ adapters/ config/ ingestion/` and `frontend/dist → ./static`; CMD `uvicorn api.main:app --host 0.0.0.0 --port 8080`
- [ ] T005 [P] Create `cloudbuild.yaml` for Cloud Build: docker build → push to Artifact Registry → deploy to Cloud Run `europe-west1` with `min-instances=1`, `memory=1Gi`, secrets from Secret Manager
- [ ] T006 [P] Create `.env.example` documenting all required env vars: `GCP_PROJECT_ID`, `GCP_REGION`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `ADMIN_TOKEN`, `VERTEX_SEARCH_DATASTORE_PRODUCTION`, `VERTEX_SEARCH_DATASTORE_STAGING`, `VERTEX_SEARCH_LOCATION`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `AUDIT_BUCKET_NAME`, `FIRESTORE_EMULATOR_HOST` (optional)
- [ ] T007 [P] Configure Firebase emulator for local dev: create `firebase.json` (Firestore emulator on port 8080) and `.firebaserc` with project ID; document `firebase emulators:start --only firestore` in quickstart reference
- [ ] T008 [P] Create `frontend/vite.config.ts`: configure Vite dev server proxy (`/api → localhost:8000`), `vite-plugin-pwa` with service worker, VAPID public key injection via `define`
- [ ] T009 [P] Create `frontend/manifest.webmanifest`: name, short_name, icons (192/512 maskable), `display: standalone`, `background_color`, `theme_color` for PWA home screen install

**Checkpoint**: Repository has correct structure, dependencies declared, build toolchain configured — nothing runs yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented. No user story tasks should begin until this phase is complete.

**⚠️ CRITICAL**: Foundational phase blocks all user story phases.

- [ ] T010 Create `config/settings.py` with `pydantic-settings` `Settings` class loading all env vars from `.env`; export a singleton `settings` instance used by all modules
- [ ] T011 [P] Create `adapters/base.py` with abstract `MessageChannel` interface defining `async send_message(to: str, body: str) -> str` — returns WhatsApp message ID; no other public methods
- [ ] T012 Create `adapters/whatsapp.py` implementing `MessageChannel`; uses `httpx.AsyncClient` to call WhatsApp Cloud API `POST /v18.0/{phone_number_id}/messages`; reads `settings.WHATSAPP_TOKEN` and `settings.WHATSAPP_PHONE_NUMBER_ID`; **must not be importable from `bot/` modules** (enforces Constitution II)
- [ ] T013 [P] Create `bot/audit.py` with `async write_audit_event(event: dict)` performing dual-write: (1) structured JSON log entry via `google-cloud-logging`; (2) append newline-delimited JSON to GCS path `gs://{AUDIT_BUCKET_NAME}/{YYYY}/{MM}/{DD}/audit.jsonl` using `google-cloud-storage`; three event schemas from data-model.md (`inbound_message`, `ai_draft`, `outbound_message`)
- [ ] T014 Create `api/main.py`: instantiate `FastAPI` app; include routers from `api/routes/webhook.py`, `api/routes/admin.py`, `api/routes/ask.py`; mount `StaticFiles("./static", html=True)` with catch-all route returning `index.html` for client-side routing; add `/health` endpoint returning `{"status": "ok"}`
- [ ] T015 Create `api/routes/webhook.py` — GET handler: verify `hub.mode`, `hub.verify_token` against `settings.WHATSAPP_VERIFY_TOKEN`, echo `hub.challenge`; POST handler skeleton: verify `X-Hub-Signature-256` HMAC-SHA256 against raw request body, return `{}` 200 immediately, dispatch processing to `BackgroundTask` (actual processing added in US1/US2 phases)
- [ ] T016 [P] Implement Bearer token auth dependency in `api/routes/admin.py` header: `Depends` function that reads `Authorization: Bearer <token>`, compares to `settings.ADMIN_TOKEN`, raises `HTTP 401` on mismatch; all admin routes use this dependency
- [ ] T017 [P] Create `frontend/src/api/admin.ts`: typed `fetch` wrapper for all Admin API endpoints; reads `VITE_ADMIN_TOKEN` env var for `Authorization: Bearer` header; exports typed async functions matching OpenAPI `admin-api.yaml` operationIds; handle 401/422/404 error shapes from `ErrorResponse` schema
- [ ] T018 Create `frontend/src/main.ts`, `frontend/src/App.vue`, and `frontend/src/router/index.ts`: Vue 3 app init with `createApp`, `createPinia`, `createRouter`; define route stubs for `/` (InboxView), `/conversation/:id` (ConversationView), `/clients` (ClientsView), `/kb-review` (KBReviewView)

**Checkpoint**: Backend starts (`uvicorn api.main:app --reload`), webhook verification passes, auth middleware rejects unauthorized requests, frontend dev server starts — no business logic yet.

---

## Phase 3: User Story 1 — Midwife Reviews and Sends AI-Drafted Reply (Priority: P1) 🎯 MVP

**Goal**: End-to-end flow — client sends WhatsApp message → midwife receives push notification → sees message + AI draft in inbox → approves/edits/writes own reply → message delivered to client.

**Independent Test**: Send a message to a test client's WhatsApp number. Verify: (1) midwife receives push notification within 30s; (2) inbox shows message with AI-drafted reply + citations; (3) approving sends the draft to the client; (4) audit log contains `inbound_message`, `ai_draft`, and `outbound_message` events.

### Bot Layer

- [ ] T019 [P] [US1] Create `bot/safety.py`: async `classify_urgency(message_body: str) -> UrgencyLevel` using Gemini 2.0 Flash via `google-cloud-aiplatform` `vertexai` SDK (`vertexai.init(project, location="europe-west1")`); prompt classifies into `urgent | high | normal | low` per research.md urgency definitions; returns `UrgencyLevel` enum
- [ ] T020 [P] [US1] Create `bot/retriever.py`: async `retrieve_context(query: str) -> list[Citation]` using `google-cloud-discoveryengine` `SearchServiceClient`; queries production data store at `projects/{project}/locations/eu/collections/default_collection/dataStores/{VERTEX_SEARCH_DATASTORE_PRODUCTION}/servingConfigs/default_serving_config`; extracts `chunk_id` and `snippet` from extractive answers; returns list of `Citation` objects (max 5 results)
- [ ] T021 [US1] Create `bot/generator.py`: async `generate_draft(message_body: str, citations: list[Citation]) -> str` using Gemini 2.0 Flash; constructs prompt with system prompt from research.md (citation-grounded, no speculation); returns draft body text with `[Source N]` citation markers
- [ ] T022 [US1] Create `bot/conversation.py` with Firestore state machine functions: `async store_inbound_message(client_id, message_id, body, urgency, timestamp)` — creates `conversations/{id}` doc if absent, writes to `conversations/{id}/messages`, updates `conversations.current_urgency` and `clients.last_client_inbound_at` via Firestore transaction; `async store_draft(conversation_id, draft_body, urgency, citations, source_message_id)` — writes to `conversations/{id}/drafts`, sets `conversations.current_draft_id`; `async action_draft(conversation_id, draft_id, status)` — updates draft status to `approved|edited|discarded`, clears `current_draft_id`; `async transition_to_active(client_ref, consent_data: dict)` — Firestore transaction: sets `clients.state = active`, writes `clients.consent = {message_id, timestamp, verbatim_reply}` from consent_data (called by T041); `async transition_state(client_id: str, new_state: str)` — updates `clients.state` to new_state (e.g. `paused`, `archived`), sets `clients.state_updated_at = now()` (called by T066 for STOP/HUMAN and T039 archive flow)

### Push Notification Service

- [ ] T023 [US1] Create `bot/pusher.py`: async `send_push(payload: dict, urgency: str = "normal")` that loads all docs from Firestore `push_subscriptions` collection and calls `pywebpush` `webpush()` for each subscription with VAPID keys from `settings`; for `urgency="high"` adds `headers={"Urgency": "high"}` per RFC 8030; handles stale subscription cleanup on 410 responses

### Webhook Processing Pipeline

- [ ] T024 [US1] Implement inbound processing pipeline as async `process_inbound(payload: dict)` in `api/routes/webhook.py` BackgroundTask: (1) parse WhatsApp message payload; (2) look up client by phone number in Firestore; (3) call `audit.write_audit_event` with `inbound_message` event; (4) call `safety.classify_urgency`; (5) call `conversation.store_inbound_message`; (6) if urgency is `normal` or `low`: call `retriever.retrieve_context` → `generator.generate_draft` → `conversation.store_draft` → `audit.write_audit_event` with `ai_draft`; (7) call `pusher.send_push` with urgency level; skip steps 6 for `urgent`/`high` (US3 will add visual treatment)

### Admin API Routes (US1)

- [ ] T025 [US1] Implement `GET /api/admin/conversations` in `api/routes/admin.py`: query Firestore `conversations` collection ordered by urgency (`urgent`/`high` first) then `updated_at` desc; join with `clients` to build `ConversationSummary` array; return inbox items per `admin-api.yaml` `listConversations` operation
- [ ] T026 [US1] Implement `GET /api/admin/conversations/{conversation_id}` in `api/routes/admin.py`: fetch conversation doc + messages subcollection (ordered by timestamp) + current draft from drafts subcollection; compute `window_open = (now - client.last_client_inbound_at) < 24h`; return `ConversationDetail` per schema
- [ ] T027 [US1] Implement `POST /api/admin/conversations/{conversation_id}/reply` in `api/routes/admin.py`: (1) fetch conversation + client; (2) enforce 24h window: `if (now - last_client_inbound_at) > 24h → return HTTP 422 {"error": "window_closed", "last_inbound_at": ...}`; (3) check client state is `active`; (4) call `adapters/whatsapp.send_message`; (5) write outbound message to `conversations/{id}/messages`; (6) call `audit.write_audit_event` with `outbound_message`; (7) call `conversation.action_draft` with appropriate status; return `ReplyResponse`
- [ ] T028 [US1] Implement `POST /api/admin/push/subscribe` (store in `push_subscriptions`) and `DELETE /api/admin/push/subscribe` (remove by endpoint hash) in `api/routes/admin.py`; document ID = SHA256 of endpoint URL

### Frontend (US1)

- [ ] T029 [P] [US1] Create `frontend/src/stores/conversations.ts` Pinia store: `fetchInbox()` → calls `listConversations`; `fetchConversation(id)` → calls `getConversation`; `sendReply(id, text, source)` → calls `sendReply`; expose `inbox`, `current`, loading/error state; handle 422 window-closed error shape
- [ ] T030 [P] [US1] Create `frontend/src/components/UrgencyBadge.vue`: props `urgency: 'urgent'|'high'|'normal'|'low'`; Tailwind color mapping: urgent=red-600, high=orange-500, normal=green-500, low=gray-400; shows label text + colored dot
- [ ] T031 [P] [US1] Create `frontend/src/components/MessageBubble.vue`: props `message: Message`; render inbound messages left-aligned, outbound right-aligned; show `UrgencyBadge` for inbound; show `action_type` label for outbound; Tailwind styled chat bubble layout
- [ ] T032 [US1] Create `frontend/src/components/DraftCard.vue`: props `draft: AIDraft`; render an "AI Draft" badge/pill at the top of the card (Constitution IX — visible AI-authorship indicator); render draft body text; collapsible citations panel (shows `snippet` for each citation); three action buttons: "Approve & Send" (`source: approved`), "Edit" (inline textarea with draft pre-filled, `source: edited`), "Write Own" (clear textarea, `source: original`); emits `reply(text, source)`; hides entirely when `draft` is null
- [ ] T033 [US1] Create `frontend/src/views/InboxView.vue`: use `conversations` store `fetchInbox()` on mount; render list of `ConversationSummary` cards; show `UrgencyBadge`, client name, message preview, `has_pending_draft` indicator; tap navigates to `ConversationView`; pull-to-refresh or polling every 30s
- [ ] T034 [US1] Create `frontend/src/views/ConversationView.vue`: load conversation by route param `id`; render `MessageBubble` list; show `DraftCard` when `current_draft` exists; handle `reply` emit → `store.sendReply` → refresh conversation; show send spinner and error states
- [ ] T035 [US1] Create `frontend/src/pwa/push.ts`: `subscribeToPush()` using `navigator.serviceWorker.pushManager.subscribe({applicationServerKey: VAPID_PUBLIC_KEY, userVisibleOnly: true})`; POST subscription object to `POST /api/admin/push/subscribe`; call on PWA install and on first inbox load; create `frontend/src/pwa/sw.ts` service worker handling `push` events (show notification with `showNotification`, on `notificationclick` open `/`)

**Checkpoint (MVP)**: User Story 1 fully functional. Send test message → push notification arrives → inbox shows draft → approve → WhatsApp delivers message → audit log has all 3 events.

---

## Phase 4: User Story 2 — Client Onboarding via Tokenized Link (Priority: P2)

**Goal**: Midwife creates a client record, shares invite link, client taps link in WhatsApp, system registers client and sends consent prompt, client replies YES and reaches active state.

**Independent Test**: Create a new client in ClientsView, copy the generated link, send it from a test phone, confirm client moves from `pending_invite` → `awaiting_consent` → `active` in the client list.

### Bot Layer

- [ ] T036 [P] [US2] Create `bot/onboarding.py`: `generate_invite(client_id: str, phone_number: str) -> (token: str, link: str)` — generates UUID4 token, builds `wa.me/{WHATSAPP_PHONE_NUMBER_ID}?text={token}` link; `CONSENT_PROMPT_TEXT` constant with AI disclosure + "Reply YES to proceed" message text. **No imports from `adapters/`** — this module is pure business logic (Constitution II). Sending the consent prompt is the caller's responsibility (see T040).

### Admin API Routes (US2)

- [ ] T037 [US2] Implement `POST /api/admin/clients` in `api/routes/admin.py`: validate `CreateClientRequest` (name, phone_number E.164, due_date); check no active client with same phone number (HTTP 409); call `onboarding.generate_invite`; write `clients` Firestore doc with state=`pending_invite`, `invite_token`, `invite_link`, `created_at`; create empty `conversations/{client_id}` doc; return `Client` schema with `invite_link`
- [ ] T038 [P] [US2] Implement `GET /api/admin/clients` (with optional `?state=` filter) and `GET /api/admin/clients/{client_id}` in `api/routes/admin.py`; query Firestore `clients` collection accordingly; return `Client` array / single `Client`
- [ ] T039 [US2] Implement `POST /api/admin/clients/{client_id}/archive` in `api/routes/admin.py`: set `clients.state = archived`, `archived_at = now()` via Firestore; return updated `Client`

### Webhook — Onboarding Flows

- [ ] T040 [US2] Extend `process_inbound` in `api/routes/webhook.py`: after client lookup — if client not found by phone number, check `clients` collection for matching `invite_token` in message body; on match: link phone to client, set state=`awaiting_consent`, call `adapters/whatsapp.send_message(phone_number, onboarding.CONSENT_PROMPT_TEXT)` **directly from the route handler** (not from `bot/` — Constitution I requires all `send_message()` calls to originate in `api/routes/`), write audit event; guard: if token already used (state != `pending_invite`), ignore
- [ ] T041 [US2] Extend `process_inbound`: if client state is `awaiting_consent` — check if body is "YES" (case-insensitive trim); on YES: call `conversation.transition_to_active(client_ref, consent_data)`, record `consent.message_id`, `consent.timestamp`, `consent.verbatim_reply`; on non-YES: call `adapters/whatsapp.send_message(phone_number, onboarding.CONSENT_PROMPT_TEXT)` directly from the route handler (same dispatch pattern as T040 — no bot/ adapter calls; same prompt text resent, no separate retry template per spec.md §Fixed MVP Content); write audit events for both paths

### Frontend (US2)

- [ ] T042 [P] [US2] Create `frontend/src/stores/clients.ts` Pinia store: `fetchClients(state?)` → `listClients`; `createClient(data)` → `createClient`; `archiveClient(id)` → `archiveClient`; expose `clients` list, `inviteLink` (most recently created), loading/error state
- [ ] T043 [P] [US2] Create `frontend/src/components/InviteLinkModal.vue`: props `link: string`; display full `wa.me` URL; QR code generated client-side (use `qrcode` npm package or `<canvas>` with `qrcode` lib); Copy to clipboard button; close button
- [ ] T044 [US2] Create `frontend/src/views/ClientsView.vue`: list clients from store; filter tabs by state (active, pending, archived); "Add Client" form (name, phone, due date) → `store.createClient` → show `InviteLinkModal` on success; "Archive" action per client row

**Checkpoint**: User Story 2 functional. Creating a client generates a link, client can onboard via WhatsApp to active state.

---

## Phase 5: User Story 3 — Urgent Message Escalation Without AI Draft (Priority: P3)

**Goal**: High/urgent messages bypass AI drafting entirely, appear in inbox highlighted in red with no draft card, and trigger a priority push notification.

**Independent Test**: Send a message with urgency signals ("severe pain", "heavy bleeding") and confirm: inbox shows item as urgent with red styling and no draft; push notification arrives with distinct priority; ConversationView shows direct reply input only.

- [ ] T045 [US3] Update `process_inbound` in `api/routes/webhook.py`: when urgency is `urgent` or `high`, explicitly call `conversation.store_inbound_message` with urgency flag and ensure `conversations.current_draft_id = null` (never set); verify no call to `retriever.retrieve_context` or `generator.generate_draft` occurs on this path
- [ ] T046 [US3] Confirm `pusher.send_push` in `bot/pusher.py` includes `headers={"Urgency": "high"}` for `urgent`/`high` messages, `headers={"Urgency": "normal"}` for `normal`/`low`; update push payload body to include `urgency` field so service worker can customize notification title
- [ ] T047 [P] [US3] Update `frontend/src/views/InboxView.vue`: sort urgent/high items to top of list; apply red background (`bg-red-50 border-red-500`) for urgent, orange (`bg-orange-50 border-orange-400`) for high; show "No draft — respond directly" label instead of draft indicator; ensure no `DraftCard` is instantiated for urgent items
- [ ] T048 [US3] Update `frontend/src/views/ConversationView.vue`: when `current_draft === null` and current message urgency is `urgent`/`high`, show direct reply textarea immediately visible (no need to tap "Write Own"); show `UrgencyBadge` prominently at top of view; suppress `DraftCard` entirely

**Checkpoint**: User Story 3 functional. Urgent messages surface to midwife immediately with no AI draft, with distinct visual and notification treatment.

---

## Phase 6: User Story 4 — Knowledge Base Tagging and Staging Review (Priority: P4)

**Goal**: After sending a reply, midwife can tag the Q&A pair for KB staging. She can review, promote, edit, or discard staged items. Promoted items become available for future AI draft generation.

**Independent Test**: Tag a sent reply → navigate to KBReviewView → item appears as pending → promote it → verify it exists in production Vertex AI Search index within 24h.

### Bot Layer

- [ ] T049 [P] [US4] Create `bot/kb_feedback.py`: `async upsert_to_staging(question: str, answer: str, chunk_id: str)` — uses `google-cloud-discoveryengine` `DocumentServiceClient` to upsert document to `VERTEX_SEARCH_DATASTORE_STAGING`; `async promote_to_production(question: str, answer: str, chunk_id: str)` — upserts to `VERTEX_SEARCH_DATASTORE_PRODUCTION`; document schema matches data-model.md Vertex AI Search document format

### Admin API Routes (US4)

- [ ] T050 [US4] Implement `POST /api/admin/conversations/{conversation_id}/tag_kb` in `api/routes/admin.py`: find most recent outbound message in conversation; check not already tagged (HTTP 409); create `kb_staging` Firestore doc with `question` (preceding inbound body), `answer` (outbound body), status=`pending`; set `tagged_for_kb=true` on outbound message; call `kb_feedback.upsert_to_staging`; return `StagedKBItem`
- [ ] T051 [P] [US4] Implement `GET /api/admin/kb/staging` in `api/routes/admin.py`: query `kb_staging` collection where `status == pending` ordered by `staged_at` desc; return `StagedKBItem` array
- [ ] T052 [US4] Implement `POST /api/admin/kb/staging/{item_id}/promote` in `api/routes/admin.py`: fetch staged item; check status is `pending` (HTTP 409 otherwise); call `kb_feedback.promote_to_production`; update `kb_staging` doc: `status=promoted`, `actioned_at=now()`, `production_chunk_id`; return updated `StagedKBItem`
- [ ] T053 [US4] Implement `POST /api/admin/kb/staging/{item_id}/edit` in `api/routes/admin.py`: accept `{question?, answer}` body; update staged item fields; call `kb_feedback.promote_to_production` with new content; set status=`promoted`; return updated `StagedKBItem`
- [ ] T054 [US4] Implement `POST /api/admin/kb/staging/{item_id}/discard` in `api/routes/admin.py`: set `status=discarded`, `actioned_at=now()`; do NOT call Vertex AI (item never enters production); return updated `StagedKBItem`

### Frontend (US4)

- [ ] T055 [P] [US4] Create `frontend/src/stores/kbStaging.ts` Pinia store: `fetchStagingQueue()` → `listStagingQueue`; `promote(id)` → `promoteStagedItem`; `editAndPromote(id, data)` → `editAndPromoteStagedItem`; `discard(id)` → `discardStagedItem`; expose `queue`, loading/error state
- [ ] T056 [US4] Create `frontend/src/views/KBReviewView.vue`: list pending staged items from store; for each item show question, answer, `staged_at` date; action buttons "Promote", "Edit & Promote" (inline edit for answer text), "Discard"; add route `/kb-review` to router
- [ ] T057 [US4] Update `frontend/src/views/ConversationView.vue`: add "Tag for KB" button visible after a reply has been sent (outbound message visible); button calls `store.tagForKB(conversation_id)`; disable if already tagged (`tagged_for_kb=true`); show success/error toast

**Checkpoint**: User Story 4 functional. KB feedback loop complete — midwife can tag, review, and promote Q&A pairs to production retrieval index.

---

## Phase 7: User Story 5 — 24-Hour Window State Enforcement (Priority: P5)

**Goal**: Midwife cannot send freeform messages when more than 24 hours have passed since the client's last inbound message. System shows a clear explanation and blocks the send action.

**Independent Test**: Manually set a test client's `last_client_inbound_at` to 25 hours ago in Firestore. Attempt to send a reply via ConversationView. Confirm send is disabled with correct warning message. Send a new inbound test message. Confirm send becomes available again.

- [ ] T058 [US5] Verify `bot/conversation.py` `store_inbound_message` correctly updates `clients.last_client_inbound_at` to message timestamp on every inbound message; add this update to the Firestore transaction used for state updates
- [ ] T059 [US5] Verify `POST /api/admin/conversations/{id}/reply` in `api/routes/admin.py` (T027) correctly returns `HTTP 422 {"error": "window_closed", "last_inbound_at": "..."}` when `(now - client.last_client_inbound_at) > timedelta(hours=24)`; ensure `window_closed` state does NOT block reading the conversation or showing messages — only sending
- [ ] T060 [US5] Verify `GET /api/admin/conversations/{id}` (T026) correctly computes `window_open` boolean in response; `window_open = last_client_inbound_at is not None and (now - last_client_inbound_at) < timedelta(hours=24)`
- [ ] T061 [P] [US5] Update `frontend/src/views/ConversationView.vue`: when `conversation.window_open === false`, disable all reply inputs and send buttons; show banner "24-hour reply window has closed. Wait for the client to message first." with `last_client_inbound_at` time displayed; update `frontend/src/stores/conversations.ts` to expose `windowOpen` computed from `current.window_open`

**Checkpoint**: User Story 5 functional. Window enforcement works end-to-end: backend blocks send, frontend shows clear warning, window reopens automatically on new client message.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Ingestion tooling, additional safety handling, logging hardening, and deployment validation.

- [ ] T062 [P] Create `ingestion/parse_whatsapp.py`: parse WhatsApp `.txt` export format into structured JSON Lines `{timestamp, direction, body}` per exchange; CLI: `--input export.txt --output structured.jsonl`
- [ ] T063 [P] Create `ingestion/extract_knowledge.py`: read structured JSONL, batch-call Gemini to extract Q&A chunks from midwife-client exchanges; CLI: `--input structured.jsonl --output chunks.jsonl`; include confidence score in output to aid manual review
- [ ] T064 [P] Create `ingestion/index_to_vertex.py`: read chunks JSONL, upsert to specified data store using `DocumentServiceClient`; CLI: `--input chunks.jsonl --datastore {staging|production}`; idempotent (upsert by chunk ID)
- [ ] T065 [P] Create `api/routes/ask.py` for `POST /ask`: accepts `{user_id, message, conversation_id?}`; calls `safety.classify_urgency` → `retriever.retrieve_context` → `generator.generate_draft`; returns `{draft, urgency, sources, requires_review: true}`; Bearer token protected; does NOT call `send_message` (co-pilot gate always open). **Scope note**: Internal developer/testing utility and foundation for future third-party integrations; not exposed to end users or the PWA in MVP. No user story dependency — deprioritise below US1–US5 if time-constrained.
- [ ] T066 [P] Add STOP and HUMAN keyword handling to `process_inbound` in `api/routes/webhook.py`: on "STOP" → call `conversation.transition_state(client_id, "paused")`, send push to midwife, skip draft; on "HUMAN" → set `clients.human_only_preference = true`, continue normal routing, surface flag in `ConversationSummary`; show `human_only_preference` flag in `ConversationView.vue` header
- [ ] T067 [P] Replace all `print` / basic logging calls with structured `google-cloud-logging` entries throughout `api/`, `bot/`, `adapters/`; add `client_id` and `conversation_id` to all log entries where available for Logs Explorer correlation
- [ ] T068 Add idempotency guard to `process_inbound` in `api/routes/webhook.py`: before any processing, attempt to write WhatsApp `message.id` as Firestore document ID; if write fails (already exists), return immediately without reprocessing (handles WhatsApp retries)
- [ ] T069 [P] Validate `quickstart.md` end-to-end: run `docker build`, `docker run`, confirm health endpoint responds, Firestore emulator connects, webhook verification passes; update quickstart if any step is stale

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately; all T001–T009 tasks are independent
- **Foundational (Phase 2)**: Depends on Phase 1 completion; T010–T018 must complete before any user story work
- **US1 (Phase 3)**: Depends on Phase 2; this is the MVP — complete before starting US2–US5
- **US2 (Phase 4)**: Depends on Phase 2; can start in parallel with US1 if staffed; shares webhook handler file
- **US3 (Phase 5)**: Depends on US1 (extends webhook pipeline and frontend views from US1)
- **US4 (Phase 6)**: Depends on US1 (KB tagging is a post-reply action); shares admin routes and conversation views
- **US5 (Phase 7)**: Depends on US1 (verifies window enforcement already scaffolded in reply endpoint)
- **Polish (Phase 8)**: Can begin incrementally once US1 is stable

### User Story Dependencies

- **US1 (P1)**: No dependencies on other stories — implement first
- **US2 (P2)**: No hard dependency on US1 (shares infrastructure); webhook handler file overlap — coordinate if working in parallel
- **US3 (P3)**: Depends on US1 (extends `process_inbound` pipeline and ConversationView)
- **US4 (P4)**: Depends on US1 (tag action is on an existing reply); shares admin.py routes
- **US5 (P5)**: Depends on US1 (validates/completes window check already in reply endpoint)

### Within Each Phase

- All `[P]`-marked tasks in a phase can run in parallel (different files, no shared state)
- Bot layer tasks before routes that call them
- Routes before frontend stores that call them
- Stores before views that consume them

---

## Parallel Execution Examples

### Phase 2 Parallel Launch

```
Parallel: T011 (adapters/base.py), T013 (bot/audit.py), T016 (auth middleware), T017 (frontend/src/api/admin.ts)
Sequential after: T012 (adapters/whatsapp.py — needs base.py), T014 (api/main.py — needs all routers exist), T015 (webhook.py — needs audit.py), T018 (main.ts — needs router)
```

### Phase 3 (US1) Parallel Launch

```
Parallel: T019 (bot/safety.py), T020 (bot/retriever.py), T029 (stores/conversations.ts), T030 (UrgencyBadge.vue), T031 (MessageBubble.vue)
Sequential after T019+T020: T021 (generator.py — needs retriever types)
Sequential after T021: T022 (conversation.py — needs draft schema), T023 (pusher.py)
Sequential after T022+T023: T024 (process_inbound pipeline)
Sequential after T024: T025, T026, T027, T028 (admin routes — needs pipeline complete)
Sequential after T029: T032 (DraftCard — needs store types), T033 (InboxView), T034 (ConversationView)
```

### Phase 4 (US2) Parallel Launch

```
Parallel: T036 (bot/onboarding.py), T038 (GET /clients routes), T042 (stores/clients.ts), T043 (InviteLinkModal.vue)
Sequential after T036: T037 (POST /clients — needs onboarding), T040 (webhook token flow — needs onboarding)
Sequential after T040: T041 (consent flow — needs token flow complete)
Sequential after T042+T043: T044 (ClientsView — needs store + modal)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T009)
2. Complete Phase 2: Foundational (T010–T018) — **blocks everything**
3. Complete Phase 3: User Story 1 (T019–T035) — this IS the product
4. **STOP and VALIDATE**: Send a real test message end-to-end; check audit log
5. Deploy to Cloud Run; share with pilot midwife

### Incremental Delivery

1. Setup + Foundational → foundation ready (no user value yet)
2. US1 → MVP deployed; midwife can review and send AI drafts ✅
3. US2 → midwife can onboard new clients ✅
4. US3 → urgent safety escalation complete ✅
5. US4 → KB feedback loop active ✅
6. US5 → 24h window compliance fully enforced ✅
7. Polish → production hardening ✅

### Parallel Team Strategy

With two developers:
- **Week 1**: Both on Setup + Foundational together
- **Week 2–3**: Dev A on US1 (bot layer + routes), Dev B on US2 (onboarding)
- **Week 4**: Dev A on US3 + US5, Dev B on US4 + KB frontend
- **Week 5**: Both on Polish + deployment validation

---

## Notes

- `[P]` marks tasks that write to different files with no shared dependencies — safe to run in parallel
- `[USn]` maps each task to a user story for traceability
- **Constitution I + II enforced in tasks**: `adapters/whatsapp.send_message` is called ONLY from `api/routes/` handlers — `api/routes/admin.py` reply handler (T027) and `api/routes/webhook.py` onboarding token match handler (T040 — consent prompt dispatch). `bot/onboarding.py` (T036) defines `CONSENT_PROMPT_TEXT` as a constant but contains **no adapter imports** and does not call `send_message()` directly. No `bot/` module imports from `adapters/`.
- **No mocks for Firestore**: use Firebase emulator for all local state testing (per research.md decision 9)
- Commit after each task or logical group
- Stop at US1 checkpoint to validate independently before proceeding
- Each phase checkpoint describes the minimum state needed to demo that story
