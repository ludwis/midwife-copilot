---
type: reference
title: Compliance Framework — Stilla Midwife Co-pilot
created: 2026-05-16
tags:
  - gdpr
  - compliance
  - consent
  - ai-disclosure
  - data-retention
  - erasure
related:
  - '[[whatsapp-registration-status]]'
---

# Compliance Framework — Stilla Midwife Co-pilot

**Version**: 1.0-draft
**Status**: Pending review (see §Review Sign-off)
**Prepared by**: Development team
**Required gate**: This document MUST be reviewed and signed off before Phase 3 (WhatsApp Integration) begins, per SC-005 and FR-009.

---

## 1. Consent Message Text

The following message is sent to a new client at the start of their first WhatsApp conversation with the midwife's bot. The message must be sent and acknowledged before any substantive exchange occurs.

### Polish version (primary)

> Witaj! Jestem asystentem midwife [Imię Położnej], wspieranym przez sztuczną inteligencję.
>
> Zanim zaczniemy, proszę zapoznać się z poniższą informacją:
>
> 1. **Twoje dane**: Twoje wiadomości są przetwarzane i przechowywane przez okres 24 miesięcy w celu udzielania Ci odpowiedzi. Masz prawo do wglądu, sprostowania i usunięcia swoich danych w dowolnym momencie.
> 2. **Sztuczna inteligencja**: Odpowiedzi są tworzone przy wsparciu AI i sprawdzane przez położną przed wysłaniem. Nie stanowią one porady medycznej i nie zastępują wizyty lekarskiej.
> 3. **Poufność**: Twoje wiadomości nie są udostępniane stronom trzecim, z wyjątkiem przypadków wymaganych przez prawo.
>
> Jeśli wyrażasz zgodę na powyższe warunki i chcesz kontynuować, odpowiedz: **TAK**.
> Aby dowiedzieć się więcej lub zrezygnować, napisz: **NIE**.

### English version (reference / international clients)

