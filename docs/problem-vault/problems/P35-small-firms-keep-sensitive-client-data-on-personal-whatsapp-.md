# P35. Small firms keep sensitive client data on personal WhatsApp and Gmail as DPDP obligations approach, with no compliance kit

**Severity:** high · **Size:** big · **Region:** India (global analogues: GDPR, US breach laws)

**Who has it:** Every Indian law firm and chamber, especially family, criminal, MACT and consumer practices, and their clients

## What goes wrong

A three-lawyer chamber holds clients' Aadhaar and PAN, medical records from MACT and matrimonial files, bank statements and opposing parties' data in personal WhatsApp, phone galleries and shared Gmail. DPDP Rules 2025 are notified, with most obligations binding after 18 months: consent, security safeguards, breach notification, deletion with 48 hours' notice and grievance handling, with penalties up to Rs 250 crore. Firms with private-client work face higher risk, and law-firm cyber incidents are rising.

## Evidence of scale

- DPDP Rules 2025 notified with an 18-month window; safeguards include encryption, access restriction, monitoring, backups, audit trails; 48 hours' notice before deletion. ([source](https://www.barandbench.com/law-firms/view-point/digital-personal-data-protection-rules-2025-a-practical-roadmap-for-data-fiduciaries-preparing-for-a-new-compliance-era))
- DPDPA applies to law firms as data fiduciaries; firms handling civil, family and criminal matters face higher risk. ([source](https://www.barandbench.com/columns/taking-coals-to-newcastle-the-dpdpas-impact-on-law-firms))
- Vidhi: Indian lawyers rely on personal messaging apps, a grey zone under BCI Rule 17. ([source](https://vidhilegalpolicy.in/blog/balancing-professional-responsibility-and-technology/))
- BakerHostetler: law-firm cyber incidents it handled nearly doubled in 2025 from more than 30 in 2024. ([source](https://www.abajournal.com/news/article/law-firms-see-more-cyberattacks-ransomware-threats-report-says))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI are hosted largely outside India and produce no DPDP consent notices or retention schedules for a chamber. Clio isn't built for Indian law. WhatsApp keeps no matter-level retention, consent or breach logs. No affordable tool replaces files on the advocate's phone with consented, masked, access-logged intake that produces DPDP evidence by default.

## Panel verdict

**Status:** solved (round 3)

**Effort:** L

### What software can fix

Giving a small chamber a working DPDP kit inside the tool it already uses:
- client data moved off personal phones and Gmail into matter-scoped, encrypted, access-logged firm storage;
- itemised consent notices;
- a personal-data inventory per matter;
- a retention schedule that surfaces matters due for review but never erases unless the client has been offered their papers safely and an owner approves;
- a data-principal request and grievance register with timers;
- a breach register that drafts the Board and data-principal intimations.
The return of papers is designed so the kit itself cannot leak a file: the notice carries no link and no matter detail, and the export is released only after the lawyer re-verifies the client's identity. Most of the plumbing already exists: trash with erasure certificates, legal hold, maker-checker approvals, consent fields and WhatsApp Business intake (migrations 012-013).

### What it can't fix

We cannot delete what stays on an advocate's personal phone or Gmail. We can import it, give a checklist and record an attestation.

The firm remains the data fiduciary. These are legal judgments the firm makes, and our defaults are labelled as such:
- whether it is a Significant Data Fiduciary;
- how s.17(1)(a) and the retention rules apply to a file;
- when a closed file may safely be destroyed (limitation for negligence claims, connected matters, appeals).

We cannot know whether a mobile number has been recycled by the operator. We reduce the risk by sending a neutral, detail-free notice only after the lawyer reconfirms the contact, and by never releasing documents without identity re-verification. A stranger who receives the neutral message still learns that the firm wanted to reach someone at that number.

Identity re-verification is the lawyer's judgment. We record its method and time but cannot verify a physical ID check ourselves. Physical handover is recorded on the lawyer's word plus a receipt upload. Paper files are covered only through scanning.

Opposing parties' data is processed under the legal-claims exemption. We record that ground but cannot decide it.

### What the user sees

A 'Data & DPDP' section with five screens: Import, Inventory, Retention review, Requests & grievances, and Breach register. Import, Inventory, Requests and Breaches are as in round 2. Retention review now works like this:

(1) Due for review. Matters past closed_at plus the retention period, with eligibility or skip reasons.

(2) Reconfirm contact. Before any notice, the lawyer sees the client's contacts with their last confirmed date. A contact is current if the client messaged from it in the last 90 days. Otherwise the lawyer must record how they reconfirmed it (spoke to the client on it, the client confirmed it by email, other source plus a note) within 14 days before sending. Where no contact can be reconfirmed, the screen offers the printable neutral letter to the last known postal address instead.

(3) Send neutral notice. The message is fixed text, English or Hindi: 'Namaste. This is <firm name>. Please contact our office at <office phone> (<office hours>) regarding papers you entrusted to us.' It carries no link, no client name, no matter title, no case number and no party names. A preview shows exactly what will be sent.

(4) Client responds. The lawyer records an identity re-verification: in-person ID check, video call, or a phone call where the client answered details on file, with a note. Only the last 4 characters of an ID shown are recorded, never the full number.

(5) Release export. Only after step 4 is a 'Create secure download' button enabled. It produces a single-use link valid for 24 hours, delivered to a contact the client confirmed during verification. A separate 6-digit code is read out on the call or sent on a different channel from the link. The page shows 'Link used' or 'Expired' afterwards. Physical collection at the office is always offered as the alternative.

(6) Outcome. Recorded as exported, returned in person (date plus receipt), keep requested, destroy requested, or no response. 'No response' is set automatically when the notice is undeliverable or unanswered after the notice period, and it shows 'Physical collection was offered at the office'.

(7) Owner approval of the erasure batch. As before, with the 'client originals not returned' flag and a typed note where needed.

### What the system does

1) Importers, the access log, the inventory, the DSR register, the breach register, the consent notice and encryption are unchanged from round 2. Importers are deterministic parsers, the inventory holds counts and HMACs, and the DSR and breach timers are computed.

2) The retention queue is unchanged. queue_retention_candidates(p_org) is SECURITY DEFINER, granted to service_role only, and only queues and skips. It never trashes. Skip reasons cover legal hold, a pending linked court_case, unpaid fees, an open DSR, and a held connected matter.

3) Contact reconfirmation. This is new in this round and fixes the objection.
- New table contact_reconfirmations: queue_id, contact_kind (whatsapp | sms | email | postal), contact_hmac, method (recent_inbound | spoke_on_number | client_confirmed_email | other), note, confirmed_by, confirmed_at.
- retention_service.can_send_notice(queue_id) is true only if one of these holds:
  - (a) the contact sent an inbound message within 90 days, derived from whatsapp_messages and recorded automatically as method recent_inbound;
  - (b) a lawyer-recorded reconfirmation exists for that exact contact_hmac with confirmed_at no more than 14 days before the send.
  Otherwise the send returns 422 'reconfirm contact'.
- The postal letter is printable without a reconfirmation, but only to the address on file, with the same neutral text.

4) Neutral notice. RETURN_NOTICE_TEMPLATES (en, hi) are product-owned P33 template_registry rows with audience 'client_matter' and param_schema [office_name, office_phone, office_hours], all filled from organizations fields only.
- render_return_notice() takes no matter object at all, so matter data cannot reach it by construction.
- A post-render guard refuses the send if the body matches a URL pattern (https?://, www., wa.me, a domain followed by '/') or contains any of the matter's title, case_number, cnr, client_name or party_index display names.
- It is sent through outbound_policy reason client_of_matter to the reconfirmed contact. notice_sent_at and notice_delivery_status are recorded, and status is updated from Meta's status webhook (sent / delivered / read / failed).

5) Identity re-verification. New table identity_verifications: queue_id, method (in_person_id | video_call | phone_known_details | id_document_match), id_last4 (nullable), performed_by, performed_at, note (required), and confirmed_delivery_contact_hmac (the contact the client asked the link to go to).
- A check requires performed_at > notice_sent_at.
- Only lawyers on the matter or partners can record one.

6) Export release. POST /dpdp/retention/{queue_id}/export-link returns 403 unless an identity_verifications row exists with performed_at > notice_sent_at.
- It creates client_export_grants: token_sha256, code_sha256 (6-digit, random), expires_at = now() + 24h, max_uses = 1, used_at, attempts (max 5), link_channel, code_channel, and a CHECK constraint link_channel <> code_channel. 'read_on_call' counts as a channel.
- The link goes to confirmed_delivery_contact only.
- GET /export/{token} shows a code form. POST with the code streams the zip of client_supplied documents and correspondence, encrypted with a key derived from the code.
- On success used_at is set. Reuse returns 410, expiry returns 410, and after 5 wrong codes the grant is locked.
- Every attempt is audited (EXPORT_CLIENT_FILE, EXPORT_CODE_FAILED), and the download is logged as DOWNLOAD_DOCUMENT.

7) No response. If notice_delivery_status='failed', or no identity verification exists by notice_sent_at + return_notice_days (>= 30, default 60), the outcome may be set to no_response, with physical_return_offered=true (the neutral text invites the client to the office). If client_supplied documents exist, owner approval needs the typed note.

