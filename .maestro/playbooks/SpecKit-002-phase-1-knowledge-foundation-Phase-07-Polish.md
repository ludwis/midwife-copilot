# Phase 07: Polish & Cross-Cutting Concerns

Add error handling, UX polish, and operational readiness across all layers, then run the full quickstart walkthrough to validate all seven success criteria (SC-001–SC-007). This phase depends on all user stories being complete and produces the final sign-off evidence for Phase 1.

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md (SC-001 through SC-007)
- **Quickstart:** specs/002-phase-1-knowledge-foundation/quickstart.md
- **Contracts:** specs/002-phase-1-knowledge-foundation/contracts/ (kb-ingestion.yaml, kb-review.yaml ErrorResponse schema)

## Tasks

- [x] T055 [P] Add descriptive error responses to `backend/api/admin/kb/imports.py` and `backend/api/admin/kb/chunks.py` (400 with `error` field for invalid `source_format`, empty file, invalid state transitions; 413 message "File exceeds 10 MB limit"; 409 message "Chunk {id} was already actioned — concurrent review conflict" per kb-review.yaml ErrorResponse schema)
  <!-- Global HTTPException handler added to api/main.py translating {detail} → {error}. Empty-file 400 added to imports.py. All three 409 sites in chunks.py use contract-exact message. 61 unit tests pass. -->
- [ ] T056 [P] Add loading and error UX to `frontend/src/pages/KbReviewPage.vue` (spinner overlay during `fetchStagedChunks` and import polling; per-action loading state on Approve/Discard buttons to prevent double-click; toast notification on success (green) and error (red); empty-state illustration when `stagedChunks` is empty with message "No chunks awaiting review")
- [ ] T057 [P] Create `backend/README.md` with backend setup instructions (Python 3.12 venv, `pip install -r requirements.txt`, `python -m spacy download xx_ent_wiki_sm` as one-time step, Firestore emulator startup, `uvicorn api.main:app --reload`, GCP ADC login)
- [ ] T058 Run `quickstart.md` end-to-end walkthrough (all 10 sections; upload `golden_whatsapp_export.txt`; review extracted chunks; promote ≥20 chunks per SC-004; run SC-007 production query validation with 5 representative midwifery questions; note any gaps or deviations from quickstart instructions)
- [ ] T059 [P] Validate all Phase 1 success criteria per `spec.md` SC-001 through SC-007 (checklist: SC-001 first promoted batch complete; SC-002 <60 s average review time measured during walkthrough; SC-003 audit coverage 100% verified by test_audit_log.py; SC-004 ≥20 production chunks confirmed; SC-005 compliance doc reviewed and signed off; SC-006 WhatsApp registration submitted; SC-007 ≥5 representative queries return relevant snippets)

## Completion

- [ ] All 7 success criteria SC-001–SC-007 are green
- [ ] 413 error is returned when uploading a file >10 MB
- [ ] 409 error is returned on concurrent review attempt
- [ ] Approve/Discard buttons show loading state and cannot be double-clicked during in-flight requests
- [ ] `backend/README.md` is complete and accurate
- [ ] `quickstart.md` walkthrough completed without deviation; any gaps documented
- [ ] Run `/speckit-analyze` to verify consistency
