# P45. India: unstamped or under-stamped contracts surface only at the dispute stage, costing penalties and delaying arbitration and suits

**Severity:** high · **Size:** big · **Region:** India (and cross-border)

**Who has it:** Litigation and arbitration practices at Indian firms, in-house counsel, foreign companies contracting with Indian parties

## What goes wrong

Years after signing, a dispute arises and the agreement is unstamped or under-stamped. It is inadmissible until duty and penalty (up to ten times) are paid. The law changed twice in 2023: N.N. Global (April 2023) held insufficiently stamped arbitration agreements couldn't be acted on; In Re Interplay (Dec 2023, 7 judges) overruled it, making stamping a curable defect for the tribunal. Clients face cost, impounding and procedural fights, including foreign parties with an Indian seat.

## Evidence of scale

- In Re Interplay (13 Dec 2023) overruled N.N. Global and SMS Tea Estates: unstamped agreements are not void but inadmissible until the curable defect is cured; objections go to the tribunal. ([source](https://www.livelaw.in/amp/top-stories/arbitration-clauses-in-unstamped-agreements-enforceable-supreme-court-7-judge-bench-overruled-nn-global-decision-244387))
- Under N.N. Global, insufficiently stamped arbitration agreements couldn't be acted on until impounded and duty paid, reaching international arbitrations seated in India. ([source](https://conflictoflaws.net/2023/to-stamp-or-not-to-stamp-critiquing-the-indian-supreme-courts-judgement-in-n-n-global/))

## Why current tools don't solve it

No AI legal tool (Harvey, CoCounsel, Lexis+ AI, Manupatra, SCC Online) audits a client's existing contracts for stamping and registration exposure before a dispute (which documents, which state Act, cost to cure now). Research tools find Interplay but don't apply it to the client's documents.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Auditing a client's or company's existing contracts for stamping and registration exposure before a dispute: for each document, what stamp evidence the copy shows (e-stamp certificate number, denomination, franking, impressed paper text), what duty the P17 table says was due, the deficit, the penalty as of today under that state's penalty provision, the route to cure (adjudication or voluntary payment of deficit and penalty), and the procedural consequence in plain terms with the authority checked (inadmissible in evidence until duty and penalty are paid; for arbitration agreements, after In Re Interplay (2023), a curable defect for the tribunal, not a bar to appointment). It also prioritises: contracts with arbitration clauses, high value, near-expiry or in dispute come first.

### What it can't fix

Whether the original physical document was stamped when the copy we have is a scan without the stamp page; we say 'no stamp evidence in this copy', never 'unstamped'. The Collector's adjudication and discretion on penalty. Whether paying now is commercially wise (it may also alert the authorities) is the client's and lawyer's decision. Privilege: in India, communications with in-house counsel may not get the protection s.132 BSA gives to an advocate's professional communications, so a company wanting the audit privileged should commission it through external counsel. The product can label the report and route it, but it can't create privilege.

### What the user sees

'Stamp exposure audit' on the repository (P42) or a selected folder. A table, one row per contract: name, state, instrument (as confirmed), stamp evidence found ('e-Stamp IN-KA12345678901234A, Rs 500' with the page image crop), duty due, deficit, penalty today (with the formula and the penalty section), registration status (compulsory and not evidenced / evidenced / not required), arbitration clause yes/no, priority. Filters: under-stamped, no evidence, needs classification. 'Cost to cure now' total at the top. A draft memo to the client (DOCX/PDF) is generated from the table: which documents, which Act, cost to cure, consequences with Interplay explained, and recommended steps. It's marked 'Draft: requires advocate review' and can't be sent or exported as final until a lawyer approves it (the existing drafts.approved_by mechanism).

### What the system does

1. Stamp evidence detection is deterministic: OCR text of the first and last pages (ocr_service; Tesseract with eng plus regional languages for stamp paper) is scanned with regexes for SHCIL certificate numbers (IN-<state code><digits><letter>), 'Certificate Issued Date', 'Stamp Duty Amount(Rs.)', 'Account Reference', franking imprints ('Franking', 'Stamp Duty Paid', denomination), impressed paper text ('INDIA NON JUDICIAL', denomination in words), and registration endorsements ('Sub-Registrar', 'Document No.', 'Book I'). The amount is parsed by code. 2. Duty due comes from the P17 assessment (confirmed instrument key and inputs); without a confirmed classification the row is 'needs classification' and no deficit is shown. 3. Penalty: the state row's penalty formula (for example a percentage per month on the deficit up to a cap, or a multiple of the deficit) evaluated with the execution date from a verified quote and today's date; the result is labelled 'maximum exposure' where the statute leaves the amount to the authority's discretion. 4. Consequence text is fixed, lawyer-written template text keyed by context (suit evidence, arbitration agreement, registration), not generated; it cites In Re Interplay and the relevant Stamp Act sections, and citation_service confirms each (Interplay must be a known_case in legal_authorities, and the sections must exist in the registry). 5. Priority score is code: arbitration clause, value band, dispute flag from the case tracker (court_cases linked), expiry soon. 6. The memo is assembled from the table plus template paragraphs; Claude may only write the cover summary, which passes verify_output_safety and citation_service and is labelled. 7. Runs as an ARQ job (task_stamp_audit) re-checking the user's role, results stored in stamp_assessments with audit_id.

### Where it is built

P17 stamp_duty registry and stamp_assessments; app/services/ocr_service.py; app/services/citation_service.py; app/services/drafting_engine.py and drafts approval (migration 013); app/worker.py job pattern; app/services/queue_service.py; court_cases (migration 011) for dispute flags; app/services/pdf_service.py. New: app/services/stamp_duty/evidence.py, app/services/stamp_duty/audit.py, task_stamp_audit in app/worker.py, frontend/src/app/obligations or a new /contracts/audit page, tests/test_stamp_evidence.py, tests/test_stamp_audit.py, fixtures with synthetic e-stamp certificate images (made by us, no real certificate numbers).

### Why current tools fail and this won't

Manupatra and SCC Online find Interplay but don't apply it to a client's documents; Harvey and CoCounsel don't know Indian stamp law; CLMs don't look at the stamp page. This audit is mostly code: evidence detection by pattern, duty from the sourced table, penalty by formula, consequences from lawyer-written templates with checked citations. The only AI step is the cover summary, which a lawyer approves.

### Safeguards

Lawyer approval before any memo leaves the system (invariant on AI output reaching a client). Fixed consequence text with citation checks (invariant 3). PII-masked AI summary. The privilege caveat for in-house audits is shown on the audit screen. No contact with stamp authorities. Audit logged. RLS per org; the job runs with the user's role re-checked, as the existing worker does.

### Acceptance tests

- tests/test_stamp_evidence.py: a synthetic e-stamp certificate OCR text gives certificate number, state code KA and amount 500; franking text gives the franked amount; a copy with no stamp page gives 'no_evidence_in_copy' (never 'unstamped').
- A Karnataka agreement with Rs 500 paid and Rs 1,000 due (golden fixture) gives deficit Rs 500 and a penalty equal to the hand-computed value for the fixture's execution date and a frozen today.
- An unconfirmed instrument key gives 'needs_classification' with no deficit or penalty.
- A memo draft can't be exported as final while approved_by is null (API returns 409); after a partner approves, editing any paragraph clears the approval (existing trigger).
- The consequence paragraph for an arbitration agreement contains the Interplay citation and citation_service returns known_case for it; with legal_authorities empty the citation is marked [unverified] and the memo is blocked from approval until fixed.
- Priority ordering on a seeded set: an arbitration-clause contract with a linked court case ranks above a low-value NDA.
- The worker job re-checks that the requesting user is still a member with associate or higher; a removed user's job does nothing.
- Penalty with discretion is labelled 'maximum exposure'.

### Reviewers' minor notes

- Add a link to the SHCIL 'verify e-stamp certificate' page per detected certificate. Fake e-stamps are common, and a matching regex isn't authenticity.
- Penalty rows for states where the authority has discretion (for example a 'up to 10 times' deficit) should show the range and the minimum as well as the maximum exposure.
- In Re Interplay's consequence text is correct. Also note that s.35 inadmissibility applies in suits and that the impounding route sits under ss.33/38 of the Indian Stamp Act or the state equivalent.
- A Drive or ZIP backfill audit run by in-house teams creates a discoverable record of known deficits. Make the privilege caveat a required acknowledgement before the run, not just a banner.
- When the stamp page is detected only from OCR, attach the page crop with the detected amount so the lawyer verifies it. Tesseract misreads denominations.
- Inherits P17's table-ownership issue. Fix that first.
- With no stamp page, 'no_evidence_in_copy' is the right wording. Keep any total exposure figure limited to rows that have a confirmed classification.
- The test for a removed user's job fits the existing worker re-check pattern.

