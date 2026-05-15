# Feature Specification: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Feature Branch**: `002-phase-1-knowledge-foundation`

**Created**: 2026-05-15

**Status**: Draft

**Input**: User description: "Break the midwife co-pilot MVP into phases and specify Phase 1: Knowledge Foundation & Compliance Skeleton"

---

## Context: Proposed MVP Phase Breakdown

The full midwife co-pilot MVP is large enough that building it end-to-end before any validation risks wasted effort. Breaking it into four sequential phases allows each phase to deliver standalone value and produce a concrete artifact that unblocks the next.

| Phase | Focus | Exit Condition |
|-------|-------|----------------|
| **Phase 1** | Knowledge Foundation & Compliance Skeleton | Midwife's knowledge is indexed and searchable; audit trail and compliance framework are in place |
| **Phase 2** | Co-pilot Core Backend | System can receive a message and return an AI-grounded draft with citations and urgency classification |
| **Phase 3** | WhatsApp Integration & Midwife PWA | Midwife can receive WhatsApp messages from real clients and approve/edit/send replies from her phone |
| **Phase 4** | Hardening & Pilot Launch | End-to-end tested with 2–3 real clients; 24h window enforcement; KB staging review live |

This specification covers **Phase 1** only.

---

## Phase 1 Overview

Phase 1 converts the midwife's existing conversational history (WhatsApp or Messenger chat exports) into a structured, searchable knowledge base, and puts the compliance and audit infrastructure in place before any client-facing functionality exists. No client-facing messages are sent in this phase — this is entirely a backend and data preparation milestone.

**What Phase 1 delivers:**
- The midwife's expertise is no longer trapped in chat exports — it is queryable, cited, and reviewable.
- An append-only audit trail captures every knowledge management event from day one.
- The compliance framework (consent design, AI disclosure design, data retention policy) is defined and documented before any client touches the system.
- The messaging channel registration process is initiated (long lead time; must start now).

**Why this phase first:**
Without a knowledge base, there is nothing to retrieve — the AI pipeline in Phase 2 has no ground to stand on. Without the audit infrastructure, Phase 2's events would be unlogged from the start. Without the compliance skeleton, Phase 3 would need a retrofit that is harder and riskier than building in from the beginning.

---

## Clarifications

### Session 2026-05-15

- Q: What type of review interface is in scope for Phase 1? → A: Minimal web app on Firebase Hosting
- Q: What authentication mechanism should protect the Phase 1 admin review interface? → A: Google OAuth via Firebase Auth
- Q: When a batch is fully discarded, should the midwife be able to re-submit the same export file? → A: Allow re-submission — creates a new import record; previous discard history preserved in audit log
- Q: When an extraction fails (e.g., persistent Gemini API error), how should the midwife recover? → A: Re-submit the file using the existing FR-015 re-import flow; no separate retry mechanism needed
- Q: What is the target deployment posture for Phase 1? → A: Single shared `dev` GCP project from day one; no local-only phase

---

## User Scenarios & Testing

### User Story 1 — Knowledge Extraction from Chat Exports (Priority: P1)

The midwife has years of WhatsApp and Messenger conversations with clients. She exports them and wants to turn those conversations into a reusable knowledge base that the AI can draw on when drafting replies.

**Why this priority**: Without extracted, indexed knowledge the AI has nothing to retrieve — every downstream phase depends on this.

**Independent Test**: Upload a batch of chat export files, run the extraction process, inspect the resulting Q&A chunks in the staging review interface, and confirm that the midwife can read, approve, or discard each one.

**Acceptance Scenarios**:

1. **Given** a WhatsApp chat export file, **When** the midwife submits it for processing, **Then** the system identifies question-and-answer exchanges within the conversation and surfaces them as discrete, reviewable knowledge chunks.
2. **Given** a Messenger JSON export, **When** the midwife submits it, **Then** the system processes it identically to a WhatsApp export and produces comparable reviewable chunks.
3. **Given** a batch of extracted chunks, **When** the midwife reviews them, **Then** she can approve a chunk (adds it to the staging index), edit it before approving, or discard it — and each action is recorded.
4. **Given** a chat export containing personal client identifiers (names, phone numbers), **When** the extraction runs, **Then** the resulting knowledge chunks contain the medical/midwifery content but not the client's personal data.

---

### User Story 2 — Staging-to-Production Knowledge Promotion (Priority: P1)

Chunks approved during extraction go into a staging index. The midwife reviews the staging batch and deliberately promotes chunks to the production index that the AI will actually use for retrieval.

**Why this priority**: Unreviewed or incorrect knowledge must never reach the production retrieval index — the two-tier gate is a safety requirement, not a nice-to-have.

