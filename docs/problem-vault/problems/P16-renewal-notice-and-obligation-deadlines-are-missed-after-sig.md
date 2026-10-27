# P16. Renewal, notice and obligation deadlines are missed after signing because nobody tracks them

**Severity:** critical · **Size:** big · **Region:** Global (UK data; same pattern assumed for India)

**Who has it:** In-house legal and procurement teams, SMEs, landlords and tenants, and their law firms

## What goes wrong

After signature the contract sits in a drive or email thread. Auto-renewal notice windows, lock-ins, price-escalation dates, SLA credits, rent escalation in leave and licence deals and indemnity notice periods sit in clause text nobody re-reads. Companies renew contracts they meant to exit, miss termination windows, fail to claim credits or breach their own obligations. Teams track dates with spreadsheets, phone reminders and Post-it notes.

## Evidence of scale

- ContractWorks survey (100 respondents, mostly UK in-house): almost half say their companies miss automatic renewals, about 2.5 a year, average contract value about GBP 29,807. ([source](https://legalfutures.co.uk/latest-news/half-of-in-house-lawyers-say-companies-miss-contract-renewals))
- ContractWorks (2021): 15% track milestones on Post-it notes, 12% on their hand, 34% phone reminders, 20% paper diary; 71% say their business doesn't focus enough on post-signature obligations. ([source](https://www.artificiallawyer.com/2021/05/06/15-of-inhousers-use-post-it-notes-to-track-contract-milestones/))
- Superscript research on UK small businesses: 37% lost money through an auto-renewal they weren't aware of; 60% say auto-renewals are an issue. ([source](https://smallbusiness.co.uk/small-firms-lost-billions-of-pounds-on-unexpected-contract-renewals-in-2020-2552976/))
- WorldCC (Aug 2025): the average business loses 8.6% of annual value to poor contract management; data sits in 24 systems on average; almost 90% of business users find contracts hard or impossible to understand; only 39% think contracts deliver the desired outcome. ([source](https://info.worldcc.com/contract-management-aug-2025))
- Deloitte (1,200+ organisations): average contract value erosion 8.6%, worst performers over 20%; contract data in 24 systems on average. ([source](https://www.deloitte.com/us/en/services/tax/articles/contract-management-lifecycle-insights.html))

## Why current tools don't solve it

CLM date fields only cover contracts someone entered, missing legacy paper, scans, side letters and amendments. Harvey, CoCounsel and Lexis+ AI answer questions on a document but don't turn signed text into live dated obligations with owners and reminders. Clio is matter- and time-centred. No tool reads an Indian scanned stamp-paper lease or vendor contract, computes the notice deadline in code from the clause, and sends a WhatsApp or email alert quoting it.

## Panel verdict

**Status:** solved (round 3)

**Effort:** L

### What software can fix

Turning signed contract text, including scanned stamp-paper leases, side letters and amendments, into dated obligations with an owner and reminders. Every obligation is a window [open, close], and three conditions hold for each. (a) It quotes its clause, and the quote is verified against the document. (b) Both bounds are computed in code under one versioned rule table, from numbers the code reads in that quote. Where the wording allows more than one reading, every plausible reading of each bound is computed. The safe window takes the LATEST reading of the opening bound and the EARLIEST reading of the closing bound. (c) Nothing is scheduled as trusted until a lawyer confirms it. Covers auto-renewal and non-renewal notice windows, two-sided option, renewal and put/call windows ('not earlier than … and not later than …', 'within N days after <anniversary>'), termination notice, lock-in end, rent and price escalation, expiry, SLA credit claim windows, warranty periods, indemnity claim notice periods, payment milestones and deposit refunds.

### What it can't fix

Contracts nobody has given us: P42 widens coverage, but we can't find a contract that was never stored. Deciding whether to renew, exercise or exit is a business decision. Whether notice was validly served (mode, address, proof) depends on facts outside the document; we show the notice clause's service wording and leave service to the lawyer. Event-triggered clauses ('within 30 days of becoming aware of a claim') can be scheduled only once someone enters the event date. We don't decide which reading a court would adopt. We schedule the narrowest safe window and show the other readings, and the lawyer may choose a different reading with a recorded reason. Whether a premature or late exercise can be cured, waived or estopped is a legal question for the lawyer. OCR quality limits scanned vernacular annexures.

### What the user sees

An Obligations calendar at /obligations, plus a section on each contract page. Each row is one of four kinds: deadline (close bound only), window (both bounds), from-date (open bound only, e.g. 'may terminate after the lock-in') or event-pending.

Deadline example: 'Non-renewal notice: send by 30 Dec 2026 (latest safe day). Basis: cl. 14.2 "not less than ninety (90) days' written notice prior to the expiry of the Term"; Term ends 31 Mar 2027 (cl. 3.1 "three years commencing on 1st April 2024", rule TERM-INCL). Readings for the closing bound: clear days gives 30 Dec 2026, plain subtraction gives 31 Dec 2026. Earliest used.'

Window example: 'Renewal option: act between 1 Oct 2026 and 30 Dec 2026 (safe window). Do NOT send before 1 Oct 2026: a notice sent before the window opens may be invalid. Basis: cl. 15.1 "not earlier than six (6) months and not later than three (3) months prior to the expiry of the Term". Opening-bound readings: 30 Sep 2026 (plain) and 1 Oct 2026 (strict), latest used. Closing-bound readings: 31 Dec 2026 (plain) and 30 Dec 2026 (clear), earliest used.' For 'within thirty (30) days after the fifth anniversary of the Commencement Date' (1 Apr 2024), the row reads 'act between 2 Apr 2029 and 30 Apr 2029; the anniversary day itself is outside the window.' When the safe window is empty, or shorter than the org's minimum (default 3 business days), the row is red, reads 'Window conflict: needs legal', and carries no business reminders. Unconfirmed items sit in legal's 'To confirm' tray with the quote highlighted in the document viewer. There the lawyer accepts the safe window or picks another reading for either bound, with a mandatory reason. The reason and the rule are printed on the row.

Reminders: before the window opens, owners get only 'Heads-up: window opens 1 Oct 2026; do not send before then'. This message has no 'Handled' button, only 'Noted'. The first 'Act now' reminder goes out on the opening day. Further reminders count back from the close (60, 30, 14, 7 and 1 days, those that fall inside the window), and a short window gets reminders on the open day, its midpoint, close-1 and the close. Action reminders carry 'Handled', 'Decided not to exercise' and 'Escalate to legal'. If someone clicks 'Handled' before the open date, they get the warning 'The window opens 1 Oct 2026. A notice sent earlier may be invalid', and the click goes to legal for review instead of closing the item. Unacknowledged items escalate to legal at close-7. The ICS feed shows two events per window, 'Window opens' and 'Last safe day'. A row superseded by an amendment is struck through with 'superseded by Amendment No. 2, cl. 1'.

### What the system does

1. Extraction: a fixed 'obligations' preset in review_service makes one PII-masked call per document. It returns candidate obligations: type, verbatim quote, and the anchor(s) the bounds depend on (start, expiry, anniversary, rent start or an event). Quotes failing evidence_service.quote_found are discarded and counted in discarded_unverified.

2. Parsing, in services/obligation_dates.py, from the verified quote only. Code splits the quote into bound phrases. Opening markers: 'not earlier than', 'not before', 'no earlier than', 'after', 'from', 'on or after', 'at any time after'. Closing markers: 'not later than', 'not less than … before', 'at least … prior to', 'within', 'by', 'before', 'prior to', 'on or before'. A phrase like 'within N days after E' produces both bounds. Durations are read in words and digits, which must agree. Indian date formats are DD/MM. Business or calendar days are detected. If code can't assign every duration in the quote to a bound, if the model's structured values disagree with what code parsed, or if code can't parse the quote at all, the item is needs_lawyer and has no dates.

3. One rule table, data/obligation_rules/v1.json, versioned. Start rules TERM-INCL, TERM-S9 and TERM-AMBIG are unchanged from round 2.
- Closing-bound rules (unchanged): NOTICE-CLEAR (anchor - N - 1), NOTICE-PLAIN (anchor - N, always computed with NOTICE-CLEAR), WITHIN-S9 (E + N) and WITHIN-INCL (E + N - 1).
- New opening-bound rules: OPEN-PLAIN, for 'not earlier than N before A', gives A - N. OPEN-STRICT reads 'earlier than' as excluding the boundary day and gives A - N + 1; both are always computed. AFTER-S9, for 'after E' / 'within N days after E', excludes E, so the window opens E + 1. AFTER-INCL (opens on E) is computed as the alternative. ANNIV gives the Nth anniversary of the named date, with 29 Feb clamped to 28 Feb and the clamp recorded.
- Month arithmetic uses workflow_service.add_months with explicit month-end clamping. Business days use the shared holiday_calendar (P15).

4. Conservative selection, now two-sided. For an act we must do: safe_open = max over all opening-bound readings, across every expiry or anchor reading as well; safe_close = min over all closing-bound readings, across every anchor reading. A deadline-only obligation has safe_open = the document's effective date. A from-date-only obligation has safe_close = null. If safe_open > safe_close, or the window is shorter than the org's minimum, the status is needs_lawyer and no business reminder is created. For an act the other side owes us (deposit refund), we remind at the earliest close reading as a follow-up and show the latest as the day it falls overdue. Any difference between readings flags the row 'ambiguous'. A lawyer override that moves the open earlier or the close later needs a reason in override_reason, plus a second lawyer where the org has one. An override that narrows the window needs only a reason.

5. Migration 015_contract_obligations.sql. contract_obligations has: org_id, document_id, contract_id, type, window_kind (deadline|window|from_date|event_pending), quote, quote_verified, parsed jsonb, open_readings jsonb, close_readings jsonb, rule_ids, rule_table_version, window_open, window_close, chosen_open_reading, chosen_close_reading, override_reason, owner_user_id, status (candidate|confirmed|needs_lawyer|superseded|done|pending_legal_review), confirmed_by, confirmed_at, superseded_by. It has CHECK (status <> 'confirmed' OR window_open IS NULL OR window_close IS NULL OR window_open <= window_close). obligation_reminders has: obligation_id, kind (heads_up|act_now|escalation), offset_days, channel, sent_at, unique(obligation_id, kind, offset_days, channel). A trigger stamps confirmation, and confirmation lapses if the quote, parsed values, either set of readings, either bound, or the rule version changes. Each obligation also shows the P42 execution_status of its document. Business-owner reminders need execution_status = 'executed', or a lawyer's 'treat as binding' flag with a reason.

6. Worker cron task_obligation_reminders (7:00 IST, next to task_hearing_reminders), confirmed items only. A pure function plan_reminders(obligation, today) returns the messages due. It never returns an act_now message when today < window_open: before the open it returns heads_up only, at the fixed offsets open-14 and open-1. act_now starts on window_open, and the close-based offsets are filtered to dates on or after window_open. Sends go through whatsapp_service.send_template (an internal staff template) or email via n8n, and every send is recorded.

7. Acknowledgement endpoint: 'Handled' with now < window_open is refused as a completion. It sets pending_legal_review, notifies legal, and is audit-logged.

8. Amendments: when P42 links an amendment, extraction reruns. Items whose clause is expressly substituted by the amendment's verified quote are superseded only after a lawyer confirms.

9. ICS feed: a per-user signed-token URL carrying only titles and the two bound dates.

### Where it is built

app/services/review_service.py (preset, masked per-document call), app/services/evidence_service.quote_found, app/services/workflow_service.add_months and its Result.deadline pattern, app/worker.py cron and the send_hearing_reminders pattern, app/services/whatsapp_service.send_template, app/services/n8n_service.py, app/services/ocr_service.py, holiday_calendar from P15 (created here first if 015 ships earlier), and P42 execution_status. New files: data/obligation_rules/v1.json, supabase/migrations/015_contract_obligations.sql, app/services/obligation_service.py, app/services/obligation_dates.py (bound parser, readings, safe-window selection), app/services/obligation_reminders.py (pure plan_reminders), app/routers/obligations.py, frontend/src/app/obligations/page.tsx, tests/test_obligation_dates.py, tests/test_obligation_windows.py, tests/test_obligation_reminders.py, evals/obligations/ (30 labelled Indian contracts, including scanned leave and licence agreements and SHAs with put/call windows).

### Why current tools fail and this won't

CLM date fields depend on someone typing a single 'notice date' at signature. That models only the deadline and misses legacy scans, side letters and two-sided windows. A premature option notice is as fatal as a late one, and none of them warn against it. Where a CLM computes dates, it uses one unexplained convention. Harvey and CoCounsel answer questions about a document but don't keep live dated obligations with owners, and an LLM's date arithmetic is neither reproducible nor explained. Clio is organised around matters and time, not contract obligations. We model every obligation as a window and compute both bounds from the verified clause under a named, versioned rule. We shrink the window from both ends under ambiguity (latest open, earliest close), refuse to schedule an empty window, and make it impossible in code for an 'act now' reminder to fire before the window opens. A lawyer sees every reading before anything is trusted, and reminders run on the proven hearing-reminder cron and WhatsApp pipeline.

### Safeguards

Text is PII-masked before Claude (invariant 1). Both bounds are computed by code from verified quotes under a named, versioned rule; the model's dates are never used. Ambiguity shrinks the window from both ends. An empty or too-narrow window goes to a lawyer and is never scheduled. A pure, tested reminder planner guarantees no 'act now' before the window opens, and early 'Handled' clicks are routed to legal. Widening a window (earlier open or later close) needs a stated reason and, where available, a second lawyer. Reminders go to business users only after a lawyer confirms, and only for executed documents or ones a lawyer has marked binding. Reminders go to internal staff only and carry the contract title, the bounds and the clause quote. The ICS feed carries the minimum. Staff WhatsApp needs opt-in (DPDP consent and purpose); email is the default. Every confirmation, override, early acknowledgement and send is audit-logged. The service role is used only in the cron, scoped per org like hearing reminders, and is documented as an invariant-2 server-side job.

### How the panel's objections were answered

Objection: conservative selection handled only one side of the window, so 'act early to be safe' could cause a premature, void exercise. Fixed as the reviewer asked.
(1) Every obligation is now a window [window_open, window_close] with a window_kind of deadline, window, from_date or event_pending. Opening-bound rules are added: OPEN-PLAIN and OPEN-STRICT for 'not earlier than N before', AFTER-S9 and AFTER-INCL for 'after E' and 'within N days after E', and ANNIV for anniversaries.
(2) Selection is two-sided: the opening bound takes the LATEST reading across all rules and anchor readings, and the closing bound takes the EARIEST.
(3) If the safe window is empty (open > close) or narrower than the org minimum, the item is needs_lawyer and has no business reminders. A DB CHECK forbids confirming an inverted window.
(4) The user sees 'act between X and Y (safe window)' with 'Do NOT send before X'.
(5) Reminders come from a pure plan_reminders function that cannot emit an act_now message before window_open. Before the open it sends only a 'window opens on X, do not send before' heads-up with no 'Handled' button. A 'Handled' click before X is refused as completion and routed to legal.
(6) Lawyer overrides that widen the window at either end need a reason and a second lawyer.
Tests added: the six-months/three-months fixture (open 2026-10-01 from the latest reading, close 2026-12-30 from the earliest), the bare-'from' variant (open 2026-10-02), the 'within 30 days after the fifth anniversary' fixture (open 2029-04-02, close 2029-04-30, plus a property test that the open is always after the anniversary), the empty-window case, a day-by-day frozen-clock reminder test proving no act_now before the open, and an eval hard failure for any open earlier than the hand-computed earliest safe day.

### Acceptance tests

- tests/test_obligation_windows.py: cl. 'not earlier than six (6) months and not later than three (3) months prior to the expiry of the Term', with Term 'three years commencing on 1st April 2024' (expiry 2027-03-31, TERM-INCL), gives open_readings {OPEN-PLAIN 2026-09-30, OPEN-STRICT 2026-10-01}, close_readings {NOTICE-PLAIN 2026-12-31, NOTICE-CLEAR 2026-12-30}, window_open 2026-10-01 (latest) and window_close 2026-12-30 (earliest), with ambiguous=true.
- The same clause with bare 'three years from 1st April 2024' (expiry readings 2027-03-31 and 2027-04-01) gives window_open 2026-10-02, the latest over both expiries and both open rules, and window_close 2026-12-30, the earliest over all.
- 'within thirty (30) days after the fifth anniversary of the Commencement Date' with commencement 2024-04-01: the anniversary is 2029-04-01, window_open is 2029-04-02 (AFTER-S9 beats AFTER-INCL), window_close is 2029-04-30 (WITHIN-INCL beats WITHIN-S9 2029-05-01). Property test: for every generated anniversary date and N, window_open > anniversary.
- Empty window: 'not earlier than two (2) months and not later than three (3) months prior to expiry' gives open > close, so status is needs_lawyer, the reminder plan is empty for business owners, and legal is notified.
- A window narrower than the org minimum (e.g. open 30 Dec, close 30 Dec) is needs_lawyer.
- tests/test_obligation_reminders.py, plan_reminders over a frozen clock from 2026-08-01 to 2026-12-31 for the six-months/three-months window: no act_now message on any day before 2026-10-01; heads_up only on 2026-09-17 and 2026-09-30; the first act_now on 2026-10-01; close-based reminders only on or after 2026-10-01; exactly one message per (kind, offset, channel) over two consecutive runs.
- 'Handled' posted on 2026-09-20 for that window doesn't set done. It sets pending_legal_review, notifies legal and writes an audit row.
- Lawyer override moving window_open earlier to 2026-09-30 without a reason is refused; with a reason in a two-lawyer org it needs a second lawyer. Narrowing the window needs a reason only.
- DB test: confirming a row with window_open > window_close violates the CHECK constraint.
- Changing open_readings, close_readings, rule_table_version or the quote clears confirmed_by/confirmed_at (trigger test). A user in another org can't read the row (RLS).
- A confirmed obligation on a document whose P42 execution_status is partially_executed sends no business-owner reminder until a lawyer sets 'treat as binding' with a reason.
- Regression tests from round 2 still pass: 'commencing on' deadline 2026-12-30, 'with effect from' TERM-INCL only, 'commencing from' TERM-AMBIG, plain 'ninety (90) days prior to' schedules 2026-12-30, 'within thirty (30) days from the date of invoice dated 1 Jan 2026' closes 2026-01-30, 'eleven (11) months commencing 1st January 2025' expires 2025-11-30, '1/4/2024' parses as 1 April, '04/05/24' gives needs_lawyer, 'sixty (90) days' gives needs_lawyer, model 60 vs quote ninety gives needs_lawyer, an unverified quote is dropped and counted, month-end clamping is recorded.
- A quote containing a duration that code can't assign to either bound gives needs_lawyer with no dates.
- Amendment fixture 'Clause 15.1 shall be substituted with: ... not earlier than four (4) months ...' supersedes the old window only after confirmation; the new one is recomputed under the same rule table.
- The ICS feed has 'Window opens' and 'Last safe day' events, no clause text, and rejects an invalid token.
- evals/obligations: recall of hand-labelled date obligations >= 0.85. Hard failures: any scheduled window_close later than the lawyer's hand-computed latest safe day, and any window_open earlier than the lawyer's hand-computed earliest safe day.

### Reviewers' minor notes

- The label 'send by 30 Dec 2026' is wrong whenever the notices clause deems service on receipt or N days after dispatch, for example 'deemed served 5 days after posting by RPAD'. That clause is in the document, so code can read it. Either label the close bound 'must be served by' or subtract the longest deemed-service period from the notices clause to give a dispatch date. Do the same check at the opening bound: a notice posted before the window but deemed served inside it.
- For an act the other side owes us, the overdue day should be the latest reading, which the proposal already says. Make sure escalation timing uses that reading and not the reminder reading.
- Migration 015 assumes the P15 holiday_calendar exists. Make the build order explicit.
- For deadline-only notices, safe_open is the effective date. Some termination notices have their own premature-notice risk, for example 'notice not earlier than the lock-in end'. The parser already handles a two-sided quote, but add an eval case where the opening bound sits in a different clause from the closing one, so it isn't silently dropped.
- WhatsApp reminders to business staff carry clause quotes from confidential contracts. Keep email as the default, as stated, and drop the clause quote from WhatsApp bodies (title and dates only), as is done for ICS.
- Typo in answers_to_objections ('EARIEST').
- It depends on P15's holiday_calendar and P42's execution_status. Ship a stub execution_status ('unknown', with lawyer 'treat as binding') if P42 lands later, so obligations aren't silently blocked.
- Migration 015 numbering must be coordinated with the other proposals.
- Staff WhatsApp reminders must go through P33's outbound_policy reason (e) with an 'internal' audience template.

