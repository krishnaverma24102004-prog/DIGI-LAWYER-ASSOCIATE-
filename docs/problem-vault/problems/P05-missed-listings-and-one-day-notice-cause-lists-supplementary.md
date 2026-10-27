# P05. Missed listings and one-day notice: cause lists, supplementary lists, next dates and orders are spread across portals and lag the court file, leading to dismissals for default

**Severity:** critical · **Size:** big · **Region:** India

**Who has it:** Solo advocates and small chambers with 100-500 live matters; munshis and juniors keeping several seniors' boards; outstation counsel; women advocates with caregiving duties; AoRs; mid-size litigation firms

## What goes wrong

Every evening an advocate or munshi checks, matter by matter, which cases are listed tomorrow, in which court and at what item number, and what happened last time. Status, cause lists and orders sit on separate eCourts pages, and the SC, 25 High Courts and thousands of district courts each publish their own PDFs. Supplementary lists come out for the same day, several per complex, with 'no passover' warnings. Cause lists load slowly or render badly on phones, data differs between portals, and sites go down on hearing days. Orders are uploaded whenever the clerk gets to them, and cases can show 'disposed' before the judgment is online, confusing limitation. At the Karnataka HC advocates get about one day's notice of final hearings since the advance list was discontinued in 2021. If nobody appears, the matter is dismissed for non-prosecution, and the firm must seek restoration plus condonation, costing months and the client's trust.

## Evidence of scale

