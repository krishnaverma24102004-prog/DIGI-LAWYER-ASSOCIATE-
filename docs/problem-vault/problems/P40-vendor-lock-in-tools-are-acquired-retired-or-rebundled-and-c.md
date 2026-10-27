# P40. Vendor lock-in: tools are acquired, retired or rebundled, and contracts escalate and auto-renew

**Severity:** high · **Size:** big · **Region:** US / Global

**Who has it:** US solos and small firms on Casetext, Westlaw or Lexis; any firm standardising on one AI vendor

## What goes wrong

Thomson Reuters bought Casetext for USD 650M and retired it on 1 April 2025, moving users to CoCounsel (about USD 360-784 per user per month). Westlaw contracts are often multi-year with escalators and auto-renew unless cancelled by mailed letter in a narrow window; reviewers report out-of-plan charges and USD 30,000+ implementation fees. A firm's prompts, playbooks and history stay inside the vendor, so switching means starting over.

## Evidence of scale

- CostBench (Oct 2026): CoCounsel Essentials USD 360, Practical Law with CoCounsel USD 596, CoCounsel Legal USD 784 per user per month; reviewers report auto-renewal, advance billing and USD 30,000+ implementation charges. ([source](https://costbench.com/software/ai-legal-tools/casetext-cocounsel/hidden-costs/))
- Westlaw: multi-year contracts commonly carry annual escalators; cancellation by physical letter before auto-renewal; a reviewer reported a USD 174 out-of-plan charge for one document (competitor source). ([source](https://www.vaquill.ai/blog/how-much-does-westlaw-cost-solo-small-firm-pricing))
- Westlaw Advantage with CoCounsel Essentials about USD 639/month for a solo; Casetext retired 1 April 2025 after a USD 650M acquisition. ([source](https://www.vaquill.ai/blog/casetext-vs-westlaw-pricing-2026))

## Why current tools don't solve it

Incumbents keep prompts, playbooks, clause libraries and review history inside their platform with no portable export; pricing is opaque and reset at renewal; acquisitions end products. No major tool contractually guarantees data portability or a price cap.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Making leaving us cheap and predictable: a complete, documented, open-format export of everything the firm put in or built (matters, documents, transcripts, drafts, practice-area prompts and playbooks, review grids, knowledge base, conflict index, audit and AI-use ledgers) that a test proves can be re-imported. Plus billing practices enforced in code: cancel in-app any time, renewal reminders before every annual renewal, no silent plan changes, and a read-only export window after cancellation. Because the stack is open infrastructure (Postgres, docker-compose, ANTHROPIC_BASE_URL), the firm can self-host or swap the model gateway.

### What it can't fix

Price caps and non-assignment on acquisition are contract terms, not code. We can publish them in our order form (commercial/legal team), and the software can only refuse to migrate a subscription to a new Price without the owner's acceptance. Shared corpus data we licence (SC judgments CC BY 4.0, Indian Kanoon results) is exported only where the licence allows. Indian Kanoon content is excluded and only references are kept. Vector embeddings are exported but are model-specific, so a new vendor may need to re-embed. Westlaw/CoCounsel lock-in for US firms is not our market.

### What the user sees

Owners see 'Export everything' on the Team/Billing page: it queues a job and emails a signed download link to a zip with a README explaining every file. 'Scheduled export' can push a monthly copy to the firm's own S3-compatible bucket or download location. The Billing page shows plan, price, renewal date, 'Cancel' (one click, effective at period end, with no phone call or letter), and a banner 30 days and 7 days before any annual renewal. If we ever change a plan's price, existing subscriptions stay on their Price until the owner clicks 'Accept new price'. After cancellation the workspace is read-only for 90 days, with export still working, then the existing retention and erasure flow applies with a certificate.

### What the system does

1) task_export_org in app/worker.py (ARQ, uses the user's JWT-scoped client re-checked as owner, as the worker already does) writes: one JSON Lines file per table (RLS guarantees only the org's rows), original uploaded files from Storage, drafts as .docx and .md, transcripts as .txt, review grids as CSV, practice_areas and playbooks as YAML, the P46 party index as CSV, ledgers as JSONL, and schema.sql plus a data dictionary (generated from migrations). manifest.json carries a SHA-256 per file and an HMAC-signed root hash. The zip goes to the reports bucket behind a short signed URL (the existing jobs pattern). 2) Import tool scripts/import_org_export.py restores an export into an empty Supabase/Postgres (self-host) and verifies the manifest. This also serves as our disaster-recovery test. 3) Billing guards in stripe_service: handle the `invoice.upcoming` webhook to create in-app and email reminders. Cancel uses Stripe's cancel_at_period_end via an owner-only route. A unit-tested rule is that code never calls subscription.modify to a different price except from the owner's explicit accept endpoint (audited). 4) Read-only mode: organizations.status = 'cancelled_readonly'. A FastAPI dependency blocks writes and AI routes but allows GET and export for 90 days, and the worker cron then starts the standard 48h notice and trash flow from P35. 5) Data portability note on the About page names the formats.

### Where it is built

Extend app/worker.py and app/services/queue_service.py (task_export_org), app/routers/jobs.py (download), app/services/stripe_service.py and app/routers/billing.py (invoice.upcoming handling, cancel, accept-price), app/services/pdf_service.py (none), frontend/src/app/team (export button) and the billing UI. New: app/services/export_service.py, scripts/import_org_export.py, docs/export-format.md (generated data dictionary), migration column organizations.status and price_acceptances table. AuditActions EXPORT_ORG, CANCEL_SUBSCRIPTION, ACCEPT_PRICE_CHANGE.

### Why current tools fail and this won't

Thomson Reuters retired Casetext after acquisition, and Westlaw contracts auto-renew with escalators, cancellable only by letter. Harvey and CoCounsel keep prompts, playbooks and review history in proprietary form with no export. Indian research subscriptions (SCC Online, Manupatra) are per-seat with no export of the firm's own work product. Our export is tested in CI by round-trip, our billing rules are code with tests, and our stack (Postgres, open Docker images, standard model gateway) runs without us.

### Safeguards

Export only by owners, audited, with a short-lived signed URL. The worker re-checks role (invariant 2's ARQ rule). PII stays as stored; the export is the firm's own data, so no masking applies, but the README warns it contains client confidences and DPDP obligations travel with it. Licence-restricted data is excluded. The post-cancellation erasure uses the existing notice, trash and certificate path.

### Acceptance tests

- Integration (embedded Postgres): seed org A with 3 matters, 5 documents, 2 drafts, 1 review grid, 1 practice area and ledger rows, then run task_export_org, import into a fresh database with scripts/import_org_export.py, and compare row counts and per-row SHA-256 of business columns per table.
- Unit: an export by org A contains zero rows with org_id = org B (scan every JSONL), and shared-corpus rows (org_id NULL) are excluded or included only per the licence flag. Indian Kanoon cached text is absent.
- Unit: tampering one byte in a file makes the manifest verify fail with that file named.
- Unit: a non-owner calling POST /organizations/{id}/export gets 403.
- Unit: a mocked invoice.upcoming webhook for an annual plan creates a reminder row and an email job, and a duplicate event id is ignored (stripe_events idempotency).
- Unit: static check that stripe.Subscription.modify with a price change is reachable only from the accept-price route (AST grep test). The cancel route sets cancel_at_period_end=true and is audited.
- Unit: with org.status='cancelled_readonly', POST /drafting/generate returns 403 while GET /transcripts and POST export succeed.

### Reviewers' minor notes

- The worker uses the service role today, not the user's JWT. The claim that 'RLS guarantees only the org's rows' is therefore false. Isolation must come from explicit org filters, including child tables without org_id (thread_messages, review_cells). Your cross-org test is the right guard: make it cover every table.
- Round-trip into a fresh Supabase will fail on FKs to auth.users unless the importer creates placeholder auth users with the same UUIDs, or remaps them. Specify this.
- Under RBI e-mandate rules a pre-debit notification is required anyway. Align the 7-day reminder with the gateway's.
- Embeddings are model-specific. Include the model id in the manifest.
- Stripe sends a single invoice.upcoming event at a dashboard-configured lead time, not separate 30-day and 7-day events. The second reminder needs your own cron. Fix the test assumption.
- Running the export job with the owner's JWT will outlive the token's lifetime on large orgs. Use the existing ARQ pattern (service role with the job user's role re-checked) and document it.
- Exported HMAC identifiers from P46 are useless without the per-org key. Either export the key under owner control or say so in the README.
- Stripe sends invoice.upcoming once per period, at one configured lead time, so it can't drive both the 30-day and 7-day banners. Compute both from current_period_end in a cron.
- A long export on the user's JWT will outlive the token. Use the ARQ worker's listed service-role path with explicit org filters and the role re-check, and keep the 'zero org B rows' test.
- Duplicates P43's task_export_org. Merge them.
- Also export the README's DPDP warning and the licence flags per table.

