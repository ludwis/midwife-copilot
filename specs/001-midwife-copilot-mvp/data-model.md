# Data Model: Midwife Co-pilot MVP

**Phase**: 1 — Design & Contracts  
**Date**: 2026-05-14  
**Storage**: Firestore (europe-west1) — mutable state; GCS (audit log, append-only)

---

## Entity Overview

```
Client ──── has one ──── Conversation
               │
               ├── contains many ── Message
               │
               └── has one ──────── AIDraft (per message cycle, overwritten)

Client ──── has one ──── ClientInvite (during onboarding)

Message (outbound) ──── may create ──── StagedKBItem
StagedKBItem ──── may be promoted to ──── ProductionKBItem (in Vertex AI Search)

PushSubscription ──── belongs to ──── midwife (singleton for MVP)
```

---

## Firestore Collections

### Collection: `clients`

**Document ID**: Auto-generated Firestore ID (also used as `client_id`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Client's full name |
| `phone_number` | string | ✅ | E.164 format (e.g., `+972501234567`) |
| `due_date` | timestamp | ✅ | Expected delivery date |
| `state` | enum | ✅ | See state machine below |
| `invite_token` | string | conditional | Single-use token; present until token is matched |
| `invite_link` | string | conditional | Full `wa.me/{number}?text=...` URL |
| `last_client_inbound_at` | timestamp | conditional | UTC; set on every inbound message; drives 24h window |
| `human_only_preference` | boolean | ✅ | Set by "HUMAN" keyword; defaults to `false` |
| `consent` | map | conditional | Set once on YES reply |
| `consent.message_id` | string | — | WhatsApp message ID of the YES reply |
| `consent.timestamp` | timestamp | — | UTC timestamp of YES reply |
| `consent.verbatim_reply` | string | — | Exact text of the client's reply (must be "YES" or variant) |
| `created_at` | timestamp | ✅ | Record creation timestamp |
| `archived_at` | timestamp | conditional | Set when midwife archives client |

**Client State Enum**:

| State | Description | Transition In | Transition Out |
|-------|-------------|---------------|----------------|
| `pending_invite` | Token issued, awaiting first WhatsApp message | Client created | First message matches token |
| `awaiting_consent` | Consent prompt sent | Token matched | Client replies YES (→ active) or anything else (re-send prompt) |
| `active` | Fully onboarded; normal message flow | YES consent received | STOP keyword, HUMAN keyword (stays active), archive, window close |
| `paused` | Client sent STOP | Any active state | Midwife manually resumes (post-MVP) |
| `human_only` | Client sent HUMAN — flag on `human_only_preference` | active (flag set, state stays active) | — |
| `window_closed` | > 24h since last inbound | active | Client sends new message → active |
| `archived` | Midwife archived client | Any state | — (terminal) |

**Note**: `human_only` is implemented as a flag on the `active` state, not a separate state — clients with `human_only_preference=true` continue normal routing; the midwife sees the flag and decides per case.

**Validation rules**:
- `phone_number` must be unique across non-archived clients
- `invite_token` must be unique globally (UUID4 recommended)
- `state` transitions must go through Firestore transactions to prevent races

---

### Collection: `conversations`

**Document ID**: Same as `client_id` (one conversation per client in MVP)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `client_id` | string | ✅ | Reference to `clients` doc |
| `current_draft_id` | string | conditional | ID of active `AIDraft`; null when none pending |
| `current_urgency` | enum | conditional | Urgency of most recent unactioned inbound message |
| `updated_at` | timestamp | ✅ | Last activity timestamp |

---

### Subcollection: `conversations/{conversation_id}/messages`

**Document ID**: WhatsApp `message.id` (inbound) or Firestore auto-ID (outbound) — use WhatsApp ID for idempotency

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `direction` | enum | ✅ | `inbound` or `outbound` |
| `body` | string | ✅ | Message text |
| `timestamp` | timestamp | ✅ | UTC; from WhatsApp for inbound, system time for outbound |
| `urgency` | enum | inbound only | `urgent`, `high`, `normal`, `low` |
| `action_type` | enum | outbound only | `ai_approved`, `ai_edited`, `midwife_original` |
| `draft_id` | string | outbound + AI | Reference to the draft this was based on |
| `tagged_for_kb` | boolean | outbound only | Whether midwife tagged this for KB staging |

---

### Subcollection: `conversations/{conversation_id}/drafts`

**Document ID**: Auto-generated (one active draft per message cycle; old drafts are NOT deleted — retained for audit)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `body` | string | ✅ | Generated draft text |
| `urgency` | enum | ✅ | Urgency classification (`urgent`, `high`, `normal`, `low`) |
| `citations` | array | ✅ | List of KB snippet objects used to generate the draft |
| `citations[].chunk_id` | string | — | Vertex AI Search document/chunk ID |
| `citations[].snippet` | string | — | Extracted text snippet shown to midwife |
| `citations[].source_metadata` | map | — | Optional source info (e.g., original Q&A date) |
| `status` | enum | ✅ | `pending`, `approved`, `edited`, `discarded` |
| `source_message_id` | string | ✅ | The inbound message ID this draft responds to |
| `created_at` | timestamp | ✅ | Draft generation timestamp |
| `actioned_at` | timestamp | conditional | When the midwife approved/edited/discarded |

---

### Collection: `kb_staging`

**Document ID**: Auto-generated

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | ✅ | Client's original message (the Q in Q&A) |
| `answer` | string | ✅ | The midwife-approved reply (the A) |
| `conversation_id` | string | ✅ | Reference to source conversation |
| `message_id` | string | ✅ | Reference to source outbound message |
| `staged_at` | timestamp | ✅ | When tagged for KB |
| `status` | enum | ✅ | `pending`, `promoted`, `discarded` |
| `actioned_at` | timestamp | conditional | When reviewed |
| `production_chunk_id` | string | conditional | Set on promotion: the Vertex AI Search chunk ID |

---

### Collection: `push_subscriptions`

**Document ID**: SHA256 hash of subscription endpoint URL (deduplication key)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `endpoint` | string | ✅ | Push service URL |
| `keys.p256dh` | string | ✅ | Public key for payload encryption |
| `keys.auth` | string | ✅ | Authentication secret |
| `registered_at` | timestamp | ✅ | Registration timestamp |
| `user_agent` | string | optional | Device/browser info for debugging |

---

## Audit Log Schema (GCS / Cloud Logging)

Written as newline-delimited JSON to GCS path: `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl`

### Event: `inbound_message`

```json
{
  "event_type": "inbound_message",
  "timestamp": "2026-05-14T10:23:45.123Z",
  "client_id": "abc123",
  "conversation_id": "abc123",
  "message_id": "wamid.xxxx",
  "body": "Is it normal to feel pressure at 36 weeks?",
  "urgency": "normal",
  "phone_number_hash": "sha256(+972501234567)"
}
```

### Event: `ai_draft`

```json
{
  "event_type": "ai_draft",
  "timestamp": "2026-05-14T10:23:48.456Z",
  "client_id": "abc123",
  "conversation_id": "abc123",
  "draft_id": "draft_xyz",
  "source_message_id": "wamid.xxxx",
  "body": "Yes, pressure in the pelvic area at 36 weeks is common...",
  "urgency": "normal",
  "citation_chunk_ids": ["chunk_42", "chunk_87"]
}
```

### Event: `outbound_message`

```json
{
  "event_type": "outbound_message",
  "timestamp": "2026-05-14T10:24:12.789Z",
  "client_id": "abc123",
  "conversation_id": "abc123",
  "message_id": "wamid.yyyy",
  "body": "Yes, pressure in the pelvic area at 36 weeks is common...",
  "action_type": "ai_approved",
  "draft_id": "draft_xyz"
}
```

**Note**: `phone_number_hash` uses SHA256 for GDPR minimization in log records. The full phone number is stored only in Firestore `clients` collection.

---

## Vertex AI Search Documents (Knowledge Base)

### Production index document

```json
{
  "id": "kb_prod_0042",
  "content": {
    "mimeType": "text/plain",
    "text": "Q: Is it normal to feel pelvic pressure at 36 weeks?\nA: Yes, pelvic pressure is common in the third trimester as the baby descends..."
  },
  "structData": {
    "question": "Is it normal to feel pelvic pressure at 36 weeks?",
    "answer": "Yes, pelvic pressure is common...",
    "source_type": "approved_reply",
    "promoted_at": "2026-05-14",
    "tags": []
  }
}
```

### Staging index document

Same schema as production. Staging documents are NOT queryable by the retriever — only the production index is queried for draft generation.

---

## State Transition Summary

```
Client created → pending_invite
pending_invite → awaiting_consent      (first inbound matches token)
awaiting_consent → awaiting_consent    (non-YES reply: re-send prompt)
awaiting_consent → active              (client replies YES)
active → window_closed                 (> 24h since last inbound — checked at send time)
window_closed → active                 (new inbound message received)
active → paused                        (client sends STOP)
active [flag: human_only_preference=true] (client sends HUMAN — not a state change)
any → archived                         (midwife archives client)
```
