# Feature Specification: Midwife Assistant Co-pilot Bot MVP

**Feature Branch**: `001-midwife-copilot-mvp`

**Created**: 2026-05-14

**Status**: Draft

**Input**: User description: "features are described in the MVP definition in midwife-assistant-bot-mvp-v4.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Midwife Reviews and Sends AI-Drafted Reply (Priority: P1)

A midwife receives a push notification when a client sends a WhatsApp message. She opens her inbox, sees the client's message alongside an AI-generated draft reply with supporting references. She taps Approve to send the draft as-is, or edits it, or writes her own reply from scratch.

**Why this priority**: This is the core daily workflow. Every other feature exists to support this loop. Without it, there is no product.

**Independent Test**: Can be fully tested by sending a message to a test client's WhatsApp number and verifying the midwife receives a notification, sees a draft, and can approve/edit/write a reply that gets delivered.

**Acceptance Scenarios**:

1. **Given** an active client sends a WhatsApp message, **When** the message is received by the system, **Then** the midwife receives a push notification and sees the message with an AI-drafted reply in her inbox within 30 seconds.
2. **Given** the midwife taps "Approve & Send", **When** the action is confirmed, **Then** the draft is delivered to the client's WhatsApp exactly as written and the conversation log records the action as "AI-drafted, midwife-approved".
3. **Given** the midwife taps "Edit", **When** she modifies the draft and sends, **Then** the edited version is delivered and the log records "AI-drafted, midwife-edited".
4. **Given** the midwife taps "Write Own", **When** she writes from scratch and sends, **Then** that message is delivered and the log records "midwife-original".
5. **Given** a draft is shown, **When** the midwife taps the citations panel, **Then** the knowledge base snippets used to generate the draft are visible.

---

### User Story 2 - Client Onboarding via Tokenized Link (Priority: P2)

A midwife adds a new client in her inbox. The system generates a unique WhatsApp link. The midwife shares the link with her client through any channel. The client taps it, WhatsApp opens with a pre-filled message, the client sends it, and the system registers the client and sends a consent/disclosure prompt. The client replies YES and is now active.

**Why this priority**: Without onboarding, there are no active clients to serve. It must work before any conversation can happen.

**Independent Test**: Can be tested end-to-end by creating a new client record, copying the generated link, sending it from a test phone, and confirming the client moves through consent to an "active" state visible in the midwife's client list.

**Acceptance Scenarios**:

1. **Given** the midwife fills in a client's name, phone number, and due date and submits, **When** the form is saved, **Then** a unique invite link and QR code are displayed for sharing.
2. **Given** a client taps the invite link, **When** WhatsApp opens, **Then** a pre-filled message containing the invite token is ready to send.
3. **Given** the client sends the pre-filled message, **When** the system receives it, **Then** the system links the phone number to the client record and sends the AI-disclosure and consent prompt automatically.
4. **Given** the client replies "YES", **When** the system receives the reply, **Then** the client's consent is recorded with message ID and timestamp, and the client status moves to "active".
5. **Given** the client replies anything other than "YES", **When** the system receives the reply, **Then** the consent prompt is resent with a reminder that YES is required to proceed.

---

### User Story 3 - Urgent Message Escalation Without AI Draft (Priority: P3)

When a client sends a message that indicates a potential emergency or high-urgency situation, the system bypasses AI drafting entirely and immediately alerts the midwife with a high-priority notification marked in red, prompting her to read and respond directly.

**Why this priority**: Safety is non-negotiable. Delayed response to a genuine emergency is the worst-case failure mode of the product.

**Independent Test**: Can be tested by sending a message containing urgency signals (e.g., pain, bleeding, fetal movement concerns) and confirming the inbox shows the message as urgent with no draft and a distinct visual treatment.

**Acceptance Scenarios**:

1. **Given** a client sends a message classified as high urgency, **When** the system processes it, **Then** no AI draft is generated and the item appears in the midwife's inbox highlighted as urgent.
2. **Given** an urgent item exists, **When** the midwife receives a push notification, **Then** the notification is sent at the highest priority level (distinct from normal message notifications).
3. **Given** the midwife opens an urgent item, **When** she views the conversation, **Then** she can write her own reply directly with no AI draft in the way.

