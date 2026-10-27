# P09. Fees are agreed orally, paid late or never, and Indian advocates must go to slow civil suits to recover them

**Severity:** critical · **Size:** big · **Region:** India (and global small firms)

**Who has it:** Solo advocates, small litigation chambers, government and PSU panel counsel; retail clients who want to pay in instalments

## What goes wrong

Many Indian litigators charge an advance and a final fee, or per appearance, often in cash or UPI instalments, tracked in a diary or Excel, with no signed terms or itemised invoices. Once the matter ends or the next date is a year away, clients stop paying or dispute the balance. Advocates can't keep the file as security (no lien, per R.D. Saxena) or stall the case (the Kerala HC imposed Rs 50,000 costs for trying). High Courts send fee disputes to civil courts, so recovery is a slow suit, even against government departments and PSUs whose panel counsel wait years. Without matter-wise records of appearances and work, the advocate struggles to prove what is owed.

## Evidence of scale

- Kalyan civil court (ex parte) ordered a client to pay the Rs 35,000 balance of a Rs 50,000 agreed fee with 6% interest (18% sought). ([source](https://www.freepressjournal.in/mumbai/kalyan-court-orders-client-to-pay-35000-pending-legal-fee-with-6-per-cent-interest-to-advocate))
- Delhi HC (July 2026): unpaid agreed fees may be adjusted from a client's compensation, but the balance must be returned promptly. ([source](https://www.scconline.com/blog/post/2026/07/07/delhi-high-court-advocate-fees-client-compensation/))
- Uttarakhand HC urged litigants to pay lawyers by cheque, draft or online banking and asked the State Bar Council to frame fee rules. ([source](https://www.barandbench.com/news/uttarakhand-hc-litigants-pay-lawyers-cashless))
- Invoice-format guide: advocate fees are usually split into advances and final fees; some charge a filing advance of 10-20%. ([source](https://vyaparapp.in/invoice-formats/advocate))
- Kerala HC (2026): an advocate can't halt proceedings or hold files until fees are paid; Rs 50,000 costs for stalling an award about ten months; fee disputes belong in a civil court. ([source](https://www.verdictum.in/court-updates/high-courts/kerala-high-court/2026ker31575-mary-help-john-david-j-v-jv-anoop-1611880))
- Allahabad HC deprecated the State's failure to pay its counsel but dismissed four writs claiming about Rs 4.8 crore, with liberty to approach a civil court. ([source](https://www.livelaw.in/high-court/allahabad-high-court/allahabad-high-court-deprecates-state-failure-pay-counsels-fee-rejects-claim-546404))
- Delhi HC criticised DDA for holding up an advocate's fees and held a writ is maintainable against State instrumentalities. ([source](https://www.barandbench.com/news/delhi-high-court-pulls-up-dda-for-not-paying-advocates-fee))
- Delhi HC ordered the Centre, Delhi government and departments to clear empanelled lawyers' bills raised before 1 Feb 2020 within 4 weeks, warning it would stop the finance secretary's salary. ([source](https://indialegallive.com/top-story/pay-panel-lawyers-fees-in-4-weeks-or-will-stay-finance-secys-salary-delhi-hc-warns-govt/))
- Clio: payment plans linked to 27% more billings and 71% more collections; nearly 40% of solo firms offer no payment plan; 81% of consumers find payment plans attractive. ([source](https://canadianlawyermag.com/resources/practice-management/solos-and-smalls-excel-in-finding-new-business-but-lag-in-turning-it-into-billables-clio-report/386381))

## Why current tools don't solve it

Clio Payments, LawPay and Clio-style billing assume hourly entries, trust accounting and cards; no UPI mandates, GST/reverse-charge invoices or Indian-language reminders. Indian billing apps produce GST invoices but no evidence trail: BCI-compliant engagement terms (no contingency or share of recovery, per B. Sunitha), a per-appearance work log tied to cause-list dates, and dated reminders that hold up in a recovery suit. Harvey and CoCounsel have no billing function.

## Panel verdict

**Status:** solved (round 4)

**Effort:** L

### What software can fix

Making fee terms provable, the balance collectable without a fight, and the advocate's accounts of client money correct under BCI Rules 25-30. The parts:
(1) Written engagement terms, checked against BCI Rules 12, 20 and 25-30, that the client acknowledges on WhatsApp before work starts. Each fee model states, in the agreement itself, how the earned part of the fee is decided.
(2) A matter-wise, append-only ledger, hash-chained in the database, with two separate accounts: a FEE account (appearances, work, stages, invoices, fee and reimbursement payments) and a CLIENT-MONEY account (expense deposits, disbursements, money received on the client's behalf, payouts, refunds).
(3) INR/GST-correct invoices with UPI pay links and instalment schedules. Each link is tagged fee or expenses.
(4) Payment capture that is honest about where it comes from. Only Razorpay payments are recorded and tagged automatically (by webhook). Payments made straight to the advocate's own UPI VPA are recorded by hand on a form prefilled from the link, or matched against an uploaded bank or UPI statement, and the lawyer confirms every match.
(5) Polite, dated reminders from fixed templates, a Rule 27 intimation for every receipt, and a lawful, lawyer-approved notice of intended withdrawal.
(6) A recovery pack with one defined claim formula, and a Rule 30 statement of account.

### What it can't fix

* No software can make a client pay, give an advocate a lien over files (R.D. Saxena), or speed up a civil suit.
* Government and PSU panel bills move at the department's pace. We only age them, follow up, and assemble the writ or suit record.
* How much of a fixed fee or retainer has been earned is the advocate's professional assessment under Rule 12. The software records it with the lawyer's reason and never computes it.
* Whether withdrawal is justified, whether the court's leave is needed, when to withdraw, and whether a proceeding has 'terminated' for Rules 28/29 are the advocate's decisions.
* We do not hold client money, run escrow or operate a trust account. Holding funds would need RBI payment-aggregator licensing.
* NPCI and the payer's UPI app send no notification to a third party when someone pays a personal or business VPA directly. Those payments therefore cannot be captured automatically. Some payer apps also drop the transaction note (tn), so a statement line can stay unmatched, and the lawyer then picks the match by hand.
* We never compute GST liability as tax advice. The firm's CA reviews the rule table.
* Whether to sue, and whether an Order XXXVII summary suit is available, is the lawyer's decision.
* The ledger is only as complete as what the advocate records.

### What the user sees

On a matter (case thread), a 'Fees' tab with FEES and CLIENT MONEY (EXPENSES) panels side by side.

Setup: the lawyer picks a fee model: fixed, stage-wise, per appearance, monthly retainer, hourly, or a combination of components. The setup form asks only for what that model needs:
* Stage-wise: a table of stages, each with an amount or a percentage. The form will not save until the amounts add up to the total fee, or the percentages to 100.
* Per appearance / hourly: the rate.
* Fixed / retainer: the amount, plus a fixed line in the terms: 'If the engagement ends early, the earned part of the fee will be assessed by the advocate, and any unearned balance refunded.'

The app shows the engagement terms in English and in the client's language. After the lawyer approves them, the client receives them on WhatsApp ('Reply AGREE to accept'). The terms keep the round-3 fixed clauses: no lien, civil court for fee disputes, withdrawal on notice with the court's leave where required, client money kept separate, and Rule 27/30 intimation and accounts.

FEES panel:
* hearings from the case tracker as 'Appearance 14 Nov - confirm?'
* stage checkboxes ('Written statement filed - mark complete', which needs the lawyer's confirmation and an optional order or document reference)
* invoices with GST treatment and a 'Fee' UPI QR code
* fee payments and reimbursement payments
* reminders with delivery ticks
* Outstanding (receivable), ageing, and 'Earned so far'. For fixed and retainer models, 'Earned so far' shows 'Not assessed' until the lawyer assesses it; for the other models it shows the computed figure with its basis ('6 confirmed appearances x Rs 5,000').

CLIENT MONEY panel: unchanged from round 3. It shows deposits, disbursements with receipts, receipts on the client's behalf with intimation ticks, payouts, refunds and the balance held. Overflow shows as 'Expenses advanced by you: Rs 2,000 - not yet invoiced [Add to next invoice]'.

'Record payment' (for UPI paid directly to the VPA, cash or cheque): the lawyer picks the invoice or expense link it pays, and purpose and reference are prefilled from that link (for example 'INV2627-0042 / Fee' or 'EXP-M17 / Expenses'). The lawyer can also enter the UTR. Purpose can never be left blank. If the payment covers an invoice with reimbursable lines, the screen shows how it will be split ('Rs 2,000 reimbursement, Rs 8,000 fee') before the lawyer saves it.

'Match bank statement': an owner or partner uploads a CSV or PDF statement. The app lists the lines it can match:
* 'Rs 10,000 - UTR 4321... - narration contains INV2627-0042 - Fee - Confirm' (matched by reference)
* lines matched by amount and date only, marked 'Low confidence - pick the matter'
* unmatched lines, which are discarded
Nothing is posted until the lawyer confirms each line.

Razorpay payments show a 'Recorded automatically' chip. Direct-VPA payments never show that chip.

Withdrawal or termination: the 'Notice of intended withdrawal' action opens the fixed template. For a fixed fee, a retainer or a fixed component, it first shows a required step: 'Earned portion (advocate's assessment): Rs ____' and 'Reason' (at least 20 characters). The approve button stays disabled until both are filled. The notice then prints:
* 'Earned portion (advocate's assessment): Rs 45,000'
* 'Unearned fee advance to be refunded: Rs 15,000'
* 'Unexpended expense deposit to be returned: Rs 6,000'
* the total refund
For stage-wise, per-appearance and hourly models, the earned figure is printed with its basis ('Stages 1-2 complete: 30% of Rs 2,00,000'). The court-leave warning for a hearing inside the notice period stays.

The Recovery pack and the Rule 30 statement have two sides:
* CLAIM: amounts invoiced minus amounts received, plus interest.
* REFUND SIDE: the unearned advance, the client money held, and any credit balance.
Every term of the formula is printed. If earned work has not been invoiced, a warning says so: 'Earned but not invoiced: Rs 12,000 - raise an invoice to include it in the claim'.

### What the system does

1. Migration 014_fees_and_ledger.sql. It keeps the round-3 structure (fee_agreements, ledger_heads, append-only ledger_entries with account/kind CHECKs, the hash-chain trigger, the no-update/delete trigger, expense_appropriations with its guard trigger, payments, invoices, fee_reminders, panel_bills) and changes or adds the following.
   a. fee_components (agreement_id, model in fixed|stage_wise|per_appearance|monthly_retainer|hourly, amount_paise or rate_paise, earning_basis). earning_basis is fixed by a CHECK from the model: stage_wise -> stages; per_appearance -> confirmed_appearances; hourly -> approved_time; fixed and monthly_retainer -> advocate_assessment. An agreement is one or more components.
   b. fee_stages (component_id, ordinal, label, amount_paise, completed_at, completed_by, evidence_ref). A deferred constraint trigger refuses to approve an agreement whose stage amounts do not sum exactly to the component's total. Percentages are converted to paise at setup, with the remainder put on the last stage, so the stored amounts always add up exactly. A stage counts as earned only once a lawyer marks it complete, which writes a 'stage_complete' ledger entry.
   c. time_entries (component_id, minutes, approved_by) for the hourly model. Only approved entries count, each written as a 'work' ledger entry.
   d. earned_assessments (component_id, earned_paise, reason text CHECK length >= 20, assessed_by, assessed_at, occasion in withdrawal|termination|statement). Each assessment is written as an 'assessment' ledger entry (an account-neutral kind) and is therefore hash-chained. A later assessment supersedes an earlier one by appending a new entry; nothing is edited. Only owner, partner or the matter's responsible advocate may insert one (RLS plus a role check).
   e. Payment purpose is NOT NULL in fee|reimbursement|expenses|on_behalf, and payments gain capture_method in razorpay|manual|statement_match|cash_cheque. The fee-account kinds become fee_payment, reimbursement_payment and fee_refund. reimbursement_payment repays the advocate's own money and never counts toward fee received or the unearned advance.
   f. payment_links (link_id, ref like INV2627-0042 or EXP-M17, purpose, invoice_id or thread_id, vpa). The tn field carries only the ref.
   g. statement_imports (id, uploaded_by, sha256, uploaded_at) and statement_candidates (import_id, utr, txn_date, amount_paise, ref_found, matched_link_id, confidence in ref|amount_date, status in proposed|confirmed|rejected). payments.utr is unique per org, so the same UTR is never posted twice.
2. Earned and unearned, computed per component by both services/fee_earnings.py and the SQL function earned_by_component(), which tests assert agree:
   * stages: the sum of the amounts of completed stages
   * confirmed_appearances: the count x rate
   * approved_time: the minutes x rate / 60, in paise, half-up
   * advocate_assessment: the latest assessment's earned_paise, or NULL if none exists
   earned_total is NULL if any component's earned figure is NULL.
   fee_received = fee_payments + expense_appropriations - fee_refunds.
   fee_advance_unearned = max(0, fee_received - earned_total). It is NULL when earned_total is NULL, and is then displayed as 'Not assessed', never as 0.
3. Receivable and claim, defined once:
   * billed = confirmed invoice fee lines + confirmed invoice reimbursable_expense lines
   * receipts = fee_payments + reimbursement_payments + expense_appropriations - fee_refunds
   * receivable = billed - receipts
   * claim_principal = max(0, receivable)
   * credit_balance = max(0, -receivable)
   * claim = claim_principal + interest
   expenses_advanced_by_advocate appears in the claim only through the reimbursable_expense invoice lines it became. It is never added again. Overflow not yet invoiced is shown as a warning, not claimed.
   The refund side = fee_advance_unearned (or 'Not assessed') + client_money_held. credit_balance is printed as a cross-check, and any difference from the unearned advance is explained by the printed 'earned but not invoiced' line.
   The view matter_balances and services/ledger.balances() both compute billed, receipts, receivable, claim_principal, credit_balance, fee_received, earned_total, fee_advance_unearned, client_money_held and uninvoiced_overflow, and tests assert that they agree.
4. Allocation and interest: services/ledger.allocate() is a deterministic waterfall. Receipts are applied to open invoices in due-date order, and within an invoice to reimbursable lines first, then fee lines.
   * A payment made through an invoice link is applied to that invoice first.
   * An invoice payment is split, at entry time, into a reimbursement_payment entry and a fee_payment entry according to the waterfall. The split is shown before saving and is part of the hashed payload.
   * Interest is simple, at the agreement's rate, on unpaid fee-line balances only, from each due date. It is never charged on reimbursables (unless a CA-reviewed agreement option says otherwise) or on client money. It is 0 if the agreement has no rate.
5. Withdrawal notice gate: the approvals record for notice_intended_withdrawal_v1 (migration 013 approvals) cannot be created while fee_advance_unearned is NULL. Both the API check in app/routers/fees.py and a CHECK in the approval insert function enforce this. The rendered notice prints the earned figure with its label ('advocate's assessment' or the computed basis), the unearned refund, the client-money refund and the total. The recovery pack and the Rule 30 statement can be produced as DRAFT before an assessment exists, with the refund side marked 'Not assessed'. A FINAL pack for an assessment-based component requires one.
6. Payment capture:
   a. Razorpay (the only automatic path): the webhook is signature-checked and idempotent (razorpay_events, mirroring stripe_events). Purpose comes from notes.purpose and notes.link_ref and is resolved against payment_links on the server, never trusted from the client. The payment is posted with capture_method 'razorpay'.
   b. Direct VPA: services/upi.py only builds the intent link and QR code. No ledger entry is ever created when a link is generated or opened. The 'Record payment' API requires a link_ref or an explicit purpose. It prefills purpose and invoice from payment_links and stores capture_method 'manual' with an optional UTR.
   c. Statement matching: services/statement_match.py parses CSV exports of the major banks (SBI, HDFC, ICICI, Axis, Kotak) with fixed column maps, plus text PDFs through the existing pypdfium2 extraction.
      * Each credit line is matched against payment_links refs by an exact regex on the narration (INV\d{4}-\d{4} / EXP-M\d+), and must have an equal amount, to give confidence 'ref'.
      * Otherwise, an open invoice or link with an equal amount, dated within 3 days of the link's creation or the invoice's due date, gives confidence 'amount_date'. It is never auto-selected when two candidates exist.
      * Only candidate rows are stored. Unmatched lines and the raw file are discarded after parsing, and only the file's hash is kept. Confirming a candidate posts a payment with capture_method 'statement_match' and its UTR. A UTR already posted is refused.
7. Unchanged from round 3: DB-side hash chain under the ledger_heads row lock; SQL and Python verifiers; appropriation guard (Rule 26 consent or Rule 28 termination with a settled invoice, plus approval); Rule 27 intimations by fixed template, idempotent per receipt, with email/print fallback after STOP; task_capture_appearances from court_cases; versioned GST rule table reviewed by the CA; gap-free invoice numbers per financial year; reminder_guard; reminders that ask only for the receivable, never client money; Rule 30 statement and recovery pack as ReportLab PDFs with separate fee, client-money and communications sections; draft s.63 BSA certificate blocked when the chain fails to verify.

### Where it is built

Extend:
* 011_court_cases.sql (hearing dates)
* 012_whatsapp_intake.sql and app/services/whatsapp_service.py (terms acknowledgement, intimations, delivery receipts)
* 013_approvals_trash_and_intake.sql approvals (terms, reminder schedule, appropriations, assessments, withdrawal notices; the ledger and invoices excluded from trash purge)
* app/services/pdf_service.py (invoice, statement and pack)
* the app/services/stripe_service.py verify_webhook + stripe_events pattern, for Razorpay
* app/services/ocr_service.py / pypdfium2 text extraction (statement PDFs)
* app/services/document_service.py (receipts, consent documents)
* app/worker.py cron (task_capture_appearances, task_fee_reminders, task_receipt_intimations)

New:
* supabase/migrations/014_fees_and_ledger.sql: adds fee_components, fee_stages, time_entries, earned_assessments, payment_links, statement_imports, statement_candidates and the earned_by_component() function to the round-3 tables, triggers and the matter_balances view
* app/services/fee_terms.py, fee_earnings.py, ledger.py (insert wrapper, verifier, balances(), allocate(), interest()), statement_match.py, gst_rules.py, upi.py, reminder_guard.py, client_money.py
* app/routers/fees.py, app/routers/razorpay_webhook.py
* frontend/src/components/FeesTab.tsx, RecordPaymentDialog.tsx, StatementMatch.tsx, EarnedAssessmentStep.tsx; frontend/src/app/fees/page.tsx
* tests/test_fee_models.py, test_claim_formula.py, test_payment_capture.py, test_fees_ledger.py, test_client_money.py, tests/db/test_ledger_concurrency.py
* fixtures tests/fixtures/statements/*.csv and evals/gst_rules.json

### Why current tools fail and this won't

* Clio Payments and LawPay assume US IOLTA trust accounting, cards and hourly billing, priced in USD per seat. They have no UPI, no GST reverse-charge labels, no Indian-language reminders, no BCI Rules 25-30 model and no stage-wise Indian fee structures.
* Indian billing apps (Vyapar, Zoho Invoice) issue GST invoices but treat every receipt as revenue. They don't separate expense deposits from fees, know nothing about hearings, and can't produce an evidence pack.
* Case diaries track dates, not money. Harvey and CoCounsel have no billing.

Why this won't fail the same way:
* Hearings and the client's WhatsApp channel are already in the system, so the work log fills itself.
* Unlike tools that quietly 'auto-reconcile', we claim automatic capture only where it truly exists: the Razorpay webhook. Direct-VPA payments go through a prefilled, purpose-mandatory manual entry or a statement match the lawyer confirms.
* The earned fee is computed only where the agreement makes it computable (stages with amounts, confirmed appearances, approved time). Where it isn't, the advocate's own assessment is recorded with a reason, so no code-generated admission reaches a notice.
* The claim has one formula, with each term printed and an SQL and a Python computation that must agree. A recovery pack therefore can't double-count.

### Safeguards

BCI:
* No contingency or share-of-recovery terms (Rule 20, B. Sunitha), validated in code.
* No lien over files.
* The withdrawal right is preserved, with notice and a court-leave warning (Rule 12).
* The refund of unearned fees is decided under the fee model the agreement states. For fixed and retainer models it is the advocate's own recorded assessment, never a figure computed by code.
* Client money: separate account, purpose-tagged receipts, no diversion to fees without Rule 26 consent or a Rule 28 basis (DB trigger), Rule 27 intimations, Rule 30 statement on demand.
* reminder_guard blocks coercion.
* Reminders are dues notices to existing clients, not solicitation (Rule 36).
* We describe the terms as 'drafted against a BCI checklist and approved by the advocate', never as compliant.

Lawyer approval: lawyers approve the terms and their translation, stage completion, time entries, every earned assessment (with its reason), invoices, reminder schedules, appropriations, statement matches and each withdrawal notice. Reminders, intimations and notices are fixed templates with no AI text. Only the client-language rendering of the terms uses the model, and the English text controls.

DPDP:
* Purpose is recorded for client contact data.
* Bank statements are minimised: only matched candidate rows are kept, unmatched lines and the raw file are discarded, and the file's hash is kept for audit. Statements are uploaded only by owners and partners.
* STOP ends reminders, while statutory intimations move to email or print.
* The ledger is retained for the tax and BCI retention period; an erasure request records that legal basis instead of deleting.

Privilege: invoice and intimation narratives are generic by default, with a 'privileged detail' toggle off by default.

Integrity:
* Hashes are computed in the DB under a per-matter row lock, and assessments and payment splits are inside the hashed payload.
* The SQL and Python computations must agree, including NULL for 'not assessed'.
* A failed chain verification blocks the s.63 certificate.
* Only Razorpay is described as automatic capture.

RLS and service role: owners and partners see all firm receivables, others only their own matters. The Razorpay webhook and worker writes are server-side jobs scoped to one org, to be added to CLAUDE.md invariant 2. Money is held in integer paise.

### How the panel's objections were answered

Objection 1 (unearned advance undefined for fixed, stage-wise and retainer): fixed as the reviewer proposed.
(a) Stage-wise agreements must give every stage an amount or a percentage. A constraint trigger refuses approval unless the amounts sum exactly to the total, and percentages are converted to paise with the remainder put on the last stage. Only stages a lawyer marks complete count as earned, each recorded as a hash-chained stage_complete entry.
(b) For fixed fees and retainers, the earning basis is 'advocate_assessment'. The earned amount is entered by a lawyer with a reason of at least 20 characters, labelled 'advocate's assessment' everywhere, hash-chained, and superseded only by a new entry. The field is never prefilled with a computed figure. Until it is entered, fee_advance_unearned is NULL and displayed as 'Not assessed'. The withdrawal-notice approval is refused at both the API and the DB, and only a DRAFT recovery pack or statement is possible.
Per-appearance and hourly earnings count only confirmed appearances and approved time.
(c) There are tests for each model (test_stage_wise_requires_amounts, test_per_appearance_model, test_hourly_model, test_fixed_fee_withdrawal_blocked_until_assessed, test_retainer_withdrawal_blocked_until_assessed), plus mixed components and assessment chaining.

Objection 2 (a direct-VPA UPI payment sends no callback): accepted. Automatic tagging is now claimed and tested only for the Razorpay webhook (capture_method 'razorpay').
* Building or opening a UPI intent link creates no entry (test_upi_direct_no_auto_entry).
* Direct-VPA, cash and cheque payments are recorded by hand on a form prefilled from the link's ref (purpose, invoice, reference), with an optional UTR. Purpose stays NOT NULL.
* Alternatively, an uploaded bank statement is matched deterministically: an exact regex on the tn ref plus an equal amount, or a low-confidence amount-and-date candidate that is never auto-selected when ambiguous. Every match needs lawyer confirmation, UTRs are unique, and unmatched lines are discarded (test_statement_match).
The round-3 claim 'a UPI payment through an EXP- link is stored as expense_deposit' is withdrawn.

Objection 3 (the claim formula double-counted): replaced by one formula, computed in both SQL and Python: receivable = billed fee lines + billed reimbursable lines - (fee_payments + reimbursement_payments + appropriations - fee_refunds); claim = max(0, receivable) + interest.
* expenses_advanced_by_advocate enters the claim only through the reimbursable invoice lines it became; overflow not yet invoiced is a warning only.
* The unearned advance and client money appear only on the refund side, and credit_balance = max(0, -receivable) is printed as a cross-check, so the advance is never subtracted twice.
* Payments of reimbursable lines are tagged reimbursement_payment by a deterministic waterfall (reimbursable lines first within an invoice), split at entry time and hashed. They never count as fee received.
* Interest is charged on fee-line balances only.
The tests the reviewer asked for are included: test_claim_overflow_not_double_counted (the Rs 2,000 overflow gives a claim of exactly Rs 2,000) and test_advance_exceeds_work (a Rs 50,000 advance against Rs 30,000 of work gives claim 0 and a refund of Rs 20,000). test_reimbursement_payment_split and test_claim_with_client_money_not_netted are also added.

All round-2 and round-3 fixes are unchanged: the withdrawal right, the DB-side hash chain, and client money under BCI Rules 25-30.

### Acceptance tests

- test_stage_wise_requires_amounts: an agreement with stages 20/10/40/30% of Rs 2,00,000 is approved and the stage amounts sum to exactly 20000000 paise. Percentages totalling 90, or a stage with no amount, are refused at approval. With stages 1-2 marked complete by a lawyer and Rs 80,000 paid, earned is Rs 60,000 and the unearned advance is Rs 20,000, and the notice prints 'Stages 1-2 complete'. A stage completed by a paralegal without lawyer confirmation does not count.
- test_per_appearance_model: Rs 5,000 per appearance, 6 confirmed appearances (2 more unconfirmed) and Rs 50,000 paid give earned Rs 30,000 and an unearned advance of Rs 20,000. Unconfirmed appearances never count.
- test_hourly_model: Rs 4,000/h, 7.5 approved hours and 2 unapproved hours, with Rs 50,000 paid, give earned Rs 30,000 and an unearned advance of Rs 20,000.
- test_fixed_fee_withdrawal_blocked_until_assessed: a fixed fee of Rs 1,00,000 with Rs 60,000 paid. Before any assessment, fee_advance_unearned is NULL in both the SQL view and Python, the UI shows 'Not assessed', and creating the withdrawal-notice approval fails at both the API and the DB. A lawyer enters Rs 45,000 with a reason of at least 20 characters; the notice then prints 'Earned portion (advocate's assessment): Rs 45,000' and a refund of Rs 15,000, and can be approved. A reason under 20 characters, or an assessment entered by a paralegal, is refused.
- test_retainer_withdrawal_blocked_until_assessed: a Rs 25,000/month retainer with Rs 75,000 paid. The notice is blocked until a lawyer's assessment is recorded (Rs 62,500 with a reason), then prints an unearned advance of Rs 12,500 labelled 'advocate's assessment'. No computed figure is ever prefilled in the assessment field.
- test_mixed_components: a fixed drafting component plus a per-appearance component. earned_total is NULL until the fixed component is assessed. After that, earned = the assessment + confirmed appearances x rate.
- test_assessment_is_chained_and_superseded: a second assessment appends a new 'assessment' ledger entry, the latest one is used, the earlier one stays in the chain, and changing an assessment amount as superuser breaks the chain at that seq.
- test_claim_overflow_not_double_counted: a deposit of Rs 3,000 and a disbursement of Rs 5,000 leave an overflow of Rs 2,000, invoiced as a reimbursable_expense line and unpaid, with no fee invoices. claim_principal is exactly Rs 2,000 (not Rs 4,000), client_money_held is 0, interest is 0, and the pack prints each term of the formula.
- test_claim_uninvoiced_overflow_warning: the same overflow before it is invoiced gives claim 0 and the warning 'Expenses advanced by you: Rs 2,000 - not yet invoiced'.
- test_advance_exceeds_work: a per-appearance model with a Rs 50,000 advance, Rs 30,000 of work invoiced, no expense deposit. claim is 0, credit_balance is Rs 20,000, fee_advance_unearned is Rs 20,000, and the refund side shows Rs 20,000. The advance is subtracted once, and the claim never goes negative.
- test_claim_with_client_money_not_netted: Rs 60,000 invoiced, a Rs 50,000 fee advance, a Rs 10,000 expense deposit and Rs 4,000 disbursed. The claim is Rs 10,000 and the refund side shows Rs 6,000 of client money, not netted. After an approved Rule 26 appropriation of Rs 6,000, the claim is Rs 4,000, client_money_held is 0, and one intimation is sent.
- test_reimbursement_payment_split: an invoice with a Rs 2,000 reimbursable line and an Rs 8,000 fee line, paid Rs 10,000 through its Razorpay link, creates one reimbursement_payment of Rs 2,000 and one fee_payment of Rs 8,000. A partial payment of Rs 3,000 is split Rs 2,000 reimbursement and Rs 1,000 fee. reimbursement_payment never increases fee_received or the unearned advance.
- test_interest_fee_lines_only: Rs 35,000 of fee lines overdue 400 days at 6% p.a. gives 230137 paise of interest (half-up). An unpaid reimbursable line of Rs 2,000 adds no interest. With no rate the interest is 0.
- test_balances_sql_equals_python: for 200 randomised ledgers covering all five models, mixed components, overflow, appropriations and reimbursement splits, the matter_balances view and services/ledger.balances() agree to the paisa on billed, receipts, receivable, claim_principal, credit_balance, fee_received, earned_total (including NULL), fee_advance_unearned and client_money_held.
- test_upi_direct_no_auto_entry: building and opening a UPI intent link for INV2627-0042 or EXP-M17 creates no ledger entry or payment. 'Record payment' with link EXP-M17 prefills purpose=expenses and stores an expense_deposit with capture_method 'manual'. A payload with no purpose and no link_ref is refused by the API and by the DB NOT NULL. A client payload claiming capture_method 'razorpay' is refused.
- test_statement_match: a fixture SBI/HDFC CSV with 6 credit lines gives: a line containing INV2627-0042 with an equal amount -> a 'ref' candidate tagged fee; EXP-M17 -> a 'ref' candidate tagged expenses; an equal amount with no reference and one open invoice -> 'amount_date'; an equal amount with two open invoices -> no auto-selected candidate; a reference with an unequal amount -> unmatched; an unrelated credit -> unmatched. Nothing is posted until confirmed. Unmatched lines and the raw file are not stored (only the sha256). Re-uploading the same statement, or confirming a UTR that is already posted, creates no duplicate.
- test_razorpay_auto_tag: a signed webhook fixture with notes.link_ref=EXP-M17 creates an expense_deposit with capture_method 'razorpay'. A retry with the same event id creates nothing. An invalid signature gets a 400. A notes.purpose that contradicts the server-side payment_links record is ignored in favour of the server record.
- Carried over from round 3 and still required: test_terms_reject_contingency, test_terms_fixed_clauses, test_appropriation_guard, test_payment_requires_purpose, test_rule27_intimation, test_reminders_never_claim_client_money (now: reminders ask only for claim_principal), test_statement_of_account, test_ack_from_whatsapp, test_ledger_append_only_and_chain, test_ledger_concurrent_writers, test_appearances_from_hearings, test_gst_rule_table, test_invoice_numbers_gap_free, test_upi_link, test_reminder_guard, test_withdrawal_notice_warnings, test_recovery_pack (now also: a FINAL pack is refused for an unassessed fixed or retainer component; a DRAFT pack shows 'Not assessed'), test_rls_fees (now also: an associate cannot insert an earned_assessment or see another org's statement_candidates).

### Reviewers' minor notes

- The worked figures check out: interest is 3,500,000 x 6% x 400/365 = 230,136.99, so 230137 paise; the per-appearance and hourly earnings are Rs 30,000; the client-money test gives Rs 10,000 then Rs 4,000.
- payments.utr is unique per org, but one bank transfer often pays invoices on two matters for the same client. Model it as one payment row (one UTR) with several allocation entries rather than one payment per invoice, or confirming the second match will be refused. Cash and cheque have no UTR: make the column a nullable unique.
- Interest on unpaid fees should be claimable only if the rate is in the acknowledged engagement terms. State that the claim formula prints interest as 0 when the terms the client agreed to carry no rate, even if a rate was added later.
- The bank CSV column maps for SBI, HDFC, ICICI, Axis and Kotak change without notice. A parse that finds no credit lines should say 'unrecognised statement format' rather than 'no matches'.
- Razorpay settles net of its fee and GST on that fee. For an expense deposit (client money), say how the gateway charge is treated. Record the gross amount as client money and the charge as the advocate's own fee-account cost, unless the written terms make it an agreed disbursement. Otherwise client_money_held either fails to reconcile with the bank, or the charge is quietly taken from the client's expense money, which Rule 26 forbids without written consent. Add a test: a Rs 10,000 EXP- payment with a Rs 236 fee records client money of Rs 10,000.
- Statement PDFs must use text extraction only, with the OCR vision fallback forced off for this path. A bank statement full of other clients' transactions must never reach Claude Vision. Add a test asserting zero Anthropic calls on a scanned statement, which should be rejected with a request for a text PDF or CSV.
- Each org's Razorpay webhook secret and key need their own storage and rotation. Add razorpay_events and the Razorpay webhook to the rate-limit exemptions and to invariant 2 together.
- Rule 26 consent to an appropriation obtained by WhatsApp 'AGREE' counts as writing under IT Act s.4. Store the exact approved text hash with that reply, as the terms acknowledgement does.
- P09 and P20 both claim supabase/migrations/014_*. Assign the numbers once across proposals (013 is the last one shipped).
- Bank CSV exports from SBI, HDFC, ICICI, Axis and Kotak change column layout without notice. Fixed column maps should fail loudly ('unrecognised statement format') rather than mis-parse. Version the fixtures per format.
- Razorpay settles into the advocate's own bank account, and expense deposits paid through Razorpay land there too. The UI and terms should say that client money is accounted for separately in the ledger (BCI Rule 25 accounts), not held in a separate bank account. This avoids implying a trust account.
- test_advance_exceeds_work should state the number of confirmed appearances and the rate, so that the earned figure (Rs 30,000) comes from confirmed appearances, not from the invoiced amount.

