# P32. Clients have no idea how long their case will take in a backlog of about 5.4 crore cases

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** All litigants in Indian courts; firms setting expectations and recommending mediation, Lok Adalat or settlement

## What goes wrong

Clients are told 'it will take time' and can't plan finances, settlements or life decisions. Over 82 lakh cases have been pending 5-10 years and over 47 lakh for more than 10, and clients feel misled when 'six months' becomes years.

## Evidence of scale

- As on 31 Dec 2025: 4,76,57,328 cases pending in district courts, 63,66,023 in HCs, 92,101 in the SC (about 5.4 crore). ([source](https://ianslive.in/over-476-crore-cases-pending-across-indian-courts-govt-tells-parliament--20260213184542))
- NJDG as of 21 July 2025: 5.29 crore pending, 4.65 crore in district and subordinate courts. ([source](https://madhyamamonline.com/amp/india/judicial-backlog-mounts-529-crore-cases-pending-indian-courts-1432099))
- NJDG (as cited): more than 82 lakh cases pending 5-10 years and more than 47 lakh over 10 years. ([source](https://countercurrents.org/2026/10/the-invisible-queue-why-millions-of-indians-walk-away-before-justice-even-begins/))
- Nearly 60% of civil and criminal cases take over a year to dispose of at subordinate level (NJDG, as cited). ([source](https://idronline.org/article/livelihoods/why-is-the-quality-of-indias-free-legal-aid-so-poor/))

## Why current tools don't solve it

NJDG publishes aggregate dashboards, not case-type and court-specific estimates for a client. Harvey, CoCounsel and Lexis+ AI have no Indian duration data; Manupatra and SCC have judgments, not disposal statistics. No tool tells a client in plain language how long matters like theirs take in their court and what would shorten it (mediation, Lok Adalat, s.138 compounding).

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Giving a client an honest, data-based range for how long matters like theirs have taken, using the firm's own matters in that court and case type (eCourts filing, disposal and hearing history). The estimator corrects for two biases in this data. Right censoring: some matters are still pending. Left truncation (delayed entry): a firm onboards matters that are already pending, and the matters it disposed of before onboarding are missing. When the client's case is already some months old, the range is conditional on that age. Published NJDG pendency-age figures appear separately, with their label. The panel says 'not enough data' instead of guessing. It also adds a lawyer-reviewed list of things that can shorten a case type (Lok Adalat, mediation, compounding), framed as options to discuss.

### What it can't fix

Judge vacancies, adjournment culture and backlog are not ours to fix. NJDG publishes aggregates (pendency by age band and court), not per-case disposal times, and its dashboards sit behind captcha-protected search, which we will never bypass. So we can't compute a district-level 'time to disposal' from NJDG. We show it only as 'X% of pending cases of this type here are older than N years'. Delayed-entry correction removes the onboarding bias, but it needs enough matters observed early in their life. A firm that only ever takes on old matters can't estimate durations for new ones, and we say so instead of extrapolating. Matters added to the system after they were already disposed can't be used without biasing the result, so they are excluded and counted. No one can predict how long a specific case will take.

### What the user sees

Lawyer, on a court case or an intake brief, sees a 'How long?' panel. Example: 'Similar matters (s.138 complaints, Saket district courts) in this firm's records: 41 (29 disposed, 12 still pending; 6 excluded because they were added after disposal). Measured from filing date. Each matter counts only from the date this firm started tracking it (Kaplan-Meier with delayed entry). For a matter already 9 months old, like this one: half were disposed within a further 14 months; 1 in 4 took more than 26 more months. Reliable from 4 months after filing (at least 10 matters under observation).' A 'Method' line names the estimator and the 'measured from' basis. A second line shows public data: 'NJDG, as of 1 Oct 2026, source link: 38% of pending NI Act cases in South Delhi are older than 3 years.' If the data can't support an estimate, the panel names the reason, for example 'Not enough similar matters observed early enough after filing to estimate', and shows only the NJDG line. A checklist offers lawyer-reviewed 'Ways this can be shorter' for the case type, each to include or leave out. 'Approve and send' gives the client a short Hindi or English WhatsApp/PDF explainer. It contains the range, what it is based on (number of matters and that it counts from filing), the sentence 'every case is different and no duration is guaranteed', and the chosen options as 'to discuss with your lawyer'.

### What the system does

1) Migration 014 adds columns to court_cases: case_type, filing_date, registration_date, disposal_date, disposal_nature and hearings_count, mapped by ecourts_service.from_provider from the provider fields. It also adds tracking_started_at date not null default (created_at::date). A BEFORE UPDATE trigger makes tracking_started_at immutable, so nobody can backdate it to put old matters at risk from day 0. 2) duration_service.similar(org, case_type, court) selects the org's matters through RLS, matching on exact normalized case_type and court. A fallback widens to district, then state, and the panel names the level used. 3) For each matter the time scale is days since filing_date. entry = max(0, tracking_started_at - filing_date); exit = disposal_date (event) or today (censored). A matter with exit <= entry was added after it was disposed. It is excluded and counted in 'excluded_added_after_disposal'. 4) duration_service.km_delayed_entry(entries, exits, events) is a plain-Python product-limit estimator with left truncation and right censoring. At each event time t the risk set is {i : entry_i < t <= exit_i}, so a matter joins the risk set only from its entry time. It returns S(t), the risk-set size at each t, n, the number of events and the method string. 5) Reliability guard: t_min is the first time the risk set reaches 10. The curve is used only from t_min onward. For the client's case at age a, the estimate is conditional: S(t | T > a0) = S(t)/S(a0), with a0 = max(a, t_min). It returns the remaining-time P25, median and P75. The estimate is suppressed, with a reason code, when n < 10, events < 5, the client's case age is below t_min ('not observed early enough'), or the risk set falls below 5 before the requested quantile. A median the curve never reaches is shown as '>X months'. 6) The naive estimator (everyone at risk from filing) is computed only for internal comparison. It is never shown, but it is logged and used in tests. 7) Hearing statistics use only fully observed matters (filing_date >= tracking_started_at, disposed). The panel shows them with that label, or suppresses them below 10 matters. The median gap between consecutive hearings is taken from hearing history inside the tracked window. P31 uses these figures. 8) njdg_benchmarks is a shared read-only table (org_id null, migration 008 pattern) loaded by scripts/load_njdg_benchmarks.py. The loader reads only CSVs a person has downloaded by hand, requires source_url and as_of, and does no captcha automation. The UI shows the figures verbatim, with their date. 9) The 'shorten' options are a static file, app/data/duration_options.json, with en/hi text per case type. CI checks every statutory reference in it with citation_service: each must have status 'statute' and none may be 'repealed'. The lawyer ticks the options that apply. 10) The client message is a fixed template filled with numbers, with no AI. It includes n, the 'measured from filing' basis and the conditional age. It goes out through the P01 approval and send path (client_updates kind 'duration').

### Where it is built

Existing: app/services/ecourts_service.py (from_provider gains the new mapped fields), migration 011's court_cases (new columns and the immutable tracking_started_at trigger in migration 014), migration 008's shared-corpus pattern (njdg_benchmarks), app/services/citation_service.py (CI check of option references), app/routers/cases.py, and the P01 client_updates send path. New: app/services/duration_service.py (similar, km_delayed_entry, conditional_quantiles, hearing_stats), scripts/load_njdg_benchmarks.py, app/data/duration_options.json, tests/fixtures/channing_house.csv with a reference-output fixture, GET /api/v1/court-cases/{id}/duration and POST /api/v1/duration/estimate (for briefs), and the panel in frontend/src/app/cases/page.tsx and the /inbox brief card.

### Why current tools fail and this won't

NJDG shows aggregate dashboards, not an estimate for a client. Harvey, CoCounsel and Lexis+ AI have no Indian disposal data. Manupatra and SCC have judgments, not timings. An LLM asked 'how long' invents a number. Practice-management trackers that report 'average age of our cases' make exactly the onboarding mistake: inherited old matters inflate it. Ours uses a standard survival estimator that corrects for both censoring and delayed entry. It conditions on the client's case age, shows its sample size, basis and reliable range, refuses below fixed thresholds, and never lets a model produce the number. Firms that track their cases with us (P01) build the dataset as a by-product, and it grows more reliable as matters are tracked from filing.

### Safeguards

UPL: the ranges are historical statistics, phrased as 'matters like this have taken', with a 'no guarantee' line. The shortening options are 'to discuss' and are ticked by the lawyer. A lawyer approves every client message. Data honesty: the estimator corrects for delayed entry, the 'measured from' basis and method are always shown, the curve is used only where the risk set is at least 10, and estimates are suppressed with a stated reason below fixed thresholds. tracking_started_at is immutable, so the bias correction can't be gamed by backdating. There is no captcha bypass and no scraping of eCourts or NJDG. DPDP: the statistics are computed over the org's own matters through RLS and never leave the org. The shared benchmarks hold aggregates only.

### How the panel's objections were answered

Both blocking objections were about left truncation (delayed entry), which the old proposal ignored. Fixed as follows. (1) Each matter now joins the risk set only from entry = tracking_started_at - filing_date, which is a delayed-entry product-limit estimator (step 4). tracking_started_at defaults to when the matter was first added to the system and is immutable after insert, so it can't be backdated. Matters added after they were disposed are excluded and counted, not used. (2) Delayed-entry KM is unstable where few matters are under observation early on. So the curve is used only from t_min, the point where at least 10 matters are at risk. Estimates are conditional on the client's case age (S(t)/S(a0)), which is the honest question for an already-pending case. Below t_min the panel says 'not observed early enough' instead of extrapolating. (3) The method and basis are shown in the panel, the API payload and the client message: 'Kaplan-Meier with delayed entry; measured from filing; each matter counted from when the firm began tracking it'. (4) Tests: Channing House, the published left-truncated example in Klein & Moeschberger, is checked against stored survival::survfit output. A seeded synthetic fixture shows the naive and delayed-entry medians differ, with the naive one biased upward and the delayed-entry one close to the truth. There are also tests of risk-set construction, exclusion and conditioning. (5) Hearing-count statistics had the same selection bias, so they now use only fully observed matters (filed after tracking began) and are labelled that way.

### Acceptance tests

- tests/test_duration.py::test_km_right_censored_known_values: on the Freireich 6-MP treatment arm with no truncation (entry=0), survival values match the published Kaplan-Meier table to 3 decimals, and the median matches the published value.
- test_km_delayed_entry_channing_house: on the Channing House left-truncated data (Klein & Moeschberger, Survival Analysis, section 4.6), S(t) and the risk-set sizes equal the stored reference output from survival::survfit(Surv(entry, exit, event)) to 4 decimals at every event time. A dev-only cross-check against lifelines KaplanMeierFitter(entry=...) produces the same values.
- test_naive_vs_delayed_entry_differ: a seeded synthetic cohort has exponential durations with a true median of 18 months. Matters are filed over 10 years. The firm onboards in year 6, so matters disposed before then are missing, and matters still pending enter late. The naive KM median exceeds 22 months (biased up). The delayed-entry median is within 18 +/- 2.5 months. Matters disposed before onboarding are counted in excluded_added_after_disposal.
- test_risk_set_built_from_entry: a matter with entry=300 days and exit=500 days is not in the risk set at t=200 and is in it at t=400.
- test_added_after_disposal_excluded: a matter whose tracking_started_at is after its disposal_date is excluded and counted, and n drops by one.
- test_conditional_on_case_age: for a case already 9 months old, the reported median is the remaining-time median from S(t)/S(9 months) and matches a hand-computed fixture.
- test_suppressed_below_t_min: when the client's case age is below the first time the risk set reaches 10, the result is suppressed with reason 'not_observed_early_enough'.
- test_suppress_small_n_and_few_events: with n=9, or with 4 events, no estimate is returned and the reason codes are 'n<10' and 'events<5'.
- test_tracking_started_at_immutable: as an authenticated user, an UPDATE of court_cases.tracking_started_at raises 42501. Other columns stay editable.
- test_method_and_basis_in_panel_payload: the API response includes method='kaplan_meier_delayed_entry', measured_from='filing_date', t_min and the level used (court, district or state).
- test_fallback_level_labelled: 3 matches in the court establishment and 15 in the district give an estimate that uses the district, and the label says 'district'.
- test_hearing_stats_only_fully_observed: a matter filed before tracking started is not counted in hearing counts. P25/P50/P75 match numpy.percentile (linear method) computed without numpy in the product code.
- test_from_provider_maps_dates_and_hearings: a provider fixture fills filing_date, disposal_date and hearings_count correctly.
- test_options_citations_valid (CI): every reference in duration_options.json passes citation_service with status 'statute', and none is 'repealed' or 'invalid'.
- test_client_template: the rendered hi and en messages contain n, the 'measured from filing' basis, the source line and the 'no duration is guaranteed' sentence, and pass verify_output_safety without triggering the disclaimer.
- test_njdg_loader_requires_source: a CSV row without source_url or as_of is rejected.

### Reviewers' minor notes

- Matters that leave the firm before disposal (client changes lawyer, transfer) are censored, and that censoring is plausibly informative. Exclude or flag them separately rather than treating them as ordinary censoring.
- Most firms will hit 'not enough data' for most (case type, court) pairs for a long time. Make the NJDG line and the fallback level the visible default, so the panel isn't usually empty.
- The client explainer should say the figures come from the firm's own past matters and are not an estimate for this case. It should also avoid figures from cells small enough (n near 10 in one court) that another client's matter could be inferred.
- Since estimates below t_min are suppressed, a0 = max(a, t_min) always equals a when an estimate is shown. Simplify the text.
- Delayed-entry KM assumes entry is independent of remaining duration. Firms that take matters at a particular stage (for example appeals after delay) can violate this. Note it in the Method line.

