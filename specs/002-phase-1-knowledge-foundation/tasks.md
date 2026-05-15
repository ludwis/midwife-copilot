# Tasks: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Input**: Design documents from `specs/002-phase-1-knowledge-foundation/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Included — testing strategy is explicitly defined in plan.md with specific test files and a golden dataset acceptance fixture.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no blocking dependencies)
- **[Story]**: User story label — [US1], [US2], [US3], [US4]
- Setup and Foundational phases carry no story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold the project directory structure, dependency manifests, config files, and test fixtures. No production logic.

- [ ] T001 Create directory structure per plan.md: `backend/`, `backend/api/admin/kb/`, `backend/bot/kb/parsers/`, `backend/core/`, `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/fixtures/`, `frontend/src/pages/`, `frontend/src/stores/`, `frontend/src/router/`, `frontend/src/services/`, `frontend/public/`, `docs/`
- [ ] T002 Create `backend/requirements.txt` (FastAPI, uvicorn[standard], spacy, pydantic>=2, google-cloud-firestore, google-cloud-storage, google-cloud-aiplatform, google-cloud-discoveryengine, vertexai, pytest, pytest-recording, httpx)
- [ ] T003 [P] Create `.env.example` with all Phase 1 env vars: `VERTEX_SEARCH_DATASTORE_PRODUCTION`, `VERTEX_SEARCH_DATASTORE_STAGING`, `VERTEX_SEARCH_LOCATION`, `GCP_PROJECT_ID`, `GCP_REGION`, `ADMIN_TOKEN`, `AUDIT_BUCKET_NAME`, `FIRESTORE_EMULATOR_HOST`, `GEMINI_MODEL`, `SPACY_MODEL`, `DUPLICATE_SIMILARITY_THRESHOLD`, `VITE_ADMIN_EMAIL`
- [ ] T004 [P] Create `frontend/package.json` with deps: vue@3, typescript, vite, @vitejs/plugin-vue, tailwindcss, autoprefixer, pinia, vue-router, vite-plugin-pwa, firebase@10
- [ ] T005 [P] Create `frontend/vite.config.ts` (Vue plugin + PWA plugin; server proxy `/api` → `http://localhost:8000`; build output to `dist/`)
- [ ] T006 [P] Create `frontend/tailwind.config.ts` (content paths covering `src/**/*.{vue,ts}`)
- [ ] T007 [P] Create `frontend/tsconfig.json` (target ES2022, module ESNext, strict true, paths alias `@/` → `src/`)
- [ ] T008 [P] Create `firebase.json` (hosting: public `frontend/dist`, rewrites all → index.html; emulators: auth on 9099, firestore on 8080)
- [ ] T009 [P] Create `frontend/.firebaserc` (default project binding from `GCP_PROJECT_ID`)
- [ ] T010 [P] Create `cloudbuild.yaml` (steps: `docker build` backend image, push to Artifact Registry, `gcloud run deploy` to `europe-west1`, min-instances=1)
- [ ] T011 [P] Create `frontend/public/manifest.json` (PWA manifest: name "Stilla Admin", short_name "Stilla", display standalone, start_url "/kb", theme_color, icons array)
- [ ] T012 Create `backend/tests/fixtures/golden_whatsapp_export.txt` (30-message WhatsApp export: mixed Q&A, social, and administrative turns; includes real-looking PII — names like "Anna Kowalska", phone "+48 601 234 567", so extraction and PII stripping can be validated)
- [ ] T013 [P] Create `backend/tests/fixtures/golden_expected_chunks.json` (expected Q&A pairs after PII stripping for `golden_whatsapp_export.txt`: JSON array of `{"question": "...", "answer": "..."}` with all PII replaced by Polish placeholders `[IMIĘ]`, `[TELEFON]`, etc.)

