---
type: reference
title: WhatsApp Business API Registration Status
created: 2026-05-16
tags:
  - whatsapp
  - registration
  - meta
  - phase-3-gate
related:
  - '[[compliance-framework]]'
---

# WhatsApp Business API Registration Status

**Feature gate**: FR-010 — Registration MUST be submitted during Phase 1.
**Required for**: Phase 3 (WhatsApp Integration & Midwife PWA)
**Last updated**: 2026-05-16

---

## Registration Steps

### Step 1 — Meta Business Suite Account

**What**: Create a verified Meta Business Suite account for the midwifery practice.

**Requirements**:
- Legal business name (as registered)
- Business website or Facebook Page
- Business phone number and address

**Date submitted**: 16.05.2026
**Status**: ✅ Complete

**Notes**:

---

### Step 2 — Healthcare Verification Documents

**What**: Submit business verification documents confirming the midwifery practice's legal status and healthcare category.

**Documents required**:
- Practice registration certificate (wpis do rejestru podmiotów wykonujących działalność leczniczą)
- National identification (NIP/REGON) of the practice entity
- Evidence of healthcare category (midwifery / położnictwo)

**Where to submit**: Meta Business Manager → Business Info → Business Verification

**Date submitted**: 16.05.2026
**Status**: ✅ Complete

**Notes**:

---

### Step 3 — WhatsApp Cloud API Application

**What**: Apply for access to the WhatsApp Cloud API through the Meta Developer portal.

**Steps**:
1. Create a Meta for Developers app (type: Business)
2. Add the "WhatsApp" product to the app
3. Select business category: **Health / Wellness**
4. Accept WhatsApp Business Platform Terms of Service

**Where**: https://developers.facebook.com → My Apps → Create App

**Date submitted**: 16.05.2026
**Status**: 🔄 In Progress

**Notes**:

---

### Step 4 — Bot Phone Number Registration

**What**: Register a dedicated phone number for the WhatsApp bot.

**Requirements**:
- Phone number must NOT be previously registered with WhatsApp (personal or business)
- Recommend: a new SIM card or VoIP number dedicated to the bot
- Number registered under the business entity (not personal)

**Recommended**: Polish mobile number (+48) to match client expectations and avoid cross-border messaging complications.

**Date submitted**: _(pending)_
**Status**: ⬜ Not started

**Notes**:

---

### Step 5 — Phone Number Verification

**What**: Complete Meta's phone number verification to activate the WhatsApp Business API for the registered number.

**Process**: Meta sends a verification code via SMS or voice call to the registered number. Code entered in Meta Business Manager.

**Date completed**: _(pending)_
**Status**: ⬜ Not started

**Notes**:

---

## Registration Summary

| Step | Description | Submitted | Status |
|------|-------------|-----------|--------|
| 1 | Meta Business Suite account | — | ⬜ Not started |
| 2 | Healthcare verification docs | — | ⬜ Not started |
| 3 | WhatsApp Cloud API application | — | ⬜ Not started |
| 4 | Bot phone number registration | — | ⬜ Not started |
| 5 | Phone number verification | — | ⬜ Not started |

---

## Expected Timeline

Meta business verification: **1–4 weeks** after submission.
WhatsApp Cloud API approval for healthcare category: **2–6 weeks** after business verification.

**Total lead time**: 3–10 weeks from submission.

Starting registration in Phase 1 is mandatory to avoid blocking Phase 3 launch.

---

## Risk Note

> **If Meta approval is not received before Phase 3 start, a fallback channel decision is required — any non-WhatsApp channel requires a constitution amendment per §Amendment Procedure before implementation.**

The fallback channel identified in research.md §8 is a **Telegram Bot API adapter**. The hexagonal architecture ensures the core pipeline requires only a `MessageChannel` interface — a Telegram adapter can be added without changes to `bot/`. However, this fallback:

1. Changes the product proposition (clients use Telegram instead of WhatsApp)
2. Changes the consent message text (§1 of the compliance framework references WhatsApp)
3. Requires the midwife to direct clients to a different messaging app

If this fallback is invoked, the following documents require updates before Phase 3 deployment:
- `docs/compliance-framework.md` — consent message text
- Constitution / Architecture Decision Records — channel adapter change
- Any client-facing communication materials

**Escalation**: If Step 3 (API application) has not been approved within 4 weeks of submission, escalate to the midwife and assess Phase 3 timeline impact.

---

## How to Update This Document

As registration progresses, update the relevant step's **Date submitted** and **Status** fields using the following status codes:

| Symbol | Meaning |
|--------|---------|
| ⬜ | Not started |
| 🔄 | In progress / awaiting response |
| ✅ | Complete |
| ❌ | Rejected / requires resubmission |