> Hello! I am the AI-assisted midwifery support bot for [Midwife's Name].
>
> Before we begin, please read the following:
>
> 1. **Your data**: Your messages are processed and stored for up to 24 months in order to provide responses to you. You have the right to access, correct, and delete your data at any time.
> 2. **Artificial intelligence**: Replies are drafted with AI assistance and reviewed by the midwife before sending. They do not constitute medical advice and do not replace an in-person consultation.
> 3. **Confidentiality**: Your messages are not shared with third parties except where required by law.
>
> If you agree to the above and wish to continue, reply: **YES**.
> To learn more or opt out, reply: **NO**.

### Implementation notes

- The consent message is the first message sent in every new conversation thread. No KB retrieval or AI draft generation occurs until explicit consent (`TAK` / `YES`) is recorded in Firestore.
- The consent response (`TAK` / `YES` / `NIE` / `NO` / or unrecognised text) is stored in the `clients.consent_status` field with a timestamp.
- If the client responds with anything other than the affirmative, the bot sends a follow-up explaining how to reach the midwife directly and takes no further automated action.
- The consent message text is version-controlled in this document. Any change to the message text requires a document revision and a new review sign-off before deployment.

---

## 2. AI Disclosure Language

### 2a. Onboarding disclosure

The consent message in §1 constitutes the onboarding AI disclosure. The key phrase is:

> "Replies are drafted with AI assistance and reviewed by the midwife before sending."

This disclosure satisfies the EU AI Act Art. 50 obligation to inform individuals they are interacting with an AI system, and the GDPR Art. 22 obligation to disclose automated decision-making involvement where applicable.

### 2b. Per-message badge label (PWA)

Each AI-drafted reply displayed in the midwife's Progressive Web App review interface carries a visible badge:

```
[AI draft — awaiting midwife review]
```

After the midwife approves, edits, or sends a reply, the badge changes to:

```
[Sent by midwife]
```

The client-facing WhatsApp message itself does **not** carry a per-message AI badge (the onboarding disclosure covers the ongoing use). If this decision is revised before Phase 3 launch, this section must be updated and the review sign-off repeated.

### 2c. Scope of AI involvement

| Action | AI involved? | Human review required? |
|--------|-------------|----------------------|
| Receiving a client message | No | — |
| Drafting a reply | Yes (Gemini) | Yes — midwife approves/edits before send |
| Sending a reply | No | Midwife initiates send |
| Knowledge base extraction | Yes (Gemini) | Yes — midwife reviews every chunk |
| Knowledge base promotion | No | Midwife initiates promotion |

No AI action results in an automated client-facing message without midwife approval.

---

## 3. Data Retention Periods

### Summary table

| Data type | Storage location | Retention period | GDPR legal basis | Deletion trigger |
|-----------|-----------------|-----------------|-----------------|-----------------|
| **Client conversation messages** | Firestore `conversations/{id}/messages` | 24 months from last message | Art. 6(1)(b) — contract performance | Expiry OR client erasure request |
| **Client profiles** | Firestore `clients/{id}` | Duration of active relationship + 24 months | Art. 6(1)(b) — contract performance | Erasure request or 24 months post-last interaction |
| **AI draft replies** | Firestore `conversations/{id}/drafts` | 30 days (transient) | Art. 6(1)(f) — legitimate interest (quality review) | Auto-purged 30 days after creation |
| **KB chunks — staging** | Firestore `kb_chunks` (status: staged/discarded) | Until discarded + 90 days | Art. 6(1)(f) — legitimate interest (knowledge operations) | 90-day auto-purge post-discard |
| **KB chunks — production** | Vertex AI Search index + Firestore `kb_chunks` (status: promoted) | Indefinite (active knowledge base) | Art. 6(1)(f) — legitimate interest | Manual removal by midwife |
| **Audit log** | GCS JSONL (append-only, retention lock) | 7 years minimum | Art. 6(1)(c) — legal obligation; Art. 17(3)(e) — legal claims | Not deleted (see §4) |
| **Chat export files** | GCS (raw uploads) | 30 days after extraction completes | Art. 5(1)(e) — storage limitation | Auto-deleted 30 days post-import |

### Notes on legal bases

- **Art. 6(1)(b) — Contract performance**: The midwifery service relationship is the lawful basis for storing conversation data. Clients are informed of this in the consent message.
- **Art. 6(1)(f) — Legitimate interest**: The midwife's legitimate interest in maintaining a high-quality, auditable knowledge base and reviewing AI drafts before sending. This interest does not override client rights; clients may object and erasure procedures apply (§4).
- **Art. 6(1)(c) — Legal obligation**: Healthcare-adjacent operations in Poland may be subject to record-keeping obligations. The 7-year audit log retention is a conservative upper bound aligned with Polish civil litigation limitation periods (art. 118 KC — 6 years general, extended by 1 year buffer).

### Automated enforcement

Retention enforcement is implemented as scheduled Cloud Functions:
- `purge_expired_messages` — runs daily; deletes `conversations` messages older than 24 months
- `purge_old_drafts` — runs daily; deletes `drafts` documents older than 30 days
- `purge_export_files` — runs daily; deletes raw GCS upload objects older than 30 days post-import completion

These functions are introduced in Phase 2+ (not Phase 1). Until they exist, retention is a manual obligation of the operator.

---

## 4. Right-to-Erasure Procedure

This section describes the procedure for responding to a client's right-to-erasure request under GDPR Art. 17. All steps are manual in Phase 1. Automated tooling is a Phase 4 enhancement.

### Who can receive an erasure request

The midwife (or designated operator). Requests arrive via:
- WhatsApp reply: client sends "USUŃ MOJE DANE" / "DELETE MY DATA" / any equivalent
- Direct contact (email, phone, in-person)

### What gets deleted

Upon receipt of a verified erasure request, the following data is deleted within 30 days (GDPR Art. 17(1)):

1. **Firestore `clients/{client_id}`** — entire document deleted
2. **Firestore `conversations/{conv_id}/messages`** — all message documents under the client's conversation(s) deleted
3. **Firestore `conversations/{conv_id}/drafts`** — all draft documents deleted
4. **Firestore `conversations/{conv_id}`** — conversation root document deleted after sub-collections are cleared
5. **Vertex AI Search** — if any KB chunks were derived from conversations with this client and contain client-attributable content (unusual; PII stripping should prevent this), those chunks are removed from the production index

### What is NOT deleted — Audit log exception

The audit log (GCS JSONL files) is **not** modified in response to an erasure request. Legal basis for retention: **GDPR Art. 17(3)(e)** — the right to erasure does not apply where processing is necessary for the establishment, exercise, or defence of legal claims.

Rationale: The audit log records knowledge management actions (extraction runs, staging approvals, production promotions) and conversation-level events. These records may be required to demonstrate compliance with healthcare record-keeping obligations, to defend against claims of medical advice given or not given, or to satisfy a data protection authority audit. The audit log does **not** contain full message content — it contains event metadata and content hashes. The privacy impact of retaining this metadata is proportionate to the legal necessity.

This exception is documented here and disclosed in the consent message (§1) via the phrase: "except where required by law."

### Step-by-step procedure

| Step | Action | Actor | Deadline |
|------|--------|-------|----------|
| 1 | Receive and log erasure request (note: client identity, date received, channel) | Midwife | Day 0 |
| 2 | Verify client identity (cross-check phone number against `clients` collection) | Midwife | Day 1 |
| 3 | Delete `clients/{client_id}` Firestore document | Operator (dev or midwife via admin tool) | Day 7 |
| 4 | Delete all `conversations/{conv_id}/messages` sub-documents | Operator | Day 7 |
| 5 | Delete all `conversations/{conv_id}/drafts` sub-documents | Operator | Day 7 |
| 6 | Delete `conversations/{conv_id}` root document | Operator | Day 7 |
| 7 | Check KB chunks for any client-attributable content; remove from Vertex AI Search if found | Operator | Day 14 |
| 8 | Send written confirmation of erasure to client | Midwife | Day 30 |
| 9 | Record erasure completion in a separate erasure register (spreadsheet or Firestore `erasure_requests` collection) | Midwife | Day 30 |

The erasure register in step 9 retains: request date, client pseudonym or ID, data deleted, completion date, and any retained data with legal basis. The register itself is retained for 7 years (legal obligation, same basis as audit log).

### Exceptions summary

| Data | Retained after erasure? | Legal basis |
|------|------------------------|-------------|
| Audit log JSONL | Yes | GDPR Art. 17(3)(e) — legal claims |
| Erasure register | Yes | GDPR Art. 6(1)(c) — legal obligation |
| Anonymised KB chunks (no PII by design) | Yes | Effectively anonymous — GDPR does not apply |
| Client conversation messages | No | Deleted within 30 days |
| Client profile | No | Deleted within 7 days |

---

## 5. Review Sign-off

Per SC-005, this document must be reviewed by at least one person with GDPR and healthcare-adjacent domain awareness before Phase 3 begins.

| Reviewer | Role | Date reviewed | Signature / initials | Notes |
|---------|------|--------------|---------------------|-------|
| | | | | |
| | | | | |

**Review checklist**:
- [ ] Consent message text reviewed and approved for Polish-language use
- [ ] AI disclosure language reviewed and consistent with EU AI Act Art. 50 requirements
- [ ] Data retention periods reviewed and consistent with Polish healthcare record-keeping law
- [ ] Right-to-erasure procedure reviewed; Art. 17(3)(e) exception rationale approved
- [ ] Document version and status updated to `reviewed` before Phase 3 deployment

**This document is NOT approved for Phase 3 deployment until the sign-off table above is completed and version status is changed to `reviewed`.**