**Checkpoint**: All config files and fixtures in place — backend and frontend can be initialized

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before any user story can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T014 Create `backend/api/main.py` (FastAPI app factory: include `admin/kb` router under `/api/admin`; apply auth dependency globally to `/api/admin`; mount `frontend/dist` as StaticFiles at `/`; lifespan startup: load spaCy model once into module-level variable)
- [ ] T015 Implement X-Admin-Token middleware in `backend/api/auth.py` (FastAPI `Security` dependency: read `X-Admin-Token` header, compare to `ADMIN_TOKEN` env var with `secrets.compare_digest`, raise `HTTPException(401)` on mismatch; import and apply in `main.py`)
- [ ] T016 Implement audit event writer in `backend/core/audit.py` (`write_event(event_type: str, actor: str, **fields)`: serialize to JSONL with ISO-8601 UTC timestamp; dual-write: `google.cloud.logging` structured entry + append line to `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl` via `google.cloud.storage`; GCS client initialized once at module level from `AUDIT_BUCKET_NAME` env var)
- [ ] T017 Create `frontend/src/main.ts` (initialize Firebase app with project config from `import.meta.env`; create Vue app; install Pinia and Router; mount to `#app`)
- [ ] T018 [P] Create `frontend/src/App.vue` (root component: `<RouterView>` wrapped in a global loading overlay that reads from `authStore.loading`)
- [ ] T019 Create `frontend/src/router/index.ts` (Vue Router createWebHistory; routes: `/` redirect to `/kb`, `/login` → LoginPage, `/kb` → KbReviewPage; navigation guard: `router.beforeEach` — if route requires auth and `authStore.isAuthenticated` is false, redirect to `/login`)
- [ ] T020 Create `frontend/src/stores/auth.ts` (Pinia store: `user` state from `onAuthStateChanged`; `signInWithGoogle()` calls `signInWithPopup(provider)` with `GoogleAuthProvider`; `signOut()`; `isAuthenticated` computed; on auth state change, reject user whose `email` does not match `VITE_ADMIN_EMAIL`; `loading` boolean true until first auth state resolved)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Knowledge Extraction from Chat Exports (Priority: P1) 🎯 MVP

**Goal**: Upload a WhatsApp or Messenger chat export → run PII-stripped Gemini Q&A extraction → surface discrete, reviewable knowledge chunks in the staging index.

**Independent Test**: POST golden_whatsapp_export.txt to `/api/admin/kb/imports`, poll until `status=completed`, GET `/api/admin/kb/chunks?status=staged` — confirm chunks are present with PII replaced by Polish placeholders and no personal identifiers visible.

### Tests for User Story 1

- [ ] T021 [US1] Write unit tests for WhatsApp parser in `backend/tests/unit/test_whatsapp_parser.py` (parametrize over DD/MM/YYYY and DD.MM.YY timestamp variants; assert multi-line message continuation is appended to previous; assert known system message strings like "Messages and calls are end-to-end encrypted" are filtered; assert empty file returns empty list)
- [ ] T022 [P] [US1] Write unit tests for Messenger parser in `backend/tests/unit/test_messenger_parser.py` (multi-file merge deduplicates on (sender_name, timestamp_ms, content); missing `content` field is skipped; output sorted ascending by timestamp_ms; sticker/photo entries with no content are excluded)
- [ ] T023 [P] [US1] Write unit tests for PII stripper in `backend/tests/unit/test_pii_stripper.py` (PERSON entity → `[IMIĘ]`; LOC entity → `[ADRES]`; phone `+48 601 234 567` → `[TELEFON]`; email `anna@gmail.com` → `[EMAIL]`; PESEL 11-digit → `[PESEL]`; post-strip re-scan flags a chunk containing a remaining 7-digit sequence)
- [ ] T024 [P] [US1] Write unit tests for deduplicator in `backend/tests/unit/test_deduplicator.py` (same SHA-256 hash as existing chunk → `exact` flag + correct `duplicate_of_chunk_id`; mocked embedding cosine similarity 0.95 → `near` flag; mocked cosine similarity 0.85 → no flag; empty cache → no flags for any input)
- [ ] T025 [US1] Write integration test for import flow in `backend/tests/integration/test_import_flow.py` (Firestore emulator `FIRESTORE_EMULATOR_HOST=localhost:8080`; VCR cassette for Gemini response; POST multipart to `/api/admin/kb/imports`; poll GET until `status=completed`; assert `kb_imports` doc created with correct fields; assert `kb_chunks` docs in Firestore with `status=staged` and no PII in question/answer)

### Implementation for User Story 1

