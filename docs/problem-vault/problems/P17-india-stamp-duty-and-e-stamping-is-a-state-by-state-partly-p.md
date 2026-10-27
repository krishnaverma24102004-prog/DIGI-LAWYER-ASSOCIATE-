# P17. India: stamp duty and e-stamping is a state-by-state, partly physical step that delays or breaks digital execution

**Severity:** critical · **Size:** big · **Region:** India

**Who has it:** Indian in-house teams, startups, NBFCs, real-estate and commercial firms, paralegals handling execution

## What goes wrong

A Bengaluru company e-signs with a Mumbai counterparty, then finds the instrument needs stamping, with rate, method (e-stamp, franking, impressed paper) and portal depending on state and place of execution. E-stamp certificates must still be printed and collected, vendors run out of stock, some states only offer impressed paper. Teams skip stamping, delay signing or courier stamp paper. Leases, leave and licence, loans and SPAs are hit hardest; powers of attorney and sale contracts for immovable property can't be e-signed at all.

## Evidence of scale

- Leegality: methods vary by state (e.g., Gujarat, UP, Delhi, Karnataka e-stamp only; Kerala, Odisha, Punjab, Goa impressed only); SHCIL certificates are printed so vendors have limited stock; NeSL digital stamping is open only to financial institutions; unstamped documents may be inadmissible and liable to up to ten times the duty. ([source](https://leegality.com/blog/stamp-duty-online))
- Legistify: stamp duty is a state subject; rules follow place of execution; penalty up to ten times the deficit; powers of attorney and immovable-property sale contracts still need wet ink; once duty and penalty are paid the document becomes admissible. ([source](https://legistify.com/learn/e-stamping-services/))
- Taxguru (older): e-stamping rollout was uneven; mandatory in Delhi above Rs 500, only in a few districts in Maharashtra, pilot in Tamil Nadu and Assam. ([source](https://taxguru.in/finance/e-stamping-the-easy-and-cost-effective-way-to-pay-stamp-duty.html))

## Why current tools don't solve it

Harvey, CoCounsel, Lexis+ AI, Clio and Ironclad have no concept of Indian stamp duty. SpotDraft and Leegality integrate e-stamp purchase but, at drafting, don't say which article of which state's Stamp Act applies, the duty on the actual consideration, whether registration is compulsory, or the penalty on an existing unstamped contract. Lawyers look up schedules by hand.

## Panel verdict

**Status:** solved (round 2)

**Effort:** L

### What software can fix

At drafting and before execution, a deterministic lookup with sources tells the team the following. Which state's Stamp Act applies: place of execution, the property's state or the state of receipt, with any differential duty. The article, and the duty on the actual consideration, rent or deposit. The stamping methods the state offers. Whether registration is compulsory. Whether the instrument can be e-signed (IT Act First Schedule exclusions). It also produces an execution checklist in order. Rates come from a vendor-maintained shared table, verified by two vendor lawyers per row, with optional per-org overrides approved inside the firm. Every assessment records which source it used.

### What it can't fix

Buying stamps, collecting printed certificates, vendor stock shortages and impressed-paper-only states are physical or government constraints; we link the portal and say what to buy. Disputed classifications are for the Collector to adjudicate. Coverage starts with ten states and the high-volume instruments; anything else returns 'not covered: check the schedule' with no amount. Rates change by notification, so freshness depends on the vendor update process below. The shared table is information, checked by our legal-content team; it is not a legal opinion, and the firm remains responsible for the classification it confirms. NeSL digital stamping is open only to financial institutions.

### What the user sees

A 'Stamp & execution' panel on every draft in Studio and every uploaded contract. Example: 'Leave and licence, Maharashtra (property in Pune). Article 36A, Maharashtra Stamp Act. Inputs: licence fee Rs 40,000/month for 11 months, deposit Rs 2,00,000 (quoted from cl. 4 and cl. 5, verified). Duty: Rs X (formula shown step by step). Methods: e-SBTR / franking / e-stamp. Registration: compulsory, within the period stated. E-sign: allowed for this instrument. Source: shared table v2026.10.2, row MH-36A (Maharashtra Stamp Act Sch. I Art. 36A, notification ref, effective_from), verified 2 Oct 2026 by two Digi Lawyer legal-content advocates (enrolment nos. shown).' If the firm has its own override, the panel reads 'Source: your firm's override (approved by P. Shah, 14 Oct 2026; shared row differs: view)'. The user confirms instrument type and state from pre-selected dropdowns, never silently. A banner warns when the row is more than 180 days past verification. A changelog page lists shared-table versions and what changed.

### What the system does

1. Shared corpus, following the migration 008 pattern. Migration 016_stamp_duty.sql adds stamp_duty_rows: org_id NULL for the shared table; columns state, instrument_key, article, act_section, formula, min, max, methods, registration_rule, esign_rule, penalty, source_url, notification_ref, effective_from, last_verified_at, verifiers jsonb (two entries: name, enrolment no., date), table_version. RLS lets every signed-in user read shared rows and their own org's override rows. Only the service role writes shared rows. 2. Vendor verification is a documented process (docs/legal-content/stamp-verification.md). The source of truth is data/stamp_duty/<state>.json in the repo. A change needs a PR reviewed by two different members of the legal-content CODEOWNERS group (practising advocates). CI (scripts/validate_stamp_tables.py) rejects any row without two distinct verifiers, a source URL, a notification reference and effective_from, and recomputes the golden fixtures. On merge, scripts/load_stamp_tables.py upserts the rows with service role and bumps table_version. This is a deploy-time loader, not a user path, and it is documented in invariant 2. A weekly vendor job, scripts/check_stamp_freshness.py, lists rows past 180 days, and the legal-content team checks state gazettes on a written monthly cadence. 3. Per-org overrides live in stamp_duty_overrides (org_id NOT NULL, same columns plus base_row_id and reason). They are created only through approval_requests with new actions 'stamp_override_create' and 'stamp_override_retire': requesters are partner/associate, approvers owner/partner, and the approver must differ from the requester. They affect only that org. Lookups prefer an active override for (org, state, instrument_key), otherwise the shared row. When the shared row for an overridden key changes later, the org gets a 'shared row changed; review your override' item. 4. Formulas use a small safe expression language (+ - * / min max ceil, slabs, percentages of named inputs) evaluated by our own parser, never Python eval. 5. Classification: Claude, on PII-masked text, proposes the instrument key and the inputs, each with a verbatim quote checked by quote_found. Amounts are parsed by code from the quote, covering Indian digit grouping, lakh, crore and words; if the model and the code disagree the field is left blank. The user confirms the instrument key and state; until then no amount is final. 6. Place-of-execution and differential-duty rules and e-sign eligibility are fixed rule tables in the same shared corpus. 7. stamp_assessments stores document_id, row_source shared|override, row_id, table_version, inputs with quotes, result, confirmed_by and confirmed_at. P15, P43 and P45 reuse it.

### Where it is built

Migration 008's org_id-NULL shared-corpus pattern and RLS policy, approval_requests (migration 013, which gains the stamp_override actions in requester_roles/approver_roles), app/services/jurisdiction_service.py (Indian state profiles), app/services/drafting_engine.py ([●stamp duty●] placeholders and the panel), app/services/review_service.py, app/services/evidence_service.quote_found, app/services/citation_service.py registry (state Stamp Acts added). New files: data/stamp_duty/*.json, docs/legal-content/stamp-verification.md, .github/CODEOWNERS entry for data/stamp_duty/, scripts/validate_stamp_tables.py, scripts/load_stamp_tables.py, scripts/check_stamp_freshness.py, app/services/stamp_duty/registry.py, formula.py, assess.py, supabase/migrations/016_stamp_duty.sql, app/routers/stamp.py, a Studio panel component, tests/test_stamp_formula.py, tests/test_stamp_assess.py, tests/db/test_stamp_rls.py, fixtures/stamp_cases.json.

### Why current tools fail and this won't

Harvey, CoCounsel, Lexis+ AI, Clio and Ironclad have no concept of Indian state stamp law. SpotDraft and Leegality sell e-stamp paper but don't give the article, the duty on the deal's own numbers, the registration requirement or the e-sign eligibility. An LLM asked about stamp duty produces confident wrong rates. Here the rate comes from a sourced table with a named two-advocate verification per row. It is maintained once for every customer, so it works from sign-up, and a firm with a different view can record an override approved inside its own firm without affecting anyone else. Every assessment says which source it used.

### Safeguards

Output is information on statutory charges with sources, marked 'check against the current schedule before payment', and the lawyer confirms classification. Shared rows change only through two-advocate review in CI and are loaded by a deploy-time service-role script, never from a user path. Overrides need maker-checker inside the firm and never leak across orgs. Every assessment records row source and version. Text is PII-masked before Claude. Citations to state Acts are checked by citation_service. The system makes no purchase or payment.

### How the panel's objections were answered

The objection was that the rate-table trust model was unclear: repo JSON was shared but approved through org-scoped approval_requests. Fixed with two separate layers. (1) A vendor-maintained shared corpus in stamp_duty_rows with org_id NULL, following migration 008: readable by all, written only by the deploy-time loader. Its verification process is documented in docs/legal-content/stamp-verification.md: two distinct legal-content advocates per row, recorded in verifiers with enrolment numbers, enforced by CODEOWNERS review and a CI validator. So the tables are active from sign-up (P43) and no firm verifies ten states by hand. (2) Optional per-org overrides in stamp_duty_overrides, created through approval_requests (new stamp_override actions, approver different from requester), affecting only that org. Every stamp_assessment records row_source shared|override, row_id and table_version. RLS tests prove that one firm can't change another's rates.

### Acceptance tests

- tests/test_stamp_formula.py: the parser rejects attribute access, imports and non-whitelisted names; slab formulas give the expected values at each boundary.
- Golden fixtures (fixtures/stamp_cases.json, 40 cases hand-computed from the official schedules with page references): each computed duty equals the expected value exactly and records table_version and row_source.
- scripts/validate_stamp_tables.py fails CI on a row with one verifier, two entries with the same verifier, or a missing source_url, notification_ref or effective_from.
- tests/db/test_stamp_rls.py: an authenticated user can read shared rows but can't insert, update or delete them. Org A's override is invisible to org B. Org B's assessment for the same key uses the shared row (row_source='shared').
- An override request by an associate stays pending. Approval by the same user is refused. A partner's approval activates it for that org only, and the next assessment records row_source='override' with the override id.
- When the shared row under an active override is reloaded with a new version, the org gets a review item.
- An unknown state or instrument returns 'not_covered' with no amount. A row past 180 days returns the amount with a stale flag, and the banner renders.
- Amount parsing: 'Rs. 2,00,000/- (Rupees Two Lakh only)' gives 200000; digits and words that disagree leave the field blank.
- A mocked model classifies a lease as 'agreement not otherwise provided for': no final amount appears until the user confirms the key, and the confirmed key is recorded with the user id.
- E-sign rule: a general power of attorney and an agreement to sell immovable property are 'cannot be e-signed'; an NDA can.
- Executed in Karnataka, received in Maharashtra: the differential line equals Maharashtra duty minus Karnataka duty paid.

### Reviewers' minor notes

- The proposal says the 'Coverage starts with ten states' but doesn't list them. Publish the list and the instrument keys on the changelog page, so users know when 'not covered' is expected.
- The two-advocate verification by vendor staff should carry professional indemnity or a clear non-opinion disclaimer on the panel, not only in the docs.
- BCI Rule 49 bars a practising advocate from being a full-time salaried employee. If the 'legal-content advocates' are Digi Lawyer employees, they cannot be described as practising. Either retain them as independent consultants or describe them as 'legally qualified content reviewers'.
- Displaying verifiers' enrolment numbers to every customer reads like an endorsement. Keep the enrolment numbers in the audit record and show names and roles only.
- Migration 016 collides with P24, P35 and P38.
- The two-advocate legal-content team and the monthly gazette cadence are organisational dependencies. Coverage should launch only for states whose rows have passed CI validation.
- Competitors: Leegality/BharatStamp and state IGR calculators compute duty. The edge is quote-backed classification on the draft plus registration and e-sign eligibility; keep that framing.