**Independent Test**: Approve several chunks into staging, trigger a review session, promote some, edit one before promoting, discard one, and verify the production index only contains the promoted chunks.

**Acceptance Scenarios**:

1. **Given** chunks in the staging index, **When** the midwife opens the weekly review queue, **Then** she sees all unreviewed staged chunks with their extracted content and source conversation context.
2. **Given** a staged chunk, **When** she promotes it, **Then** it moves from staging to production and is available for retrieval.
3. **Given** a staged chunk with an error or overly specific content, **When** she edits and promotes it, **Then** the corrected version reaches production and the original draft is preserved in the audit log.
4. **Given** a staged chunk that should not be generalized (e.g., advice specific to one client's history), **When** she discards it, **Then** it is removed from staging and never enters production.

---

### User Story 3 — Compliance Framework Documentation & Review (Priority: P2)

Before any client-facing message is sent, the compliance posture must be defined: what consent language will be used, what AI disclosure language will appear, how long data is retained, and what the right-to-erasure process looks like.

**Why this priority**: Regulatory exposure (GDPR, AI Act transparency obligations, potential medical device classification) requires these decisions to be made and documented before pilot launch. Retrofitting compliance after clients are onboarded is significantly harder.

**Independent Test**: A compliance reviewer (or the midwife herself) can read a single document that answers: "What does the client consent to? How is AI involvement disclosed? How long is data kept? How does a client request deletion?"

**Acceptance Scenarios**:

1. **Given** the compliance framework document, **When** reviewed, **Then** it specifies the exact consent message text the system will send to new clients.
2. **Given** the framework, **When** reviewed, **Then** it specifies how AI involvement is disclosed to clients (at onboarding and optionally per-message).
3. **Given** the framework, **When** reviewed, **Then** it defines retention periods for conversation data, audit logs, and knowledge base entries, with justification under applicable law.
4. **Given** the framework, **When** reviewed, **Then** it describes the right-to-erasure workflow: what gets deleted, what is retained and why.

---

### User Story 4 — Audit Trail for Knowledge Events (Priority: P2)

Every extraction run, every staging action (approve / edit / discard / promote), and every production index update is recorded in an immutable audit log so that the provenance of any knowledge base entry can be reconstructed.

**Why this priority**: Healthcare-adjacent operations require evidence. Knowing what the AI knows — and when it learned it — must be auditable from day one.

**Independent Test**: Run an extraction, approve two chunks, discard one, promote one to production. Then query the audit log and confirm all four events appear with timestamps, actor identity, and content reference.

**Acceptance Scenarios**:

1. **Given** a completed extraction run, **When** the audit log is queried, **Then** it records: timestamp, source file identifier, number of chunks produced, and the identity of the operator who triggered it.
2. **Given** a staging review action (approve / discard / edit), **When** recorded, **Then** the audit entry includes the chunk ID, action taken, operator identity, and timestamp.
3. **Given** a promotion to production, **When** recorded, **Then** the entry includes the chunk ID, content hash before and after any edit, and timestamp.
4. **Given** the audit log, **When** a chunk's provenance is queried, **Then** the full history from extraction to production is reconstructable.

---

### Edge Cases

- What happens when a chat export contains no identifiable Q&A pairs (e.g., it is purely social conversation)?
- If extraction fails due to a persistent API error, the midwife recovers by re-submitting the file. The `kb_imports.error_message` field surfaces the failure reason in the review UI. No separate retry mechanism is provided; the re-submission path (FR-015) is the recovery path for both failed and fully-discarded imports.
- What happens when two extractions produce near-identical chunks — does the system flag potential duplicates before staging?
- If the midwife discards all extracted chunks from a batch, she MAY re-submit the same export file. A new `kb_imports` document is created (same `filename_hash`, new `import_id`); the prior import and all its discarded chunks remain in the audit log. Multiple `kb_imports` records sharing a `filename_hash` are valid and expected in this scenario.
- What if the messaging channel registration is rejected by the platform — is there a documented fallback channel?

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST accept chat export files in WhatsApp text format and Messenger JSON format and extract question-and-answer knowledge pairs from them.
- **FR-002**: System MUST strip personally identifiable information (client names, phone numbers) from extracted knowledge chunks before they enter the staging index.
- **FR-003**: Extracted chunks MUST be placed in a staging index before any can reach the production retrieval index.
- **FR-004**: The midwife MUST be able to review each staged chunk and take one of three actions: approve, edit-then-approve, or discard.
- **FR-005**: Only chunks explicitly promoted by the midwife (or a designated reviewer) MUST reach the production index.
- **FR-006**: The production index MUST be queryable to validate that promoted chunks are retrievable before Phase 2 builds on it.
- **FR-007**: Every knowledge management event (extraction, staging action, promotion, discard) MUST be written to an append-only audit log with timestamp, actor, and content reference.
- **FR-008**: The audit log MUST be stored in a manner that prevents modification or deletion for a minimum of 7 years.
- **FR-009**: A compliance framework document MUST be produced and reviewed before Phase 3 begins, covering: consent message text, AI disclosure language, data retention periods, and right-to-erasure procedure.
- **FR-010**: Messaging channel business registration MUST be initiated by end of Phase 1 (registration approval has a long and unpredictable lead time).
- **FR-011**: System MUST maintain two separate knowledge indexes (staging and production) that are independently queryable.
- **FR-012**: When near-duplicate chunks are detected during extraction, the system MUST surface them for explicit reviewer decision rather than auto-deduplicating silently.
- **FR-013**: Phase 1 MUST include a minimal web app deployed to Firebase Hosting that provides the chunk review interface — supporting read, approve, edit-then-approve, discard, and promote-to-production actions. This app establishes the hosting and auth infrastructure the Phase 3 PWA will extend.
- **FR-014**: The Phase 1 admin review app MUST be protected by Firebase Auth using Google OAuth as the sole sign-in provider. Access is restricted to a single pre-authorised Google account (the midwife's). No unauthenticated routes may reach review or promotion functionality.
- **FR-015**: The system MUST allow re-submission of a previously imported export file. Each submission creates a new `kb_imports` document with the same `filename_hash` and a new `import_id`. Multiple `kb_imports` records with the same `filename_hash` are valid; deduplication logic (FR-012) handles any resulting duplicate chunks at staging time. This re-submission path serves as the recovery mechanism for both fully-discarded batches and failed extractions (`status: failed`).

### Key Entities

- **ChatExport**: A raw file (WhatsApp text or Messenger JSON) submitted by the midwife as input to the extraction process. Identified by file name and import timestamp.
- **KnowledgeChunk**: A discrete extracted Q&A pair. Has a status (staged / promoted / discarded), a content hash, a source export reference, and an extraction timestamp.
- **StagingIndex**: The holding area for extracted chunks awaiting human review. Writable during extraction; readable during review.
- **ProductionIndex**: The retrieval index used by the AI in Phase 2+. Only written to via explicit promotion.
- **AuditEvent**: An immutable record of a single knowledge management action. Contains: event type, timestamp, actor identity, entity reference, and a content snapshot or hash.
- **ComplianceFramework**: The documented set of decisions about consent, disclosure, retention, and erasure. A versioned document, not a database entity.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: At least one batch of chat exports is processed, reviewed, and has a first set of chunks promoted to production by end of Phase 1.
- **SC-002**: The midwife can complete a single chunk review (read, decide, act) in under 60 seconds on average during the first review session.
- **SC-003**: 100% of knowledge events (extraction, staging, promotion, discard) are captured in the audit log — verified by cross-checking event count against reviewer action count for a test batch.
- **SC-004**: The production index contains a minimum of 20 manually reviewed and approved knowledge chunks before Phase 2 begins.
- **SC-005**: The compliance framework document is complete and has been reviewed by at least one person with GDPR and healthcare-adjacent domain awareness before Phase 3 begins.
- **SC-006**: Messaging channel business registration application is submitted within the Phase 1 window.
- **SC-007**: A test query against the production index returns relevant results for at least 5 representative midwifery questions — confirming the index is semantically useful.

---

## Assumptions

- The midwife has existing chat exports (WhatsApp or Messenger) available to submit for ingestion.
- The initial volume of exports is manageable for manual review in approximately one week (estimated 20–50 chunks from first batch after discards).
- A designated compliance reviewer (the midwife herself or a qualified advisor) is available to review the compliance framework before Phase 3.
- Messaging channel approval has no guaranteed timeline; initiating registration in Phase 1 is necessary to avoid blocking Phase 3.
- The two-index architecture (staging and production) is a fixed architectural constraint — unreviewed knowledge must never reach production.
- Phase 1 targets a single shared `dev` GCP project from day one. Unit and integration tests use the Firestore emulator and VCR fixtures for Gemini; Vertex AI Search and GCS audit log tests require the real `dev` GCP project (no local emulator exists for Vertex AI Search). A separate `prod` GCP environment is introduced no earlier than Phase 4.
- Right-to-erasure for the audit log follows the applicable legal exception: audit records are retained even after client erasure requests because they constitute evidence needed for legal claims.
- Personal identifiers in source chat exports are removed at extraction time, not at staging time, so that no client PII ever enters the staging index.
- 30–50% of auto-extracted chunks will be discarded after manual review — this is expected and acceptable.