- [ ] T026 [P] [US1] Implement WhatsApp .txt parser in `backend/bot/kb/parsers/whatsapp.py` (`WHATSAPP_LINE_RE` regex per research.md §1; iterate lines: if line matches, save previous message and start new; if no match, append to current message content; filter lines matching known system-message prefixes; return `list[dict]` with keys `timestamp`, `sender`, `content`)
- [ ] T027 [P] [US1] Implement Messenger .json parser in `backend/bot/kb/parsers/messenger.py` (accept list of file paths for multi-file exports; parse each `message_N.json`; skip entries without `content`; deduplicate on `(sender_name, timestamp_ms, content)` using a set; sort ascending by `timestamp_ms`; convert `timestamp_ms` to ISO-8601 UTC; return `list[dict]` with keys `timestamp`, `sender`, `content`)
- [ ] T028 [US1] Implement PII stripper in `backend/bot/kb/pii_stripper.py` (load `xx_ent_wiki_sm` once at module level; `strip_pii(text: str) -> tuple[str, bool]`: pass 1 — spaCy NER, replace `PERSON` → `[IMIĘ]`, `LOC` → `[ADRES]`, `ORG` → `[FIRMA]` using span offsets; pass 2 — four regex patterns per research.md §3 for phone/email/PESEL/NIP; post-strip rescan: flag if any digit sequence >6 digits remains; return stripped text + flag bool)
- [ ] T029 [US1] Implement Gemini 2.0 Flash Q&A extractor in `backend/bot/kb/extractor.py` (extraction prompt per research.md §4; batch conversation turns into windows of 50 with 10-turn overlap when token estimate >8k; call `vertexai.generative_models.GenerativeModel(GEMINI_MODEL).generate_content()` with `response_mime_type="application/json"`; parse JSON with Pydantic `list[ChunkDraft]`; retry max 2× on `ValidationError` or `JSONDecodeError`; return `list[ChunkDraft]` — empty list is valid and signals `no_pairs_found`)
- [ ] T030 [US1] Implement near-duplicate detector in `backend/bot/kb/deduplicator.py` (load GCS embedding cache `gs://midwife-bot-audit-{env}/embeddings/cache.jsonl` at startup into `dict[chunk_id, embedding]`; `check_duplicate(question: str, chunk_id: str, existing_hashes: set[str]) -> DedupResult`: pass 1 — SHA-256 of normalized question (lower, collapsed whitespace); if hash in `existing_hashes` return `DedupResult(flag="exact", ...)`; pass 2 — compute Vertex AI `textembedding-gecko-multilingual@001` embedding in `eu` region; cosine similarity vs all cached embeddings; if max similarity >0.90 return `DedupResult(flag="near", similarity=..., duplicate_of_chunk_id=...)`; else return `DedupResult(flag=None)`)
- [ ] T031 [US1] Implement staging writer in `backend/bot/kb/staging.py` (`stage_chunks(chunks: list[ChunkDraft], import_id: str, client: AsyncClient) -> list[str]`: for each chunk: compute `content_hash = SHA-256(question + "\n" + answer)`; call `deduplicator.check_duplicate()`; create `kb_chunks` Firestore doc with fields per data-model.md (`status=staged`, `staged_at`, `source_type=export`, `import_id`, `duplicate_flag`, `duplicate_of_chunk_id`, `similarity_score`); write document to Vertex AI staging data store using Discovery Engine API with schema per data-model.md §Vertex AI Search Documents; return list of `chunk_id` strings)
- [ ] T032 [US1] Implement `POST /api/admin/kb/imports` and `GET /api/admin/kb/imports` in `backend/api/admin/kb/imports.py` (POST: validate `file` ≤10 MB and `source_format` enum; compute `filename_hash = SHA-256(original_filename)`; create `kb_imports` doc in Firestore with `status=processing`; emit `kb_import_started` audit event; enqueue `BackgroundTasks` task running: detect format → parse → PII strip → Gemini extract → dedup + stage → update `kb_imports` with `status`, `chunks_extracted`, `chunks_flagged_duplicate`, `completed_at` → emit `kb_import_completed`; return 202 `ImportCreatedResponse`; GET: list `kb_imports` newest-first with optional `status` filter and `limit` param per kb-ingestion.yaml)
- [ ] T033 [US1] Implement `GET /api/admin/kb/imports/{import_id}` in `backend/api/admin/kb/imports.py` (fetch `kb_imports` Firestore doc by `import_id`; return `ImportDetail` schema with `error_message` field populated on `failed` status; raise 404 if document not found)
- [ ] T034 [US1] Implement `frontend/src/pages/LoginPage.vue` (Tailwind-styled centered card; "Sign in with Google" button; on click calls `authStore.signInWithGoogle()`; on success `router.push('/kb')`; on failure display error message; show spinner during sign-in; if already authenticated redirect immediately to `/kb`)
- [ ] T035 [US1] Create `frontend/src/services/api.ts` (typed API client: read token from `import.meta.env.VITE_ADMIN_TOKEN`; attach `X-Admin-Token` header on all requests; `createImport(file: File, sourceFormat: 'whatsapp_txt' | 'messenger_json'): Promise<ImportCreatedResponse>`; `listImports(status?: string): Promise<{imports: ImportSummary[]}>`; `getImport(id: string): Promise<ImportDetail>`; all interfaces typed per kb-ingestion.yaml schemas)
- [ ] T036 [US1] Add import upload section to `frontend/src/pages/KbReviewPage.vue` (file input accepting `.txt` and `.json`; `source_format` radio buttons; "Upload & Extract" button calling `api.createImport()`; on 202 response start polling `api.getImport(importId)` every 3 s; display current status badge (processing/completed/failed/no_pairs_found); on completed show summary: chunks extracted, duplicates flagged; stop polling on terminal status)

