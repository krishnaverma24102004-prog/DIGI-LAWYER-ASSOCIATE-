# P06. Indian limitation and statutory deadlines are unforgiving: certified-copy delays, hand-computed exclusions, forfeited written statements and courts refusing condonation

**Severity:** critical · **Size:** big · **Region:** India

**Who has it:** Litigators who file appeals and revisions, government panel counsel and PSU legal departments, AoRs, defendants in commercial suits, solo district-court advocates, and clients who lose their remedy

## What goes wrong

Some Indian deadlines destroy a right outright. A written statement in a commercial suit not filed within 120 days of summons is forfeited, and since A.K. Ghosh (July 2026) the same limit binds a plaintiff's reply to a counter-claim. An appeal, revision or SLP needs a certified copy of the impugned order: the advocate applies, waits, has to remember to collect it, and then works out the excluded period under s.12 Limitation Act along with ss.4 and 14 exclusions, COVID-era windows and special-statute periods. Juniors compute this by hand in diaries. Whether a given copy even counts for limitation can itself be litigated. Meanwhile the Supreme Court has hardened on s.5: administrative lethargy, including the State's, is not sufficient cause, so a missed date can end the client's remedy.

## Evidence of scale

- Karnataka HC (June 2021): waiting for certified copies may be one reason appeals against acquittal are filed late; it directed the State to start forming its opinion from depositions and an ordinary copy of the judgment. ([source](https://barandbench.com/news/litigation/scst-act-waiting-for-certified-copies-reason-for-delay-filing-appeals-acquittal-karnataka-high-court))
- Shivamma v Karnataka Housing Board (2025 INSC 1104): the SC set aside an HC order condoning a 3,966-day delay; administrative lethargy can never be sufficient cause. ([source](https://www.verdictum.in/court-updates/supreme-court/shivamma-v-karnataka-housing-board-2025-insc-1104-state-authorities-condonation-of-delay-1591239))
- Shivamma: bureaucratic lethargy cannot be routinely excused under s.5 Limitation Act. ([source](https://theindianlawyer.in/supreme-court-re-defines-standards-for-condonation-of-delay-under-the-limitation-act/))
- On 9 Feb 2026 the SC refused to condone Odisha's delay and dismissed its SLP as time-barred, calling the State 'utterly lethargic, tardy and indolent'. ([source](https://www.scconline.com/blog/post/2026/02/20/sc-rejects-condonation-of-delay-in-government-litigation/))
- SBI v India Power Corporation (2024): NCLAT held a free copy of an NCLT order was not a certified copy for limitation and threw out an appeal; the SC reversed, condoned a 3-day delay and restored it. ([source](https://www.scconline.com/blog/?p=332718))
- SCG Contracts (2019): filing the written statement within 120 days of summons in commercial suits is mandatory; the right is forfeited and the court has no power to take it on record. ([source](https://www.khaitanco.com/thought-leadership/supreme-court-filing-of-written-statement-within-120-days-from-issuance-of-summons-is-mandatory))
- A.K. Ghosh & Co. v. Biman Bose (2026 INSC 684, 14 July 2026): the 120-day outer limit under Order VIII Rule 1 CPC also binds a plaintiff's reply to a counter-claim; a reply filed after 238 days was rightly refused. ([source](https://www.verdictum.in/supreme-court/ak-ghosh-company-and-others-v-biman-bose-and-others-2026-insc-684-1617737))

## Why current tools don't solve it

No Indian practice tool (Manupatra, SCC Online, LegitQuest, eCourts app, LawStar) computes limitation from the Schedule to the Limitation Act with s.4/12/14 exclusions (copy applied, ready, delivered), COVID windows and special-statute periods per forum. They retrieve judgments about limitation but don't calculate a matter's date, chase copy-section status or alert before a window closes. Clio-style calendaring follows US rules; Harvey and CoCounsel don't model Indian procedure.

## Panel verdict

**Status:** solved (round 1)

**Effort:** L

### What software can fix

Computing a matter's limitation or statutory date correctly and showing how: the Schedule article or special-statute period, s.12 exclusions (day of judgment, time from copy application to copy ready, decree copy), s.4 (court closed on the last day), s.14 (bona fide proceedings in a wrong forum), the Supreme Court's COVID exclusion (15.03.2020 to 28.02.2022), and hard non-condonable outer limits (commercial written statement 120 days, s.34 Arbitration Act 3 months + 30 days). Also chasing the certified copy and telling the lawyer the date is provisional until the copy-ready date is known.

### What it can't fix

Whether a court will condone delay under s.5, whether a given free or ordinary copy counts as a certified copy (SBI v India Power is itself litigation), how slow a copying section is, and novel questions of which article applies. We cannot pull copy-section status from court systems that have no API; the copy-ready date is entered by the clerk.

### What the user sees

A Limitation calculator on each matter and at /workflows/limitation: pick the remedy (appeal, revision, SLP, s.34, written statement, etc.) and forum; enter date of judgment/service, copy applied, copy ready (notified), copy delivered, and any s.14 period. The result is a dated worked computation: start date, period, each exclusion line with its section and days, the COVID line if relevant, the s.4 shift with the holiday from the loaded court calendar, the final date, and a red line if the limit cannot be extended. If the copy-ready date is missing it shows two dates: 'if the copy is ready today' and 'without copy exclusion (safe date)', and the docket uses the safe date. A Copy tracker lists every pending certified-copy application with days since applied and a 'check the copy section' task every 3 working days.

### What the system does

1. New deterministic module app/services/limitation_service.py with a rule registry as data (app/data/limitation_rules.json): rule_id, remedy, forum, period (days or months), start event, which exclusions apply, whether s.5 applies or the statute excludes it (s.29(2)), outer limit, statutory source, status draft/verified, verified_by (two advocates). Only `verified` rules are offered; draft rules are invisible outside an admin view.
2. Computation follows the statute: day of the start event excluded (s.12(1)); for appeals/revisions/reviews the time from the copy application to the date the copy was ready is excluded (s.12(2)), but not time before applying and not if applied after the period expired; decree copy time likewise (s.12(3)). COVID: if the period would have expired between 15.03.2020 and 28.02.2022, the date becomes 90 days from 01.03.2022 or the balance if longer; otherwise the window is excluded. s.4: if the last day of the prescribed period is a day the court is closed (from `court_calendars`), it moves to the reopening day; s.4 is not applied to a condonable extension window (e.g. the 30 days under s.34(3)).
3. Conservatism rule, in code: when an input or calendar is missing, the engine uses the assumption that gives the earlier date and says so; it never shows a later date than the safe one.
4. `court_calendars` table (court, date, closed reason, source URL, entered_by, verified_by) loaded from each court's published annual calendar; a court with no loaded calendar gets no s.4 shift and a warning.
5. Results write deadlines (P13) with rule_id, version and inputs, so a rule correction re-computes every affected deadline and notifies its owner.
6. Every statutory reference in the basis text is run through citation_service (status must be `statute`).

### Where it is built

New app/services/limitation_service.py and app/data/limitation_rules.json; reuse add_months and Result.deadline from app/services/workflow_service.py and register a `limitation` Pack there; citation_service.py for basis checking; migration 014_deadlines.sql adds court_calendars and copy_applications (applied_on, ready_on, delivered_on, court, matter); frontend/src/app/workflows/page.tsx gets the calculator, cases page a Copy tracker tab.

### Why current tools fail and this won't

Manupatra, SCC Online and LegitQuest retrieve judgments on limitation but compute nothing; the eCourts app and LawStar have no limitation model; Clio-style calendaring follows US rules; Harvey and CoCounsel will produce a plausible date in prose, which is exactly what must not be trusted. Ours is a rule table signed off by two advocates, computed in code, shown line by line, conservative when inputs are missing, and re-computed when a rule changes.

### Safeguards

Results are labelled 'computation for a lawyer to check', not advice; no AI is involved in the date. Rules activate only after two advocates sign off (recorded). Calendar entries carry their source URL. No client data leaves the server. Deadlines inherit P13's escalation.

### Acceptance tests

- tests/test_limitation.py golden table: tests/fixtures/limitation_cases.json with at least 60 worked examples prepared by our litigation team (and cross-checked by a second advocate), covering month-end and leap-year arithmetic, s.12(2) copy exclusion, copy applied after expiry (no exclusion), s.4 with a holiday on the last day, s.4 not applied to the s.34 grace window, COVID inside and outside the window, commercial WS day 120 vs day 121, ordinary WS 90 days; every example must match exactly.
- Property tests (hypothesis): the final date is never earlier than the unexcluded date when exclusions are valid; adding copy-ready days never moves the date by more than those days; a missing copy-ready date always yields the safe (earlier) date.
- test_unverified_rule_hidden: a rule with status draft cannot be evaluated through the API (422).
- test_rule_change_recomputes: bumping a rule's version re-computes linked deadlines and creates a notification for each owner.
- test_basis_citations: every basis string in the registry passes citation_service with status statute.
- test_calendar_missing_warns: a court with no calendar rows returns the unshifted date plus a warning.

### Reviewers' minor notes

- When s.4 shifts a date because the court is closed, the shift should be shown as a separate line. Where the shift is legally uncertain (special statutes reached through s.10 General Clauses Act, hard outer limits like the commercial WS day 120), the docket should keep the unshifted date as the safe date and treat the shift as informational.
- Ad hoc closures (sudden holidays, local declarations) are frequent. Let a clerk add a closure with its source mid-year, and re-compute the affected deadlines.
- The 60 golden cases depend on advocates who are not yet on the team. Name them and record their sign-off in the repo before the rules go live.
- Say whose advocates sign off the rule registry (the vendor's or each firm's). Let each firm see the sign-off and add a firm-level confirmation, so the vendor's rule table is not presented as advice to the firm.
- Apply s.4 Limitation Act and s.10 General Clauses Act only where the special statute allows them, and record which one applies in each rule (s.29(2)).
- The COVID exclusion lines matter little by 2026. Keep them, but show the SC order reference as a statute or judgment that passes citation_service, not as free text.
- The property test 'adding copy-ready days never moves the date by more than those days' is false once s.4 runs: one extra excluded day can land the date on a court holiday and shift it by several days. Assert it on the pre-s.4 date, or restate it as 'by at most those days plus the closure run'.
- The 60 golden examples need a named advocate and a second checker who actually exist. Record their sign-off in the repo as for P22's correspondence file.
- Say whether the COVID exclusion is applied to condonable outer limits (the SC order of 10.01.2022 covers them) and test it for s.34(3).

