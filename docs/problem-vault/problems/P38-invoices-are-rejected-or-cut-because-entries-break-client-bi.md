# P38. Invoices are rejected or cut because entries break client billing guidelines (OCGs)

**Severity:** high · **Size:** big · **Region:** Global; India (cross-border panel work)

**Who has it:** Mid-size and large firms with institutional clients; Indian firms on MNC panels; billing teams and CFOs

## What goes wrong

Corporate clients run AI over law-firm invoices against outside counsel guidelines (block billing, vague narratives, unapproved rates or timekeepers). Most firms check compliance by hand, so rejections and write-downs rise and billing staff spend days on appeals. Indian firms on MNC panels face the same checks.

## Evidence of scale

- Elite research (about 400 firms): invoice rejection rates rose from 11% to 18% in 2025; 71% rely mainly on manual OCG compliance; 48% of Global 200 CFOs call e-billing their biggest revenue-cycle challenge. ([source](https://itbrief.com.au/story/ai-invoice-checks-drive-law-firms-rejection-rates-up))
- ALA/Bellefield survey of 198 US firms: write-offs about 20% of invoice totals; 43% said 5-10% of e-bills rejected or reduced. ([source](https://www.canadianlawyermag.com/news/general/most-law-firms-struggle-with-client-guidelines/323617))

## Why current tools don't solve it

Clients have AI invoice review (Brightflag, LegalVIEW, Onit); most firms don't. Elite, Aderant and Intapp pre-bill checks are rule-based with OCGs configured by hand. Harvey and CoCounsel don't read OCG PDFs or rewrite narratives. Nothing turns each client's OCG into rules and rewrites noncompliant entries from the work record before sending.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Checking every entry against the client's billing guidelines before the invoice leaves. Each client's OCG becomes explicit, reviewable rules, each tied to a verified quote from the OCG. The rules run deterministically on confirmed time entries. Flagged entries are fixed from the underlying work record: block entries are split by apportioning the already-confirmed billed time (never increasing it), vague narratives are replaced, and disallowed tasks are dropped. Export is LEDES 1998BI (currency and tax fields) for INR/GST invoices, with LEDES 1998B only for clients whose invoices carry no tax and use the platform's base currency.

### What it can't fix

We cannot change a client's guideline, their AI reviewer's judgement, negotiated rates or a write-down the client decides on commercially. Appeals against rejections remain the billing team's work; we provide the evidence. We don't integrate natively with each e-billing portal (Brightflag, Legal Tracker and others) in round 1; we export the standard LEDES file they accept. LEDES XML 2.x export is a later addition. Whether a split entry should be written down further is a billing partner's decision.

### What the user sees

Client settings: upload the OCG PDF and choose the e-billing format (LEDES 1998BI by default, 1998B only where allowed, or PDF/GST invoice only). The app lists proposed rules, for example 'No block billing - p.4: "Each task must be separately itemised"', 'Max 10 hours per timekeeper per day', 'Internal conferences not billable', 'Rate cap for associates Rs 9,000/h', 'Approved timekeepers: ...', 'Minimum increment 0.1h', 'UTBMS task codes required'. Each rule has its quote highlighted in the PDF, and the billing partner approves or edits each one.

Before an invoice is approved, a 'Pre-bill check' marks each entry green, amber or red, with the rule it breaks and a suggested fix. For a block entry the fix is a split such as: 'Split 1.5h into 0.7 / 0.3 / 0.5 (total unchanged 1.5h), apportioned by recorded event time 40 / 20 / 30 min.' Other fixes are narrative rewrites or dropping a disallowed task. The check also shows the invoice total after fixes, which a split never increases. Export produces a PDF/GST invoice and the LEDES file, which is validated before download.

### What the system does

1. Migration 016_billing_guidelines.sql adds:
   * client_billing_profiles (org, client name, increment_minutes, currency, ledes_format in 1998BI|1998B|none, ledes_client_id, client_tax_id, firm_tax_id)
   * ocg_rules (profile_id, rule_type enum, params jsonb, source_document_id, source_quote, quote_verified bool, status proposed|active|retired, approved_by/at)
   * prebill_findings (invoice_id, time_entry_id, rule_id, severity, suggestion jsonb, resolution)
2. OCG extraction: the OCG is uploaded through the existing document pipeline (OCR, PII masking). claude-sonnet-5-5 maps the text into a closed set of rule types only: block_billing, vague_narrative(verb list), min_increment, max_daily_hours, rate_cap(class, paise), approved_timekeepers, non_billable_task(categories), travel_pct, expense_cap, code_required, staffing_limit, each with params and a verbatim quote. Each quote is checked with evidence_service.quote_found (exact, or a contiguous match of at least 85%). Unverified rules are shown as 'unverified, enter manually' and cannot be activated until a human edits and approves them. Rules outside the enum go into a 'not automatable' list shown to the partner.
3. The pre-bill engine, services/prebill.py, is a set of pure functions per rule type that run over confirmed time_entries. For example, block billing is an entry built from 2 or more work_events, or an entry whose narrative contains 2 or more task verbs from a fixed lexicon joined by ';' or 'and' under a single duration. The engine is deterministic: the same input always gives the same output.
4. Block-billing split (services/prebill.apportion, deterministic):
   * Input: the entry's confirmed billed units U (billed minutes / the client's increment; 1.5h at 6 minutes is 15 units) and the raw event durations as weights (40, 20, 30).
   * Each line's quota is U * w_i / sum(w). Each line gets floor(quota). The remaining U - sum(floors) units go to the lines with the largest fractional remainders, ties broken by event start time and then event id.
   * Result: 6.667, 3.333 and 5.0 give floors 6, 3 and 5; the 1 remaining unit goes to the first line, so the lines are 7, 3 and 5 units = 0.7, 0.3 and 0.5h. sum(split units) == U always. The billed total never changes; raw event minutes are shown only as the basis.
   * If U is smaller than the number of lines, or any line would get 0 units, no split is proposed; the finding asks the lawyer to apportion or merge.
   * Manual entries without events get 'apportion durations' and a form whose units must sum to U before it can be saved. Durations are never invented.
5. Narrative rewrites are done by haiku from the source event's masked summary. The rewrite is re-run through the same rules and a guard (no new tasks, no change of duration or date). If it still fails, the entry stays red.
6. UTBMS: a suggestion table maps source_kind to task and activity codes (for example, hearing -> appearance codes) as editable deterministic defaults.
7. Export (services/ledes.py):
   * LEDES 1998BI is the default. It is pipe-delimited and carries INVOICE_CURRENCY=INR, the firm and client tax ids, per-line tax type/percent/total for GST, and invoice tax totals.
   * Reverse-charge invoices carry a zero tax amount with the reverse-charge treatment noted, matching the PDF invoice from P09's gst_rules.
   * The field order and required fields come from the 1998BI specification table checked into tests/fixtures/ledes_1998bi_fields.json, and the validator enforces field count, required fields, date format, decimals and that line totals and tax add up to the invoice total.
   * LEDES 1998B export is refused when an invoice has any tax line or its currency differs from the profile's platform base currency, with the message 'use 1998BI'.
   * Invoice approval is blocked while red findings are unresolved, unless a partner overrides with a reason (logged in audit_logs).

### Where it is built

Extend:
* app/routers/documents.py upload and app/services/ocr_service.py (OCG ingestion)
* app/services/evidence_service.quote_found and the review_service quote verification
* P10's time_entries and work_events (raw event seconds as apportionment weights, confirmed units as the total)
* P09's invoices and gst_rules (tax treatment shared by the PDF and LEDES)
* app/services/audit_service.py (overrides)

New:
* supabase/migrations/016_billing_guidelines.sql
* app/services/ocg_rules.py, app/services/prebill.py (including apportion()), app/services/ledes.py (1998BI writer and validator, plus a guarded 1998B writer)
* app/routers/billing_guidelines.py
* frontend/src/components/PrebillCheck.tsx, frontend/src/app/clients/[id]/guidelines/page.tsx
* tests/test_prebill.py, tests/test_ledes.py, tests/fixtures/ledes_1998bi_fields.json, tests/fixtures/invoice_inr_gst.ledes1998bi
* evals/ocg_samples/ (synthetic OCGs with expected rules)

### Why current tools fail and this won't

Clients run AI review (Brightflag, LegalVIEW, Onit). Firms rely on manual checks (71%) or on Elite/Aderant/Intapp rule engines whose OCG rules are configured by hand, and the US-centric tools default to 1998B, which can't carry INR or GST. Harvey and CoCounsel don't read OCGs or rewrite entries. We do the tedious part, reading the OCG into rules, with AI, but the rules are explicit, quote-verified and approved by a human, and the checks are deterministic. We fix entries from the actual work record, which billing-only tools don't have, and the fix never raises the bill, so it doesn't trip the client's own reviewer. The export format carries the currency and GST that Indian invoices need.

### Safeguards

Confidentiality: OCG and invoice data are client-confidential, with org-scoped RLS; billing profiles are readable by owners/partners and the matter's lawyers.

Masking: entry narratives and summaries pass mask_pii before the model, and the OCG text is masked too.

Human approval: every rule before activation, every invoice before sending, and partner overrides with a reason in the audit log.

The AI never sets durations, rates or totals. Splits only redistribute the confirmed billed units: they can never increase the bill, and no line is rounded up independently. Any change to billed time other than a split is a lawyer's edit with a recorded reason. Export formats are validated, so tax and currency cannot be silently dropped.

### How the panel's objections were answered

Objections 1 and 2 (split inflates the bill): fixed as proposed.
* Splits now use largest-remainder apportionment of the original confirmed billed units, weighted by the raw event durations, with deterministic tie-breaking.
* 40/20/30 minutes on a 1.5h entry gives 0.7, 0.3 and 0.5h, so the total is unchanged. Raw minutes are shown only as the basis.
* Lines that would get 0 units, or U smaller than the number of lines, fall back to manual apportionment, which must also sum to U.
* The old test is replaced by test_block_billing_split_total_unchanged, which asserts sum(split) == the original billed units, plus test_apportion_property (500 random fixtures) and test_apportion_ties_deterministic.

Objection 3 (LEDES 1998B can't carry INR or GST): fixed.
* The default export is now LEDES 1998BI, with currency, firm/client tax ids and line/invoice tax fields.
* The format is chosen per client profile.
* The golden-file test validates against the 1998BI field table, with an INR + GST fixture and a reverse-charge fixture.
* 1998B is still available but refused whenever the invoice has tax or a currency other than the platform's base currency.
* LEDES XML 2.x is listed as a later addition.

### Acceptance tests

- test_ocg_extraction_quotes: on evals/ocg_samples/sample1.pdf (synthetic) with a mocked model response, rules whose quotes appear in the PDF are quote_verified=true. A rule whose quote was altered is unverified, and activate() raises.
- test_rule_type_closed_set: a model output with rule_type 'be_reasonable' lands in the not-automatable list, not in ocg_rules.
- test_block_billing_split_total_unchanged: the entry 'Drafted reply; call with client; reviewed order', confirmed at 1.5h (15 units at 0.1h) and built from events of 40, 20 and 30 minutes, is flagged. apportion() yields 0.7, 0.3 and 0.5h, and sum(split units) == 15 == the original billed units.
- test_apportion_property: for 500 random fixtures (2-6 events, weights 1-300 min, U from 1 to 100 units), sum(split) == U every time, no line exceeds ceil(quota), the output is identical across runs, and U < number of lines produces an 'apportion manually' finding instead of a split.
- test_apportion_ties_deterministic: equal weights 30/30/30 with U=10 give 4/3/3, with the extra unit on the earliest event.
- test_manual_block_not_invented: the same narrative as a manual entry with no events yields the finding 'apportion durations' and no split with durations. Saving a manual apportionment whose units don't sum to U is rejected.
- test_max_daily_and_rate_cap: a fixture timekeeper with 11.2h on one date and an associate rate above the cap produces exactly two red findings.
- test_rewrite_guard: a rewritten narrative that adds 'and drafted settlement deed' (not in the source event) is rejected, and the entry stays red.
- test_ledes_1998bi_export: export of a fixture INR invoice with 18% GST lines matches the golden file tests/fixtures/invoice_inr_gst.ledes1998bi byte for byte. It passes the validator built from ledes_1998bi_fields.json (field count, required fields, INVOICE_CURRENCY=INR, line tax totals summing to the invoice tax total, line totals plus tax equal to the invoice total).
- test_ledes_reverse_charge: a reverse-charge invoice exports with a zero tax amount and the reverse-charge treatment, and its totals match the P09 PDF invoice.
- test_ledes_1998b_refused_with_tax: requesting 1998B for an invoice with GST lines, or in INR for a USD-platform profile, raises 'use 1998BI'. A tax-free invoice in the profile's base currency exports valid 1998B.
- test_override_audited: approving an invoice with a red finding requires the partner role and a reason, and writes an audit_logs row.

### Reviewers' minor notes

- OCG quotes are verified against PII-masked text, but highlighted in the original PDF. Map masked spans back to the original offsets, or verify against unmasked server-side text, so highlights line up.
- Most domestic Indian corporate clients don't use LEDES. Make the PDF/GST-only path the default for INR clients without an e-billing portal, and keep 1998BI as the default only when a portal is configured.
- Migration 016 collides with P24, P17 and P35.
- OCGs often contain confidentiality clauses that restrict sharing with third-party processors. Show the partner the processors involved (from P20's register) before sending an OCG to the model, and allow a manual-only mode.
- Migration 016 collides with P17, P24 and P35.
- Incumbent check: Intapp Terms and Aderant/Elite already do AI-assisted OCG extraction with human review. The differentiator is INR/GST LEDES 1998BI and splits driven by the work record, so say so rather than claiming firms only check by hand.
- Migration 016 collides with P17, P24 and P35.
- The golden LEDES file should be checked against at least one real e-billing portal's validator (or a published 1998BI sample), not only our own field table.