**Checkpoint**: POST import → extraction pipeline completes → staged chunks visible via GET /api/admin/kb/chunks?status=staged

---

## Phase 4: User Story 2 — Staging-to-Production Knowledge Promotion (Priority: P1)

**Goal**: The midwife reviews staged chunks and deliberately promotes approved ones to the production Vertex AI Search index; unreviewed knowledge never reaches production.

**Independent Test**: Seed 5 staged chunks. Approve 2, edit-approve 1, discard 1. Verify `/api/admin/kb/chunks?status=promoted` returns 3. Query `/api/admin/kb/production/query` and confirm promoted chunks are returned for a matching query.

### Tests for User Story 2

- [ ] T037 [US2] Write integration test for review actions in `backend/tests/integration/test_review_actions.py` (Firestore emulator; seed 3 `kb_chunks` docs with `status=staged`; test `approve`: PATCH → assert doc `status=promoted`, `production_vertex_id` set, `reviewed_at` set; test `edit_approve`: assert `content_hash` updated, `content_hash_before_edit` preserved, `status=promoted`; test `discard`: assert `status=discarded`; test 409 on second PATCH to already-actioned chunk via simulated concurrent request)
- [ ] T038 [P] [US2] Write acceptance test for golden dataset end-to-end pipeline in `backend/tests/integration/test_kb_pipeline.py` (`test_golden_dataset`: load `golden_whatsapp_export.txt`, run full pipeline with VCR Gemini cassette, assert extracted and PII-stripped chunks match `golden_expected_chunks.json` structure and content; assert no digit sequence >6 digits in any chunk question or answer)

### Implementation for User Story 2

