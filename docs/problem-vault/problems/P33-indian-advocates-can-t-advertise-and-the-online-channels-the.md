# P33. Indian advocates can't advertise, and the online channels they used are under disciplinary attack

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Independent advocates in their first 10 years, small chambers, boutique firms, lawyer-listing platforms

## What goes wrong

BCI Rule 36 forbids advertising or soliciting. After the Madras HC (P.N. Vignesh, 2024), the BCI sent cease-and-desist notices to Justdial, Sulekha, Quikr and Grotal and told State Bar Councils to act against advocates soliciting online; Sulekha's challenge is pending in the SC. The BCI (March 2025) condemned social-media promotion and influencer endorsements, and the Bar Council of Delhi called it serious misconduct. New advocates with no family practice are left with referrals, a senior's overflow or touts, and can't tell what they may post.

## Evidence of scale

- BCI sent cease-and-desist notices to Quikr, Sulekha, Just Dial and Grotal, told State Bar Councils to act, and set four weeks to remove illegal ads. ([source](https://www.scconline.com/blog/post/2024/07/09/bci-bans-illegal-solicitation-of-legal-services-by-lawyers-on-online-portals-after-madras-hc-decision/))
- Madras HC (P.N. Vignesh, 2024 MHC 2515) directed the BCI to act against intermediaries advertising lawyers with ratings and 'Platinum'/'Premium' labels. ([source](https://verdictum.in/court-updates/high-courts/mrpnvignesh-v-the-chairman-and-members-of-the-bar-council-2024mhc2515-madras-high-court-1542732))
- In Nov 2024 the SC issued notice on Sulekha's SLP against the Madras HC judgment. ([source](https://www.verdictum.in/court-updates/supreme-court/sulekhacom-new-media-private-limited-v-pn-vignesh-ors-special-leave-to-appeal-c-nos-257942024-1557830))
- Bar Council of Delhi (4 Aug 2025): promotion on YouTube, Instagram and X breaching Rule 36 is 'serious misconduct' with Section 35 proceedings. ([source](https://www.verdictum.in/news/delhi-bar-council-issues-caution-against-lawyers-advertising-legal-services-on-social-media-1587620))
- BCI (March 2025) warned against social media ads, promotional videos and influencer endorsements. ([source](https://www.medianama.com/2025/03/223-the-bar-council-of-india-warns-against-legal-advertising-online/))
- Advocates (Amendment) Bill 2023: courts may publish tout lists; listed touts face up to 3 months' imprisonment. ([source](https://prsindia.org/billtrack/the-advocates-amendment-bill-2023))

## Why current tools don't solve it

Global growth tools (Clio Grow, Avvo, Martindale, legal SEO, review solicitation, paid ads) assume advertising is legal and are a misconduct risk in India. No tool checks a website, bio or post against Rule 36, or turns permitted assets into more work: repeat and referral clients and fast service to people who make contact first.

## Panel verdict

**Status:** open (round -)

**Effort:** M

### What software can fix

Letting an advocate publish only what BCI Rule 36 permits, with a deterministic checker for bios, websites and posts.

The product's own outbound channels cannot open a conversation with a stranger, and cannot be turned into a marketing channel to past enquirers or clients.

Every legitimate send, template or in-window, goes through one registry and one guard, under one contract that P24 and P33 both cite. Each send carries a typed, recorded reason.

No client-facing slot carries staff-typed free text. Every value is a typed primitive, or is rendered by the server from closed enums, structured fields or a lawyer-approved, hash-pinned record of the same matter.

### What it can't fix

Whether a post or message is misconduct is decided by the State Bar Council under Advocates Act s.35, and the law is unsettled: Sulekha's SLP is pending. Our checker is conservative information, not clearance.

We will not build directories, ratings, badges, SEO, paid ads or review solicitation.

We cannot police what advocates post or send outside the product, or offline touting.

A lawyer can still approve a promotional explanation, either by phrasing it impersonally or by using the audited override. The approver stays responsible; we make it traceable, not impossible.

A lawyer typing a reply in the inbox, inside the 24-hour window to someone who wrote first, is a human message. It is checked and audited, but the lawyer stays responsible for it.

Template approval and categorisation by Meta, and its changing parameter rules, are outside our control. We re-sync and fail closed.

Generic labels ('your document dated 12 Oct') are less specific than a document's title. That is the price of closing the free-text channel.

### What the user sees

Unchanged: the 'Public profile' page, 'Check my text', the 'Who we can message' panel, the follow-up dialog and the Rule 36 override on approval.

Send dialog: it shows P24's template from template_registry in the client's language, every slot filled by the server and labelled with its source, for example:
- 'Document: Lease deed dated 12 Oct 2026 (from document type and date)';
- 'Case: Sharma v. Verma (from eCourts sync)', or 'Case: your case (hand-entered title not sent)';
- 'Explanation part 2 of 3: approved by A. Rao on 12 Oct';
- 'Consent notice v4 (Hindi)';
- 'Rs 25,000 received on 10 Oct: ledger entry #88'.

Slots cannot be typed into. A filename or title the staff typed is never shown as a slot value.

An in-window explanation (inside the 24-hour window) is sent as the approved record body itself, with the same labels.

A blocked send shows a specific reason:
- 'Changed since approval: re-approve';
- 'Record belongs to a different matter';
- 'Document type not set: choose one';
- 'Value looks like a contact or solicitation';
- 'Too long for this template in Hindi: send as document'.

### What the system does

1) One contract, app/services/template_contract.py, cited identically by P24 and P33.
- Store: template_registry is the only store. It is seeded and versioned by P24's migration. data/wa_templates.json and every P33-defined row are deleted.
- Ownership: P24 owns the content (names, bodies, languages, per-language max_len, param_schema, Meta categories). P33 owns enforcement (outbound_policy, slot resolvers, meta_param_check and the send functions).
- Canonical names are P24's: client_explanation_v1, client_explanation_doc_v1, affidavit_text_review_v1 and channel_consent_optin_v1. They sit alongside the P09, P35, reminder and enquiry templates under their round-4 names. CANONICAL_TEMPLATES in the contract module is the single list; explanation_ready_v1, explanation_doc_v1 and consent_optin_v1 exist nowhere.
- Slot kinds (SLOT_KINDS):
  - primitives: date, time, enum, int_small;
  - bound: org_field, document_title_from_record, case_title_from_matter, hearing_date_from_matter, approved_record_text, record_part_label, approved_record_media, consent_notice, and the ledger_* and invoice_* kinds.
- APPROVED_TEXT_SOURCES maps kind to (table, param_text_col, param_sha_col, body_text_col, body_sha_col, approved_by_col, approved_at_col, matter_col, part_label_col, media_sha_col). P24 fills the entries for its tables and P09 the entry for fee_terms.
- P33 hardcodes no template's slots or limits. The guard reads param_schema and max_len (for example P24's 350 for client_explanation_v1 {{3}} in hi) from the row being sent.

2) document_title_from_record(ref) replaces document_title.
- The ref resolves to a same-org, same-matter document, draft or explanation-source record.
- It renders DOC_KIND_LABELS[lang][doc_kind] + DATED[lang] + format_date(lang, document_date). doc_kind is a closed enum (lease_deed, leave_and_licence, sale_deed, agreement, nda, employment_agreement, loan_agreement, guarantee_deed, sha, spa, will, poa, affidavit, legal_notice, bail_application, plaint, written_statement, order, other_document) and the labels are P24-authored per language.
- Filenames, titles and storage paths are never read by the resolver. It selects only doc_kind and document_date, and a test asserts the column list.
- If doc_kind is null, it falls back to case_title_from_matter; failing that, to GENERIC_DOC[lang] ('your document' / 'आपका दस्तावेज़').

3) case_title_from_matter is closed the same way.
- It renders '<petitioners[0]> v. <respondents[0]>' only from a court_cases row with source='ecourtsindia', whose arrays equal the provider_data snapshot, which is itself hash-checked.
- Hand-entered rows (source='manual'), court_cases.title and case_threads.title are never used. They render GENERIC_CASE[lang] ('your case').

4) Defence in depth on every rendered bound value (except org_field(office_phone) and the ledger and date kinds), via slot_value_guard:
- it refuses digit runs of 7 or more, URLs and e-mail addresses, and the record-profile solicitation patterns ('call', 'refer', 'contact us', 'best', 'no. 1' and their Hindi forms) with slot_value_flagged;
- org fields are checked by the publication profile when they are saved.

5) In-window sends: send_text(body_ref) replaces free-form text for anything not typed by a human.
- whatsapp_service.send_text is renamed _post_text. A CI grep fails on any call outside outbound_policy.
- outbound_policy offers exactly three in-window functions:
  - send_body_ref(kind, id, reason): resolves APPROVED_TEXT_SOURCES body_text_col for the same org and matter, checks sha256(NFC(body)) equals body_sha_col (otherwise approval_stale), checks approved_by is not null, applies Meta's 4,096-character text limit, requires an open 24-hour window from an inbound message, and records body_sha256 and ref;
  - send_lawyer_reply(text): an authenticated lawyer's own typed text, in an open window only, checked by the publication profile (a flag blocks unless overridden with a reason) and audited with the actor;
  - send_intake_reply: the existing P07 intake path, unchanged, in-window only.
- AI-generated text can never reach send_lawyer_reply: the route takes only a request body typed in the inbox and rejects any draft_id.

6) Template sends.
- meta_param_check is unchanged: no newlines, tabs or runs of 4 or more spaces; per-slot max_len and a hydrated body of at most 1,024 characters, both from the row; body_sha256 pinned per language.
- assert_may_initiate is unchanged: reasons (a)-(f), the enquiry caps, MARKETING refused and no bulk.
- The Rule 36 record and publication profiles are unchanged from round 5.
- Sent rows store reason, ref, template, language, body_sha256, slot_refs and slot_values_sha256. Blocked attempts are audited (OUTBOUND_BLOCKED) with an HMAC of the number.

### Where it is built

Extend:
- app/services/whatsapp_service.py: send_text becomes the private _post_text; send_template takes a language and resolved parameters only;
- app/services/whatsapp_intake.py and app/routers/whatsapp.py: inbox replies go through send_lawyer_reply;
- app/worker.py: hearing reminders use hearing_reminder with case_title_from_matter and hearing_date_from_matter;
- app/services/twilio_service.py: as in round 4.

New (P33):
- app/services/outbound_policy.py;
- app/services/slot_resolvers.py (document_title_from_record, case_title_from_matter, approved_record_text, record_part_label, approved_record_media, consent_notice, org_field, ledger and invoice);
- app/services/slot_value_guard.py;
- app/services/rule36_service.py, app/rules/rule36.yaml, data/rule36_record_allowlist.yaml;
- app/routers/profile.py.

Shared and cited identically by both proposals:
- app/services/template_contract.py (CANONICAL_TEMPLATES, SLOT_KINDS, APPROVED_TEXT_SOURCES, DOC_KINDS and the per-language labels, with P24 authoring the labels);
- tests/fixtures/template_refs.py;
- tests/test_template_contract.py.

Data and migrations:
- template_registry and its seed rows come from P24's migration;
- P33's migration adds the doc_kind enum column and document_date on documents and drafts (nullable, set in the upload and studio UI), the sent-message columns, approve_text() with the override columns, and the wa_templates_status view;
- P33's migration deletes nothing from P24's rows.

### Why current tools fail and this won't

Clio Grow, Avvo, Justdial, Sulekha and SEO agencies assume advertising is legal. WhatsApp CRMs (Interakt, WATI, AiSensy) run broadcasts with free-text variables, so any 'reminder' can carry a pitch, and even their 'document name' variable is whatever staff typed.

Ours has no broadcast path and refuses MARKETING templates. It has one registry, owned for content by P24 and for enforcement by P33, under one contract module and one cross-proposal test. No slot ever carries a filename, a hand-typed title or other free text: labels come from closed enums, dates and court-synced party names, or from hash-pinned, lawyer-approved records of the same matter, with a contact and solicitation guard on top.

### Safeguards

Outbound sending is an allowlist in the send functions:
- no bulk endpoint and no MARKETING template;
- capped enquiry follow-ups;
- no free-text slot, and no filename or hand-typed title in any slot;
- one registry, one contract module and one cross-proposal CI test;
- every bound value is server-rendered from enums, structured or court-synced fields, or hash-pinned approved records of the same org and matter, then passes the contact and solicitation guard and Meta's checks before the call;
- in-window sends are either an approved, hash-checked body_ref, or a lawyer's own typed and checked reply. AI text never goes out free-form.

Overrides need a reason, are audited and stay labelled. The checker is information, not clearance.

### How the panel's objections were answered

Objections on the registry contradicting P24 (two sources, names, slot kinds, max_len, opt-in slots, circular ownership, no send_text(body_ref)):
- We align with P24's design. template_registry, seeded by P24's migration, is the only store, and data/wa_templates.json is deleted. The names are P24's (client_explanation_v1, client_explanation_doc_v1, affidavit_text_review_v1, channel_consent_optin_v1), and explanation_ready_v1 and the other P33 names are gone. The slot kinds are P24's (document_title_from_record, approved_record_media).
- Ownership is stated once: P24 owns the content, P33 owns the enforcement. Both proposals cite app/services/template_contract.py for CANONICAL_TEMPLATES, SLOT_KINDS and the APPROVED_TEXT_SOURCES columns.
- P33 hardcodes no slot lists or max_len values. It reads param_schema and max_len from the row, so P24's 350 and its opt-in slots govern.
- send_body_ref resolves approved bodies and checks their hashes for in-window sends, and raw send_text is made private and grep-gated.
- One shared test file checks the inventory and runs every seeded row through the guard.

Objections on document_title(ref) being a free-text hole:
- It is replaced by document_title_from_record, which renders a doc_kind enum label plus a date in the template language and never reads a filename or title. The fallback is case_title_from_matter, which itself now uses only eCourts-synced party names and never hand-entered titles, and then a generic label.
- slot_value_guard adds a contact and solicitation check on every rendered value.
- Tests added: the promotional filename is absent from the payload, the resolver's column list is asserted, and a hand-entered case title is not sent.

### Acceptance tests

- Unit (objection, filename injection): a same-matter document stored as 'BEST PROPERTY LAWYER PUNE - REFER FRIENDS call 98xxxxxxxx.pdf' with doc_kind=lease_deed and date 12 Oct 2026. client_explanation_v1 in hi renders {{2}} as 'लीज़ डीड दिनांक 12 अक्टूबर 2026', and none of 'BEST', 'LAWYER', 'REFER', '98' or the filename appears in the Meta payload. With doc_kind null, it renders the case title fallback or 'आपका दस्तावेज़'.
- Unit (objection): slot_resolvers.document_title_from_record issues a SELECT whose column list is exactly (id, org_id, matter_id, doc_kind, document_date); asserted against the query builder mock.
- Unit (objection): case_title_from_matter on a court_cases row with source='manual' and title 'Best lawyer call 98xxxxxxxx' renders GENERIC_CASE[lang]. On source='ecourtsindia' it renders 'Sharma v. Verma' from the synced arrays; if the arrays are edited away from the provider_data snapshot, it is refused with snapshot_mismatch.
- Unit: slot_value_guard refuses an eCourts party name containing a URL or a 10-digit number with slot_value_flagged, with 0 Meta calls.
- Cross-proposal CI (objection, registry): tests/test_template_contract.py applies every migration to embedded Postgres and loads template_registry. It asserts:
- the row names equal template_contract.CANONICAL_TEMPLATES exactly;
- 'explanation_ready_v1', 'explanation_doc_v1' and 'consent_optin_v1' appear in no row, no file under app/ or data/, and no test fixture;
- data/wa_templates.json does not exist;
- every param_schema slot kind is in SLOT_KINDS;
- every template has a reason mapping;
- no MARKETING row exists.
P24's inventory assertions live in the same file.
- Cross-proposal CI (objection, registry): for every (name, language) row, with refs from tests/fixtures/template_refs.py, outbound_policy.send_template passes assert_may_initiate, slot resolution, meta_param_check against that row's own max_len, and the body_sha256 pin, against a mocked Meta. This covers client_explanation_v1, client_explanation_doc_v1 (approved_record_media), affidavit_text_review_v1, channel_consent_optin_v1 (its seeded slots), fee terms, the Rule 27 intimation, the invoice reminder, the office notice, the hearing reminder and the enquiry follow-up.
- Unit (objection, body_ref): send_body_ref(client_explanation, E) inside the window sends E's body_text exactly and stores body_sha256. With the body edited after approval it is refused with approval_stale. A ref from matter N sent to M's client is refused with record_other_matter. Outside the window it is refused with window_closed and points to client_explanation_v1. All refusals make 0 Meta calls.
- Unit: a CI grep finds no call to whatsapp_service._post_text outside outbound_policy. POST /whatsapp/inbox/reply with a draft_id is rejected with 422. A lawyer reply 'We are the best, refer friends' is flagged by the publication profile and blocked unless overridden with a reason of at least 20 characters, which writes RULE36_OVERRIDE.
- Unit: meta_param_check refuses '\n' in a resolved value, a slot over the row's hi max_len (350 for client_explanation_v1 {{3}}) with too_long_send_as_document, and a hydrated body of 1,030 characters.
- Round-5 tests retained: the record profile gives 0 refusals on 120 contract explanations and refuses all 40 promotional negatives; the override needs at least 20 characters; consent_notice hash and version rules; fee_terms stale and re-approved; ledger refs; the org_field allowlist; enquiry caps and the 30-day boundary; conflict_hold refused; no array-recipient route; a cold number refused; at most 2 of 50 neutral bios flagged; immutable sent rows.

### Still blocking

- The in-window allowlist leaves out the existing AI reply paths, and the safeguard 'AI text never goes out free-form' is false. app/services/whatsapp_intake.py sends AI conversation output with whatsapp_service.send_text in _reply (line ~154). It also sends a lawyer-reviewed, held AI reply (the 013 hold_reasons flow, line ~298), where the body is the AI's text unless the lawyer edits it. The proposal allows exactly three in-window functions. send_intake_reply is 'the existing P07 intake path, unchanged', so AI-generated text to prospective clients goes out free-form with no Rule 36 publication-profile check and no slot_value_guard. The held-reply approval has no named function at all. send_lawyer_reply rejects anything other than typed inbox text, so either that flow breaks under the CI grep or it is routed through send_intake_reply unchecked. An AI intake reply such as 'our firm has won many such cases, call us' is the exact self-promotion Rule 36 forbids, and it reaches a stranger who has only just written in. Fix I would accept: (1) name a fourth function, send_reviewed_ai_reply(message_id), bound to the whatsapp_messages row, its sha256 and the reviewing lawyer. (2) Run send_intake_reply and send_reviewed_ai_reply through the Rule 36 publication profile plus slot_value_guard's contact and solicitation patterns, blocking or holding for a lawyer on a flag. (3) Correct the safeguard text. (4) Add tests: an AI intake reply containing a promotional phrase is held with 0 Meta calls, and approving a held reply goes through send_reviewed_ai_reply and is audited.
- case_title_from_matter trusts court_cases rows with source='ecourtsindia' whose petitioner and respondent arrays equal provider_data. All of those columns are writable by the staff member. Migration 011 grants authenticated a plain INSERT and UPDATE policy on court_cases with no column restriction. app/routers/cases.py sync_case runs ecourts_service.sync on ctx.db(), the user's own client. So anyone can POST to PostgREST a row with source='ecourtsindia', petitioners=['Pune's top property advocate Sharma'] and a matching provider_data. Any 'hash check' stored in a user-writable column proves nothing. slot_value_guard catches digits, URLs and a short word list, but not ordinary self-promotion like that. This reopens the free-text slot that this round claims is closed, in hearing reminders and in the fallback for document titles. Fix I would accept: have the server sign the provider payload with an HMAC key the database user cannot read, stored alongside the row, and have the resolver verify it. Alternatively, move eCourts writes to a SECURITY DEFINER function or the service-role worker, and add a trigger that rejects authenticated writes setting source='ecourtsindia' or changing petitioners, respondents or provider_data on such rows. Add a db test: a direct authenticated insert of a forged 'ecourtsindia' row is refused, or renders GENERIC_CASE.