8) Erasure is unchanged: request_approval('retention_erase'), owner-only via approver_roles, the requester cannot decide, and trash_item runs under the owner's JWT, re-checking legal hold. Then the 30-day trash and the erasure certificate follow.

### Where it is built

Extend:
- supabase/migrations/013 functions, via migration 016: retention_erase in request_approval and approver_roles; trash_item accepts a retention_erase approval.
- app/services/safety_service.py.
- app/worker.py: task_retention_review, queue only.
- app/services/whatsapp_intake.py: the status webhook updates notice_delivery_status, and inbound messages feed recent_inbound reconfirmation.
- app/services/document_service.py and app/services/ocr_service.py: the client_supplied flag.
- app/core/guardrails.py: analyze-only counting.
- app/services/audit_service.py: IMPORT_CHAT, VIEW_DOCUMENT, DOWNLOAD_DOCUMENT, LOG_DSR, CLOSE_DSR, LOG_BREACH, SEND_RETURN_NOTICE, RECONFIRM_CONTACT, VERIFY_CLIENT_IDENTITY, CREATE_EXPORT_GRANT, EXPORT_CLIENT_FILE, EXPORT_CODE_FAILED, RECORD_RETURN, REQUEST_RETENTION_ERASE and ATTEST_DEVICE_CLEANUP.
- CLAUDE.md invariant 2: the retention queue builder.
New:
- app/services/import_service.py, app/services/dpdp_service.py and app/services/retention_service.py (render_return_notice, can_send_notice, export grants);
- app/routers/dpdp.py, plus the public app/routers/client_export.py (token plus code, no JWT, rate-limited by IP and token);
- supabase/migrations/016_dpdp_kit.sql: personal_data_inventory, retention_queue (notice_sent_at, notice_delivery_status, physical_return_offered), contact_reconfirmations, identity_verifications, client_export_grants (with the channel CHECK), data_principal_requests, breach_incidents and device_cleanup_attestations, plus the closed_at, retention_years, return_notice_days and client_supplied columns, all with RLS;
- frontend/src/app/data/ (retention flow steps 1-7) and frontend/src/app/export/[token]/page.tsx (code entry).
Uses P33's outbound_policy and template_registry, and P46's party_index for the leak guard.

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis+ AI have no concept of a chamber's DPDP obligations. Clio isn't built for Indian law or WhatsApp. WhatsApp and Gmail keep no matter-level retention, consent or breach logs. Generic DPDP platforms treat retention as automatic deletion, which ignores the advocate's duty to return papers (no lien: R.D. Saxena v. Balram Prasad Sharma, 2000). Client portals that 'share files by link' send document links to whatever contact is on file, which in India may be a recycled number years later.

