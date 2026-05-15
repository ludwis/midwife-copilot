# Research: Phase 1 — Knowledge Foundation & Compliance Skeleton

**Phase**: 0 — Outline & Research
**Date**: 2026-05-15
**Status**: Complete — all unknowns resolved

---

## 1. WhatsApp Text Export Format

**Decision**: Parse the standard WhatsApp `.txt` export using a regex that handles both common locale variants of the timestamp prefix.

**Rationale**: WhatsApp exports produce a UTF-8 text file where each message line begins with a timestamp in brackets. The exact format varies by device locale, but two patterns cover >99% of real exports:

```
[DD/MM/YYYY, HH:MM:SS] Sender Name: message text
[DD.MM.YY, HH:MM:SS] Sender Name: message text
```

Multi-line messages (message text continues on the next line without a timestamp prefix) must be appended to the previous message before processing.

**Parser strategy**:
```python
WHATSAPP_LINE_RE = re.compile(
    r"^\[?(\d{1,2}[/\.]\d{1,2}[/\.]\d{2,4}),?\s(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s[-–]\s(.+?):\s(.+)$"
)
```

System messages (e.g., "Messages and calls are end-to-end encrypted", "You deleted this message") are identified by the absence of a sender name separator or by a known set of prefixes and discarded before extraction.

**Alternatives considered**: Using a third-party `whatsapp-chat-parser` library — rejected because the library assumptions do not cover all locale variants encountered in Polish-language midwifery exports, and the parsing logic is simple enough to own directly.

---

## 2. Messenger JSON Export Format

**Decision**: Parse the `message_1.json` (and `message_N.json` for paginated exports) from Facebook's "Download Your Information" tool.

**Structure**:
```json
{
  "participants": [{"name": "Sender A"}, {"name": "Sender B"}],
  "messages": [
    {
      "sender_name": "Client Name",
      "timestamp_ms": 1715000000000,
      "content": "message text"
    }
  ],
  "title": "Conversation Title"
}
```

Messages without a `content` field (photos, stickers, reactions) are skipped. `timestamp_ms` is converted to UTC ISO-8601. Messages are sorted ascending by timestamp (the export is newest-first by default).

**Multi-file handling**: If the midwife uploads multiple `message_N.json` files for the same conversation, the importer merges them by deduplicating on `(sender_name, timestamp_ms, content)` and sorting chronologically.

**Alternatives considered**: Parsing Messenger HTML exports — rejected because the HTML format is unstable and the JSON format is the structured export option. HTML parsing would be fragile.

---

## 3. PII Stripping

**Decision**: Two-pass approach — spaCy multilingual NER first, then regex patterns for structured identifiers.

**Rationale**: Midwifery chats are likely in Polish or Polish-English mixed. spaCy's `xx_ent_wiki_sm` (multilingual) model detects `PERSON`, `LOC`, and `ORG` entities across many languages including Polish. This covers names and place references. Regex patterns handle the structured data that NER misses: phone numbers, email addresses, and any remaining numeric identifiers.

**PII replacement strategy**: Replace detected spans with a placeholder indicating the entity type. This preserves the grammatical structure and readability of the Q&A pair while removing the personal data.

```python
# Example replacements
"Czy Ania powinna..." → "Czy [IMIĘ] powinna..."
"+48 601 234 567"    → "[TELEFON]"
"anna@gmail.com"     → "[EMAIL]"
"ul. Krótka 5"       → "[ADRES]"
```

**spaCy model**: `xx_ent_wiki_sm` — smallest multilingual model; adequate for NER in Polish. Load once at startup; thread-safe for concurrent requests.

**Regex patterns** (applied after NER):
- Phone: `(\+\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}`
- Email: standard RFC 5322 simplified pattern
- Polish PESEL: `\b\d{11}\b` (11-digit national ID)
- Polish NIP: `\b\d{3}-\d{3}-\d{2}-\d{2}\b` or `\b\d{10}\b`

**Verification**: After stripping, the chunk is re-scanned for any remaining digit sequences >6 digits and flagged for human review if found (conservative, avoids false negatives).

