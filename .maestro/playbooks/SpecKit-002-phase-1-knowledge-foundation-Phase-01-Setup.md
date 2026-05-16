# Phase 01: Setup — Shared Infrastructure

Scaffold the complete project directory structure, dependency manifests, configuration files, and test fixtures for the Phase 1 Knowledge Foundation feature. No production logic is written in this phase — by the end, the backend and frontend can be initialized and all config is in place.

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md
- **Plan:** specs/002-phase-1-knowledge-foundation/plan.md
- **Data Model:** specs/002-phase-1-knowledge-foundation/data-model.md
- **Research:** specs/002-phase-1-knowledge-foundation/research.md

## Tasks

- [x] T001 Create directory structure per plan.md: `backend/`, `backend/api/admin/kb/`, `backend/bot/kb/parsers/`, `backend/core/`, `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/fixtures/`, `frontend/src/pages/`, `frontend/src/stores/`, `frontend/src/router/`, `frontend/src/services/`, `frontend/public/`, `docs/`
- [x] T002 Create `backend/requirements.txt` with all required packages: FastAPI, uvicorn[standard], spacy, pydantic>=2, google-cloud-firestore, google-cloud-storage, google-cloud-aiplatform, google-cloud-discoveryengine, vertexai, pytest, pytest-recording, httpx
- [x] T003 [P] Create `.env.example` with all Phase 1 env vars: `VERTEX_SEARCH_DATASTORE_PRODUCTION`, `VERTEX_SEARCH_DATASTORE_STAGING`, `VERTEX_SEARCH_LOCATION`, `GCP_PROJECT_ID`, `GCP_REGION`, `ADMIN_TOKEN`, `AUDIT_BUCKET_NAME`, `FIRESTORE_EMULATOR_HOST`, `GEMINI_MODEL`, `SPACY_MODEL`, `DUPLICATE_SIMILARITY_THRESHOLD`, `VITE_ADMIN_EMAIL`, `VITE_ADMIN_TOKEN`
- [x] T004 [P] Create `frontend/package.json` with deps: vue@3, typescript, vite, @vitejs/plugin-vue, tailwindcss, autoprefixer, pinia, vue-router, vite-plugin-pwa, firebase@10
- [x] T005 [P] Create `frontend/vite.config.ts` (Vue plugin + PWA plugin; server proxy `/api` → `http://localhost:8000`; build output to `dist/`)
- [x] T006 [P] Create `frontend/tailwind.config.ts` (content paths covering `src/**/*.{vue,ts}`)
- [x] T007 [P] Create `frontend/tsconfig.json` (target ES2022, module ESNext, strict true, paths alias `@/` → `src/`)
- [x] T008 [P] Create `firebase.json` (hosting: public `frontend/dist`, rewrites all → index.html; emulators: auth on 9099, firestore on 8080)
- [x] T009 [P] Create `frontend/.firebaserc` (default project binding from `GCP_PROJECT_ID`)
- [x] T010 [P] Create `cloudbuild.yaml` (steps: `docker build` backend image, push to Artifact Registry, `gcloud run deploy` to `europe-west1`, min-instances=1)
- [x] T011 [P] Create `frontend/public/manifest.json` (PWA manifest: name "Stilla Admin", short_name "Stilla", display standalone, start_url "/kb", theme_color, icons array)
- [ ] T012 Create `backend/tests/fixtures/golden_whatsapp_export.txt` (30-message WhatsApp export: mixed Q&A, social, and administrative turns; includes real-looking PII — names like "Anna Kowalska", phone "+48 601 234 567", so extraction and PII stripping can be validated)
- [ ] T013 [P] Create `backend/tests/fixtures/golden_expected_chunks.json` (expected Q&A pairs after PII stripping for `golden_whatsapp_export.txt`: JSON array of `{"question": "...", "answer": "..."}` with all PII replaced by Polish placeholders `[IMIĘ]`, `[TELEFON]`, etc.)

## Completion

- [ ] Verify all directories exist: `backend/`, `backend/api/admin/kb/`, `backend/bot/kb/parsers/`, `backend/core/`, `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/fixtures/`, `frontend/src/pages/`, `frontend/src/stores/`, `frontend/src/router/`, `frontend/src/services/`, `frontend/public/`, `docs/`
- [ ] Verify `backend/requirements.txt`, `.env.example`, all frontend config files, `firebase.json`, `cloudbuild.yaml`, and both fixture files exist
- [ ] Verify `golden_whatsapp_export.txt` contains ≥30 messages with PII and mixed turn types
- [ ] Verify `golden_expected_chunks.json` is valid JSON and all PII is replaced with Polish placeholders
- [ ] Run `/speckit-analyze` to verify consistency