Ours offers the papers back without exposing them:
- a neutral, detail-free notice, guarded in code, sent only to a reconfirmed contact;
- documents released only after a recorded identity check;
- a single-use, 24-hour link bound to a code sent on a separate channel;
- physical collection always offered.
Every destruction still has a client-return record and an owner's approval behind it.

### Safeguards

The return notice is fixed, neutral text with no link and no matter detail, rendered without access to the matter and guarded in code against URLs and party names. It is sent only to a contact reconfirmed within 14 days, or one active in the last 90 days, and a postal letter is the fallback.

Documents are released only after a recorded identity re-verification made after the notice, through a single-use, 24-hour, code-bound, encrypted link where the code and the link travel on different channels. Physical collection is always offered. Every export attempt is audited.

Nothing is erased automatically. The cron only queues, through a service_role-only definer function. Erasure needs a recorded return outcome and an owner's approval under maker-checker, then trash_item under the owner's JWT with a legal-hold re-check, the 30-day trash and the certificate.

The inventory stores counts and HMACs. Imports never call the AI. Defaults are labelled as firm choices to be confirmed by counsel.

### How the panel's objections were answered

Blocking objection (the signed export link to the whole file goes to a possibly recycled number):
- (1) The notice now carries no document link and no matter detail. It is fixed neutral text: '<firm> asks you to contact the office about papers you entrusted to us', with the office phone and hours only. render_return_notice has no access to the matter, and a post-render guard refuses any URL or any matter title, CNR, case number, client name or party name.
- The notice is sent only after the contact is reconfirmed: an inbound message within 90 days, or a lawyer-recorded reconfirmation of that exact contact within 14 days. Otherwise 422, and a postal letter is the alternative.
- (2) The export is released only after the client responds and the lawyer records an identity re-verification (in-person ID, video call, a call with known details, or an ID match, with only the last 4 characters recorded) dated after notice_sent_at.
- The link is single-use and expires in 24h. It is bound to a 6-digit code delivered on a different channel (a database CHECK makes link_channel and code_channel differ), sent to a contact the client confirmed during verification, locked after 5 wrong codes, and every attempt is audited.
- (3) An undeliverable notice (Meta 'failed' status) or no answer within the notice period counts as no_response, with physical collection at the office offered in the notice itself.
- Tests added for each point: no URL or matter detail in the notice body; export-link 403 until a verification exists after notice_sent_at; the link works once and expires; the channel CHECK; the reconfirmation window.

