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
- [x] T056 [P] Add loading and error UX to `frontend/src/pages/KbReviewPage.vue` (spinner overlay during `fetchStagedChunks` and import polling; per-action loading state on Approve/Discard buttons to prevent double-click; toast notification on success (green) and error (red); empty-state illustration when `stagedChunks` is empty with message "No chunks awaiting review")
  <!-- Spinner overlay (bg-gray-50/70 + animate-spin) on review queue during loadingChunks. Refresh button now calls refreshQueue() which gates loadingChunks. Toast system added (addToast, auto-dismiss 3.5 s, transition-group animation). Success toast on approve/discard/edit_approve; error toast mirrors per-chunk inline error. Import polling fires success toast with chunk count on completed, error toast on failed. Empty-state SVG illustration added with "No chunks awaiting review" + sub-text. Inline spinner added to Approve/Save&Approve/Discard buttons. -->
- [x] T057 [P] Create `backend/README.md` with backend setup instructions (Python 3.12 venv, `pip install -r requirements.txt`, `python -m spacy download xx_ent_wiki_sm` as one-time step, Firestore emulator startup, `uvicorn api.main:app --reload`, GCP ADC login)
  <!-- backend/README.md created: venv setup, pip install, spacy one-time download, GCP ADC login, Firestore emulator startup, uvicorn command, env vars table, test commands, project structure, and admin endpoint reference. -->
- [x] T058 Run `quickstart.md` end-to-end walkthrough (all 10 sections; upload `golden_whatsapp_export.txt`; review extracted chunks; promote ≥20 chunks per SC-004; run SC-007 production query validation with 5 representative midwifery questions; note any gaps or deviations from quickstart instructions)
  <!-- Walkthrough executed 2026-05-16. All 84 tests pass (2 skipped: live Vertex AI). Golden dataset pipeline PASS: 8 chunks extracted, PII stripped, all expected questions present. GAP SC-004: golden dataset yields only 8 Q&A pairs — ≥12 additional chunks needed from real exports to reach the 20-chunk target. GAP SC-007: live Vertex AI query not run (requires real GCP data store population). SC-003 (audit) PASS via test_audit_log.py. SC-006 and SC-005 pending manual action. Full report at .maestro/playbooks/Working/T058-quickstart-walkthrough-report.md -->
- [ ] T059 [P] Validate all Phase 1 success criteria per `spec.md` SC-001 through SC-007 (checklist: SC-001 first promoted batch complete; SC-002 <60 s average review time measured during walkthrough; SC-003 audit coverage 100% verified by test_audit_log.py; SC-004 ≥20 production chunks confirmed; SC-005 compliance doc reviewed and signed off; SC-006 WhatsApp registration submitted; SC-007 ≥5 representative queries return relevant snippets)

## Completion

- [ ] All 7 success criteria SC-001–SC-007 are green
- [ ] 413 error is returned when uploading a file >10 MB
- [ ] 409 error is returned on concurrent review attempt
- [ ] Approve/Discard buttons show loading state and cannot be double-clicked during in-flight requests
- [ ] `backend/README.md` is complete and accurate
- [ ] `quickstart.md` walkthrough completed without deviation; any gaps documented
- [ ] Run `/speckit-analyze` to verify consistency
