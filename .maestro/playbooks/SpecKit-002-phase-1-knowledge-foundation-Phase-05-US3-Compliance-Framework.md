# Phase 05: User Story 3 — Compliance Framework Documentation

Author the two compliance documents required before Phase 3 (WhatsApp Integration) can begin: the GDPR-compliant framework covering consent, AI disclosure, data retention, and right-to-erasure; and the WhatsApp Business registration status tracker. These are documentation-only tasks with no code dependencies — they can run in parallel with US1/US2 after Phase 02 Foundational is complete.

**Priority**: P2. Required gate before Phase 3 launch; long lead time for WhatsApp registration means this must be initiated now.

## Spec Kit Context

- **Feature:** 002-phase-1-knowledge-foundation
- **Specification:** specs/002-phase-1-knowledge-foundation/spec.md (§User Story 3, FR-009, FR-010, SC-005, SC-006)
- **Research:** specs/002-phase-1-knowledge-foundation/research.md (§7 compliance, §8 WhatsApp registration)

## Tasks

- [x] T046 [P] [US3] Author `docs/compliance-framework.md` with four mandatory sections: (1) **Consent message text** — exact WhatsApp onboarding message in Polish + English versions; (2) **AI disclosure language** — onboarding disclosure paragraph + per-message badge label for the PWA; (3) **Data retention periods** — per data type (conversation messages, KB chunks, audit log JSONL, client profiles) each with GDPR legal basis and retention duration; (4) **Right-to-erasure procedure** — step-by-step describing what Firestore collections are deleted, what stays in the audit log with GDPR Art. 17(3)(e) legal claims exception rationale; include a review sign-off section per SC-005
- [x] T047 [P] [US3] Create `docs/whatsapp-registration-status.md` to track WhatsApp Business API registration per FR-010 (document all 5 steps: Meta Business Suite account, healthcare verification docs required, WhatsApp Cloud API application, bot phone number registration, phone number verification; record date submitted; include a risk note: "If Meta approval is not received before Phase 3 start, a fallback channel decision is required — any non-WhatsApp channel requires a constitution amendment per §Amendment Procedure before implementation"; leave status field to update as application progresses)

## Completion

- [x] Verify `docs/compliance-framework.md` answers all four questions: (1) what consent message text does the client receive? (2) how is AI involvement disclosed? (3) what are the retention periods? (4) what is the erasure procedure step-by-step?
- [x] Verify `docs/whatsapp-registration-status.md` documents all 5 registration steps and includes the fallback risk note
- [x] Verify the compliance framework review sign-off section is present (SC-005)
- [ ] Run `/speckit-analyze` to verify consistency