---

### User Story 4 - Knowledge Base Tagging and Staging Review (Priority: P4)

After the midwife sends a reply she considers especially valuable, she tags the Q&A pair for the knowledge base. Tagged pairs enter a staging queue. Once a week, the midwife reviews staged items and promotes, edits, or discards each one before it becomes available as a reference for future AI drafts.

**Why this priority**: The KB is the quality engine behind the AI drafts. Without a feedback loop, draft quality degrades over time. This is a medium-term priority: needed in MVP but not day-one critical.

**Independent Test**: Can be tested by tagging a sent reply, navigating to the KB review screen, and confirming the item appears in the staging queue with promote/edit/discard options.

**Acceptance Scenarios**:

1. **Given** the midwife has just sent a reply, **When** she taps "Tag for KB", **Then** the client question and the approved reply are queued to the staging index.
2. **Given** staged items exist, **When** the midwife opens the KB review screen, **Then** she sees all pending items with the original question, the proposed answer, and action buttons.
3. **Given** the midwife promotes a staged item, **When** the action is confirmed, **Then** the item becomes available as a retrieval reference for future AI draft generation.
4. **Given** the midwife discards a staged item, **When** the action is confirmed, **Then** the item is permanently removed from the staging queue and never enters production.

---

### User Story 5 - 24-Hour Window State Enforcement (Priority: P5)

When the midwife tries to send a reply to a client but more than 24 hours have passed since the client's last inbound message, the system blocks freeform sending and informs the midwife that the service window is closed.

**Why this priority**: Required for compliance with WhatsApp's messaging policy. Violations can result in the business number being banned.

**Independent Test**: Can be tested by simulating a reply attempt more than 24 hours after a test client's last inbound message and confirming the send action is blocked with the correct warning shown.

**Acceptance Scenarios**:

1. **Given** a client's last inbound message was more than 24 hours ago, **When** the midwife attempts to send a freeform reply, **Then** the send action is blocked and a clear explanation is shown.
2. **Given** a client's last inbound message was within 24 hours, **When** the midwife sends a reply, **Then** the message is delivered normally with no restriction.

---

### Edge Cases