**Alternatives considered**:
- Presidio (Microsoft) — more complete PII coverage but adds a heavy dependency and is not optimized for Polish text
- OpenAI moderation/GPT for PII extraction — rejected (data would leave EU before stripping)
- `pl_core_news_sm` (Polish-only spaCy model) — considered, but the midwife may have English-language clients; the multilingual model covers both

---

## 4. Q&A Extraction via Gemini

**Decision**: Use Gemini 2.0 Flash with a structured extraction prompt to identify question-answer pairs from parsed, PII-stripped conversation turns.

**Rationale**: Rule-based Q&A detection (e.g., detecting `?` in client messages) produces too many false positives and misses implicit questions ("I've been having backaches"). LLM extraction with a constrained output format is more accurate and can be validated by schema.

**Extraction prompt**:
```
You are processing a chat conversation between a midwife and a client.
The conversation has been stripped of personal identifiers.

Your task: extract discrete question-and-answer knowledge pairs that represent 
general midwifery knowledge — advice, explanations, and guidance that would be 
useful to answer similar questions from other clients.

Rules:
- Include only exchanges where the client asks a substantive question and the 
  midwife provides a substantive answer.
- Do NOT include scheduling, administrative, or purely social exchanges.
- Each pair must be standalone — no references to "you" (client-specific context).
- Output as a JSON array of objects: {"question": "...", "answer": "..."}
- If no qualifying pairs exist, output: []

Conversation:
{conversation_turns}
```

**Output validation**: The response is parsed as JSON and validated with Pydantic. Invalid JSON triggers a retry (max 2 retries). Empty arrays are valid — the batch is recorded as "no extractable pairs."

**Batching**: Conversations are split into windows of 50 turns (with 10-turn overlap for context continuity) if the total token count exceeds 8k tokens.

**Alternatives considered**:
- Rule-based extraction — rejected (too many false positives on implicit questions)
- Fine-tuned classifier — rejected (insufficient training data in Phase 1)

---

## 5. Near-Duplicate Detection

**Decision**: Two-pass deduplication: exact hash first, then cosine similarity on Vertex AI embeddings for near-duplicates.

**Pass 1 — Exact hash**: SHA-256 of normalized question text (lowercased, whitespace-collapsed, Polish diacritics preserved). If a chunk with the same hash already exists in staging or production, the new chunk is flagged as `duplicate_exact` and surfaced to the reviewer rather than silently dropped (FR-012).

**Pass 2 — Semantic similarity**: For chunks that pass the hash check, compute the Vertex AI text embedding (`textembedding-gecko-multilingual@001`, `eu` region) of the question text. Compare cosine similarity against the embedding cache of all existing staging and production chunks. Threshold: `similarity > 0.90` → flag as `duplicate_near`. The reviewer sees both the candidate and the similar existing chunk side-by-side.

**Embedding cache**: Stored as a JSON file in GCS (`gs://midwife-bot-audit-{env}/embeddings/cache.jsonl`) and loaded at startup. Updated after each promotion to production. In Phase 1 volume (< 200 chunks), a full pairwise scan is acceptable (O(n) per new chunk, n ≤ 200).

**Alternatives considered**:
- TF-IDF cosine similarity — considered as a simpler alternative; rejected because it underperforms on short Polish-language texts and would require building/maintaining a custom vocabulary
- Pinecone or similar vector DB — rejected (external service, GDPR residency concerns, premature for Phase 1 scale)

---

## 6. Audit Log for Knowledge Events

**Decision**: Reuse the dual-write pattern established in the 001 plan: Cloud Logging (structured JSON) + GCS append (JSONL, daily partitioned). The 001 audit log schema is extended with knowledge-event-specific fields.

**Knowledge audit event types** (in addition to 001 message events):