- Practitioner guide: eCourts portals make you open separate pages for status, cause lists and orders; cause lists often load slowly or display poorly on mobile; data is sometimes inconsistent across portals; FAQs cover cases wrongly shown as 'disposed' and sites down on hearing day. ([source](https://sudhirrao.com/insights/common-issues-faced-by-advocates-using-indian-court-websites))
- Karnataka HC published an advance cause list for final hearings until November 2021, then stopped; advocates now get about a day's notice, women advocates with caregiving duties are hit hardest, and DAKSH and advocates have petitioned the Chief Justice to restore it. ([source](https://dakshindia.org/advance-causelist-petition-high-court-of-karnataka))
- No fixed national deadline for uploading orders; a Nagpur suit showed 'disposed' on eCourts three weeks before the judgment appeared online. ([source](https://righttoinformation.wiki/practical-guides/court-order-not-uploaded-online-case-status-wrong))
- Delhi HC (April 2025): because of an acute shortage of judges, the list of regular matters often isn't reached by the end of the day. ([source](https://www.verdictum.in/court-updates/high-courts/delhi-high-court/mukesh-gupta-vs-central-bureau-of-investigation-2025-dhc-2936-acute-shortage-of-judges-1575708))
- Gujarat HC launched 'Email My Case Status', sending automated updates on HC and District Court cases, an official attempt to push status changes rather than make people check the portal. ([source](https://www.barandbench.com/news/gujarat-high-court-email-my-case-status-service))
- A Supreme Court daily cause list (12-02-2026, Court 17 chamber matters) lists consecutive items carrying both a 'restoration' IA and a 'condonation of delay in filing application for restoration' IA. ([source](https://api.sci.gov.in/jonew/cl/2026-02-12/M_C_1.pdf))
- Delhi HC issues multiple supplementary cause lists for the same day (e.g. 03.07.2026), with notes such as 'no passover will be given in the first five cases in supplementary list'. ([source](https://delhihighcourt.nic.in/files/2026-07/cause-list/sup-7_for_03.07.26_revised.pdf))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI have no connection to Indian court data. SCC Online and Manupatra are research databases, not docket tools. The eCourts app, eCourtsIndia API, LawStar and India Case Status re-serve portal data by CNR and inherit its lag; they miss late supplementary lists, matters listed under a different counsel or wrong number, tribunals and High Court-specific board formats, and need manual CNR entry. None reconciles a firm's whole matter list against that night's cause-list PDFs from every court, resolves court and item number, flags a misprinted counsel name, warns that a past order is still not uploaded, assigns a responsible person and fallback, or escalates when nobody confirms appearance.

## Panel verdict

**Status:** solved (round 1)

**Effort:** L

### What software can fix

Reconciling the firm's whole matter list every evening against that night's cause lists (daily, supplementary, advance) from every court the firm appears in, resolving court number and item number, catching matters listed under the firm's advocates that we don't track or that carry a misprinted number, warning when a past order hasn't been uploaded, assigning an appearing advocate and a fallback, and escalating until someone confirms appearance.

### What it can't fix

Courts publishing late or not at all, portal downtime, the one-day notice policy of a High Court, and whether a matter is reached. We never bypass eCourts captchas: where a list sits behind a captcha, a munshi downloads and forwards it and we parse it. Coverage is per court parser; unsupported courts fall back to the provider API or manual entry.

### What the user sees

Tonight's board (/board): for tomorrow, every listed firm matter grouped by court complex and courtroom, with item number, bench, list type (daily / supplementary-3 / advance), the appearing advocate and fallback, and a Confirm button. Unconfirmed items turn amber at 20:00 and red at 21:00. A 'Possibly ours' section shows list items naming a firm advocate that match no tracked matter, or match a tracked matter on parties but not number, for someone to claim or dismiss. Matter rows carry warnings: 'last hearing 14 Oct, order not uploaded yet', 'shown disposed with no judgment online: limitation is provisional'. Forwarding a cause-list PDF to the firm's email-in address or WhatsApp number adds it.

### What the system does

1. Sources: per-court fetchers for cause lists published as open PDFs/HTML (starting with Supreme Court, Delhi HC, Bombay HC and the courts our firm uses most); the eCourtsIndia provider where it offers cause lists; and forwarded PDFs. Fetchers poll from 17:00 to 10:00 IST every 30 minutes for supplementary lists, keyed by URL + content hash so a revised list replaces the old one.
2. Parsing is deterministic: pypdfium2 text extraction (OCR fallback via ocr_service for scans, with Tesseract only; no vision fallback for lists), then a per-court grammar (regex plus table layout) producing items {court no, bench, item no, list type, case type, number, year, parties, advocates}. Every parser ships with labelled fixture PDFs.
3. Matching: case-type alias table (e.g. 'W.P.(C)', 'WP(C)', 'Writ Petition (Civil)') and normalized number/year give exact matches; then a second pass matches parties plus advocate name (token similarity above threshold) as 'probable'; any item naming a firm advocate (roster with name variants and enrolment numbers) that is unmatched goes to 'Possibly ours'. Match type and reason are shown; only exact matches update next_hearing_date automatically, probable ones need a click.
4. Assignment: the matter's default advocate and fallback are pre-filled; the advocate confirms. Escalation via deadline_service (P13): unconfirmed at 20:00 goes to the fallback, at 21:00 to the partner, again at 07:30.
5. Order lag: when last_hearing_date passes and no order appears in provider_data or uploads within 3 days, a warning is raised; a 'disposed' status with no judgment marks any P06 limitation computation provisional and uses the safe date.
6. Each list ingested is stored (`cause_lists`, `cause_list_items`) with source URL and hash for audit.

### Where it is built

app/services/ecourts_service.py (provider, sync, agenda); app/services/ocr_service.py and document_service for PDF text; new app/services/causelist_service.py with app/services/causelists/<court>.py parsers; app/worker.py cron `task_fetch_cause_lists`; whatsapp_intake.py to accept forwarded PDFs from firm members' numbers; migration 016_cause_lists.sql (cause_lists, cause_list_items, listing_matches, advocate_aliases); frontend/src/app/board/page.tsx.

### Why current tools fail and this won't

The eCourts app, eCourtsIndia API, LawStar and India Case Status re-serve portal data by CNR and inherit its lag; they miss supplementary lists, items under a different counsel or a wrong number, and High Court board formats. Harvey, CoCounsel and Lexis+ AI have no Indian court data; SCC Online and Manupatra are research databases. We read the actual list PDFs the court publishes tonight, match the whole firm's roster deterministically, surface near-misses for a human, and escalate until someone confirms appearance.

### Safeguards

Public cause lists contain names of parties; stored under RLS per org (shared raw list storage is read-only and holds only public court data). No AI in parsing or matching. Forwarded PDFs are accepted only from registered firm members' numbers. Court terms of use respected: polite polling intervals, no captcha bypass. The fetch job is a server-side job scoped per org and must be added to invariant 2.

### Acceptance tests

- tests/test_causelists.py parser fixtures: at least 20 real public cause-list PDFs per supported court (including the Delhi HC supplementary list of 03.07.2026 and the SC chamber list of 12.02.2026 cited in the vault) with hand-labelled items; case-number field recall 100% and precision at least 99%; item numbers exact.
- test_alias_matching: seeded matters 'W.P.(C) 1234/2025' match list items written 'WP(C) 1234 of 2025' and 'W.P.(C.) 1234/2025' exactly; '1243/2025' with matching parties is 'probable', not exact.
- test_possibly_ours: an item naming a firm advocate's enrolment-name variant with no tracked matter appears under 'Possibly ours'.
- test_revised_list_replaces: a second PDF at the same URL with a different hash replaces items and re-notifies only changed matters.
- test_confirmation_escalation: freezegun at 20:00 and 21:00 shows escalation to fallback then partner for an unconfirmed item.
- test_order_lag_warning: last hearing 4 days ago, no order: warning raised; order uploaded: cleared.
- Captcha test: fetchers have no code path for captcha-protected URLs (static check that the eCourts services URL isn't in any fetcher).

### Reviewers' minor notes

- An exact match in an advance list is not a listing for tomorrow. Only daily and supplementary items should set next_hearing_date; advance items should be shown as 'expected'.
- Delhi HC and other supplementary lists often appear after 21:00. The amber/red escalation clock should run from when the list is ingested, not from a fixed time.
- Handle items marked 'deleted', 'not to be listed' and 'after notice' in the grammar, or they will create false listings.
- Forwarded PDFs from members arriving on the client intake number must be routed away from the client-intake AI path entirely, and never reach consent or intake flows.
- Record each court website's terms of use and robots policy in the fetcher config, and skip any court whose terms forbid automated access instead of only avoiding captchas.
- The incumbent section omits advocate-name cause-list alerts that already exist: court-run advocate-wise lists and alerts on several HC sites, and commercial trackers such as Provakil. 'They miss items under a different counsel' is partly untrue. Restate the differentiator as reconciling the whole firm's roster against tracked matters (alias and probable matches), the order-lag warnings and the confirmation escalation.
- Confirm per court that the chosen cause-list URLs aren't behind a captcha (district lists on eCourts are, so they're forward-only). The static check should cover every captcha host you know of, not just the eCourts services URL.
- 100% recall on case numbers across 20 PDFs per court is achievable only on those fixtures. Monitor parse failures in production (an items-per-page anomaly alert).