- [ ] T039 [US2] Implement chunk promotion writer in `backend/bot/kb/promotion.py` (`promote_chunk(chunk_id: str, question: str, answer: str, content_hash: str)`: write document to Vertex AI production data store using Discovery Engine API with full schema per data-model.md §Vertex AI Search Documents; on success: Firestore transaction to update `kb_chunks` doc: `status=promoted`, `production_vertex_id`, `promoted_at`; update GCS embedding cache by appending new `{chunk_id, embedding}` entry to `embeddings/cache.jsonl`)
- [ ] T040 [US2] Implement `GET /api/admin/kb/chunks` and `GET /api/admin/kb/chunks/{chunk_id}` in `backend/api/admin/kb/chunks.py` (`listChunks`: filter by `status`, `import_id`, `duplicate_flag` query params; cursor-based pagination using Firestore `start_after`; when `duplicate_flag` is set, fetch and embed `duplicate_of` ChunkSummary in each result; include `total_staged` count; `getChunk`: full `ChunkDetail` including `content_hash_before_edit`, `reviewed_by`, `production_vertex_id`)
- [ ] T041 [US2] Implement `PATCH /api/admin/kb/chunks/{chunk_id}` in `backend/api/admin/kb/chunks.py` (Firestore `@firestore.transactional` to prevent concurrent review races; read chunk and assert `status=staged`, raise 409 if already actioned; `approve`: call `promotion.promote_chunk()`, update status; `edit_approve`: recompute `content_hash = SHA-256(new_question + "\n" + new_answer)`, set `content_hash_before_edit`, update question/answer, call `promotion.promote_chunk()`; `discard`: set `status=discarded`; emit corresponding audit event via `core.audit.write_event()`; return updated `ChunkDetail`; raise 400 if `edit_approve` missing question or answer)
- [ ] T042 [US2] Implement `GET /api/admin/kb/production/query` in `backend/api/admin/kb/production.py` (require non-empty `q` param, raise 400 if missing; query Vertex AI Search production data store with Discovery Engine `SearchServiceClient`; map results to `QueryResult` array with extractive answer snippet; emit `kb_query_test` audit event with `query_text` and `result_count`; return typed response per kb-review.yaml)
- [ ] T043 [US2] Extend `frontend/src/services/api.ts` with review and query methods (`listChunks(params: {status?, importId?, duplicateFlag?, cursor?}): Promise<ChunksListResponse>`; `getChunk(id: string): Promise<ChunkDetail>`; `reviewChunk(id: string, action: ReviewAction): Promise<ChunkDetail>`; `queryProduction(q: string, limit?: number): Promise<QueryResponse>`; all typed per kb-review.yaml schemas)
- [ ] T044 [US2] Create `frontend/src/stores/kb.ts` (Pinia: `stagedChunks: ChunkSummary[]`, `nextCursor: string | null`, `imports: ImportSummary[]`; actions: `fetchStagedChunks()` with cursor pagination; `approveChunk(id)`, `editApproveChunk(id, question, answer)`, `discardChunk(id)` — each calls `api.reviewChunk()` then removes chunk from local `stagedChunks`; `queryProduction(q)` returns results; `fetchImports()`)
- [ ] T045 [US2] Implement review queue section in `frontend/src/pages/KbReviewPage.vue` (fetch and display `stagedChunks` from `kbStore`; per-chunk card: question text, answer text, `staged_at`, source badge; if `duplicate_flag` show warning badge with similarity score and link to similar chunk; action buttons: Approve (calls `kbStore.approveChunk()`), Edit & Approve (expands inline textarea for question/answer edit then `kbStore.editApproveChunk()`), Discard (calls `kbStore.discardChunk()`); load-more button for cursor pagination; production query test panel: text input + Search button + results list with snippets)

**Checkpoint**: Full extraction-to-production pipeline operational; SC-004 (≥20 promoted chunks) achievable; SC-007 (5 representative queries return relevant results) testable

---

## Phase 5: User Story 3 — Compliance Framework Documentation (Priority: P2)

**Goal**: Author the compliance framework document covering consent, AI disclosure, data retention, and right-to-erasure before Phase 3 begins; initiate WhatsApp Business registration.

**Independent Test**: A reviewer can read `docs/compliance-framework.md` and find exact answers to: (1) what consent message text does the client receive? (2) how is AI involvement disclosed? (3) what are the retention periods? (4) what is the erasure procedure step-by-step?

### Implementation for User Story 3

- [ ] T046 [P] [US3] Author `docs/compliance-framework.md` per research.md §7 — four mandatory sections: (1) **Consent message text**: exact WhatsApp onboarding message Polish + English versions; (2) **AI disclosure language**: onboarding disclosure paragraph + per-message badge label for the PWA; (3) **Data retention periods**: per data type (conversation messages, KB chunks, audit log JSONL, client profiles) each with GDPR legal basis and retention duration; (4) **Right-to-erasure procedure**: step-by-step — what Firestore collections are deleted, what stays in audit log with GDPR Art. 17(3)(e) legal claims exception rationale; include a review sign-off section per SC-005
- [ ] T047 [P] [US3] Create `docs/whatsapp-registration-status.md` to track WhatsApp Business API registration per FR-010 and research.md §8 (document all 5 steps: Meta Business Suite account, healthcare verification docs required, WhatsApp Cloud API application, bot phone number registration, phone number verification; record date submitted; note Telegram Bot API as fallback adapter if Meta approval delayed beyond Phase 3 start; leave status field to update as application progresses)

**Checkpoint**: SC-005 achievable (compliance doc ready for GDPR-aware review before Phase 3 kick-off); SC-006 achievable (registration submitted)

---

## Phase 6: User Story 4 — Audit Trail for Knowledge Events (Priority: P2)

**Goal**: Every extraction, staging, and review action is captured in the immutable audit log with correct fields; the full provenance of any chunk is reconstructable from extraction to production.

**Independent Test**: Run full extraction → approve 2 chunks → discard 1 → promote 1 to production. Query GCS `audit.jsonl` and confirm `kb_import_started`, `kb_import_completed`, `kb_chunk_staged` ×3, `kb_chunk_approved` ×2, `kb_chunk_discarded` ×1, `kb_chunk_promoted` ×2 all appear with required fields.

