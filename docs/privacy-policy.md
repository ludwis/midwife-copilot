---
type: reference
title: Privacy Policy — Stilla Midwife Co-pilot
created: 2026-05-16
tags:
  - gdpr
  - privacy-policy
  - whatsapp
  - meta
  - compliance
related:
  - '[[compliance-framework]]'
  - '[[whatsapp-registration-status]]'
---

# Privacy Policy

**Service name**: Stilla — Midwifery Support Assistant  
**Last updated**: 16 May 2026  
**Version**: 1.0

---

## 1. Who We Are

This service is operated by **[Midwife's Full Name]**, a licensed midwife (położna) practising under the registration in the Register of Entities Conducting Medical Activity (Rejestr Podmiotów Wykonujących Działalność Leczniczą), entry number **[RPWDL number]**.

**Practice name**: [Practice name]  
**Business address**: [Full address, Poland]  
**NIP**: [NIP number]  
**REGON**: [REGON number]  
**Contact e-mail**: [contact@example.com]  
**Contact phone**: [+48 XXX XXX XXX]

The midwife is the **data controller** within the meaning of Article 4(7) of the General Data Protection Regulation (GDPR).

---

## 2. What This Service Does

Stilla is an AI-assisted communication support tool. When a client sends a WhatsApp message to the midwife's business number, Stilla:

1. Receives the message via the WhatsApp Business API (Meta Platforms, Inc.).
2. Retrieves relevant information from a midwifery knowledge base.
3. Prepares a **draft reply** for the midwife to review.
4. The midwife reads, edits if needed, and **personally approves** every reply before it is sent.

**No message is sent to a client without the midwife's explicit approval.**  
**No automated medical decisions are made.**

---

## 3. What Data We Collect

| Data category | Examples | Source |
|---------------|----------|--------|
| Contact data | WhatsApp phone number | WhatsApp Business API |
| Conversation content | Messages sent and received in the chat | WhatsApp Business API |
| Consent record | Whether and when you agreed to these terms | Recorded at first message |
| Communication metadata | Message timestamps, delivery status | WhatsApp Business API |

We do **not** collect your name, address, email, or any health records through this channel unless you explicitly include them in a message you send to us.

---

## 4. Why We Process Your Data (Legal Bases)

| Purpose | Legal basis (GDPR) |
|---------|-------------------|
| Providing midwifery support responses | Art. 6(1)(b) — necessary for the performance of a contract / service relationship |
| AI-assisted reply drafting (reviewed by midwife) | Art. 6(1)(b) — contract performance; Art. 6(1)(f) — legitimate interest in efficient, high-quality care |
| Audit logging for compliance and legal defence | Art. 6(1)(c) — legal obligation; Art. 17(3)(e) — legal claims |
| Improving the midwifery knowledge base | Art. 6(1)(f) — legitimate interest; all client identifiers are removed before any content enters the knowledge base |

For **special categories of health data** (if shared by you in messages): processing is based on Art. 9(2)(h) GDPR — necessary for the provision of health care — and is subject to professional secrecy obligations under Polish law (Act of 15 July 2011 on the Professions of Nurse and Midwife, Article 17).

---

## 5. How Long We Keep Your Data

| Data type | Retention period | Reason |
|-----------|-----------------|--------|
| Conversation messages | 24 months from the last message | Duration of the support relationship |
| Your client profile (phone number, consent record) | 24 months after the last interaction | Service continuity and legal basis |
| AI reply drafts | 30 days from creation | Quality review only; purged automatically |
| Audit log (event metadata, no full message content) | 7 years | Legal obligation / Polish civil limitation periods |

After the retention period expires your data is deleted automatically. You may also request earlier deletion — see §7.

---

## 6. Who Receives Your Data

We share your data only with the sub-processors necessary to operate this service:

| Sub-processor | Role | Location | Safeguard |
|---------------|------|----------|-----------|
| **Meta Platforms, Inc.** | WhatsApp Business API message delivery | USA / EU | [Meta Data Processing Terms](https://www.facebook.com/legal/terms/dataprocessing) |
| **Google Cloud Platform** (Firebase, Firestore, Cloud Storage) | Data storage and backend hosting | EU (europe-west3 — Frankfurt) | Google Cloud Data Processing Addendum |
| **Google Vertex AI / Gemini** | AI reply drafting | EU / USA | Google Cloud Data Processing Addendum |

We do **not** sell your data. We do **not** share your data with any other third party except where required by law (e.g. a court order or a request from a supervisory authority).

---

## 7. Your Rights Under GDPR

You have the right to:

- **Access** — obtain a copy of the personal data we hold about you.
- **Rectification** — correct inaccurate data.
- **Erasure** — request deletion of your data (see below for limitations).
- **Restriction** — ask us to limit processing while a dispute is resolved.
- **Portability** — receive your data in a structured, machine-readable format.
- **Object** — object to processing based on legitimate interest (Art. 6(1)(f)).
- **Withdraw consent** — where processing is based on consent, you may withdraw it at any time without affecting the lawfulness of prior processing.

### How to exercise your rights

Send your request by:
- **WhatsApp**: Reply "USUŃ MOJE DANE" (Polish) or "DELETE MY DATA" (English) in the chat.
- **Email**: [contact@example.com]
- **In person or by post**: [Practice address]

We will respond within **30 days**. For erasure requests, deletion is completed within 30 days of verification.

### Erasure — what we cannot delete

The **audit log** (which contains event metadata such as "message received at T", not full message content) is retained for up to 7 years under GDPR Art. 17(3)(e) — necessary for the establishment, exercise, or defence of legal claims. The **erasure register** (a record that an erasure took place) is retained under Art. 6(1)(c) — legal obligation.

Knowledge base entries derived from your conversations do **not** contain your personal data — client identifiers are removed during extraction — so GDPR erasure does not apply to them.

---

## 8. AI Transparency

Replies in this service are **drafted with the assistance of an AI system** (Google Gemini). Every draft is reviewed and approved by the midwife before being sent to you. This service does not make automated decisions that produce legal or similarly significant effects.

This disclosure satisfies:
- **EU AI Act Art. 50** — obligation to inform individuals interacting with AI systems.
- **GDPR Art. 22** — disclosure of automated processing involvement.

---

## 9. Data Security

We implement appropriate technical and organisational measures:

- Data is stored in Google Cloud Firestore and Cloud Storage in the **EU (Frankfurt)** region.
- Access to the midwife's review interface is protected by **Google OAuth** authentication.
- The knowledge base extraction interface is accessible only to the authenticated midwife.
- Audit logs are append-only and protected against modification.
- All data in transit is encrypted (TLS 1.2+).

---

## 10. International Transfers

Our primary data storage is within the EU (Frankfurt). Vertex AI / Gemini processing may involve servers in the USA. Such transfers are covered by Google's Standard Contractual Clauses (SCCs) under GDPR Chapter V.

---

## 11. Cookies and Tracking

This service operates through WhatsApp and does not operate a website that sets cookies. If a web interface is made available in the future, this section will be updated.

---

## 12. Children's Privacy

This service is not directed at children under 16 years of age. If you believe a child has submitted data without parental consent, contact us at [contact@example.com] and we will delete it promptly.

---

## 13. Changes to This Policy

We may update this policy when the service changes. When we do, we will update the "Last updated" date at the top and, where practical, notify active clients via WhatsApp. Continued use of the service after the update constitutes acceptance of the new policy.

---

## 14. Complaints

If you believe we have not handled your personal data lawfully, you have the right to lodge a complaint with the Polish supervisory authority:

**Urząd Ochrony Danych Osobowych (UODO)**  
ul. Stawki 2, 00-193 Warszawa  
https://uodo.gov.pl  
Tel: +48 22 531 03 00

---

## 15. Contact

For any privacy-related questions:

**[Midwife's Full Name]**  
[Practice name]  
[Address]  
[contact@example.com]  
[+48 XXX XXX XXX]

---

*This policy is published to satisfy the privacy policy requirement of the WhatsApp Business Platform Terms of Service and Meta's healthcare business verification process.*