### Acceptance tests

- Unit (objection): render_return_notice for a fixture matter (title 'Sharma v. Verma', CNR DLHC010012342024, client 'Ravi Sharma') in English and Hindi. The body matches no URL regex (https?://, www\., wa\.me, [a-z0-9-]+\.[a-z]{2,}/), and contains neither the title, the CNR, the case number, 'Ravi Sharma' nor any party_index name. Injecting a URL into organizations.office_name makes the guard refuse the send.
- Unit (objection): POST /dpdp/retention/{id}/export-link returns 403 with no identity_verifications row. It also returns 403 when the only verification has performed_at before notice_sent_at. It returns 201 once a verification exists after notice_sent_at.
- Unit (objection): an export grant works once (200, zip streamed). The second use returns 410. With frozen time at +24h01m an unused grant returns 410. After 5 wrong codes the grant is locked, and the correct code then returns 423.
- DB test: inserting a client_export_grants row with link_channel = code_channel = 'whatsapp' violates the CHECK constraint.
- Unit: sending the notice to a contact with no inbound message for 2 years and no reconfirmation returns 422 'reconfirm contact', with 0 Meta API calls. A reconfirmation dated 15 days before the send returns 422, and one dated 3 days before succeeds. A contact with an inbound message 10 days ago is accepted automatically.
- Unit: a reconfirmation recorded for contact A does not permit sending to contact B on the same matter.
- Unit: a Meta status webhook 'failed' on the notice sets notice_delivery_status='failed'. With frozen time past notice_sent_at + return_notice_days, the outcome no_response is accepted with physical_return_offered=true. Before that time, no_response is refused unless delivery failed.
- Unit: identity_verifications insert by a paralegal not on the matter returns 42501. A row with method in_person_id and a 12-digit id value in id_last4 is rejected (max 4 characters).
- Unit: WhatsApp fixture parsing, zip-slip rejection, and an inventory with no raw values, as in round 2.
- Unit, frozen time: retention_queue eligibility and skip reasons. After 400 simulated days trash_item has been called 0 times.
- DB test: queue_retention_candidates as authenticated gets 42501. As service_role it touches only the given org.
- DB test: request_approval('retention_erase') by an associate, decide_approval by the same user or a partner gets 42501, owner approval lets trash_item succeed for listed matters only, and a hold placed after approval blocks execution.
- Unit: a no_response outcome with client_supplied documents and no typed note means owner approval returns 422.
- Unit: the breach 72h deadline, the DSR legal-hold outcome rules and the bilingual consent notice, as in round 2.

### Reviewers' minor notes

- The export zip is 'encrypted with a key derived from the 6-digit code'. A 10^6 keyspace adds nothing once the file is downloaded, so don't present it as a safeguard. The real protections are the single use, the 24-hour expiry and the 5-attempt lock.
- The P33 template_registry slot types must include office_phone and office_hours (see the objection on P33).
- The method 'phone_known_details' on a possibly recycled number is weak. Require at least two details that aren't public (for example a fee paid or a date of first consultation), not just the case name.
- Migration 016 collides with P24.
- A zip encrypted with a key derived from a 6-digit code can be brute-forced offline if the file leaks. Use a random per-grant key that the server holds and delete it after use, and treat the code only as the online gate (already limited to 5 tries).
- The neutral notice still tells whoever holds a recycled number that this firm was trying to reach someone. This is disclosed. For sensitive practice areas (criminal, matrimonial), let firms default to the postal letter or the in-person route.
- Encrypting the zip 'with a key derived from the 6-digit code' adds nothing: 20 bits can be brute-forced offline. The real control is the server-side code check before streaming. Either drop the claim or use a random key delivered with the code.
- The export link and code sent over WhatsApp need a template or an open session window. Reuse P24's wa_delivery.route instead of a separate path.
- Migration 016 collides with P24.

