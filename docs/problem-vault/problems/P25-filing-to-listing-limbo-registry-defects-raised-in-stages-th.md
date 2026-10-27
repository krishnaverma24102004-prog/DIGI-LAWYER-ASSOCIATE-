# P25. Filing-to-listing limbo: Registry defects raised in stages, then matters not listed for weeks

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** SC AoRs, HC practitioners, filing clerks, litigants in urgent matters

## What goes wrong

In the SC and High Courts, a petition gets a diary number and the Registry raises defects (certified copies, court fee, pagination, affidavits, vakalatnama, illegible annexures, condonation applications, IA nomenclature); after curing, a new set can appear. Under SC Rules 2013 O.III R.8 cure time is capped at 28 days total, and defects uncured after 90 days go to the Judge in Chambers. Even after curing, verification and listing take days or weeks. In urgent matters (liberty, demolition, auction, limitation) every extra round hurts.

## Evidence of scale

- LiveLaw (12 June 2026): defects sometimes raised in instalments; lists recurring types; SC Rules O.III R.8 allows up to 28 days to cure and sends defects uncured after 90 days to Chambers; proposes a one-shot defect memo and checklist. ([source](https://www.livelaw.in/articles/filing-becomes-battle-defect-scrutiny-supreme-court-registry-537576))
- A SCAORA representation by 137 AoRs flagged lags in Registry defect curing and lack of timelines. ([source](https://www.livelaw.in/amp/top-stories/supreme-court-advocates-on-record-raises-concerns-regarding-filing-listing-process-online-appearances-etc-269353))
- SC Observer: after registration it could take days or weeks for an urgent matter to be verified. ([source](https://www.scobserver.in/journal/the-listing-game-and-the-registry-at-the-supreme-court-of-india/))
- Madras HC (July 2026) dismissed an advocate's writ to list 21 pending matters; listing involves thousands of filings a week and there is no vested right to out-of-turn listing. ([source](https://www.verdictum.in/madras-high-court/individual-litigant-counsel-no-vested-fundamental-right-out-of-turn-listing-matter-1617314))

## Why current tools don't solve it

No tool pre-scrutinises a draft SLP or writ against a specific court's Registry checklist before filing (court fee, pagination, legibility, translation, limitation/condonation, vakalatnama). Harvey and CoCounsel don't know Indian Registry rules. E-filing portals show defects only after filing, one round at a time. Nothing tracks cure deadlines or listing status across matters.

## Panel verdict

**Status:** solved (round 1)

**Effort:** L

### What software can fix

Catching Registry defects before filing, in one pass, against the specific court's published checklist (pagination, index-to-page consistency, annexure references, true/certified copy markers, court fee, vakalatnama and affidavit presence and dates, legibility, untranslated vernacular pages, limitation and condonation application), and after filing, tracking defect rounds, cure deadlines and days since cure without listing.

### What it can't fix

The Registry's own pace, defects raised in instalments by scrutiny staff, out-of-turn listing decisions, and the judgment calls a scrutiny officer makes. Court fee is computed only for courts whose fee schedule we have encoded and verified. We don't submit to the e-filing portal.

### What the user sees

A Pre-scrutiny tab in the Studio: upload the filing bundle (PDF or DOCX parts) and pick the court and case type. A report lists each check as pass/fail/needs-human with page numbers: 'Index says Annexure P-4 at p.57; it starts at p.61', 'Annexure P-7 referred in para 12 is not in the bundle', 'pages 33-35 illegible (OCR confidence 41%)', 'page 80 appears to be in Marathi; no translation follows', 'impugned order dated 02.06.2026; 112 days have passed; no condonation application found', 'vakalatnama page not detected: confirm'. After filing, a Defects tracker per matter: round number, defects raised, date, cure deadline under the court's rule, and listing status, with a 'listing delayed' flag after a firm-set threshold.

### What the system does

1. Checklist rules as data per court (app/data/registry_checklists/<court>.json): check id, type (structural, presence, arithmetic, date), source (rule or practice direction URL), status draft/verified by two advocates.
2. Structural checks in code on the PDF: page count vs. stamped page numbers, index table parsed and compared with detected annexure headers, cross-references 'Annexure P-n' in the body vs. annexures present, OCR confidence per page via ocr_service, script/language detection per page, file size and page size.
3. Presence checks: keyword and layout detection for vakalatnama, affidavit, verification, court-fee page; uncertain detections become 'needs human', never 'pass'.
4. Limitation: impugned-order date and remedy go through limitation_service (P06); if delay exists and no application titled for condonation is present, fail.
5. Court fee: computed from the encoded state schedule where verified; otherwise 'not computed'.
6. Post-filing: defect rounds entered by the clerk (or imported from portal emails forwarded in); cure deadline computed from the court's rule as data; each becomes a P13 deadline.
No AI decides pass/fail; Claude may optionally suggest IA titles, shown as suggestions.

### Where it is built

app/services/ocr_service.py, document_service, limitation_service (P06), deadline_service (P13); new app/services/scrutiny_service.py and app/data/registry_checklists/; migration 017_filing_checks.sql (filing_checks, defect_rounds); Studio UI in frontend/src/app/studio/page.tsx.

### Why current tools fail and this won't

E-filing portals show defects only after filing, one round at a time; Harvey and CoCounsel don't know Indian Registry rules; nothing tracks cure deadlines across matters. Ours runs the whole checklist before filing in one pass and is deterministic, so the same bundle always gets the same report.

### Safeguards

Bundles are client documents: stored under RLS, processed on our server; no AI needed for checks (Tesseract only, OCR vision fallback disabled for this path). Checklist rules carry sources and two-advocate sign-off.

### Acceptance tests

- tests/test_scrutiny.py fixtures: synthetic SLP and writ bundles with planted defects (index mismatch, missing annexure, illegible page, Marathi page without translation, 112-day delay without condonation IA, no vakalatnama); every planted defect is reported with the right page, and a clean bundle reports zero fails.
- test_uncertain_is_not_pass: a vakalatnama page with low-confidence detection is 'needs human'.
- test_court_fee_unknown_court: a court without a verified schedule returns 'not computed', never a number.
- test_defect_round_deadline: a defect round raised 2026-10-01 under a court rule of 28 days total creates a deadline and reduces the remaining days on a second round.
- Determinism: running the same bundle twice yields byte-identical reports.

### Reviewers' minor notes

- Too many 'needs human' results will drown the report. Track the share per check and tune it before calling the feature done.
- Limitation defects depend on choosing the right remedy. Show the remedy that was assumed in the report so a wrong pick is visible.
- Name the reviewer of each court's checklist in the report footer, so a 'pass' is not read as the vendor certifying compliance.
- Marathi and Hindi share the Devanagari script. Tesseract OSD detects the script, not the language, so the 'page appears to be in Marathi' test needs a language-ID step (or should flag 'vernacular page' without naming the language).
- Byte-identical reports require fixed timestamps and stable ordering. Exclude generated_at from the hashed body.

