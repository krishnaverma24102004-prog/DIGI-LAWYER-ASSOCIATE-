# P46. Conflict checks are slow, manual and error-prone, and small firms run them from memory

**Severity:** medium · **Size:** big · **Region:** India and Global

**Who has it:** All firms, especially small and mid-size Indian firms with no client database, solo advocates sharing files, firms growing through laterals

## What goes wrong

A new matter needs checking against every past client, adverse party and related entity. Small Indian firms rely on a register, memory and WhatsApp search, missing names spelled differently in Hindi and English or relatives in related suits, though BCI Rules bar acting for the opposing side in the same or related matter. Larger firms pass incomplete intake forms back and forth for weeks. Conflicts are among the most frequently alleged errors in malpractice claims, and complaints reach the SC.

## Evidence of scale

- Loeb & Loeb (vendor case study): manual onboarding could take weeks; after automation conflicts handled up to 800 requests a month, up from about 200. ([source](https://www.intapp.com/case-study/loeb-and-loeb/))
- Swiss Re on the ABA Profile of Legal Malpractice Claims 2020-2023: conflicts of interest are one of the most frequently alleged errors; administrative errors increased. ([source](https://corporatesolutions.swissre.com/newsletters/2024-11-aba-profile-legal-malpractice-claims.html))
- LiveLaw on BCI Rules: an advocate who advised or was briefed by one party should not act for the opposing party in the same or related matter. ([source](https://livelaw.in/law-firms/law-firm-articles-/bci-rules-conflict-of-interest-238398))
- SC (2025) set aside an unreasoned BCI order on a conflict-of-interest misconduct complaint and directed a fresh decision. ([source](https://www.scconline.com/blog/post/2025/03/06/supreme-court-strikes-down-unreasoned-bci-order-advocates-professional-misconduct/))
- Aon/Attorneys' Advantage (ABA data): firms of 1-5 attorneys make up 63% of malpractice claims; solos 32%; administrative errors 20%. ([source](https://www.attorneys-advantage.com/getmedia/5fabf74d-11c9-490d-9822-f0263f92e363/AA-Malpractice-Infographic-5-26-2022pdf.pdf))

## Why current tools don't solve it

Intapp and Aderant are enterprise-priced and search structured party names. Clio and PracticePanther do exact-name search over their own contacts, missing transliterations, relatives and related entities, and have no data for firms that never used them. Harvey and CoCounsel do no conflicts. No tool builds a conflict index automatically from a firm's WhatsApp, Gmail, consultations and scanned files and runs it at intake before advice is given.

## Panel verdict

**Status:** open (round -)

**Effort:** L

### What software can fix

Building a firm-wide party index automatically from data the firm already has, and running a deterministic match (transliteration- and relation-aware) on identity fields before any facts are received.

The decisions a lawyer can record are constrained by BCI Rule 33, computed in code and enforced by a database trigger:
- a hard link to an existing matter, adverse to our client, allows only Decline;
- only 'undetermined' connections can be cleared, by a countersignature;
- wrong links are cured only by audited data correction;
- 'not the same person' applies only to Strong name hits.

New this round: the side a prospective client says they are on is never trusted. On a hard link, a role taken from intake answers is 'claimed' and counts as adverse. A same-side role must come from a case type the firm set or eCourts synced, or from corroboration that a lawyer recorded against a document and a different partner countersigned.

### What it can't fix

Relationships that exist nowhere in the firm's data, other firms' clients, and undisclosed corporate groups are out of reach.

Whether a matter 'arises from' another cannot be fully decided by code; the residual judgment stays with a lawyer and a countersigning partner.

Police-station coverage is limited to the states we have seeded.

A corroborating document can itself be forged, or misread by the lawyer. We bind the confirmation to the document's hash and two lawyers' names; we cannot authenticate an FIR copy.

Genuine co-accused or same-side enquirers at pre-filing stage will see Decline-only until a lawyer corroborates their role. That is deliberate friction.

What eCourtsIndia returns and what lawyers enter limit the linkage. Name matching is imperfect, and we report precision and recall.

### What the user sees

Conflict check card: as in round 5, with four bands and matter-link labels, plus a role line on every hard link:
- 'Role: claimed by enquirer: complainant (not verified). Treated as adverse.' The buttons are Decline only, plus 'Record role corroboration'.
- 'Role: from case type (bail application, set by A. Rao)' or 'from eCourts record'.
- 'Role: corroborated by A. Rao from FIR copy p.2, countersigned by S. Iyer'.

'Record role corroboration' opens a form:
- pick a document on the check: an FIR copy, chargesheet, court order or eCourts party list;
- give a page or paragraph reference;
- pick the role it shows, from the closed enum;
- give a reason of at least 30 characters;
- submit, which creates a conflict_role_confirmation approval that a different owner or partner must execute.
Until it is executed, the card stays Decline-only.

The intake questions are unchanged, but the enquirer's role answer is labelled 'claimed' everywhere it appears.

### What the system does

1)-3) party_index, normalisation, matching, police stations, fir_compare and same_matter v4 are unchanged from round 5.

4) Role side, revised. role_new is (value, source), with source in {case_type_firm, case_type_ecourts, corroborated, claimed, unknown}.
- case_type_ecourts: the case type comes from a court_cases row with source='ecourtsindia', mapped through ROLE_BY_CASE_TYPE (a bail, anticipatory bail or quashing applicant is on the accused side; an execution petitioner is the decree-holder; and so on).
- case_type_firm: the case type was set by an authenticated member with role associate or above, through the matter form. The case-type column has case_type_source and case_type_set_by, and a value written by whatsapp_intake, telephony_session or any service-role intake path is stored with case_type_source='intake' and maps to claimed.
- corroborated: an executed conflict_role_confirmation approval exists for this check_id and link_hash.
- claimed: the role comes from intake answers (WhatsApp, phone, web form) or from an intake-set case type.
- unknown: there is no information.

Adverse for a hard link: effective_adverse = (role_new.source in {claimed, unknown}) OR (role value opposite to our client's role on the linked matter). Only the case_type_firm, case_type_ecourts and corroborated sources can make a hard link same-side.

5) allowed_decisions is unchanged in shape:
- hard and effective_adverse gives {declined};
- hard, same-side and trusted source gives {cleared, declined};
- undetermined, Strong or Possible, and different are as in round 5.

6) DB enforcement, extended.
- record_conflict_check() (SECURITY DEFINER) writes, for each hit, the role value, role_source and link_hash. link_hash covers the hard link bases, the party identities and the linked matter's client role, but not role_new, so a role confirmation does not void itself.
- The BEFORE INSERT trigger on conflict_decisions now recomputes effective_adverse itself from the stored hit. For each hard hit it treats role_source in ('claimed','unknown') as adverse, and accepts 'corroborated' only if an executed conflict_role_confirmation approval exists that:
  - matches check_id and link_hash;
  - names a document_id on the same org and matter-intake, whose stored sha256 equals the approval's doc_sha256;
  - has a requester of role associate or above, and an approver who is a different owner or partner.
  It raises on any decision other than 'declined' while any hard hit is effectively adverse. The trigger does not trust the adverse flag written by the API.
- Any change to the hits (a new link, a linkage correction) changes link_hash, and that voids the confirmation.

7) Linkage correction, the intake hold, purge on decline and re-check on linkage change are unchanged.

8) Corroboration flow. POST /conflicts/{check_id}/role-confirmation {hit_id, document_id, page_ref, role, reason} creates the approval (migration 013's machinery, new kind conflict_role_confirmation). Executing it re-runs the check: role_source becomes corroborated and allowed_decisions is recomputed. Each step is audited (CONFLICT_ROLE_CONFIRMATION_REQUESTED and EXECUTED).

### Where it is built

Extend:
- app/services/conflict_service.py: role_side v5 with sources, effective_adverse and link_hash;
- app/routers/conflicts.py: the role-confirmation endpoint;
- app/services/whatsapp_intake.py and telephony_session.py: intake answers are written with role_source='claimed', and any case type they infer gets case_type_source='intake';
- app/routers/cases.py: the case-type write sets case_type_source='firm' and case_type_set_by from the caller's JWT;
- the migration 013 approvals, which gain the kind conflict_role_confirmation with doc_sha256, page_ref and role;
- the frontend ConflictCard: the role line and the corroboration form.

Migration 017_conflict_index.sql adds:
- the hit fields role_value, role_source and link_hash;
- case_type_source and case_type_set_by on court_cases and on intake records;
- the v5 trigger, which recomputes effective_adverse.

Fixtures: role_claims.csv, with intake-claimed roles against the true FIR roles.

### Why current tools fail and this won't

Intapp and Aderant follow US and UK rules, where consent cures most conflicts, and trust the intake form's role field. Clio and PracticePanther do exact-name search with free-text resolution. Harvey and CoCounsel do no conflicts. Indian small firms rely on a register and memory.

Ours links proceedings deterministically, makes a hard same-matter link Decline-only in code and in the trigger, and never lets the enquirer's own account of which side they are on unlock it. Only firm-set or court-synced case types, or a document-bound corroboration countersigned by a different partner, can show a same-side role, and the trigger checks this itself.

### Safeguards

Rule 33 is enforced in code and in a database trigger that recomputes adverseness itself.

On a hard link, an enquirer's self-reported role and an unknown role both count as adverse. Same-side status needs:
- a firm-set case type, with the setter recorded;
- an eCourts-synced case type;
- or a document-hash-bound corroboration by a lawyer, countersigned by a different owner or partner and voided by any change in the links.

Only 'undetermined' connections can be cleared. Wrong links are cured by audited correction. Identity comes before facts, nothing substantive is processed on hold, and identifiers are HMACs.

### How the panel's objections were answered

Objection (the Decline-only rule depends on a role the untrusted prospective client supplies):
- role_new now carries a source.
- Intake answers, and any case type inferred or written by an intake path, are 'claimed'. On a hard link, a claimed or unknown role is adverse, both in conflict_service and, independently, in the trigger, which recomputes from the stored role_source and does not trust the API's adverse flag.
- A same-side role on a hard link comes only from a firm-set case type (setter recorded from the JWT), an eCourts-synced case type, or an executed conflict_role_confirmation. That approval is bound to the check_id, the link_hash and the corroborating document's sha256, with page reference and reason, and is countersigned by a different owner or partner.
- Test added: a same-FIR intake claiming the complainant role, with no corroboration, gives {declined} only, and a direct INSERT of 'cleared' raises.

### Acceptance tests

- DB test (objection): our client is the complainant on FIR 123/2025, PS Saket. A WhatsApp intake gives the same FIR, and the enquirer answers 'I am the complainant / victim'. There is no case type and no corroboration. role_source='claimed', allowed_decisions={declined}, and the API offers nothing else. A direct INSERT of 'cleared' into conflict_decisions raises, as service_role or as a partner, even when record_conflict_check's stored adverse flag is forced to false in the fixture.
- DB test: in the same case, an associate files conflict_role_confirmation with an FIR copy that shows the enquirer as complainant. Until a different partner executes it, the card is Decline-only. After execution, role_source='corroborated' and {cleared, declined} is offered. If the requester executes their own request, it raises. If the document's sha256 no longer matches the approval's doc_sha256, the trigger raises on 'cleared'.
- DB test: after the confirmation, a linkage correction that adds a connected CNR changes link_hash. The confirmation is void and the card returns to Decline-only.
- Unit: a case type 'Bail Application' written by whatsapp_intake has case_type_source='intake' and maps to claimed. The same case type set by an associate in the matter form maps to case_type_firm (accused side); against our complainant client that is adverse, so Decline-only.
- Unit: a co-accused, our client being the accused on the same FIR, with the case type synced from eCourts as a bail application, gets the same-side options. The same co-accused with only an intake claim gets Decline-only.
- Fixture: role_claims.csv (60 rows of claimed roles, including false ones) gives 0 hard-link checks where a claimed role unlocks anything other than Decline (a hard CI gate).
- Round-5 tests retained: the same-FIR adverse hit raises on consent or cleared even with executed approvals; not_same_person does not remove a hard matter-link finding; the linkage_correction flow and hash voiding; an Exact identifier hit never offers not_same_person; Mehroli against Mehrauli unseeded gives undetermined; Kotwali in different districts gives differ; the sessions case with committal details skipped gives undetermined, and with them gives same; an unknown case type gives undetermined; linked_proceedings.csv has 0 linked pairs classified 'different'; recall at least 0.95 and precision at least 0.90; the intake hold with 0 AI calls; purge on decline; party_hits_view isolation.

### Still blocking

- case_type_firm is accepted as a trusted source that can make a hard link same-side, but for a new enquiry it is only the enquirer's claim re-typed by one associate. Before filing, the case type on the prospective matter (for example 'Bail Application') reflects what the enquirer told the firm. A single associate entering it in the matter form turns role_source from 'claimed' into 'case_type_firm', and that unlocks {cleared, declined} with no document, no hash binding and no different-partner countersignature. The corroborated path requires all three, so case_type_firm is a one-person bypass of the control this round adds. Under Rule 33, a complainant who poses as a co-accused (to conflict the firm out, or to learn the defence) gets cleared by an associate's data entry. Fix I would accept: for role_new on a hard link, a firm-set case type counts as trusted only when it is tied to a filed proceeding, meaning the new matter's court_cases row has a CNR/case number confirmed by eCourts sync (case_type_ecourts), or when it goes through the same conflict_role_confirmation approval (document sha256, page_ref, a different owner or partner). Otherwise map it to 'claimed'. Add a DB test: an associate sets 'Bail Application' on an intake that hard-links to our complainant client's FIR, and the result is still {declined}, with a direct 'cleared' insert raising.
- The 'case_type_firm' path re-launders the enquirer's claim, and the trigger does not verify it. (1) For a pre-engagement enquiry, the only source of a case type for the new matter is what the enquirer said. A single associate who types 'Bail Application' into the matter form after hearing the enquirer's account produces role_source='case_type_firm'. That unlocks {cleared, declined} on a hard same-FIR link with no document and no second lawyer, while the 'corroborated' path for the same fact needs a document hash and a different partner's countersignature. (2) The trigger accepts 'corroborated' only after checking the approval, but it takes 'case_type_firm' and 'case_type_ecourts' as stored by record_conflict_check. It does not re-derive them from court_cases.case_type_source and case_type_set_by, or apply ROLE_BY_CASE_TYPE in SQL. A buggy or forged hit payload with role_source='case_type_firm' therefore clears a hard adverse link, the same class of trust the round claims to remove. Fix I would accept: (a) on a hard link, a firm-set case type on a matter not yet engaged, or on one whose case type was set after the conflict check began, counts as claimed unless it is eCourts-synced or corroborated with countersignature. Equivalently, require the same different-partner countersignature for case_type_firm. (b) The trigger re-reads the linked court_cases or intake record, checks case_type_source and the setter's role, and maps the role in SQL, ignoring role_source from the hit payload except for 'corroborated', which it verifies. (c) Add a test: a hit with role_source forced to 'case_type_firm' and no matching firm-set court_cases row raises on 'cleared'. A second test: an associate setting the case type on the enquiry's own matter does not unlock clearing without a countersignature.
- The trusted sources that unlock a same-side hard link can be forged by staff or are hearsay. (1) case_type_source, case_type_set_by and source='ecourtsindia' are set only in app/routers/cases.py. But authenticated users have direct INSERT and UPDATE on court_cases (011), and the eCourts sync itself writes through the user's client. Any member, including a paralegal, can PATCH case_type_source='firm', case_type_set_by=<a partner's uuid>, or source='ecourtsindia' with any case type through PostgREST. The trigger that 'checks this itself' then reads forged sources. (2) Even an honest case_type_firm is only the enquirer's story relayed by a single associate. In the round's own example, the associate sets a case type mapping the enquirer to the complainant side, and the hard link becomes clearable with no countersignature. The countersigned, document-bound corroboration path exists precisely to stop that, so this source is a bypass of it. Fix I would accept: add a BEFORE INSERT OR UPDATE trigger on court_cases and intake records. It derives case_type_source and case_type_set_by from auth.uid(), role and session role ('intake' for service_role intake paths), ignores client-supplied values, and refuses authenticated writes of source='ecourtsindia' or of the provider fields. Alternatively, verify a server HMAC over the provider payload. Then, for hard links, accept only case_type_ecourts (server-verified) or an executed corroboration as same-side, and let case_type_firm narrow only 'undetermined' findings. Add db tests for a direct forged PATCH and for a single-associate case type on a hard link (Decline-only).