| Event Type | When | Key Fields |
|------------|------|-----------|
| `kb_import_started` | File uploaded, extraction begins | `import_id`, `source_format`, `filename_hash`, `actor` |
| `kb_import_completed` | Extraction finished | `import_id`, `chunks_extracted`, `chunks_flagged_duplicate`, `duration_ms` |
| `kb_chunk_staged` | Chunk enters staging index | `import_id`, `chunk_id`, `content_hash` |
| `kb_chunk_approved` | Reviewer approves (no edit) | `chunk_id`, `actor` |
| `kb_chunk_edited` | Reviewer edits before approve | `chunk_id`, `actor`, `content_hash_before`, `content_hash_after` |
| `kb_chunk_discarded` | Reviewer discards | `chunk_id`, `actor` |
| `kb_chunk_promoted` | Chunk moves to production index | `chunk_id`, `actor`, `production_vertex_id`, `content_hash` |
| `kb_query_test` | Production index test query | `query_text`, `result_count`, `actor` |

**GCS path**: `gs://midwife-bot-audit-{env}/{YYYY}/{MM}/{DD}/audit.jsonl` (same bucket, same daily file as message events — event_type field differentiates them).

**Actor identity**: In Phase 1, actor is always `"midwife"` (single-user admin system). The field is included for forward-compatibility with multi-operator scenarios.

**Alternatives considered**: A separate Firestore collection for KB audit — rejected because it does not provide the tamper-evident, append-only guarantee required by FR-008. The GCS retention lock is irreversible; Firestore document deletion is trivially possible.

---

## 7. Compliance Framework Document Scope

**Decision**: The compliance framework (FR-009) is a Markdown document at `docs/compliance-framework.md`, covering the four mandatory areas before Phase 3. It is NOT a database entity.

**Required sections**:
1. **Consent message text**: Exact WhatsApp message sent at onboarding (Polish + English versions)
2. **AI disclosure language**: Onboarding disclosure text + per-message badge label in the PWA
3. **Data retention periods**: Per data type — conversation messages, drafts, KB chunks, audit log, client profiles — with legal basis
4. **Right-to-erasure procedure**: Step-by-step: what gets deleted from Firestore, what stays in the audit log and why (GDPR Art. 17(3)(e) legal claims exception)

**Delivery**: Document is authored in Phase 1, reviewed by the midwife (and ideally a GDPR-aware advisor), and marked as reviewed with a signature line before Phase 3 begins (SC-005).

**Alternatives considered**: A structured JSON/YAML compliance config — rejected because the compliance framework is a human-reviewed legal document, not machine-consumed config. Markdown with clear section structure is more appropriate.

---

## 8. Messaging Channel Registration

**Decision**: Initiate WhatsApp Business API registration with Meta immediately (FR-010). This is an administrative action, not a code deliverable.

**Steps to initiate**:
1. Create a Meta Business Suite account for the midwifery practice
2. Submit business verification documents (healthcare practice registration)
3. Apply for the WhatsApp Cloud API — select "Health / Wellness" as business category
4. Register a dedicated phone number for the bot (must not be previously registered with WhatsApp personal)
5. Complete the business phone number verification

**Fallback channel**: If Meta registration is rejected or delayed beyond Phase 3's start, the fallback is a Telegram Bot API adapter. The hexagonal architecture (Constitution II) ensures the core pipeline requires only a `MessageChannel` interface — a Telegram adapter can be added without changes to `bot/`.

**Expected timeline**: Meta business verification typically takes 1–4 weeks; WhatsApp Cloud API approval for healthcare can take 2–6 weeks. Starting in Phase 1 is mandatory to avoid blocking Phase 3.

---

## 9. Testing Strategy for Phase 1

**Decision**: Mirror the 001 testing approach.

- **Integration tests** use Firestore emulator for all state-critical paths: import tracking, chunk state transitions, audit log writes (mocked as GCS local file in integration mode).
- **Unit tests** cover: WhatsApp parser (all timestamp variants), Messenger JSON parser (multi-file merge, missing-content skip), PII stripper (known entity types), deduplicator (hash and similarity threshold logic).
- **No Vertex AI Search or Gemini in unit tests**: VCR-pattern recorded fixtures (`pytest-recording`) for Gemini extraction calls; real Vertex AI Search queries gated behind `INTEGRATION=true` env flag.
- **Acceptance test**: A golden dataset — a hand-crafted 30-message WhatsApp export with known Q&A pairs and known PII — is used as a regression fixture. The expected extracted chunks (PII-stripped) are version-controlled as a JSON file.
