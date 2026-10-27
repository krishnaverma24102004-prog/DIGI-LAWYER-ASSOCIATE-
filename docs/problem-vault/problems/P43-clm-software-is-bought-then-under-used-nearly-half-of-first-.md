# P43. CLM software is bought then under-used: nearly half of first implementations fall short

**Severity:** high · **Size:** big · **Region:** Global

**Who has it:** Legal ops, GCs, procurement; mid-size Indian companies

## What goes wrong

A department spends a year and a large budget on a CLM. Templates are over-customised, sales and procurement keep emailing Word files, legacy contracts are never migrated, and the system becomes a second incomplete repository. Two years later the team shops for a new CLM. Indian mid-size companies often avoid CLM because of cost and setup time.

## Evidence of scale

- Cimplifi quoting Gartner: nearly 50% of initial CLM implementations will fall short, due to poor data quality and integration, unfit technology, resistance to change and insufficient training. ([source](https://www.cimplifi.com/resources/why-many-first-time-clm-implementations-fail/))
- Legal Technology Insider repeats the Gartner prediction and lists causes: lack of preparedness, stakeholders not engaged, poor CRM/ERP integration, unrealistic expectations. ([source](https://legaltechnology.com/guest-post-the-five-reasons-clm-implementations-fail-and-how-to-avoid-them/))
- DocuSign blog with legal ops leads from Ciena, Meta and Uber cites Gartner predicting 50% of first-time CLM deployments would fail by 2023. ([source](https://www.docusign.com/blog/legal-ops-experts-weigh-successful-contract-management-implementation-and-adoption))
- CLOC 2025: contract management implemented at 62% and among top planned implementations (30%). ([source](https://abovethelaw.com/2025/05/interpreting-the-2025-cloc-in-house-survey-results/))

## Why current tools don't solve it

Ironclad, Icertis, Agiloft and DocuSign CLM need workflow design, integrations and migration before value. No product offers a zero-setup layer working on contracts where they already sit (email, WhatsApp PDFs, Drive, scans) that builds the repository and obligation calendar automatically.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Contract-management value without a CLM implementation project. A zero-configuration start: pick files or folders, or forward emails, and within a day get a repository, candidate obligations, and a count of contracts awaiting stamp classification. Exposure appears only for confirmed assessments. Indian defaults work out of the box (Indian playbook pack, review presets, and vendor-verified shared stamp tables). Adoption is measured in the product, and full export means the customer is never trapped.

### What it can't fix

Organisational change management, executive sponsorship and training culture: per Gartner, the main reasons CLMs fail are people and data problems that software can only nudge. Deep ERP/CRM integration and complex approval workflows are deliberately not built. We can't make sales stop emailing Word files; we can only make the email-in path catch them. We won't show stamp exposure figures before a person confirms the classification, so the first-day headline is a to-do count, not a rupee number.

### What the user sees

An onboarding screen with three steps. 1. Pick Drive files or folders in Google Picker, share a folder with the workspace's service account, or get your forwarding address (verify your domain in one DNS step). 2. Pick your contract types (presets). 3. Invite your team. Within hours a progress page shows, for example: 'Ingested 412 files (9 rejected: 6 legacy .doc, 3 password-protected); 371 contracts (298 executed, 41 drafts, 32 to confirm); 58 amendments linked, 11 to confirm; 1,204 candidate obligations, 0 confirmed. Start confirming: next 30 days first. 23 contracts need stamp classification: confirm each in two clicks. Confirmed stamp exposure: none yet.' As legal confirms, the line becomes 'Confirmed stamp exposure: Rs 1.8 lakh across 7 contracts (16 still need classification)'. There is no unconfirmed amount or range. The GC's Adoption page shows: share of contract requests that came through intake versus contracts found later without one, obligations confirmed versus pending, stamp classifications confirmed versus pending, reminders acknowledged, and median time to answer business questions. 'Export everything' downloads a ZIP containing original files, CSV and JSON of all fields with quotes and confirmation status, obligations as CSV and ICS, stamp assessments with row source and version, and playbooks as JSON.

### What the system does

1. Defaults: the repository preset (P42), obligations preset (P16), Indian playbook (P44) and the shared stamp corpus (P17, vendor-verified, org_id NULL) are active from sign-up, and nothing needs configuring. 2. A backfill background job runs over connected sources, with per-org progress counters (files, rejections by reason, execution_status counts, link items, candidate and confirmed obligations). 3. Stamp exposure on onboarding and adoption pages is a SQL view: the sum of deficit or duty only over stamp_assessments with confirmed_by not null and status computed. It is shown beside a count of contracts needing classification (stamp_assessments missing or unconfirmed on executed contracts). Unconfirmed assessments contribute no amount anywhere: not in UI, digest or export totals. 4. An onboarding work queue orders confirmations by urgency: obligations due soonest, then high-value stamp classifications, so the headline numbers fill in fast. 5. Adoption metrics are SQL views over contract_requests, contracts, contract_obligations, obligation_reminders and stamp_assessments. A 'bypass' is a contract whose earliest source date has no matching request (same counterparty and type within 30 days). 6. A weekly digest of aggregate counts goes to the GC via n8n. 7. Export is a worker job producing a ZIP in the reports Storage bucket, downloaded via a signed URL (the existing pattern), with a schema README. It is available on every plan, and for 30 days after cancellation. 8. Pricing is per contract volume, not seats (note to P19).

### Where it is built

app/worker.py and the reports bucket signed-URL pattern (task_generate_pdf_report), app/routers/jobs.py, app/services/n8n_service.py, the P42/P16/P17/P44 modules (stamp_assessments.confirmed_by, contract_documents.execution_status), the team page and invitations (migration 009), frontend/src/app/team. New files: app/services/adoption_service.py, app/services/export_service.py, app/services/onboarding_queue.py, task_export_org in app/worker.py, SQL views in supabase/migrations/019_adoption_views.sql, frontend/src/app/onboarding/page.tsx and frontend/src/app/adoption/page.tsx, tests/test_export.py, tests/test_adoption.py, tests/test_onboarding.py.

### Why current tools fail and this won't

Ironclad, Icertis, Agiloft and DocuSign CLM deliver value only after workflow design, integrations and migration, which is where half of first implementations stall. We start from contracts where they already are, with Indian defaults and shared stamp tables already verified, so first value arrives before anyone designs a workflow. The first numbers are honest: candidates and to-confirm counts, with rupee figures only once a person confirms. The adoption page shows the GC under-use early instead of at renewal, and full export removes the lock-in fear that stops mid-size Indian companies from buying.

### Safeguards

Export is restricted to owners and audit-logged, and signed URLs expire. The digest contains aggregates only. No rupee figure for stamp duty is shown, sent or exported unless a person has confirmed the classification, consistent with P17/P45. Backfill uses the same PII masking, minimal-scope connectors and DMARC rules as P42. Deletion and retention follow the existing trash and legal-hold rules.

### How the panel's objections were answered

The objection was that the zero-configuration 'stamp exposure Rs 4.6 lakh' headline contradicted P17/P45's rule of no amount before confirmation. Fixed: onboarding now shows 'N contracts need stamp classification', with an urgency-ordered queue to confirm them. Confirmed exposure is a SQL view summing only stamp_assessments with confirmed_by set, and it starts at 'none yet'. No unconfirmed amount or range appears in UI, digest or export. The acceptance tests were changed to match: confirmed_exposure_inr = 0 with no amount fields before confirmation, then exactly the sum of the confirmed rows. The same honesty applies to obligations, shown as candidates versus confirmed, and to execution status counts from P42.

### Acceptance tests

- tests/test_onboarding.py: a local folder connector fixture of 20 sample contracts with a mocked Claude, and no configuration beyond choosing the folder, creates repository rows, candidate obligations and unconfirmed stamp assessments. The progress payload shows 'N need stamp classification' with N equal to the unconfirmed executed contracts and confirmed_exposure_inr = 0. No amount field for unconfirmed rows exists in the payload or the rendered page (snapshot test).
- After two stamp assessments are confirmed in the test, confirmed_exposure_inr equals exactly the sum of those two results, and the 'need classification' count drops by two.
- The weekly digest and the export totals exclude unconfirmed assessments (seeded case with one confirmed and three unconfirmed).
- tests/test_adoption.py: on seeded data, a contract ingested via Drive with no request for that counterparty and type within 30 days counts as a bypass; one with a request doesn't.
- tests/test_export.py: the ZIP contains every original file (hash-matched); contracts.csv has one row per contract with its execution_status; obligations.ics parses with the icalendar library; stamp_assessments.csv carries row_source and table_version; playbooks.json re-imports into a fresh org to the same positions.
- Export is refused for a non-owner, and is available for 30 days after cancellation (Stripe status fixture).
- The weekly digest payload contains only aggregate counts, with no clause text or party names.

### Reviewers' minor notes

- 'Within a day' and 'within hours' depend on OCR volume and Claude rate limits for large backfills. Show an ETA computed from the queue instead of promising a time.
- The bypass metric (no request within 30 days for the same counterparty and type) will over-count legacy contracts signed before the product was adopted. Exclude contracts whose execution date predates onboarding.
- The 'Export everything' ZIP contains counterparty and employee personal data. Encrypt it, or at least put a short expiry on the signed URL, and record the export in the P35 processing records.
- Depends entirely on P42, P16, P17 and P44 shipping first. 'Within a day' assumes the backfill throughput of OCR plus a per-document Claude call. Measure it on a 400-file fixture before promising it on the onboarding screen.