### Tests for User Story 4

- [ ] T048 [P] [US4] Write integration test for audit log in `backend/tests/integration/test_audit_log.py` (Firestore emulator + mock GCS write capturing written lines; run import → review sequence; assert all 8 event types emitted; assert `kb_chunk_edited` includes `content_hash_before` and `content_hash_after`; assert every event has `event_type`, `timestamp`, and `actor` base fields; assert `kb_import_completed` includes `duration_ms`)
- [ ] T049 [P] [US4] Write `INTEGRATION=true`-gated Vertex AI Search test in `backend/tests/integration/test_vertex_search.py` (skip unless `os.environ.get("INTEGRATION") == "true"`; ingest a test document to staging data store; query staging — assert document retrievable; ingest to production data store; query production — assert document retrievable; verify document schema matches data-model.md Vertex AI Search document structure)

### Implementation for User Story 4

- [ ] T050 [US4] Verify `kb_import_started` and `kb_import_completed` audit events are emitted in `backend/api/admin/kb/imports.py` (`kb_import_started`: fields `import_id`, `source_format`, `filename_hash`, `actor="midwife"`; `kb_import_completed`: fields `status`, `chunks_extracted`, `chunks_flagged_duplicate`, `duration_ms`; add any missing `audit.write_event()` calls; verify fields match data-model.md audit schema)
- [ ] T051 [US4] Verify `kb_chunk_staged` audit event is emitted per chunk in `backend/bot/kb/staging.py` (fields: `import_id`, `chunk_id`, `content_hash`, `duplicate_flag`; add missing `audit.write_event()` call in the chunk creation loop if absent)
- [ ] T052 [US4] Verify `kb_chunk_approved`, `kb_chunk_edited`, `kb_chunk_discarded`, `kb_chunk_promoted` are emitted in `backend/api/admin/kb/chunks.py` (`kb_chunk_edited` MUST include `content_hash_before` and `content_hash_after` per data-model.md; add any missing `audit.write_event()` calls for each action branch)
- [ ] T053 [US4] Verify `kb_query_test` audit event is emitted in `backend/api/admin/kb/production.py` (fields: `query_text`, `result_count`; add missing `audit.write_event()` call if absent)
- [ ] T054 [US4] Document production GCS retention lock procedure in `cloudbuild.yaml` as a commented-out step (commands: `gsutil mb -l europe-west1 gs://midwife-bot-audit-prod`, `gsutil retention set 7y`, `gsutil retention lock`; add `# IRREVERSIBLE — run once on production project only` warning; keep dev bucket creation as an active step for CI; add `AUDIT_BUCKET_NAME` substitution variable)

**Checkpoint**: SC-003 achievable (100% of knowledge events captured in audit log — verified by test_audit_log.py)

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Error handling, UX polish, operational readiness, and success criteria validation.

- [ ] T055 [P] Add descriptive error responses to `backend/api/admin/kb/imports.py` and `backend/api/admin/kb/chunks.py` (400 with `error` field for invalid `source_format`, empty file, invalid state transitions; 413 message "File exceeds 10 MB limit"; 409 message "Chunk {id} was already actioned — concurrent review conflict" per kb-review.yaml ErrorResponse schema)
- [ ] T056 [P] Add loading and error UX to `frontend/src/pages/KbReviewPage.vue` (spinner overlay during `fetchStagedChunks` and import polling; per-action loading state on Approve/Discard buttons to prevent double-click; toast notification on success (green) and error (red); empty-state illustration when `stagedChunks` is empty with message "No chunks awaiting review")
- [ ] T057 [P] Create `backend/README.md` with backend setup instructions (Python 3.12 venv, `pip install -r requirements.txt`, `python -m spacy download xx_ent_wiki_sm` as one-time step, Firestore emulator startup, `uvicorn api.main:app --reload`, GCP ADC login)
- [ ] T058 Run `quickstart.md` end-to-end walkthrough (all 10 sections; upload `golden_whatsapp_export.txt`; review extracted chunks; promote ≥20 chunks per SC-004; run SC-007 production query validation with 5 representative midwifery questions; note any gaps or deviations from quickstart instructions)
- [ ] T059 [P] Validate all Phase 1 success criteria per `spec.md` SC-001 through SC-007 (checklist: SC-001 first promoted batch complete; SC-002 <60 s average review time measured during walkthrough; SC-003 audit coverage 100% verified by test_audit_log.py; SC-004 ≥20 production chunks confirmed; SC-005 compliance doc reviewed and signed off; SC-006 WhatsApp registration submitted; SC-007 ≥5 representative queries return relevant snippets)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational only — no dependency on US2/US3/US4
- **US2 (Phase 4)**: Depends on US1 (review requires staged chunks) — builds directly on Phase 3 output
- **US3 (Phase 5)**: Depends on Foundational only — no code dependencies; can proceed in parallel with US1/US2
- **US4 (Phase 6)**: Depends on US1 and US2 (audit verification covers all event types) — best after Phase 4
- **Polish (Phase 7)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — no story dependencies
- **US2 (P1)**: Can start after Foundational + US1 (needs staged chunks to review)
- **US3 (P2)**: Can start after Foundational — independent of US1/US2 (documentation only)
- **US4 (P2)**: Can start after Foundational; completes after US1+US2 (verifies audit events from both)

