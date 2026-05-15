# Implementation Plan: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Branch**: `002-phase-1-knowledge-foundation` | **Date**: 2026-05-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-phase-1-knowledge-foundation/spec.md`

---

## Summary

Convert the midwife's existing WhatsApp and Messenger chat exports into a structured, reviewed, searchable knowledge base — stripping all PII at extraction time — and put the immutable audit infrastructure and compliance documentation in place before any client-facing functionality exists. The technical approach uses Gemini 2.0 Flash to extract Q&A pairs from raw exports, spaCy + regex for PII removal, Vertex AI Search for two-tier indexing, and Cloud Logging → GCS for the append-only audit log.

---

## Technical Context

**Language/Version**: Python 3.12 (locked per constitution)

**Primary Dependencies**:
- FastAPI (async REST, serves PWA static files)
- `google-cloud-discoveryengine` (Vertex AI Search SDK — staging and production data stores)
- `google-cloud-aiplatform` / `vertexai` SDK (Gemini 2.0 Flash — Q&A extraction, embedding)
- `google-cloud-firestore` (chunk state, import tracking)
- `google-cloud-logging` + `google-cloud-storage` (dual-write audit log)
- `spaCy` + `xx_ent_wiki_sm` model (PII NER — multilingual; supports Polish/English midwifery context)
- Vue 3 + TypeScript + Tailwind + Vite + Pinia (Admin PWA — KB review UI)

**Storage**:
- Firestore `europe-west1` — chunk state (`kb_chunks`), import tracking (`kb_imports`)
- Vertex AI Search `eu` region — `midwife-staging` and `midwife-production` data stores (pre-existing per 001 plan)
- GCS `europe-west1` + Cloud Logging — append-only audit log (7-year retention lock, pre-existing per 001 plan)

**Testing**: pytest + Firestore emulator (no Firestore mocks per constitution pre-merge gate)

**Target Platform**: Linux (Cloud Run `europe-west1`); Admin PWA runs in browser

**Project Type**: Backend service (FastAPI) + Admin PWA (Vue 3) — single-artifact Docker image per constitution VI

**Performance Goals**:
- Process a batch of 50 extracted chunks in <60 seconds end-to-end (parse → strip → stage → index)
- Chunk review action (approve/edit/discard) responds in <200ms p95
- Test query against production index returns results in <500ms p95

**Constraints**:
- PII MUST be stripped before any chunk enters the staging index (FR-002, constitution IX)
- Audit log is append-only and tamper-evident; 7-year retention lock is pre-configured (constitution V, FR-008)
- All data stores in EU region for GDPR residency (constitution tech constraints)
- No client-facing messages in Phase 1 — admin UI is midwife-only, behind `ADMIN_TOKEN` auth

**Scale/Scope**: One midwife operator; 20–50 chunks from first batch after discards; up to a few hundred chat export messages per import run

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Human-in-the-Loop | ✅ Pass | No outbound client messages in Phase 1. The staging→production gate IS the human-in-the-loop for KB. |
| II. Ports & Adapters | ✅ Pass | Ingestion and KB services live under `bot/`. No core module imports from `adapters/`. Admin UI calls core via API only. |
| III. RAG | ✅ N/A | No AI draft generation in Phase 1. RAG infrastructure (Vertex AI Search indexes) is being built here for Phase 2. |
| IV. Fail-Closed Safety | ✅ N/A | No urgency classification or drafting in Phase 1. |
| V. Immutable Audit Log | ✅ CORE | Every extraction run, staging action, and promotion MUST write to Cloud Logging + GCS. This is a primary deliverable of Phase 1 (FR-007, FR-008, SC-003). |
| VI. Single-Artifact | ✅ Pass | Admin KB review UI is part of the same Vue 3 PWA, served by the same FastAPI instance. |
| VII. Token-Based Onboarding | ✅ N/A | No client onboarding in Phase 1. |
| VIII. Two-Tier KB | ✅ CORE | The staging→production gate is the central architectural deliverable. Direct production writes are prohibited (FR-003, FR-005). |
| IX. Compliance-by-Design | ✅ CORE | PII stripped at extraction time (FR-002). Compliance framework document produced before Phase 3 (FR-009). |

**No violations. No Complexity Tracking entries required.**

---

## Project Structure

### Documentation (this feature)

```text
specs/002-phase-1-knowledge-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── kb-ingestion.yaml    # OpenAPI: import upload + extraction trigger
│   └── kb-review.yaml       # OpenAPI: chunk review, promote, query
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

Phase 1 introduces the ingestion pipeline and KB review UI. It does NOT introduce the full application scaffolding (that is Phase 2's job). Files below are the Phase 1 additions — they will coexist with Phase 2+ additions in the same repo.

```text
backend/
├── api/
│   ├── main.py                      # FastAPI app entry point (Phase 2 will expand)
│   └── routes/
│       ├── ingestion.py             # POST /api/admin/kb/imports (upload + extract)
│       └── kb_review.py             # GET/PATCH/POST for chunk review and promotion
├── bot/
│   ├── ingestion/
│   │   ├── parsers/
│   │   │   ├── whatsapp.py          # WhatsApp text export parser
│   │   │   └── messenger.py         # Messenger JSON export parser
│   │   ├── extractor.py             # Gemini-based Q&A extraction
│   │   ├── pii_stripper.py          # spaCy NER + regex PII removal
│   │   └── deduplicator.py          # Near-duplicate detection (hash + embedding)
│   └── kb/
│       ├── staging.py               # Staging index CRUD (Firestore + Vertex AI Search)
│       ├── production.py            # Production index promotion (Vertex AI Search)
│       └── audit.py                 # Audit event writer (Cloud Logging + GCS)
└── config/
    └── settings.py                  # Pydantic settings (env vars)

frontend/
└── src/
    ├── views/
    │   ├── KbIngestionView.vue      # Upload form + extraction status
    │   └── KbReviewView.vue         # Chunk list: approve / edit / discard / promote
    └── services/
        └── kb.ts                    # Typed API client for KB endpoints

tests/
├── integration/
│   └── test_kb_pipeline.py         # Full pipeline: parse→strip→stage→promote (Firestore emulator)
└── unit/
    ├── test_whatsapp_parser.py
    ├── test_messenger_parser.py
    └── test_pii_stripper.py
```

**Structure Decision**: Backend option 2 (separate `backend/` and `frontend/` dirs), matching the 001 plan's established layout. Phase 1 populates `bot/ingestion/` and `bot/kb/` — directories that Phase 2 will extend with `bot/pipeline/` and `bot/conversation/`.

---

## Complexity Tracking

> No constitution violations — this table is intentionally empty for Phase 1.
