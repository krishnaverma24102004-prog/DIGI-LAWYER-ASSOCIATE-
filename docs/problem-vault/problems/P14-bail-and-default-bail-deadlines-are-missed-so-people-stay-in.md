# P14. Bail and default-bail deadlines are missed, so people stay in jail

**Severity:** critical · **Size:** big · **Region:** India

**Who has it:** Criminal defence advocates, DLSA panel lawyers, undertrials and families; prosecutors and jail superintendents

## What goes wrong

Default bail (s.187(3) BNSS / s.167(2) CrPC) must be applied for once the 60- or 90-day chargesheet period passes and before a chargesheet is filed; filing is the 'point of no return'. If not filed in time, the right is lost when even a late chargesheet arrives. Undertrials who have served half (one-third for first-time offenders) of the maximum sentence are eligible under s.479 BNSS, but the SC found identification of eligible undertrials deficient. Defence and legal-aid lawyers with dozens of custody files count days by hand from remand dates.

## Evidence of scale

- Prison Statistics India 2023: undertrials are 76.2% of prisoners (4,22,238 of 5,54,034); nearly one-third have spent over a year in custody. ([source](https://www.policyedge.in/p/ncrbs-prison-statistics-india-2023))
- About three in four of India's prisoners are undertrials, per NCRB data for 2023. ([source](https://www.moneylife.in/article/half-a-million-indians-behind-bars-74-percentage-still-awaiting-trial/78578.html))
- SC (23 Aug 2024) directed jail superintendents to process s.479 BNSS applications and later found identification of eligible undertrials 'somewhat deficient'. ([source](https://www.livelaw.in/amp/top-stories/take-proactive-steps-to-release-deserving-undertrial-prisoners-under-s479-bnss-supreme-court-to-statesuts-273246))
- SC: identifying s.479 BNSS-eligible undertrials should be continuous; justice must reach those 'standing unheard and unseen within the four walls of jails'. ([source](https://www.verdictum.in/court-updates/supreme-court/in-re-inhuman-conditions-in-1382-prisons-release-undertrial-prisoners-prolonged-incarceration-1559091))
- Practitioner analysis: the default-bail right survives a later chargesheet only if availed of by filing; 'the point of no return is the filing of the application'. ([source](https://bhattandjoshiassociates.com/the-indefeasible-right-a-jurisprudential-treatise-on-default-bail-and-the-temporal-efficacy-of-subsequent-chargesheet-filing/))

## Why current tools don't solve it

No tool watches a custody file (remand date, offence and maximum sentence, 60 vs 90 days, BNSS vs CrPC by offence date, s.479 eligibility date), alerts on the exact day and drafts the application. Global tools are US-centric; Indian research databases return case law, not computed dates.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Watching every custody file and telling the right lawyer, on the exact day, that default bail has accrued (s.187(3) BNSS or s.167(2) CrPC, picked by when the investigation began) or that an undertrial has reached the s.479 BNSS threshold, which applies to every undertrial whatever the offence date. The application is drafted and the statutory basis shown, so the right is used before a late chargesheet extinguishes it.

### What it can't fix

Whether the court grants bail, surety arrangements, the prosecution filing a chargesheet on day 59, and identifying undertrials inside the jail. We only know about prisoners whose files the firm or legal-aid panel holds; we don't scrape e-Prisons. Unsettled transition questions under s.531 BNSS (e.g. differing High Court views on proceedings begun around 1 July 2024) are flagged for the lawyer, not decided by the software. The s.479 exclusions that turn on facts (other pending cases, delay caused by the accused) are confirmed by the lawyer.

### What the user sees

A Custody board (/custody) lists every client in custody with offence sections (BNS or IPC), offence date, FIR date, remand date, days in custody today, the default-bail date and provision, whether the chargesheet is filed, and the s.479 BNSS date (with 'one-third: first-time offender' or 'one-half'). Where it is more favourable, s.436A CrPC is shown alongside as an alternative citation. A transition badge reads 'Offence before 1 Jul 2024, FIR after: check s.531 BNSS' where applicable. Red 'apply today' rows sit at the top. Maximum and minimum punishment are filled from a statute table, not typed. On the accrual day the counsel, backup and partner get an alert with a prefilled application (marked AI DRAFT, UNREVIEWED until a lawyer approves). A legal-aid panel can upload a CSV of undertrials and get a list of who is eligible under s.479 and from when, including pre-July-2024 cases.

### What the system does

1. New `custody_files`: matter; accused; offence_date (used only for the substantive BNS/IPC punishment lookup); fir_date; investigation_started_on (defaults to fir_date); arrest_date; sections; first_remand_date; custody type; chargesheet_filed_on; first_time_offender (lawyer-confirmed); other_pending_cases (lawyer-confirmed); special-statute flags; extension orders.
2. Statute table app/data/offence_punishments.json: for BNS and IPC sections, maximum term, minimum term, death/life flags, and special-statute periods (UAPA, NDPS periods and extension provisions), verified by two criminal advocates. The substantive code (IPC or BNS) is picked by offence date, because punishment is fixed by the law in force when the offence was committed.
3. Procedural code for default bail, by s.531 BNSS: if the investigation began (FIR registered, or for a complaint case the complaint filed) before 1 July 2024, the provision is s.167(2) CrPC; on or after, s.187(3) BNSS. The offence date plays no part in this choice. If fir_date is missing, the system uses arrest_date and flags 'FIR date not entered: provision assumed from arrest date'. If the offence predates 1 July 2024 but the FIR doesn't, it shows 'transition: check s.531 BNSS' for the lawyer. Same rule in the custody watch and the existing pack.
4. Default-bail period, fixed in code: 90 days only where the offence is punishable with death, life imprisonment or a term of not less than ten years (keyed on minimum term/life/death from the table); otherwise 60 days. This fixes the current `_bail` pack's `max_years >= 10` test (workflow_service.py line 273), which gives 90 days for 'up to ten years' offences that attract 60 under Rakesh Kumar Paul v State of Assam (2017).
5. Day counting includes the remand date, per the Supreme Court rule (encoded only after our criminal team signs the golden cases). Special-statute extensions are applied only when an extension order date is entered.
6. Undertrial release under s.479 BNSS, computed for every undertrial whatever the offence, FIR or arrest date. The basis text cites s.479 BNSS and the Supreme Court's order of 23.08.2024 in In re Inhuman Conditions in 1382 Prisons applying it to undertrials in cases registered before 1 July 2024. The threshold is one-third of the maximum for a first-time offender, otherwise one-half. Offences punishable with death or life are excluded. The s.479(2) other-pending-cases exclusion and any delay caused by the accused are shown as a checklist the lawyer confirms. Where the case began under the CrPC, s.436A CrPC (one-half) is shown as an alternative citation only when it is more favourable. Under current arithmetic it never gives an earlier date, so in practice it appears as a supporting citation, and the deadline is always the s.479 date.
7. Fix to the existing pack: `_bail` gets new optional fields `fir_date` and `min_punishment_years`. The procedural code follows step 3, the 60/90 test follows step 4, and the undertrial computation follows step 6. The error raised without offence_date stays, because offence_date is still needed for the punishment lookup.
8. Each date becomes a P13 deadline with a hard flag ('the right is lost once a chargesheet is filed'). The ladder runs daily from T-5 and the sweep re-runs every morning at 07:00 IST.
9. On accrual, the drafting engine is called with the computed facts (PII-masked). The draft stays unreviewed until approved through the existing /drafting/{id}/approve.

### Where it is built

Extend `_bail` in app/services/workflow_service.py (procedural code by FIR/investigation date, minimum-term test, s.479 for all) and reuse it per row in a stateful custody watch; new app/data/offence_punishments.json; new app/services/custody_service.py and app/routers/custody.py; migration 014_deadlines.sql (custody_files); deadline_service from P13; drafting_engine.py and the existing draft approval flow; citation_service for the basis strings; frontend/src/app/custody/page.tsx and new fields in frontend/src/app/workflows; CSV import reuses review_service's upload handling pattern.

### Why current tools fail and this won't

No tool watches a custody file. Global tools are US-centric, and Indian research databases (SCC Online, Manupatra, Indian Kanoon) return case law, not dates. Even our own current pack is a one-off calculator that relies on a typed maximum, has the 60/90-day error, and picks the code by offence date, which wrongly denies the s.479 one-third rule to pre-July-2024 first-time offenders. The fix is a statute table, the s.531 BNSS rule keyed on the FIR date, s.479 for all undertrials per the Supreme Court's order, and a daily sweep that alerts on the accrual day and hands the lawyer a drafted application.

### Safeguards

Custody data is sensitive personal data under DPDP. It is stored under RLS and never sent to Claude except as masked facts for the draft, which passes a lawyer before filing. Legal-aid CSVs are processed for the DLSA panel's own clients only. Every date on the board carries its statutory basis and the disclaimer that dates are computations for the advocate to check. Transition cases and the s.479 exclusions are flagged for a lawyer's decision.

### How the panel's objections were answered

Both objections (s.479 denied to pre-July-2024 undertrials; procedural code chosen by offence date): (a) s.479 BNSS is now computed for every undertrial whatever the offence, FIR or arrest date, with the basis citing s.479 BNSS and the Supreme Court's order of 23.08.2024 in In re Inhuman Conditions in 1382 Prisons. The one-third first-time-offender rule applies to pre-July cases. s.436A CrPC is shown only as an alternative citation where the case began under the CrPC, never as the governing date. (b) custody_files gains fir_date and investigation_started_on. The default-bail provision (s.167(2) CrPC vs s.187(3) BNSS) is chosen by that date under s.531 BNSS; the offence date is used only for the substantive BNS/IPC punishment lookup. When the offence predates 1 July 2024 and the FIR doesn't, a 'transition: check s.531 BNSS' flag is shown; a missing FIR date falls back to the arrest date with a flag. (c) Golden cases and unit tests cover a pre-July offence with a post-July FIR (test_procedure_by_fir_date) and a pre-July first-time offender under s.479 (test_s479_pre_july_first_time_offender). (d) The existing `_bail` pack is fixed the same way (new fir_date and min_punishment_years fields, minimum-term 60/90 test, s.479 for all), with regression tests in tests/test_workflows.py::test_bail_pack_regressions.

### Acceptance tests

- tests/test_custody.py::test_up_to_ten_years_is_60_days: an offence with maximum 10 and no minimum yields 60 days (regression for the current bug); 'not less than 10 years' and life yield 90.
- test_procedure_by_fir_date: offence 2024-06-20, FIR 2024-07-05 gives s.187(3) BNSS plus the 'transition: check s.531 BNSS' flag; offence 2024-06-20, FIR 2024-06-25 gives s.167(2) CrPC; offence 2024-08-01, FIR 2024-08-02 gives s.187(3) BNSS with no flag.
- test_missing_fir_date_flag: no fir_date uses arrest_date and raises the 'FIR date not entered' flag.
- test_s479_pre_july_first_time_offender: offence and FIR in 2023, max 7 years, first-time offender, custody from 2023-03-01 gives the s.479 date at one-third (custody_from + 7*365.25/3 days), with basis text naming s.479 BNSS and the SC order of 23.08.2024; s.436A appears only as an alternative citation, never as the deadline.
- test_s479_pre_july_not_first_time: same facts without first-time status give one-half under s.479, with s.436A shown as an alternative citation.
- test_s479_excluded_life_death: a life-punishable offence gives no undertrial date and an explanation.
- test_s479_pending_cases_checklist: other_pending_cases unconfirmed shows the deadline with an 'exclusion check pending' badge, not an eligibility statement.
- tests/test_workflows.py::test_bail_pack_regressions: the existing pack, given offence 2023-05-01, first-time offender, max 6 years, returns the one-third s.479 date (previously one-half s.436A); given 'up to 10 years' with no minimum, returns 60 days; existing passing cases still pass.
- Golden custody cases (tests/fixtures/custody_cases.json, at least 30, signed off by two criminal advocates): pre-July offence with post-July FIR, pre-July first-time offender under s.479, BNSS vs CrPC by FIR date, remand-date counting, UAPA/NDPS extension entered vs not, chargesheet filed before vs after accrual.
- test_offence_table_complete: every section in the table has a max term or a life/death flag, and every statute reference passes citation_service.
- test_accrual_alert: freezegun at the accrual date shows the counsel, backup and partner alerted at 07:00 IST and a draft created with status unreviewed.
- test_chargesheet_stops_clock: entering chargesheet_filed_on before accrual marks the deadline done with that evidence; after accrual with no application, the history shows 'right lost'.
- test_csv_import: a 500-row legal-aid CSV with mixed pre- and post-July cases yields the s.479 eligible list in under 5 s with no AI calls (call counter asserted zero), and pre-July first-time offenders appear at one-third.

### Reviewers' minor notes

- The 60/90-day test under s.187(3) BNSS ('ten years or more') differs in wording from s.167(2) CrPC ('not less than ten years'). Whether Rakesh Kumar Paul carries over unchanged, and how to treat offences with a maximum above 10 years and no minimum, should be golden-case items signed off by the criminal team, not hard-coded from the CrPC reading alone.
- The _bail fix overlaps with P22's criminal_codes() change to the same function. Implement it once and share it, otherwise the two will diverge.
- s.479(2) (multiple pending cases) excludes release outright. Make the badge read 'not eligible if other cases are pending' rather than only 'exclusion check pending'.
- DPDP Act 2023 has no 'sensitive personal data' category (that was the SPDI Rules). Say 'personal data of an accused / custody data, treated with heightened safeguards'.
- s.187(3)(i) BNSS reads 'imprisonment for a term of ten years or more', while s.167(2)(a)(i) CrPC reads 'not less than ten years'. Whether Rakesh Kumar Paul's reading carries over to the BNSS wording (for example, maximum exactly 10, no minimum) is arguable. The 60-day alert is the safe direction, but for BNSS cases show a 'BNSS wording differs; 90 days arguable' note and keep the alert at day 60.
- s.436A CrPC excludes only death-punishable offences, not life. For CrPC-era life-but-not-death offences, the 'no undertrial date' explanation should say that s.479 BNSS does not apply and s.436A may be argued (half of an indeterminate maximum), instead of implying no remedy.
- For legal-aid CSV imports, record the DLSA as data fiduciary and the org as processor, with a written processing instruction, and set a retention limit for uploaded undertrial lists.
- For multiple offence sections, state that the gravest section (highest minimum, then life/death, then maximum) decides both the 60/90-day period and the s.479 maximum. Add a golden case for it.
- s.479 counts total detention, so interrupted custody (released, then re-arrested) needs custody periods, not a single custody_from date.
- P14 adds fir_date/investigation_started_on and P22 adds proceeding_instituted_on, and both rewrite _bail. Unify on one field and one criminal_codes() function so they don't diverge.
- Remand-date inclusion (ED v. Kapil Wadhawan, 2023) is correctly gated on sign-off. Cite the authority in the basis text once signed.