### Within Each User Story

- Unit tests before parser/stripper implementation (TDD approach for unit-tested components)
- Parsers (T026, T027) before PII stripper (T028) before extractor (T029)
- Extractor (T029) + deduplicator (T030) before staging writer (T031)
- Staging writer (T031) before import endpoints (T032, T033)
- Backend review endpoints (T040, T041, T042) before frontend store (T044) before review UI (T045)

---

## Parallel Execution Examples

### Phase 1 Setup (run together)
```
T003 Create .env.example
T004 Create frontend/package.json
T005 Create frontend/vite.config.ts
T006 Create frontend/tailwind.config.ts
T007 Create frontend/tsconfig.json
T008 Create firebase.json
T009 Create frontend/.firebaserc
T010 Create cloudbuild.yaml
T011 Create frontend/public/manifest.json
T013 Create golden_expected_chunks.json
```

### US1 Unit Tests (run together after T014–T020)
```
T021 Unit tests — WhatsApp parser
T022 Unit tests — Messenger parser
T023 Unit tests — PII stripper
T024 Unit tests — deduplicator
```

### US1 Parsers (run together)
```
T026 WhatsApp parser implementation
T027 Messenger parser implementation
```

### US3 Documentation (run together, independent of code)
```
T046 Author docs/compliance-framework.md
T047 Create docs/whatsapp-registration-status.md
```

### US4 Tests (run together)
```
T048 Integration test — audit log
T049 Integration test — Vertex AI Search (INTEGRATION=true)
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (extraction pipeline + staging)
4. Complete Phase 4: User Story 2 (review + promotion to production)
5. **STOP AND VALIDATE**: SC-004 (≥20 promoted chunks), SC-007 (5 representative queries)
6. Deploy to Cloud Run + Firebase Hosting

### Incremental Delivery

1. Setup + Foundational → infrastructure scaffolded
2. US1 → extraction pipeline working; staged chunks visible via API (MVP backend)
3. US2 → review UI and promotion working; production index populated (MVP complete)
4. US3 → compliance doc authored and reviewed (Phase 3 gate cleared)
5. US4 → audit trail verified and tested (compliance gate for production)
6. Polish → SC-001–SC-007 all green

### Parallel Team Strategy (two developers)

1. Both complete Setup + Foundational together
2. Once Foundational done:
   - **Developer A**: US1 (extraction pipeline, backend parsers, PII stripper, extractor, staging) → US4 (audit verification)
   - **Developer B**: US3 (compliance framework doc) → US2 frontend (review UI, Pinia store, api.ts extensions) — can start US2 backend after Developer A completes T031–T033
3. Developer A completes US2 backend (T039–T042); Developer B connects frontend (T043–T045)
4. Together: Polish + success criteria validation (T055–T059)

---

## Notes

- `[P]` marks tasks that can run concurrently because they target different files with no incomplete shared dependencies
- `[US1]`–`[US4]` labels map each task to its user story for traceability
- Firestore emulator must be running on `:8080` for all integration tests
- VCR cassettes for Gemini calls are created on first real run then replayed — commit cassette files
- Vertex AI Search and Gemini calls require real GCP credentials (`gcloud auth application-default login`)
- INTEGRATION=true tests (T049) require a real GCP dev project and will incur GCP costs
- `gsutil retention lock` in T054 is irreversible — document clearly and only run on production project
- Each user story should be independently completable and testable before moving to the next