- What happens when a client sends multiple messages before the midwife has reviewed the first draft? (Each message should produce its own draft/urgent item; inbox should handle multiple pending items per client.)
- What happens when the AI draft generation fails due to a downstream service error? (Item should appear in inbox with no draft, flagged for midwife to write original; failure should not block the message from being visible.)
- What happens when a client sends the stop keyword "STOP"? (Conversation moves to "paused" state; midwife is notified; no further drafts generated until resumed.)
- What happens when a client sends "HUMAN"? (A "human-only preference" flag is set; drafts are still generated but the midwife sees the flag and knows the client prefers no AI-visible involvement.)
- What happens when the client uses the invite link twice (e.g., two phones)? (Second attempt should fail gracefully — token is single-use after the first successful match.)
- What happens when push notifications are not delivered (e.g., midwife's phone offline)? (Inbox remains the source of truth; messages are still visible when the midwife opens the PWA.)

---

## Requirements *(mandatory)*

### Functional Requirements

**Client Onboarding**

- **FR-001**: The midwife MUST be able to create a new client record by entering: client name, phone number, and due date.
- **FR-002**: The system MUST generate a unique, single-use invite link and QR code for each new client.
- **FR-003**: The system MUST match an incoming WhatsApp message to a pending invite record via the invite token embedded in the first client message.
- **FR-004**: The system MUST automatically send an AI-disclosure and consent prompt to the client upon successful token match.
- **FR-005**: The system MUST record the client's consent as: message identifier, timestamp, and verbatim reply text.
- **FR-006**: The client record status MUST transition to "active" only after a confirmed "YES" consent reply.

**Inbound Message Processing**

- **FR-007**: The system MUST classify every inbound message from an active client into one of four urgency levels:
  - **urgent**: Immediate safety concern — active emergency, imminent birth, heavy bleeding, loss of consciousness, signs of eclampsia or severe pre-eclampsia.
  - **high**: Elevated concern requiring prompt midwife attention but not an active emergency — reduced fetal movement, moderate pain, unusual symptoms not clearly emergent.
  - **normal**: Routine clinical or logistical question that can be addressed with an AI-drafted reply — appointment queries, medication questions, general pregnancy advice.
  - **low**: Non-clinical or administrative message — greetings, confirmations, thank-yous, scheduling acknowledgements.
- **FR-008**: The system MUST NOT generate an AI draft for any message classified as `urgent` or `high` urgency (both levels defined in FR-007).
- **FR-009**: The system MUST send a push notification to the midwife for every inbound message — high-priority (RFC 8030 `Urgency: high`) for `urgent` and `high`, standard-priority for `normal` and `low`.
- **FR-010**: For normal-urgency messages, the system MUST generate an AI draft reply grounded in the knowledge base, including citations to the source material used.
- **FR-011**: Every inbound message MUST be written to the append-only audit log before any further processing occurs.

**Midwife Review & Reply**

- **FR-012**: The midwife MUST be able to approve an AI draft and send it to the client in a single action.
- **FR-013**: The midwife MUST be able to edit an AI draft before sending.
- **FR-014**: The midwife MUST be able to discard the AI draft and write an original reply.
- **FR-015**: The system MUST record the reply action type in the audit log: "AI-drafted/midwife-approved", "AI-drafted/midwife-edited", or "midwife-original".
- **FR-016**: The AI draft MUST be visible to the midwife alongside the cited knowledge base snippets before she acts.

**Urgent & Safety Handling**

- **FR-017**: High-urgency items MUST be visually distinct in the inbox (e.g., color-coded) from normal-urgency items.
- **FR-018**: The system MUST surface high-urgency messages to the midwife even when no draft is available — the inbox must never hide a message because drafting failed.

**24-Hour Window**

- **FR-019**: The system MUST track the timestamp of each client's most recent inbound message.
- **FR-020**: The system MUST block freeform outbound messages when the service window has been closed for more than 24 hours since the client's last inbound.
- **FR-021**: The midwife MUST see a clear explanation when a send action is blocked due to window expiry.

**Knowledge Base Feedback**

- **FR-022**: After sending a reply, the midwife MUST be able to tag the Q&A pair (client question + approved reply) for KB staging review.
- **FR-023**: Tagged Q&A pairs MUST enter a staging queue and NOT go directly to the production knowledge base.
- **FR-024**: The midwife MUST be able to promote, edit-then-promote, or discard each staged item in a dedicated review screen.
- **FR-025**: Only promoted items MUST become available to the AI draft generation process as retrieval sources.

**AI Disclosure**

- **FR-026**: Every new client MUST receive a disclosure message explaining that replies are AI-drafted and reviewed by the midwife before sending.
- **FR-027**: Every AI-drafted reply sent to a client MUST be traceable as AI-assisted in the audit log, even if the client's WhatsApp view does not show a badge.

**Audit & Compliance**

- **FR-028**: The audit log MUST be append-only; no record may be modified or deleted once written.
- **FR-029**: The audit log MUST capture: every inbound message, every AI draft, and every outbound message — each with timestamp and action metadata.

**Client State Management**

- **FR-030**: The system MUST recognise a client-sent "STOP" keyword and transition the conversation to "paused" state with no further AI drafting.
- **FR-031**: The system MUST recognise a client-sent "HUMAN" keyword, set a "human-only preference" flag visible to the midwife, and continue normal inbox routing.
- **FR-032**: The midwife MUST be able to archive a client, which stops all inbound processing for that client.

---

### Key Entities

- **Client**: A pregnant, birthing, or postpartum woman. Attributes: name, phone number, due date, consent record, current state (pending_invite / awaiting_consent / active / paused / human_only / window_closed / archived), invite token, last inbound timestamp.
- **Conversation**: The thread between one client and the midwife. Contains an ordered list of messages and holds current draft state.
- **Message**: A single inbound or outbound communication event. Attributes: direction, body text, timestamp, urgency level (inbound), action type (outbound), AI draft reference if applicable.
- **AI Draft**: A generated reply candidate. Attributes: body text, urgency classification, knowledge base citations, status (pending / approved / edited / discarded).
- **Knowledge Base Item (Production)**: A verified Q&A pair available for AI retrieval. Attributes: question, answer, source metadata, date promoted.
- **Staged KB Item**: A candidate Q&A pair awaiting midwife review. Attributes: question, answer, originating conversation reference, staging date, status (pending / promoted / discarded).
- **Client Invite**: A pending onboarding record. Attributes: token (single-use), associated client profile, creation timestamp, status (pending / used / expired).
- **Push Subscription**: A registered device endpoint for delivering notifications to the midwife.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The midwife can approve and send an AI-drafted reply with no more than 3 taps from the point of opening the push notification.
- **SC-002**: At least 80% of normal-urgency client messages result in a usable AI draft that the midwife approves or edits rather than discarding entirely, within 8 weeks of launch.
- **SC-003**: Every high-urgency message produces a midwife notification within 60 seconds of the client sending it.
- **SC-004**: The onboarding flow — from midwife creating a client to the client reaching "active" state — can be completed end-to-end in under 5 minutes.
- **SC-005**: Zero outbound messages are delivered to clients without an explicit midwife send action (co-pilot gate is never bypassed).
- **SC-006**: Every inbound message, every AI draft, and every outbound reply is traceable in the audit log within 10 seconds of the event.
- **SC-007**: The midwife's inbox is usable on a mobile browser installed to the home screen with no native app installation required.
- **SC-008**: The 24-hour window constraint is enforced 100% of the time — no freeform messages are sent outside an active window.
- **SC-009**: A staged KB item promoted by the midwife becomes available to the AI draft process within 24 hours of promotion.
- **SC-010**: The pilot midwife can migrate at least 3 existing clients onto the system within the first week of launch.

---

## Assumptions

- Single midwife for the MVP pilot; multi-midwife support is out of scope.
- WhatsApp is the only client-facing messaging channel in MVP; other channels (Telegram, Messenger) are future work.
- The knowledge base is seeded from the midwife's existing chat export history before launch; clients interact only with the production index.
- The AI disclosure + consent prompt text is fixed for MVP; customisable templates are future work.
- Pre-approved outbound templates for re-opening a closed 24-hour window are post-MVP; MVP blocks freeform sending when the window is closed and shows a static message.
- The midwife is the sole KB reviewer; delegated review roles are post-MVP.
- Payment/subscription handling for clients is post-MVP; access control is managed manually by the midwife via the client record.
- The midwife accesses the inbox via a PWA installed to her mobile home screen; desktop-browser optimisation is secondary.
- All client data is stored in a European region to meet GDPR residency expectations; formal DPA and legal review are pre-launch gates, not MVP-blocking code tasks.
- iOS push notifications require the PWA to be installed to the home screen (iOS 16.4+); if the pilot midwife uses Android, this constraint does not apply.
- Right-to-be-forgotten self-service flow for clients is post-MVP; data deletion is handled manually on request during the pilot.

---

## Fixed MVP Content

### Consent & AI-Disclosure Prompt (`CONSENT_PROMPT_TEXT`)

The following text is sent verbatim to every new client upon successful invite token match (FR-004, FR-026). It is fixed for MVP; customisable templates are post-MVP.

> Welcome! You are connecting to your midwife's secure messaging service.
>
> Please note: this service uses AI-assisted reply drafting. Your midwife personally reviews and approves every message before it is sent to you — no message is ever delivered automatically without her review and consent.
>
> To confirm you understand and agree to receive messages this way, please reply **YES**.

**On non-YES reply**, the same prompt is resent as-is (no separate retry template in MVP). The client must reply YES to proceed.
