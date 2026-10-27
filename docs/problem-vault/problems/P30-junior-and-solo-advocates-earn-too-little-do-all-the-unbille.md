# P30. Junior and solo advocates earn too little, do all the unbilled admin themselves, and can't afford tools priced in dollars per seat

**Severity:** high · **Size:** big · **Region:** India and Global

**Who has it:** Junior advocates (0-5 years), solo practitioners, senior advocates and small chambers relying on juniors; about 20 lakh enrolled advocates in India

## What goes wrong

Juniors do the nightly cause-list checks, copy-section and filing queues, proxy appearances, first drafts and client follow-ups, often for under Rs 10,000-20,000 a month. Solos do their own typing, filing, client calls and collections, so most of their day goes unbilled. Bar Councils and High Courts push minimum stipends, raising chambers' costs without making routine work faster. Practice-management and legal AI tools are priced in dollars per user, a large share of a junior's income, so those who most need automation are priced out.

## Evidence of scale

- Vidhi survey (about 2,800 advocates, 8 HCs): 40-49% at Allahabad, Bombay, Kerala, Madras and Patna put first-two-years income at Rs 5,000-20,000; in Calcutta and Gujarat most put it at Rs 20,000-40,000. ([source](https://www.barandbench.com/amp/story/columns/perception-of-corruption-in-higher-judiciary-average-monthly-income-of-lawyers-and-more-vidhi-survey-of-high-court-advocates))
- Vidhi: over 40% chose the Rs 2,000-5,000 a month bracket in later surveys; 50% in Calcutta and Gujarat earned under Rs 10,000. ([source](https://barandbench.com/columns/financial-well-being-of-advocates-is-not-all-black-and-white))
- Vidhi survey cited in Delhi HC: over 79% of advocates with under two years' practice across 7 HCs earn under Rs 10,000 a month. ([source](https://lawbeat.in/news-updates/seniors-law-profession-ensure-stipend-paid-juniors-enough-delhi-high-court))
- BCI (15 Oct 2024) recommends Rs 20,000 urban / Rs 15,000 rural minimum stipend for three years; not mandatory. ([source](https://www.scconline.com/blog/post/2024/10/16/bci-issues-guidelines-to-pay-minimum-stipend-to-junior-advocates/))
- BCI recommended stipends are advisory, not binding. ([source](https://law.careers360.com/articles/early-career-struggles-in-legal-profession-bci-recommends-indian-rupee-20000-minimum-stipend-for-junior-advocates))
- MP HC ordered the State Bar Council to frame stipend guidelines (Vipin Pandey v Rani Durgavati University). ([source](https://www.barandbench.com/news/litigation/juniors-lawyers-must-be-paid-stipend-madhya-pradesh-high-court-orders-state-bar-council-to-frame-guidelines))
- Delhi HC asked seniors to pay juniors good stipends (Pankaj Kumar v Bar Council of Delhi, Sept 2022). ([source](https://www.barandbench.com/news/delhi-high-court-appeals-senior-lawyers-pay-good-stipend-juniors))
- Clio 2025: utilization 27% for solos, 32% for small firms, about 50% for mid-sized; solos lag in AI adoption, mostly experimenting with ChatGPT. ([source](https://www.canadianlawyermag.com/news/general/solos-and-small-firms-lag-with-ai-adoption-clio-report/392441))
- About 20 lakh (2.01 million) registered advocates in India (Ministry of Law and Justice reply). ([source](https://lawinsider.in/report/what-is-the-total-number-of-advocates-in-india-today))

## Why current tools don't solve it

Clio, CoCounsel and Harvey charge USD per user for US billing rates and BigLaw research and drafting, not an Indian junior's clerical and court-logistics work. Indian tools are mostly diaries and trackers. No product priced per matter or per minute in INR automates the whole unbilled day: intake, cause list, proxy briefs, copy-section follow-up, client updates, fee reminders and first drafts.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Taking the unbilled clerical day off juniors and solos and making the rest of their work visible and paid: an automated daily run-sheet (tomorrow's hearings, proxy briefs, certified-copy follow-ups, client updates queued for approval, fee reminders, first drafts), plus credit for juniors' work on matter ledgers and invoices, so seniors can see and bill the value juniors create.

### What it can't fix

Low junior incomes and stipends are set by seniors, Bar Councils and the market; BCI stipend guidelines are advisory and no software makes them binding. Court-logistics work that is physical (standing in filing queues, collecting certified copies at the copying section, terminal shortages) stays physical; we only track and schedule it. Product pricing in INR is a commercial decision (noted to the P19 owner).

### What the user sees

A 'My day' page (and a 7 pm WhatsApp summary to the junior): 'Tomorrow: 4 matters. Saket Court 2 items - proxy briefs ready (open). Certified copy applied 12 days ago in Sharma - follow up at copying section (limitation exclusion running). 3 client updates drafted - waiting for Adv. Rao's approval. 2 fee reminders scheduled. Draft vakalatnama for new matter Mehta - ready.' Each item has one action button. The senior sees a 'Junior contribution' tab: appearances, proxy appearances, drafts and hours each junior logged, how much of it was invoiced and collected.

### What the system does

1. services/run_sheet.py (deterministic) builds the next day's list per user from court_cases (next_hearing_date = tomorrow, court, item number when the cause-list provider returns it), copy_applications (new small table: matter, order date, applied_on, status, ready_on; feeds the limitation exclusion owned by P06), queued client updates (P01 owner's queue), P09 fee reminders due, and drafts with status draft assigned to the user.
2. Proxy brief: a one-page brief per hearing generated from the case thread: last order text (from eCourts provider_data or uploaded order), stage, what was sought last time, open tasks; facts and dates are copied from records by code; the 'what to ask for' paragraph is AI (sonnet) from masked thread memory with citations checked by citation_service; the brief is internal (lawyer-to-lawyer) and marked 'for the appearing advocate, verify against file'.
3. Assignment: court_cases and case_threads get assigned_to (user) and appearing_advocate; junior work is captured as work_events (P10) under the junior's user id, and invoice lines carry timekeeper so the 'Junior contribution' report sums invoiced and collected amounts per junior from the P09 ledger.
4. Worker task_run_sheet at the user's chosen evening hour sends the summary via an approved WhatsApp template to the member's own registered number (not to clients).
5. Time saved is shown only as counts of completed automated items, not invented minutes.

### Where it is built

Extend: supabase/migrations/011_court_cases.sql (assigned_to, appearing_advocate columns in a new migration), app/services/ecourts_service.py (agenda(), provider_data orders), app/services/memory_service.py and app/services/citation_service.py (proxy brief), app/services/drafting_engine.py (first drafts), app/worker.py (task_run_sheet), P09 ledger and P10 work_events. New: supabase/migrations/017_run_sheet.sql (copy_applications, assignment columns), app/services/run_sheet.py, app/services/proxy_brief.py, app/routers/run_sheet.py, frontend/src/app/today/page.tsx, frontend/src/components/JuniorContribution.tsx, tests/test_run_sheet.py.

### Why current tools fail and this won't

Clio, CoCounsel and Harvey are priced in USD per seat for BigLaw research, drafting and US billing, not an Indian junior's cause-list, copying-section and proxy-appearance day. Indian tools are diaries and trackers that list dates but don't prepare the brief, queue the client update, chase the fee or credit the junior. We already hold the hearings, case memory, drafting and WhatsApp channel, so the run-sheet is assembled from existing data; only the brief's argument paragraph is AI, citation-checked and labelled.

### Safeguards

Client updates and fee reminders in the run-sheet still need the responsible lawyer's approval (no AI text to clients without a lawyer). Proxy briefs are internal and labelled as aids to verify against the file; citations checked (invariant 3). PII masked before the model. Junior contribution data visible to the junior and to owners/partners only. Run-sheet worker runs server-side per org (to be added to the invariant 2 list).

### Acceptance tests

- test_run_sheet_tomorrow: frozen date 2026-11-13, fixture with 4 court_cases on 2026-11-14 assigned to junior J and 1 assigned to another user: J's run-sheet lists exactly 4 hearings ordered by court then item number.
- test_copy_followup: a copy_application applied 12 days ago with status 'applied' appears with 'follow up' and the days elapsed; one marked 'received' does not.
- test_proxy_brief_facts_from_records: the brief's last-order date, stage and next date equal the court_case/provider_data values exactly; an invented citation in the mocked AI paragraph is marked [unverified] by citation_service.
- test_brief_masking: the prompt payload for the AI paragraph contains no unmasked phone or Aadhaar from the thread fixture.
- test_junior_contribution: invoices with lines by timekeeper J totalling Rs 18,000 of which Rs 12,000 paid yield J's contribution invoiced=18,000, collected=12,000.
- test_summary_only_to_members: task_run_sheet sends only to numbers registered to org members; a court_case client_phone never receives the run-sheet template.

### Reviewers' minor notes

- A proxy appearance needs the appearing junior to be on the vakalatnama or to file a memo of appearance. Show that status on the brief.
- The 'limitation exclusion running' label for certified copies (s.12(2) Limitation Act) should link to P06's computation, not state it independently.
- The junior-contribution report covers invoiced and collected amounts. Most chambers don't invoice junior time separately, so also show appearances and drafts counts, which you do. Keep money optional.
- Run-sheet WhatsApp to member numbers must be allowed by P33's outbound lock.
- The 7 pm run-sheet on a junior's personal WhatsApp lists client names and matter status, which conflicts with P35's goal of getting data off personal phones. Default to counts and a login link.
- P33's assert_may_initiate as specified (clients, consented parties and the inbound 24-hour window only) would block sends to members' own numbers, so test_summary_only_to_members cannot pass. P33 needs an 'internal template to verified member number' category.
- Proxy briefs should carry the appearing advocate's name, and the brief's AI paragraph should pass verify_output_safety as well as the citation check.
- Item numbers depend on whether the eCourtsIndia provider returns cause-list data. It is stated as conditional, which is fine, but test the 'no item number' ordering.
- Depends on P01, P06, P09 and P10 tables. Sequence accordingly.
- Migration 017 collides.

