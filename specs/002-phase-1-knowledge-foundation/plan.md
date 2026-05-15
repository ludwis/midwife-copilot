# Implementation Plan: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Branch**: `002-phase-1-knowledge-foundation` | **Date**: 2026-05-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-phase-1-knowledge-foundation/spec.md`

---

## Summary

Phase 1 converts the midwife's existing WhatsApp and Messenger chat exports into a structured, two-tier knowledge base (staging → production) using Gemini 2.0 Flash extraction with PII stripping, and puts the compliance and audit infrastructure in place before any client-facing functionality exists. The primary technical deliverable is a FastAPI backend with background extraction tasks, a Vue 3 admin review PWA deployed to Firebase Hosting with Google OAuth, and an append-only audit log written to Cloud Logging + GCS with a 7-year retention lock.

---

## Technical Context

**Language/Version**: Python 3.12 (backend) + Node.js 20 LTS (frontend build)

**Primary Dependencies**:
- Backend: FastAPI (async REST), spaCy `xx_ent_wiki_sm` (PII NER), Pydantic v2, `google-cloud-firestore`, `google-cloud-storage`, `google-cloud-aiplatform`, `google-cloud-discoveryengine`, `vertexai` (Gemini)
- Frontend: Vue 3 + TypeScript + Tailwind CSS + Vite + Pinia, `vite-plugin-pwa`, Firebase JS SDK v10 (Auth)
- Test: pytest, `pytest-recording` (VCR fixtures for Gemini), Firebase Emulator Suite (Firestore)

**Storage**:
- Firestore (europe-west1): `kb_imports`, `kb_chunks` collections — mutable state
- Vertex AI Search (eu): two data stores — `midwife-staging`, `midwife-production`
- GCS (europe-west1) + Cloud Logging: append-only JSONL audit log, `gs://midwife-bot-audit-{env}/`
- GCS: embedding deduplication cache (`embeddings/cache.jsonl`)

**Testing**:
- Unit: pytest (WhatsApp/Messenger parsers, PII stripper, deduplicator logic)
- Integration: pytest + Firestore emulator (import flow, chunk state transitions, audit writes)
- Acceptance: golden dataset (30-message WhatsApp fixture with expected Q&A output)
- Vertex AI Search / Gemini: gated behind `INTEGRATION=true` (requires real GCP dev project)

**Target Platform**: Google Cloud Run (europe-west1), min-instances=1; Firebase Hosting (admin PWA)

**Project Type**: Web service (FastAPI backend) + Admin PWA (Vue 3)

**Performance Goals**: Import pipeline < 2 min for a 50-message export; review UI actions < 500ms p95; extraction batch window = 50 turns with 10-turn overlap

**Constraints**: All infrastructure in GCP europe-west1 (GDPR residency); no client PII may enter the staging index; audit log must be tamper-evident for 7 years; no unauthenticated routes in review UI

**Scale/Scope**: Phase 1 handles a single operator (the midwife), ~20–50 chunks per initial batch, < 200 total chunks by end of phase. Single shared `dev` GCP project from day one.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Human-in-the-Loop** | ✅ PASS | Phase 1 has zero outbound client messages. No `send_message()` call exists. All chunk promotion requires explicit midwife action. |
| **II. Ports & Adapters** | ✅ PASS | Phase 1 introduces no messaging adapter. The extraction pipeline (`bot/kb/`) is isolated from any channel adapter. Constitution II constraint is not yet exercised. |
| **III. RAG** | ✅ PASS | Phase 1 builds the production retrieval index that Phase 2 will query. The index structure (Vertex AI Search, Q&A document schema) is designed for the RAG pipeline. No generation in Phase 1. |
| **IV. Fail-Closed Safety** | ✅ PASS | Extraction failures set `kb_imports.status = failed` and surface `error_message` in the review UI. Re-submission via FR-015 is the recovery path. No best-effort auto-reply path exists in Phase 1. |
| **V. Immutable Audit Log** | ✅ PASS | All knowledge events written to Cloud Logging + GCS JSONL with daily partitioning. Dev bucket has no retention lock; production bucket gets 7-year retention lock (irreversible — documented in quickstart). `kb_chunk_edited` preserves `content_hash_before` and `content_hash_after`. |
| **VI. Single-Artifact Deployment** | ⚠️ JUSTIFIED DEVIATION | Phase 1 deploys the admin review PWA to **Firebase Hosting** separately from the FastAPI backend on Cloud Run. This is a temporary structural deviation for the admin-only Phase 1 UI. FR-013 explicitly scopes this: "establishes the hosting and auth infrastructure the Phase 3 PWA will extend." The Phase 3 PWA will be migrated into the single-artifact Cloud Run image. The Firebase Hosting deployment is admin-only and never client-facing. No separate frontend hosting service is introduced for the production client path. |
| **VII. Token-Based Client Onboarding** | ✅ PASS | Not applicable to Phase 1 (no client onboarding occurs). Principle applies to Phase 3+. |
| **VIII. Two-Tier Knowledge Base** | ✅ PASS | Staging and production are separate Vertex AI Search data stores. Chunks enter staging via extraction, and promotion to production requires explicit midwife action (`approve` or `edit_approve`). Direct ingestion to production is impossible via the API contracts. |
| **IX. Compliance-by-Design** | ✅ PASS | FR-009 requires the compliance framework document (`docs/compliance-framework.md`) before Phase 3. PII stripping (spaCy NER + regex) runs at extraction time — no client identifiers enter staging. Audit log captures all events from day one. |

### Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Firebase Hosting for admin PWA (separate from Cloud Run) | FR-013 + FR-014 require a minimal web app with Google OAuth for Phase 1; setting up the full Cloud Run single-artifact build before any backend code exists adds unnecessary build complexity for an admin-only tool | Bundling the Vue app into the Cloud Run image requires a working Dockerfile with a multi-stage build before the backend is scaffolded; Firebase Hosting + Firebase Auth is a faster path for the admin-only Phase 1 UI and the work is not thrown away (Phase 3 PWA extends it) |

---

## Project Structure

### Documentation (this feature)

```text
specs/002-phase-1-knowledge-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 output — all unknowns resolved
├── data-model.md        # Phase 1 output — Firestore + Vertex AI Search + audit log schema
├── quickstart.md        # Phase 1 output — local dev setup and end-to-end walkthrough
├── contracts/
│   ├── kb-ingestion.yaml   # OpenAPI 3.1 — POST/GET /api/admin/kb/imports
│   └── kb-review.yaml      # OpenAPI 3.1 — GET/PATCH /api/admin/kb/chunks, GET /api/admin/kb/production/query
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output — generated by /speckit-tasks (not yet created)
```

### Source Code (repository root)

```text
backend/                        # Python 3.12 FastAPI service
├── api/
│   ├── main.py                 # FastAPI app entrypoint; serves static PWA files
│   ├── auth.py                 # X-Admin-Token middleware
│   └── admin/
│       └── kb/
│           ├── imports.py      # POST /api/admin/kb/imports, GET /api/admin/kb/imports/{id}
│           ├── chunks.py       # GET /api/admin/kb/chunks, PATCH /api/admin/kb/chunks/{id}
│           └── production.py   # GET /api/admin/kb/production/query
├── bot/
│   └── kb/
│       ├── parsers/
│       │   ├── whatsapp.py     # WhatsApp .txt parser
│       │   └── messenger.py    # Messenger .json parser (multi-file merge)
│       ├── pii_stripper.py     # spaCy NER + regex PII removal
│       ├── extractor.py        # Gemini 2.0 Flash Q&A extraction
│       ├── deduplicator.py     # SHA-256 exact + Vertex AI embedding near-duplicate detection
│       ├── staging.py          # Write chunks to Firestore kb_chunks + Vertex AI staging index
│       └── promotion.py        # Promote chunk from staging → production Vertex AI index
├── core/
│   └── audit.py                # Audit event writer (Cloud Logging + GCS JSONL)
├── tests/
│   ├── unit/
│   │   ├── test_whatsapp_parser.py
│   │   ├── test_messenger_parser.py
│   │   ├── test_pii_stripper.py
│   │   └── test_deduplicator.py
│   ├── integration/
│   │   ├── test_import_flow.py         # Firestore emulator; VCR for Gemini
│   │   ├── test_review_actions.py      # Firestore emulator; chunk state transitions
│   │   ├── test_audit_log.py           # Firestore emulator; audit write verification
│   │   ├── test_kb_pipeline.py         # Golden dataset acceptance test
│   │   └── test_vertex_search.py       # INTEGRATION=true; real GCP dev project
│   └── fixtures/
│       ├── golden_whatsapp_export.txt
│       └── golden_expected_chunks.json
├── requirements.txt
└── .env.example

frontend/                       # Vue 3 + TypeScript + Vite + Pinia admin PWA
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/
│   │   └── index.ts            # Vue Router — /kb route (auth-guarded)
│   ├── stores/
│   │   ├── auth.ts             # Firebase Auth state (Pinia)
│   │   └── kb.ts               # KB chunks + imports state (Pinia)
│   ├── pages/
│   │   ├── LoginPage.vue       # Google OAuth sign-in
│   │   └── KbReviewPage.vue    # Review queue, approve / edit / discard / promote
│   └── services/
│       └── api.ts              # Typed API client (wraps X-Admin-Token calls)
├── public/
│   └── manifest.json           # PWA manifest
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── .firebaserc                 # Firebase Hosting config

docs/
└── compliance-framework.md    # FR-009 — authored in Phase 1, reviewed before Phase 3

.env.example                    # All Phase 1 env vars documented
cloudbuild.yaml                 # Cloud Build pipeline (backend deploy to Cloud Run)
firebase.json                   # Firebase Hosting + Auth config
```

**Structure Decision**: Web application layout (backend/ + frontend/) following Option 2. Backend is the FastAPI service; frontend is the Vue 3 admin PWA. The frontend is deployed to Firebase Hosting in Phase 1 (temporary; migrated into the single-artifact Cloud Run image in Phase 3 per Constitution VI). The `bot/kb/` package houses the extraction pipeline and is isolated from any messaging adapter.

---

## Artifacts Generated

| Artifact | Path | Status |
|----------|------|--------|
| Research (Phase 0) | `specs/002-phase-1-knowledge-foundation/research.md` | ✅ Complete |
| Data Model (Phase 1) | `specs/002-phase-1-knowledge-foundation/data-model.md` | ✅ Complete |
| API Contract — Ingestion (Phase 1) | `specs/002-phase-1-knowledge-foundation/contracts/kb-ingestion.yaml` | ✅ Complete |
| API Contract — Review (Phase 1) | `specs/002-phase-1-knowledge-foundation/contracts/kb-review.yaml` | ✅ Complete |
| Quickstart (Phase 1) | `specs/002-phase-1-knowledge-foundation/quickstart.md` | ✅ Complete |
| Tasks | `specs/002-phase-1-knowledge-foundation/tasks.md` | ⏳ Next step (`/speckit-tasks`) |
