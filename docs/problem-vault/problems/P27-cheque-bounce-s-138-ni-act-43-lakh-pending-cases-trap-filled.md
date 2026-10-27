# P27. Cheque-bounce (s.138 NI Act): 43 lakh pending cases, trap-filled timelines and stalled summons

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Recovery and banking-litigation firms, NBFC/MSME in-house teams, solo advocates with s.138-heavy practices, complainants

## What goes wrong

A s.138 case has a strict sequence: cheque presented within validity, demand notice within 30 days of the return memo, 15 days for payment, complaint within one month after the cause of action. One day early is premature, one day late is time-barred, and multiple cheques mean parallel clocks. Firms and NBFC/collection desks run thousands of files; once filed, cases stall on service of summons, and lawyers track s.143-A interim compensation, mediation and warrants by hand.

## Evidence of scale

- 43,05,932 s.138 cases pending (Parliament reply 20.12.2024), up from about 35.16 lakh at end-2019; Delhi District Courts had 6,50,283 pending (Sep 2025), close to half of Delhi's trial-court criminal pendency; Kolkata 2,65,985, Mumbai 1,17,190. ([source](https://www.scconline.com/blog/post/2026/10/13/section-138-cheque-bounce-case-backlog-india-judicial-reforms/))
- On 23 Sept 2025 the SC directed all States, UTs and HC Registrars General to file status reports on increasing disposal of cheque-bounce cases. ([source](https://www.verdictum.in/app-lite/court-updates/supreme-court/file-status-reports-on-steps-taken-to-increase-disposal-of-cheque-bounce-cases-supreme-court-to-states-uts-1592274?hasShare=1))
- SC: service of summons on the accused remains one of the main reasons for delay in these complaints. ([source](https://www.tribuneindia.com/news/india/sc-issues-fresh-guidelines-to-reduce-staggeringly-high-backlog-of-cheque-dishonour-cases/))

## Why current tools don't solve it

No legal AI tool (Harvey, CoCounsel, SpotDraft, Manupatra or SCC AI) handles bulk s.138 work: per-cheque notice and complaint windows from the return memo, notice and complaint drafting, service and s.143-A tracking, and flags for files about to go premature or time-barred. Clio doesn't know NI Act timelines.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

An internal s.138 NI Act pack for law firms that handle cheque-bounce work, built on the P13 docket and P06 limitation engine rather than sold as a standalone collections platform. It gives per-cheque clocks from the return memo, a deemed-service computation that brackets an uncertain service date and shows only the safe filing window, and deterministic demand notices from the firm's template. Post-filing it tracks summons service, s.143A interim compensation, warrants and the s.148 deposit on appeal. Every date flows into the firm's verified docket with sampled partner approval.

### What it can't fix

Service of summons by the court, police executing warrants, the accused absconding, and court disposal rates. India Post delivery status is imported from bulk-customer reports or entered by hand; we don't scrape tracking pages behind captchas. Lender-side collection operations at portfolio scale (dialling, settlement, ODR, legal-notice dispatch as a service) are what CredGenics, Legodesk and similar platforms do, and we don't compete there. Whether a court accepts a particular presumed service date is for the court; where the evidence leaves no safe window we flag it for the lawyer, not decide it.

### What the user sees

A Cheque files page (/cheques) inside the firm's matters. The user imports a CSV from the client (one row per cheque: drawer, amount, cheque date, presented on, memo received, reason, branch), including exports from CredGenics/Legodesk-style platforms via a column mapper. Each file shows its stage and next date in columns: Notice due, Awaiting service, Pay window running, Safe filing window open, Filed, Summons, Evidence. For uncertain service, the file shows 'Service between 5 Mar (earliest) and 20 Mar (latest): safe filing window 5 Apr to 5 May', or a red 'no safe filing date: partner decision needed'. Other banners: 'premature if filed before 5 Apr', 'window closes in 3 days', 'cheque presented after validity'. Batch actions: generate notices for files in 'Notice due' from the template, approve in bulk after spot-checking, export a print/post manifest. After filing: summons service attempts, s.143A order date and its due date, s.148 deposit dates. Every date also appears on /deadlines with its owner and verification status.

### What the system does

1. `cheque_files` table (one row per cheque, grouped by transaction/drawer) with every date. The existing `_cheque_bounce` logic is the per-row engine. Each computed date is a P13 deadline (ladder from creation, earliest candidate governs).
2. Notice text is a fixed, partner-approved firm template filled from row fields in code (amount demanded equals the cheque amount, 15 days from receipt, s.138/142 language), never AI-generated. Template edits need partner approval.
3. Service date resolution, deterministic:
   a. Actual delivery date from the tracking report or acknowledgement card, if present, is the service date.
   b. For a 'refused' or 'unclaimed / intimation delivered' return, the endorsement date on the article or tracking report (date of refusal, or of intimation for unclaimed) is the service date. It is entered or imported with its source and flagged 'deemed service (C.C. Alavi Haji; s.27 General Clauses Act): check'.
   c. If no endorsement or delivery date is available, the system computes earliest_service = dispatch date + minimum transit (firm setting, default 1 day) and latest_service = the date the returned envelope came back (or, if never returned, dispatch + the firm's outer bound, default 30 days, flagged).
4. Safe filing window (via limitation_service, P06): the cause of action arises the day after the 15-day pay period ends. Window start = latest_service + 15 days + 1 day (never premature under any plausible service date, per Yogendra Pratap Singh). Window end = one month from earliest_service + 15 days + 1 day (never time-barred under any plausible service date; s.142(1)(b)), with s.4 Limitation Act / court-closure rules and COVID exclusion applied by P06. With a known service date, earliest = latest and the window is the ordinary one.
5. Empty intersection (start > end): the file is flagged 'no safe filing date' and blocked from batch approval. The partner must record a decision. The options shown are factual: file on or after the start date with a s.142(1)(b) delay-condonation application, or obtain the endorsement date and recompute. The system never picks a date inside the risky range by itself.
6. P06's rule holds throughout: the docket shows the window end computed from earliest_service, never a later date.
7. Jurisdiction (s.142(2)) is chosen from the payee's bank branch in the row and the firm's court table; mismatches are flagged.
8. Post-filing: summons attempts are logged. s.143A interim compensation gives the 60-day payment date (plus the 30-day extension if ordered); failure flags a recovery step. s.148 deposit dates are tracked on appeal.
9. Bulk approval: the partner approves a batch, but every flagged file and every 10th file must be opened first.

### Where it is built

app/services/workflow_service.py `_cheque_bounce` (per-row engine, extended with the service-date bracket); limitation_service (P06) for window arithmetic and exclusions; deadline_service (P13); drafting_engine.render for the fixed template (no AI path); new app/services/cheque_service.py and app/routers/cheques.py; migration 015_cheque_files.sql (cheque_files, cheque_service_events with source and endorsement_date); frontend/src/app/cheques/page.tsx; export via drafting_engine.to_pdf/to_docx; CSV import and column mapping following review_service.

### Why current tools fail and this won't

We re-scope rather than claim the market is empty. Lender-side platforms (CredGenics, Legodesk and similar) already generate bulk s.138 notices from NBFC CSVs, track dispatch and delivery, and track cases after filing. We have not verified their internal date logic, so we don't claim they lack a premature/time-barred guard. Our pack is for the law firm those lenders instruct (and for MSME and individual clients who have no such platform). Its dates live in the same docket as the firm's other matters, with owners, backups, reminder ladders and verification (P13). It computes a bracketed safe filing window when the service date is uncertain, refusing to show a date later than the safe one (P06). It applies s.4/COVID exclusions and tracks s.143A and s.148 clocks, and it requires sampled partner approval before notices go out. It imports those platforms' exports instead of replacing them. Harvey, CoCounsel, Manupatra and SCC AI don't do s.138 workflow; Clio doesn't know NI Act timelines.

### Safeguards

Notices go to the drawer only after a lawyer's (batch) approval; nothing is sent automatically. Files with no safe filing date need a recorded partner decision. Drawer data is personal data under DPDP and stays under RLS, and the ledger needs no AI processing. The notice template is the firm's own, approved by a partner. Deemed-service dates carry their source (tracking report, article endorsement, or computed bracket) in the audit log.

### How the panel's objections were answered

Objection 1 (pay window counted from the return date): the service date is now the actual delivery date or, for refused/unclaimed, the postal endorsement date from the tracking report or article, recorded with its source (C.C. Alavi Haji; s.27 General Clauses Act). If neither is available, the system brackets service between dispatch + minimum transit and the return date, and shows only the safe filing window. It starts the day after the 15 days end for the latest plausible service date and ends one month after the cause of action for the earliest plausible service date, so no displayed date is premature (Yogendra Pratap Singh) or time-barred. An empty intersection is flagged and blocked pending a partner's decision. Tests: test_endorsement_vs_return_date (return and endorsement dates differ), test_bracketed_window, test_empty_window_flag, and the property test test_never_later_than_safe. Objection 2 (wrong incumbent claim): we name CredGenics and Legodesk, accept that they already do bulk notices, dispatch tracking and post-filing tracking for lenders, and take option (b). P27 is re-scoped as an internal pack on top of P13/P06 for law firms (and their non-NBFC clients), importing those platforms' exports. We claim as deltas only what this pack does that we have built and tested; we don't assert, unverified, what those platforms lack.

### Acceptance tests

- Existing tests/test_workflows.py cheque tests keep passing.
- tests/test_cheques.py::test_bulk_import_1000: 1,000 synthetic rows import and compute in under 10 s with zero AI calls.
- test_endorsement_vs_return_date: notice dispatched 2026-03-02, endorsed 'refused' 2026-03-05, envelope returned 2026-03-20. With the endorsement date entered, the pay window runs from 5 Mar (cause of action 21 Mar, window to 20 Apr per P06 arithmetic), not from 20 Mar.
- test_bracketed_window: same dispatch and return dates with no endorsement give earliest 2026-03-03 and latest 2026-03-20; window start = 20 Mar + 16 days, window end = one month after (3 Mar + 16 days); every date shown is inside the intersection.
- test_empty_window_flag: a case where latest_service + 16 days falls after one month from earliest_service + 16 days is flagged 'no safe filing date', excluded from batch approval, and shows no suggested filing date until a partner records a decision.
- test_never_later_than_safe: property test over random dispatch, endorsement and return dates: the displayed window end is always <= the end computed from the true (earliest) service date, and the start is always >= the start from the latest service date.
- test_premature_guard: with a known service date, a complaint dated on day 15 of the pay window is flagged premature, day 16 passes, and a date after one month is flagged time-barred.
- test_parallel_clocks: three cheques from one drawer with different memo dates produce three independent windows.
- test_notice_amount_equals_cheque: the generated notice text contains the row's amount in Indian grouping and no other demanded sum; property test across random amounts.
- test_s143a: an interim compensation order dated 2026-10-01 yields a payment due date 60 days later, and 90 when an extension is recorded.
- test_deadlines_flow_to_docket: each computed date creates a P13 deadline with the rule id and inputs, and the ladder fires while it is unverified.
- test_batch_approval_gate: batch approval is refused until every flagged file and every 10th file has been opened.
- test_csv_mapper: a sample export with differently named columns (fixture modelled on a generic collection-platform export) maps to cheque_files without loss.

### Reviewers' minor notes

- Notices are commonly sent by both RPAD and Speed Post, sometimes with email or WhatsApp copies. Let service events from multiple channels feed the bracket, with the earliest proved service governing the end of the window.
- Allow interest and costs to be stated separately from the cheque amount where the firm's template does so (Suman Sethi), as long as the cheque amount is distinctly demanded. The property test should check that the cheque amount is stated distinctly, not that no other sum appears.
- A s.138 notice goes out on an advocate's letterhead under their signature. Sampling every 10th file is a policy choice, but the fields that void a notice (drawer name, cheque number, amount, bank) should be checked for every file against the return memo image (OCR match or 100% field confirmation). Approving on a 10% sample of client-supplied CSV data is weak diligence if challenged.
- The notice should be signed by a named enrolled advocate per batch, recorded in the audit row. The BCI rule against acting on instructions of anyone but the client applies when a collection platform's export, not the lender itself, is the source.
- limitation_service (P06) and deadline_service (P13) don't exist yet. Sequence P27 after them.
- A default outer bound of 30 days for never-returned notices almost always produces an empty or one-day window. Make the flag message explain that obtaining the tracking or endorsement date is the real fix.

