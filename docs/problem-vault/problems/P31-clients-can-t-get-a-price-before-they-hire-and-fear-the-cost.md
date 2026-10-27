# P31. Clients can't get a price before they hire and fear the cost, so they delay, overpay, give up or pick the lowest quote

**Severity:** high · **Size:** big · **Region:** India and Global

**Who has it:** Individual clients, MSMEs, first-time litigants; solo and small firms trying to quote fixed fees

## What goes wrong

A litigant asks 'how much will my case cost?' and hears 'it depends'. Indian litigation is billed per appearance and nobody says how many appearances there will be, plus drafting fees, court fees and stamp duty. Lawyers quote vaguely or demand money upfront over the phone. Clients drop legitimate claims or switch lawyers midway; firms lose prospects because they can't scope a fee quickly. The SC in B. Sunitha said exorbitant fees violate the poor's access to justice, and price transparency is poor even in regulated markets like England.

## Evidence of scale

- B. Sunitha v. State of Telangana: exorbitant fees violate the poor's right to justice; SC expected legislation to cap fees; Law Commission's 131st Report proposal never acted on; percentage-of-award fee held misconduct. ([source](https://ssrana.in/articles/india-supreme-court-calls-for-regulating-hefty-fees-of-lawyers/))
- DAKSH: litigants spend about Rs 30,000 crore a year attending hearings and lose about Rs 50,387 crore in productivity; 90% earn Rs 3 lakh a year or less. ([source](https://www.dakshindia.org/access-to-justice-survey-findings-india))
- Uttarakhand HC asked the State Bar Council to draft fee rules and urged cashless payment. ([source](https://www.barandbench.com/news/uttarakhand-hc-litigants-pay-lawyers-cashless))
- SRA research (1,001 conveyancing purchasers): 66% considered more than one solicitor, but only 15% could get price information without contacting a solicitor directly. ([source](https://www.sra.org.uk/sra/how-we-work/reports/price-transparency-legal-services-market))
- Clio 2019 consumer survey: 76% want a clear sense of cost; 74% want to know the full process. ([source](https://lawyersmutualnc.com/blog/survey-most-clients-shop-around-before-picking-a-lawyer))
- LSC Justice Gap 2022: the most common reason low-income Americans didn't seek help was believing they couldn't afford it. ([source](https://lsc.gov/press-release/low-income-americans-face-immense-justice-gap-according-new-legal-services-corporation-report))
- WJP: 16% found it difficult or nearly impossible to find the money to resolve their legal problem; 17% gave up. ([source](https://worldjusticeproject.org/news/groundbreaking-study-reveals-unmet-legal-needs-worldwide))
- Private fees cited at Rs 20,000 minimum up to Rs 1 lakh, against Rs 18,000 per case for legal aid counsel in Delhi. ([source](https://idronline.org/article/livelihoods/why-is-the-quality-of-indias-free-legal-aid-so-poor/))

## Why current tools don't solve it

No product estimates an Indian matter's cost from its procedural path (likely hearings in a s.138 complaint or consumer case, state court fee, stage-wise drafting and appearances). Clio bills flat fees after engagement but doesn't estimate. Harvey, CoCounsel and Lexis+ AI price their own seats, not the client's case. LawRato/Vakilsearch list consultation prices only. Nothing combines NJDG duration data with the firm's fee card into a written stage-wise quote that respects the BCI ban on contingency fees.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Letting a firm give a prospect a written, stage-wise fee estimate within minutes of an enquiry. It is built in code from the firm's own fee card (drafting, per-appearance and stage fees), the out-of-pocket items the firm enters (court fee, typing, stamp, travel), and an expected range of appearances for that matter type in that court (from P32's statistics, or the firm's default). It checks that no line breaks BCI fee rules, needs a lawyer's approval before it goes out, and later shows quoted vs actual.

### What it can't fix

We don't set or recommend what lawyers charge, and we don't publish a public price list (that may be advertising under Rule 36, and it's the firm's call). State court-fee schedules are many and changing, so the firm enters them; we compute only the few we can encode safely and cite (e.g., consumer commission fee slabs, already in workflow_service). The opponent's conduct, adjournments and appeals make any estimate a range, not a promise. Affordability is a legal-aid problem software can't fix (a pointer is given on decline; see P08).

### What the user sees

Lawyer: on an intake brief or case thread, 'Prepare estimate'. The matter type and court are prefilled. The screen shows: 'Fixed: legal notice Rs 5,000; complaint drafting Rs 15,000. Per appearance Rs 3,000 x expected 8-14-22 appearances (based on 41 similar s.138 matters of this firm in Saket courts; median 14). Out of pocket: court fee Rs (firm entry); process fee. Estimate: Rs 44,000 / 62,000 / 86,000 (low/expected/high).' Assumptions are listed, lines can be edited, and Approve and send sends it. Prospect: a one-page PDF and a WhatsApp message in their language with the same stage-wise table, an 'estimate, not a final bill' line and 'fees per hearing apply only for hearings actually attended'. Later the lawyer sees 'Quoted 62,000; billed so far 38,000 after 9 appearances'.

### What the system does

1) Migration 014 adds `fee_cards` (org_id, matter_type enum shared with workflow packs and practice areas, court_level, items[] {code, label, kind fixed|per_appearance|per_stage|out_of_pocket, amount_paise, stage}). A validator in code rejects kind values or labels matching contingency or percentage patterns ('% of', 'percent', 'success fee', 'share of award', 'हिस्सा'), citing BCI Rules Part VI ch. II r.20 and B. Sunitha; amounts must be fixed rupee values. 2) `fee_quote.compute(card, appearances_range, out_of_pocket, overrides) -> Quote` is pure integer-paise arithmetic giving low/expected/high totals and per-stage subtotals. 3) appearances_range comes from duration_service.hearing_counts(org, matter_type, court) (P32): P25/P50/P75 of hearings per disposed matter, used only if n >= 10. Otherwise the firm's default range is used, labelled 'firm default'. 4) The quote is stored in `fee_quotes` (status draft|approved|sent|accepted|expired, approved_by/at stamped by trigger and cleared on any edit, valid_until), rendered by pdf_service (ReportLab) and a fixed message template per language. 5) Sending: as a pending whatsapp_message inside the client's own conversation, released only by settle_held_reply after approval (intake_guard would hold any amount anyway), or attached to the engagement letter (P09 owner). 6) Variance: actual appearances come from court_cases hearings history, and billed amounts from the P09/P10 billing data when it exists; the variance panel is lawyer-only. 7) Audit: GENERATE_QUOTE, APPROVE_QUOTE, SEND_QUOTE.

### Where it is built

app/services/workflow_service.py (matter types; consumer fee rule reused), app/services/pdf_service.py (quote PDF), app/services/whatsapp_intake.py settle_held_reply (sending through the held-message path), app/services/audit_service.py. New: app/services/fee_quote.py, app/services/fee_card_rules.py (BCI validator), app/routers/quotes.py (GET/PUT /api/v1/fee-cards, POST /api/v1/quotes, POST /quotes/{id}/approve, POST /quotes/{id}/send), migration 014 (fee_cards, fee_quotes with RLS: owners/partners edit fee cards, all members create quotes, approval by owner/partner or the matter's lawyer), frontend/src/app/quotes/page.tsx and a 'Prepare estimate' button on the /inbox brief card.

### Why current tools fail and this won't

Clio bills flat fees after engagement but doesn't estimate an Indian per-appearance matter. Harvey, CoCounsel and Lexis+ AI price their own seats, not the client's case. LawRato and Vakilsearch list consultation prices only. Nobody knows how many appearances a s.138 complaint takes in a given court. We get that from the firm's own disposed matters (synced from eCourts hearing history), compute the money in code from the firm's own card, refuse contingency lines, and send nothing without a lawyer. So the quote is the firm's real price, defensible and compliant, and it reaches the client in the window where P07 says they choose a lawyer.

### Safeguards

BCI: a deterministic rule against contingency and percentage-of-award fees; quotes go only to someone who contacted the firm (no public price advertising unless the firm chooses it). UPL: a quote states fees, not legal outcomes; assumptions text is fixed. A lawyer approves every quote. DPDP: the quote is tied to the consented conversation and erased with it. No AI in the arithmetic: the only data inputs are the firm card and statistics, both visible on the quote.

### Acceptance tests

- tests/test_fee_quote.py::test_compute_golden: card {notice 5000, complaint 15000, per_appearance 3000}, appearances (8,14,22), out_of_pocket 1200 -> totals exactly 45,200 / 63,200 / 87,200 in paise, with per-stage subtotals matching the fixture.
- test_validator_rejects_contingency: items labelled '10% of recovered amount', 'success fee', 'award ka 20 percent' -> ValidationError citing the BCI rule; a fixed 'Rs 10,000 on filing' passes.
- test_small_sample_falls_back: duration stats with n=6 -> the quote uses the firm default range and the label 'firm default', not the statistics.
- test_approval_cleared_on_edit: an approved quote whose line is edited -> approved_at null and the send endpoint returns 409.
- test_send_only_after_approval: POST /send on a draft -> 409 and the mocked whatsapp_service is not called.
- test_quote_message_template: the rendered hi/en message contains the 'estimate, not a final bill' line and no percentage sign.
- test_pdf_renders: the quote PDF builds and its extracted text contains each line label and total.
- RLS test: an associate can't edit fee_cards; org B can't read org A quotes.

### Reviewers' minor notes

- Show the GST treatment on the quote. Legal services to business entities are under reverse charge, so the client pays GST directly. Otherwise business clients receive wrong totals.
- Widen the contingency validator to outcome-linked triggers ('on success', 'if we win', 'on recovery', 'jeetne par', 'वसूली पर') on per_stage items. Keep partner approval of fee cards as the real control.
- The example in what_the_user_sees (44,000 / 62,000 / 86,000) disagrees with the golden test (45,200 / 63,200 / 87,200) for the same inputs. Align them.
- The quoted-vs-actual panel depends on P09/P10 billing, which doesn't exist yet. Show it as unavailable until then.

