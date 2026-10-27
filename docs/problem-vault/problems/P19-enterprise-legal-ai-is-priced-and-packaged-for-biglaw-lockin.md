# P19. Enterprise legal AI is priced and packaged for BigLaw, locking out solos, small firms and nearly all Indian firms outside the top tier

**Severity:** high · **Size:** big · **Region:** Global, especially acute in India

**Who has it:** Solo practitioners, small and mid firms (2-50 lawyers), Indian district and High Court practitioners

## What goes wrong

Harvey and Legora publish no prices and sell quote-based contracts; third-party reports put Harvey around USD 1,200-2,000+ per seat per month with 20-25 seat minimums on 12-month terms (about USD 288,000-360,000 a year), with no self-serve sign-up or trial, and reportedly declined demos for small firms. CoCounsel tiers run about USD 360-784 per user per month. A 3-10 lawyer firm can't get in and falls back on consumer ChatGPT with confidentiality and fake-citation risk, while large firms like SAM roll out Harvey firm-wide. AI use grows much faster at large firms than solos.

## Evidence of scale

- Harvey publishes no pricing; leaked figures cite USD 1,200/seat/month (USD 399 reduced tier up to USD 2,400-2,500), 20-seat minimum on 12 months (about USD 288k/yr), no self-serve or trial, reportedly declined small-firm demos (competitor source). ([source](https://www.eesel.ai/blog/harvey-ai-pricing))
- Reported Harvey pricing about USD 1,200-2,000+/user/month, 12-month terms, floor of about 25 seats (about USD 360k/yr) (competitor source). ([source](https://www.vaquill.ai/blog/harvey-legora-cocounsel-pricing-reality))
- Harvey: unconfirmed 20-25 seat minimum and USD 1,200-2,000+/user/month (Harvey called one estimate 'wildly off'); targets firms and enterprise. ([source](https://www.bindlegal.com/resources/comparisons/harvey-pricing-2026/))
- ABA 2024 TechReport: 18% of solos use AI tools vs 30% at 10-49 lawyer firms and 46% at 100+. ([source](https://lawnext.com/2025/03/aba-tech-survey-finds-growing-adoption-of-ai-in-legal-practice-with-efficiency-gains-as-primary-driver.html))
- Manupatra survey (sponsored): implementation costs, ethical implications and shortage of skilled professionals are the main barriers to AI adoption in India. ([source](https://www.barandbench.com/news/ai-adoption-and-impact-legal-industry-indian-perspective))
- Shardul Amarchand Mangaldas announced a firm-wide Harvey partnership across seven offices (June 2025). ([source](https://www.barandbench.com/news/corporate/shardul-amarchand-mangaldas-announces-partnership-with-harvey-ai))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI are priced in USD per seat for US/UK large-firm work, with sales-led contracts and seat minimums. Clio and SpotDraft handle practice and contract management, not verified Indian litigation research. No tool offers transparent, usage-priced, single-seat or per-matter access in INR with verified Indian authority and an audit trail.

## Panel verdict

**Status:** solved (round 3)

**Effort:** L

### What software can fix

Software cannot make frontier models free, but it can fix the four things that shut a 1-10 lawyer Indian firm out:
1. Opaque, sales-led, seat-minimum pricing in USD.
2. No safe way for us to price low. Today we don't know what an org costs us: Claude tokens are only a global Prometheus counter in app/core/metrics.py, and in prompted-output mode only the last retry attempt is counted.
3. Payment rails that don't fit Indian practice. Stripe takes USD cards only; there is no UPI AutoPay and no GST tax invoice carrying the firm's GSTIN for input tax credit.
4. All-or-nothing subscriptions for district-court practitioners who need AI on three matters a month, not a seat.

We fix these with:
- a published INR plan catalog: Free, Solo (1 seat, no minimum), Chambers (per seat), a per-matter pass and prepaid credit packs;
- a per-org AI cost ledger that drives deterministic entitlements and budget caps;
- Razorpay UPI AutoPay alongside the existing Stripe flow;
- GST invoices computed in code;
- self-serve monthly cancellation;
- a rule that safety features are never paywalled.

Cheap, self-serve access has to stay a professional tool. AI features, paid plans and Matter Passes are available only to orgs whose buyer is verified as an enrolled advocate, an in-house legal department or a legal-aid institution. The verification gate is deterministic code plus a human reviewer, with no AI in it.

Round 3 fixes the non-lawyer exit path. A person who says they are not a lawyer gets only institutional routes: NALSA 15100, their DLSA or SLSA, Tele-Law, and the official website of their State Bar Council. The platform never names, lists, ranks or links to any individual advocate or firm, so the product never acts as a directory, referral channel or marketplace.

### What it can't fix

We cannot control Anthropic, Deepgram, Tavily or Indian Kanoon list prices. If they rise, the catalog must be re-priced; the ledger tells us when, but cannot prevent it.

At a solo price we cannot match Harvey's bespoke BigLaw features, or the proprietary headnotes of SCC Online and Lexis. Our research rests on the public SC corpus, Indian Kanoon and the firm's own material. Whether a firm can afford even INR 1,500/month is outside software.

Our CA confirms the GST classification (SAC code) and our own GST registration; the code only computes tax from the configured rates. Payment-gateway onboarding, the RBI e-mandate rules (additional factor of authentication for larger recurring debits) and chargebacks are handled by Razorpay and Stripe.

Advocate verification has hard limits:
- India has no official, machine-readable all-India advocate roll or API. State Bar Council rolls differ in format and availability, and some online lookups sit behind captchas, which we never bypass (the same stance as eCourts). The roll check is therefore a reviewer's manual lookup where a council publishes a roll, and a document review where it doesn't.
- A determined impostor with a forged certificate can pass document review. Duplicate-claim detection, name matching, the attestation, revocation and the audit trail reduce this risk; they cannot remove it.
- Bar Councils don't push suspensions and removals to us. We catch them only through the annual re-attestation, Certificate of Practice expiry and reports.
- If a verified advocate later misuses the tool, for example by handing raw output to a client without review, that is their professional responsibility under BCI rules. We enforce the review points we control; P11 and P21 own the in-product review gates.

For non-lawyers:
- We do not help a member of the public find or choose a lawyer. Whether NALSA, the DLSA or Tele-Law answers quickly is outside our control.
- Matching a person to a private advocate is deliberately not built, because under BCI Rule 36 it would be solicitation by the platform.
- A State Bar Council's own website may list advocates. That is the council's statutory function; we link only to the council's homepage, not to any search result or profile.

Adoption barriers other than cost that the Manupatra survey names (ethics anxiety, skills) belong to P11, P21 and P30.

### What the user sees

**Pricing page.** A public /pricing page in INR, generated from the same catalog the server enforces:
- Free: no card. Non-AI tools, plus a small monthly AI allowance once the firm is verified. Citation check, PII masking and the UPL disclaimer are included.
- Solo: 1 seat, monthly, cancel any time.
- Chambers: per seat, 2 or more seats, no minimum term.
- Matter Pass: all AI features on one case thread for 90 days, paid once by UPI.
- Credit top-ups.

Each plan lists exactly what is included (AI actions, review-grid cells, audio minutes) and the overage rate. The page says plainly that the product is for advocates, law firms, in-house legal teams and legal-aid bodies, and that AI features unlock after Bar Council enrolment is verified. Public pages (/pricing, sign-up, /about) carry no customer firm names, advocate names, logos or testimonials.

**Sign-up.** Sign-up asks 'I am:' with four options:
- **An advocate or law firm.** State Bar Council (dropdown), enrolment number, enrolment date, name as on the roll, an optional Certificate of Practice number, and an upload of the enrolment certificate, Bar Council ID card or Certificate of Practice.
- **A corporate legal department.** Company CIN or LLPIN, a work email on the company domain, the legal head's name and an authorisation letter.
- **A legal-aid institution or clinic.** An official email or authorisation letter, plus the enrolment of the supervising advocate.
- **Not a lawyer, I need help with my own matter.**
  - No account and no workspace are created, and the person is not asked to describe their matter.
  - A static page says that this product is a tool for lawyers, that we don't give legal advice to individuals, and that we don't recommend or refer anyone to a lawyer.
  - It lists only institutional routes:
    - the NALSA legal-aid helpline 15100;
    - the DLSA and SLSA for their state (the state is picked from a dropdown);
    - Tele-Law, through Common Service Centres;
    - a link to the official website of that State Bar Council.
  - Each route shows a one-line note on what it is (free legal aid under the Legal Services Authorities Act, for example), and the page shows a 'last reviewed' date.
  - The page has no search box, no list of lawyers and no 'contact a lawyer' button, and it names no advocate, firm or customer of ours.

Every professional path ends with a versioned attestation. For advocates it reads: 'I am enrolled as stated, I will use outputs as drafts for my own professional review, and I will not give access to clients or other unrepresented persons.'

**While verification is pending.** The workspace opens immediately with the non-AI tools: the case tracker, hearing calendar, code-computed workflow deadlines, document storage, the team page, the knowledge base without AI answers, and exports.
- AI buttons show 'Available after verification (usually within 1 working day)'.
- A status chip shows Pending, Needs more information (with the reviewer's reason) or Verified.
- Checkout for paid plans, Matter Passes and top-ups is disabled until the org is verified.

**After verification.** Owners see a Usage page: rupees of AI used this month by feature (consultation, drafting, review grid, research, OCR vision, audio), by member and by matter, with an optional monthly budget cap that they set.
- Before an expensive action (a 50 x 15 review grid, a bulk embed, a long OCR job), the button shows an estimate ('about 180 credits, you have 2,400 left') and asks the lawyer to confirm.
- When a cap or free allowance is reached, AI actions show 'allowance reached: top up or upgrade'. The lawyer can still open, export and download everything they have ever created.
- Checkout offers UPI AutoPay, cards and netbanking (Razorpay) or international cards (Stripe). The firm enters its GSTIN once, and every payment produces a downloadable GST tax invoice PDF.
- 'Cancel plan' is one button. It takes effect at period end, with no call to sales.
- An annual re-attestation prompt, and a reminder before the recorded Certificate of Practice renewal date, keep verification current.

**Reviewers.** Our own staff, listed in a platform_reviewers table, see a Verification Queue page. For each application it shows:
- the submitted fields;
- the deterministic check results (format, year match, name match, duplicate claims);
- the uploaded evidence;
- a link to the council's public roll search, where one exists.

The reviewer chooses Verify, Ask for more, Reject or Revoke, with a reason. Every decision is audit-logged.

### What the system does

0. **Non-lawyer exit (round 3 fix).** This path is static, institutional-only data and makes no database lookup of organizations or members.
   - GET /api/v1/public/legal-aid-routes?state=XX is unauthenticated and rate-limited. It returns a payload built only from app/core/legal_aid_routes.py, a reviewed, versioned registry. For each state code the registry holds:
     - the SLSA name and official URL;
     - the DLSA directory URL on the SLSA's or NALSA's own site;
     - the State Bar Council display name and official homepage URL, taken from the app/core/bar_councils.py registry;
     - the national entries: NALSA 15100 and the Tele-Law/CSC description and official URL;
     - reviewed_at.
   - Every URL must have an allowlisted host: a gov.in or nic.in host, or a host explicitly listed in that council's registry entry. A unit test enforces this.
   - The payload schema (LegalAidRoutes, a Pydantic model with extra='forbid') has no field that could carry an org, user, advocate, enrolment or firm.
   - The handler imports nothing from app/database.py and never calls Supabase. A test patches both clients and asserts zero calls.
   - The registry contains no person names: a test rejects honorific patterns and the 'Adv'/'Advocate' token. It also rejects any URL that points to a profile or search-result path. For example, a Bar Council entry must be a bare homepage with no query string and no '/advocate/' or '/search' path segments.
   - The frontend /help-not-a-lawyer page renders only this payload, has no free-text input and sets no tracking. The server keeps one aggregate daily counter per state for capacity planning. It stores no IP and no matter text.
   - If a sign-up is submitted with user_type=non_lawyer anyway, for example by direct API use, the migration 009 handle_new_user trigger, extended in 014, creates no organization and no membership. The user row is flagged non_professional, and every org-scoped route returns 403 with the same legal-aid payload link.
   - No referral, lead-routing or 'matching' table or endpoint exists. There is no firm-finder, and P08's intake hand-off is not wired to this path.
1. **Plan catalog** (app/core/plans.py, deterministic and versioned).
   - Each plan has an id and version, an INR price in paise, seat rules (min_seats, max_seats), included allowances (credits, review cells, audio minutes, matter scope), overage rates, a requires_verification flag (true for every AI allowance and every paid item), and gateway price or plan ids from settings.
   - GET /api/v1/billing/plans returns the catalog without authentication, and /pricing renders only from it, so displayed and enforced prices cannot diverge.
   - billing_accounts stores plan_id and plan_version, so a price change never silently re-prices an existing subscriber.
2. **Professional verification gate.**
   - **(a) Data.** Migration 014 adds three tables:
     - **advocate_enrolments:**
       - user_id, state_bar_council (a code from app/core/bar_councils.py) and enrolment_no, normalised to upper case;
       - enrolment_date, name_as_enrolled, and an optional cop_number and cop_valid_until;
       - evidence_path in a private Storage bucket 'verifications', with evidence_sha256;
       - attestation_version and attested_at;
       - status (pending, needs_info, verified, rejected or revoked), method (roll_lookup or document_review) and check_flags (jsonb);
       - reviewed_by, reviewed_at and reason.

       A partial unique index on (state_bar_council, enrolment_no), covering rows whose status is pending, needs_info or verified, means one enrolment can't back two people.
     - **org_verifications:**
       - org_id, org_type (advocate_practice, legal_department or legal_aid) and status;
       - basis: an enrolment id, a CIN/LLPIN plus a company domain, or a legal-aid authorisation;
       - reviewer fields, verified_at, and review_due_at (verified_at plus 12 months).
     - **platform_reviewers:** user_id only. Rows are inserted by migration or from the SQL console, never through the API.
   - **(b) Deterministic checks** (app/services/verification_service.py, pure functions run on submit). Results are stored in check_flags.
     - The council must be one of the State Bar Councils in the registry.
     - enrolment_no must match that council's configured pattern. Where a council's format isn't configured, a generic pattern applies: a 1-5 letter prefix, a number and a 4-digit year, separated by '/'.
     - The year in the number must equal the year of enrolment_date. A mismatch is flagged.
     - enrolment_date must fall between 1961-12-01 (the Advocates Act) and today. A future date is rejected.
     - name_as_enrolled, once normalised (case, spacing, honorifics removed, initials compared token by token), must match the account's full_name. A mismatch is flagged.
     - Any active claim on the same enrolment by another user is flagged, and both claims go to review.
     - The evidence file must be PDF, JPG or PNG and at most 5 MB. It is never sent to OCR vision or any AI.
     - For legal departments: the CIN must be 21 characters and match the MCA structure (LLPIN: 3 letters, '-', 4 digits). The work-email domain must not be on a free-mail blocklist and must equal the declared company domain.
     - Legal-aid bodies need a gov.in or nic.in domain, another listed institutional domain, or a supervising advocate's verified enrolment.
   - **(c) Human decision.** Automated checks never verify an org on their own; every application waits for a reviewer.
     - Where app/core/bar_councils.py marks a council as having a public roll search, the reviewer looks the advocate up and records method=roll_lookup with the roll entry's reference.
     - Otherwise the reviewer compares the certificate with the entered fields and records method=document_review.
     - Decisions go through two security-definer RPCs, list_verification_queue() and decide_verification(id, decision, reason). Both raise 42501 unless auth.uid() is in platform_reviewers. A reviewer can't decide their own application or one from their own org. So there is no new service-role use in a user-facing path (invariant 2).
   - **(d) Effective status.** The SQL function public.org_ai_enabled(org) is true only when:
     - org_verifications.status is 'verified', and review_due_at has not passed;
     - for advocate_practice orgs, the basis enrolment is also still 'verified' and belongs to a current owner or partner.

     Members invited into a verified org work under that advocate's supervision. The invitation adds an attestation that the invitee is firm staff, not a client, and is audit-logged.
   - **(e) Revocation.** If the basis advocate is revoked, leaves the org or lets re-attestation lapse, org_ai_enabled turns false immediately. Running live sessions poll the flag every 30 s and close gracefully with a notice. This is the only mid-session stop, because it is a legal-eligibility stop, not a billing one.
   - **(f) Evidence and privacy.** The existing worker cron deletes the evidence file 30 days after the decision. The extracted fields, the sha256 and the decision are kept.
3. **Cost ledger.**
   - metrics.record_claude_usage is extended to write one ai_usage row per API attempt, including prompted-mode retries. Each row carries org_id, user_id, feature, thread_id, model, the input, output, cache-read and cache-write tokens, and cost_micro_inr from the rate table.
   - The context comes from a contextvar set by OrgContext, from a feature tag on each limit('llm') router, and by the worker, telephony and WhatsApp jobs for their org.
   - Tavily and Indian Kanoon calls get fixed per-call cost rows; audio stays in audio_usage.
   - Rows hold counts only, never prompt or output text.
   - Rows are written through the service role under the existing usage-metering exception. Owners and partners read them through RLS.
4. **Credits.** One credit is a fixed micro-INR amount set in the catalog.
   - Usage converts to credits with integer arithmetic, rounding up per call.
   - Allowances, top-ups and matter passes are credit_grants rows, each with a source, amount, expiry, thread_id and status (active or held).
   - The balance is the sum of active grants minus the ledger, computed in SQL.
5. **Entitlements** (app/core/entitlements.py).
   - The dependency require_entitlement(feature, estimate) runs before:
     - every AI route;
     - every live-session start (WS audio, WebRTC offer, telephony stream, WhatsApp AI step);
     - telephony and WhatsApp number registration;
     - every paid checkout.
   - It is pure code, and it checks in this order:
     1. org_ai_enabled(org) holds, else 403 {reason: 'verification_required'};
     2. the plan includes the feature;
     3. the seat count is within the plan;
     4. a matter pass matches the request's thread_id and has not expired;
     5. the budget cap is not reached;
     6. the balance covers the estimate, else 402 with a machine-readable reason.
   - Estimates use count_tokens on the masked input where available, else characters/3.5 plus max_tokens.
   - Billing reasons never cut a live session mid-way. Paid plans keep CLAUDE.md's rule that overage is billed, not blocked.
   - Read, export, download, trash-restore and data-deletion routes are never gated.
   - Safety is never gated.
6. **Checkout and webhooks respect verification.**
   - Checkout, matter-pass and top-up requests return 403 verification_required before any gateway call.
   - If a payment still arrives for an org that isn't verified, the webhook records a 'held' credit_grant and queues the org for review.
   - If the org is later rejected, the payment is refunded through the gateway's refund API, with an audit row.
7. **Budget caps.** Owners set monthly_cap_inr. At 80% the owner gets one alert; at 100%, new AI actions return 402 budget_reached.
8. **Model routing for unit cost.**
   - Haiku handles extraction and classification; Sonnet handles drafting and summaries.
   - Prompt caching follows invariant 5, and embeddings stay local.
   - scripts/cost_report.py prints measured INR per action and per month, so the catalog is priced from measured cost.
9. **Indian payments** (services/razorpay_service.py).
   - Subscriptions use UPI AutoPay or e-mandate; passes and top-ups are one-off Orders.
   - The webhook verifies X-Razorpay-Signature (HMAC-SHA256 of the raw body), is idempotent through payment_events, and is exempt from the rate limiter.
10. **GST invoices** (services/gst_invoice.py, a pure function, then ReportLab).
    - The buyer's GSTIN is checked by regex and check digit.
    - Place of supply decides CGST + SGST or IGST, and tax is rounded to paise.
    - Invoice numbers are consecutive per financial year and at most 16 characters.
    - Invoices are immutable; corrections are credit notes. Downloads use signed URLs.
11. **No lock-in.** POST /billing/cancel sets cancel-at-period-end. A downgrade, or a lost verification, keeps all data readable and exportable.
12. **Audit.** Every billing and verification change is audit-logged. START_CHECKOUT already exists. New actions: CHANGE_PLAN, SET_BUDGET, CANCEL_PLAN, BUY_MATTER_PASS, SUBMIT_VERIFICATION, DECIDE_VERIFICATION, REVOKE_VERIFICATION, HOLD_PAYMENT, REFUND_UNVERIFIED.
13. **Existing orgs.** Migration 014 sets every existing org to 'unverified', with no grace period in code. Before the release reaches production, ops verify known paying customers from the enrolments they submit.

### Where it is built

Extend:
- app/services/stripe_service.py: plan catalog in place of TIERS/price_for/included_minutes; credit grants (held when unverified); cancel at period end; refunds for rejected orgs.
- app/routers/billing.py: GET /plans, POST /cancel, PUT /budget, POST /matter-pass, POST /topup, GET /usage/breakdown, GET /invoices and the Razorpay webhook. Checkout endpoints call require_entitlement('purchase').
- app/core/metrics.py record_claude_usage: ledger rows, with every retry attempt counted.
- app/services/anthropic_service.py: per-attempt ledger and feature tag.
- app/core/rate_limiter.py: exempt the Razorpay webhook; add a public-tier limit for /public/legal-aid-routes.
- app/core/config.py: Razorpay keys, supplier GSTIN and state, GST rate, credit value, rate table, VERIFICATION_EVIDENCE_RETENTION_DAYS.
- app/dependencies/org.py: contextvar for org, user, feature and thread. OrgContext gains ai_enabled; non_professional users get a 403.
- app/core/rbac.py: BILLING_MANAGE and VERIFICATION_SUBMIT.
- app/services/pdf_service.py: invoice layout.
- app/worker.py: evidence-retention cron, re-attestation and Certificate of Practice reminders, metering context.
- services/telephony_session.py and services/whatsapp_intake.py: verification check at the start of the AI step, and the 30 s revocation poll.
- app/routers/audio_stream.py and app/routers/webrtc.py: session-start entitlement and revocation poll.
- app/routers/telephony.py and app/routers/whatsapp*: number registration requires a verified org.
- services/review_service.py: estimate before a grid run.
- supabase/migrations/009 handle_new_user: extended in 014 so that user_type=non_lawyer creates no org.
- frontend sign-up form: the 'I am' selector and the enrolment fields.
- frontend/src/components/ConfirmDialog.tsx: cost confirmation.
- frontend/src/app/about/page.tsx: one line stating that we don't refer the public to lawyers.

New:
- app/core/plans.py
- app/core/entitlements.py
- app/core/bar_councils.py: State Bar Council registry with code, display name, official homepage URL, enrolment-number patterns, and the public roll search URL with whether it is captcha-free. Reviewed data, not scraped.
- app/core/legal_aid_routes.py: NALSA, SLSA/DLSA, Tele-Law and Bar Council homepage per state. Reviewed and versioned, with an allowlisted host for every URL and no person or firm names.
- app/routers/public_help.py: GET /api/v1/public/legal-aid-routes, built from static data with no database access.
- app/services/verification_service.py
- app/routers/verification.py
- app/services/usage_ledger.py, app/services/razorpay_service.py and app/services/gst_invoice.py
- scripts/cost_report.py and evals/fixtures/solo_month.json
- supabase/migrations/014_inr_plans_usage_ledger_gst_and_verification.sql:
  - plan_tier gains 'solo' and 'chambers';
  - new tables: ai_usage, credit_grants, payment_events, gst_invoices, billing_profiles, advocate_enrolments, org_verifications, platform_reviewers;
  - new columns on billing_accounts;
  - users.non_professional;
  - functions org_ai_enabled, submit_enrolment, list_verification_queue and decide_verification;
  - private bucket 'verifications';
  - RLS policies.
- frontend/src/app/pricing/page.tsx
- frontend/src/app/help-not-a-lawyer/page.tsx: renders only the legal-aid-routes payload; no inputs and no lawyer listing.
- frontend/src/app/usage/page.tsx and components/UsagePage.tsx
- frontend/src/app/verification/page.tsx
- frontend/src/app/admin/verifications/page.tsx
- frontend/src/components/AiGate.tsx

### Why current tools fail and this won't

- **Harvey and Legora** sell quote-based, 12-month, 20-25 seat USD contracts with no self-serve. They never reach a 3-lawyer Saket or Dharwad practice. They verify buyers through enterprise sales, which is what makes them expensive.
- **CoCounsel and Lexis+ AI** price per user in USD, above an Indian solo's AI budget, and their content is built for US and UK law.
- **SCC Online and Manupatra** sell annual subscriptions, and their AI layers ride on those.
- **India-built AI assistants** mostly charge flat subscriptions without metering. Several are sold openly to the public as 'AI lawyers'. Others run lawyer directories and 'consult a lawyer' marketplaces, which is the solicitation exposure that BCI notices and P.N. Vignesh target.
- **Clio and SpotDraft** are practice and contract management, not verified litigation AI.

Ours won't fail in the same ways:
- The price comes from a measured per-action cost ledger.
- The cost base is lean by construction: Haiku routing, caching, local embeddings, the free SC corpus and no sales team.
- Metering lets a light user pay per matter.
- The payment rails are Indian: INR, UPI AutoPay and GST invoices.
- Self-serve doesn't mean consumer-serve. A lightweight enrolment check with a human reviewer replaces the enterprise sales gate, so a solo advocate gets in within a working day.
- An unrepresented litigant is sent only to statutory legal-aid institutions and their Bar Council's own site. They are never matched with, or shown, a private advocate.

The product has no directory, marketplace or referral feature, and the guardrails run on every tier.

### Safeguards

- **UPL and BCI.**
  - AI features, paid plans and Matter Passes are sold only to verified advocate practices, in-house legal departments and legal-aid institutions. The gate is the first check in require_entitlement, and a route-walk test enforces it.
  - Self-identified non-lawyers get no workspace and only statutory, institutional routes: NALSA 15100, SLSA/DLSA, Tele-Law and the State Bar Council's official homepage.
  - The platform never names, lists, ranks, matches or links to any individual advocate or firm. Public pages carry no customer names or testimonials. There is no directory, marketplace, lead routing or referral fee anywhere (BCI Rule 36, consistent with P33).
  - Client-facing telephony and WhatsApp intake run only for verified orgs, on that firm's own number, reached by people who already contacted that firm. We never route anyone to them.
  - Revocation, the supervising advocate leaving, or a lapsed re-attestation switches AI off.
  - Attestations forbid giving access to clients, and invitations carry a staff-not-client attestation.
- **Human approval points.**
  - Only a platform reviewer can verify an org, through definer RPCs that refuse self-review.
  - Only owners (BILLING_MANAGE) buy, change plans, set caps or cancel.
  - Bulk runs need an explicit confirmation.
  - The legal-aid registry changes only through a reviewed code change, with reviewed_at enforced.
- **Safety is never premium.** PII masking, citation grounding, the UPL disclaimer and quote verification run on every tier.
- **Data access is never gated.** Read, export, delete and restore work regardless of plan or verification, so DPDP rights are not paywalled.
- **DPDP.**
  - Verification collects only what it needs. Evidence stays in a private bucket, is never sent to AI, and is deleted 30 days after the decision.
  - The non-lawyer path stores no personal data and no matter text, only an aggregate per-state daily counter.
  - The cost ledger stores counts and ids only, and card and UPI data stay with the gateway.
- **RLS and service role.**
  - Verification uses definer RPCs, not the service role.
  - The public legal-aid endpoint touches no database.
  - Service-role writes fall only under the existing webhook and usage-metering exception, extended by name to Razorpay and the ledger.
- **Webhooks.** They are signature-verified and idempotent. A payment from an unverified org is held, and refunded if the org is rejected.
- **Audit.** Every billing and verification decision is in audit_logs.
- **Pricing display.** Prices state GST explicitly.
- **No AI in the gate.** Every number and status is computed by code or decided by a named human.

### How the panel's objections were answered

**Blocking objection (round 3).** The non-lawyer sign-up path showed 'the firm-finder from P08'. That would be a referral channel under BCI Rule 36, would contradict P33, and is undefined in the P08 page.

Fixed as follows:
1. **Removed.** The firm-finder is gone from the non-lawyer path and from the whole proposal, and nothing in P19 depends on P08 for that path.
2. **Institutional routes only.** The path now shows only NALSA 15100, the state's SLSA and DLSA route, Tele-Law, and a link to the State Bar Council's own official homepage. The links come from a reviewed static registry (app/core/legal_aid_routes.py) with allowlisted gov.in, nic.in or council hosts. Bar Council links must be bare homepages, never search or profile URLs.
3. **No advocate or firm named.**
   - The endpoint makes no database call.
   - Its schema forbids extra fields and has no field that could carry an org, advocate or firm.
   - The page has no inputs, search or 'contact a lawyer' control, and states that we don't refer anyone to a lawyer.
   - Public pages carry no customer names or testimonials.
   - No referral, matching or lead table or endpoint exists.
   - A non_lawyer sign-up sent directly to the API creates no org.
4. **Tests.**
   - **test_non_lawyer_payload_has_no_lawyer_identifiers:** the schema has no identifier keys; no seeded org, user, enrolment, firm name, email or phone appears in the payload; and both Supabase clients record zero calls.
   - **test_routes_are_institutional_only:** host allowlist, bare homepages and no person names.
   - **test_no_referral_surface:** route walk plus a grep for firm-finder, directory and referral wording.
   - **Frontend test:** the help page has no inputs and only the payload's links.

**Round 2 objection (unverified buyers).** Still fixed by the verification gate in step 2, with tests test_unverified_org_blocked_on_every_ai_route and test_unverified_cannot_buy. Nothing about it changed this round.

### Acceptance tests

- tests/test_public_help.py::test_non_lawyer_payload_has_no_lawyer_identifiers:
- For every state code, GET /api/v1/public/legal-aid-routes validates against LegalAidRoutes (extra='forbid').
- Its JSON contains no keys matching org|user|advocate|enrol|firm|member|lawyer_id.
- With seeded test orgs, users, enrolments and organization_members, none of their ids, names, firm names, enrolment numbers, emails or phone numbers appears anywhere in the serialised payload.
- The mocked Supabase user and admin clients record zero calls.
- tests/test_public_help.py::test_routes_are_institutional_only:
- Every URL in app/core/legal_aid_routes.py has a gov.in or nic.in host, or a host on that council's allowlist in bar_councils.py.
- Bar Council links are bare homepages: no query string, and no 'advocate', 'profile', 'search' or 'directory' path segment.
- No string in the registry matches the honorific/'Adv'/'Advocate <Name>' pattern.
- NALSA 15100 and Tele-Law are present for every state.
- reviewed_at is set and less than 12 months old (frozen clock).
- tests/test_public_help.py::test_no_referral_surface: a route walk over app.routes finds no endpoint under /public, /help or /signup that accepts free text or returns an org or advocate record. A grep over app/ and frontend/src/ for 'firm-finder', 'find a lawyer', 'lawyer directory' and 'referral' outside tests and docs returns nothing.
- tests/test_signup_paths.py:
- A sign-up with user_type=non_lawyer through the 014 handle_new_user trigger creates no organization and no organization_members row, and sets users.non_professional.
- Every org-scoped route then returns 403, with a link to /help-not-a-lawyer.
- Advocate sign-up stores attestation_version and attested_at.
- Telephony and WhatsApp number registration by an unverified org returns 403.
- frontend: a test renders /help-not-a-lawyer from a mocked payload and asserts there are no <input>, <textarea> or search elements. The only links are those in the payload. The text states that we do not recommend or refer anyone to a lawyer. /pricing, sign-up and /about contain no customer firm or advocate names.
- tests/test_verification_gate.py::test_unverified_org_blocked_on_every_ai_route:
- A route walk collects every route that is an AI route or a live-session start.
- For unverified, pending and needs_info orgs, each returns 403 verification_required, and the mocked Anthropic, Deepgram and Tavily clients record zero calls.
- The set of gated routes must equal the set of AI routes, so a new AI route without the gate fails CI.
- tests/test_verification_gate.py::test_unverified_cannot_buy: POST checkout-session, matter-pass and topup return 403, and the mocked Stripe and Razorpay create calls are never invoked.
- tests/test_verification_gate.py::test_non_ai_features_work_unverified: an unverified org gets 200 on case tracker CRUD, the hearing calendar, code-computed workflow deadlines, document upload and download, the team page and exports.
- tests/test_verification_gate.py::test_verified_then_revoked:
- After verification, /drafting/generate succeeds; after revocation it returns 403.
- An open WS session closes within one 30 s poll tick (simulated clock).
- A session in budget overrun is not closed.
- tests/test_verification_gate.py::test_basis_advocate_leaves: org_ai_enabled is false when the basis owner or partner leaves the org, and false when review_due_at has passed (frozen clock).
- tests/test_verification_service.py:
- Council patterns pass for valid numbers.
- A year mismatch sets a flag.
- A date before 1961-12-01 or in the future returns 422.
- The name matching cases from the earlier round give the expected flags.
- duplicate_claim is set on both claims.
- An invalid CIN and a gmail.com work email are rejected.
- An oversized or wrong-MIME evidence file is rejected.
- The module does not import anthropic_service or ocr_service.
- tests/test_migration_014.py (embedded Postgres):
- A non-reviewer calling the queue or decide RPCs gets 42501, as does a reviewer acting on their own application or their own org's.
- Users cannot update status columns directly.
- The partial unique index rejects a second active claim.
- Cross-org reads are blocked.
- Associates and paralegals cannot read billing rows.
- The 'verifications' storage policy holds.
- plan_tier accepts 'solo' and 'chambers'.
- tests/test_webhook_held_grant.py:
- A payment for an unverified org creates a held grant, and the balance is unchanged.
- On verification, the grant is activated once.
- On rejection, a refund is issued once and audit-logged.
- A replayed event changes nothing.
- tests/test_evidence_retention.py: evidence is deleted 30 days after the decision, and the fields and sha256 are kept. Pending evidence is not deleted.
- tests/test_plans.py: the catalog has integer paise prices and the requires_verification flag. The pricing snapshot equals the catalog. Every paid plan has a gateway price id or is marked unavailable.
- tests/test_usage_ledger.py:
- A single attempt writes one ai_usage row whose cost matches a hand computation.
- Two failed parses followed by a success write three rows.
- No row contains prompt or output text.
- A metering failure never fails the request.
- tests/test_entitlements.py:
- A Free org at its allowance gets 402 on drafting and 200 on exports and restore.
- A Solo org gets 402 seat_limit for a second member.
- A matter pass returns 402 matter_scope on another thread.
- A 91-day-old pass is rejected.
- verification_required is checked before any 402.
- tests/test_entitlements.py::test_live_session_not_cut_for_billing: the session continues past a negative balance, and the next session start is refused for a Free org.
- tests/test_safety_never_gated.py: on every plan, including zero balance, mask_pii runs before Anthropic, the citation check runs, and the disclaimer is appended. No safety endpoint carries a billing gate.
- tests/test_budget_cap.py: exactly one 80% alert, 402 at 100%, only BILLING_MANAGE can set the cap, and every change is audit-logged.
- tests/test_estimate.py: the grid estimate is deterministic, and a run is refused before any Claude call when the balance is below the estimate.
- tests/test_gst_invoice.py: CGST + SGST for an intra-state supply, IGST for an inter-state supply, check-digit rejection, paise rounding, a consecutive FY sequence that restarts in April, and idempotent regeneration.
- tests/test_razorpay_webhook.py: signature check, replay de-duplication, the charged/halted transitions, and exemption from the rate limiter.
- tests/test_cancel_and_downgrade.py: data remains listable and exportable after cancellation and after revocation.
- scripts/cost_report.py --fixture evals/fixtures/solo_month.json prints INR per action and per month, and CI asserts the Solo cost-to-price ratio stays under the configured ceiling.
- frontend: npm run lint and npm run build pass with /pricing, /usage, /verification, /admin/verifications and /help-not-a-lawyer. AiGate states are tested.

### Reviewers' minor notes

- Merge the per-attempt ai_usage ledger with P20's ai_use_ledger and guarded_call, so cost and attribution come from one row per call.
- In-house lawyers who are full-time employees generally have their enrolment suspended (BCI Rule 49), so the legal-department path must not ask for or rely on enrolment. As designed, it rightly relies on CIN and domain.
- The enrolment-number year check should stay a flag only. Several councils' numbers carry the year of application or roll entry, which can differ from the enrolment date.
- Setting every existing org to unverified with no grace period in code depends entirely on ops finishing before release. Add a release checklist gate, or a one-time owner banner, so paying customers don't lose AI without notice.
- Migration 014 collides with P09 and P20.
- The host allowlist test will fail on real institutional URLs that are not on gov.in or nic.in. Tele-Law's portal is on tele-law.in, and several State Bar Councils use .org or .com domains. Keep an explicit reviewed allowlist for the national entries as well as the per-council ones.
- In-house legal department members are not practising advocates (BCI Rule 49). The attestation for org_type legal_department should say that outputs are for the employer's internal use, not for third parties or the public.
- Migration 014 collides with P09 and P20. Renumber.
- test_routes_are_institutional_only will fail on real data. Tele-Law (tele-law.in) and several SLSAs (e.g. Delhi SLSA at dslsa.org) aren't gov.in or nic.in hosts. Keep a reviewed per-entry host allowlist for SLSA, Tele-Law and Bar Council entries, not only for councils.
- Setting every existing org to 'unverified' with no grace period turns AI off for current paying customers on deploy unless ops finish first. Gate the release on that checklist, or add a time-boxed grace period audited per org.
- P09 and P19 both add Razorpay webhooks: ours for subscriptions, and the firm's own account for client fees. Keep the routes, secrets and idempotency tables distinct.
- Migration 014 collides with P09 and P20.

