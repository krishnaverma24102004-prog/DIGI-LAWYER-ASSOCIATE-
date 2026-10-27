# P47. No time to prepare for hearings because notice is short and admin eats the day

**Severity:** medium · **Size:** small · **Region:** Global (sharpest in India)

**Who has it:** Litigation associates and juniors in India and globally, outstation counsel, solo advocates

## What goes wrong

Final hearings can be notified a day ahead, boards are long, and matters are called with little warning. Lawyers rebuild a matter's history (last order, pending IAs, the bench's directions) from scattered PDFs, eCourts order sheets and WhatsApp notes in an hour, because nearly half the working day goes to administration. Preparation suffers, causing adjournments, weak arguments and missed points.

## Evidence of scale

- Karnataka HC advocates get only a day's notice before final hearings since the advance list was discontinued after November 2021. ([source](https://dakshindia.org/advance-causelist-petition-high-court-of-karnataka))
- Clio 2017 (via Attorney at Work): 2.3 billable hours a day and 48% of the day on office administration. ([source](https://www.attorneyatwork.com/?p=99970375))
- ABA Journal on Clio: lawyers bill about 28% of available hours; solos closer to 22%. ([source](https://www.abajournal.com/news/article/lawyers_are_only_billing_a_fraction_of_their_time_how_can_they_be_more_effi))
- Thomson Reuters Future of Professionals 2025 (2,275 respondents): AI users predicted to save 5 hours weekly (a forecast). ([source](https://www.thomsonreuters.com/en/press-releases/2025/june/the-ai-adoption-reality-check-firms-with-ai-strategies-are-twice-as-likely-to-see-ai-driven-revenue-growth-those-without-risk-falling-behind))

## Why current tools don't solve it

Harvey and CoCounsel summarise uploaded documents but don't pull Indian order sheets and cause-list entries to auto-build a one-page hearing brief (last order, compliance due, open IAs, bench directions, limitation points) when a matter is listed. Indian trackers show dates, not a hearing-ready summary.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Building the hearing-ready one-pager automatically the moment a matter is listed: last order and its directions, compliance due, open IAs, the bench, adjournment history, limitation points and open tasks, from the order sheets and files the firm already holds.

### What it can't fix

Reading the full brief and preparing arguments, which stays the lawyer's job; orders the court has not uploaded; documents that never reached the matter file.

### What the user sees

At 19:00 for every matter on tomorrow's board (or when a short-notice listing is detected), a Hearing brief appears on the matter and in the advocate's board strip: listing details (court, item, bench, list type); last order date with its operative paragraph quoted; directions and whether each was complied with; pending IAs; deadlines from the docket; adjournment count; prior bench; key documents with links. Each AI-written line has a 'source' link highlighting the quote in the order PDF. One click exports to PDF for the phone.

### What the system does

1. Trigger: P05 match or next_hearing_date within 2 days.
2. Deterministic sections from data: listing, deadlines (P13), adjournments (P04), IAs and documents linked to the matter, order list from provider_data/uploads.
3. AI section: the latest order text (PII-masked) is sent to Claude with a cached system prompt (prompt_engine.build_system) asking for directions and compliance items, each with a verbatim quote; quote_match verifies each against the order; failures are discarded and counted. Dates in directions are computed in code from the order date.
4. Citation check on any authority mentioned (citation_service).
5. Brief stored per hearing date; regenerated if a new order arrives.

### Where it is built

P05 board, P13 deadline_service, P04 hearing_outcomes; app/services/evidence_service.quote_match; prompt_engine.build_system; anthropic_service; pdf_service for export; new app/services/brief_service.py and app/routers/briefs.py; frontend matter panel in frontend/src/app/cases/page.tsx.

### Why current tools fail and this won't

Harvey and CoCounsel summarise what is uploaded but don't pull Indian order sheets and cause-list entries or know a matter is listed tomorrow; Indian trackers show dates, not a summary. Ours is triggered by the listing itself and every AI line is quote-verified against the order.

### Safeguards

Internal work product, not client-facing; PII masked before Claude; prompt caching per invariant 5; citations checked per invariant 3.

### Acceptance tests

- tests/test_briefs.py::test_trigger: a P05 exact match for tomorrow creates one brief; a second ingest of the same list does not duplicate it.
- test_quote_verification: mocked Claude output with one verified and one fabricated direction keeps one and reports discarded_unverified=1.
- test_direction_date: 'file reply within four weeks' in an order dated 2026-10-01 yields 2026-10-29 computed in code.
- test_no_order_available: with no order text the brief still renders deterministic sections and says 'last order not available'.
- Eval: evals/cases.json gains 10 Indian order sheets (English and Hindi) with expected directions; scripts/run_evals.py checks recall at least 80% and zero unverified quotes.

### Reviewers' minor notes

- Directions often run from receipt or service, not from the order date. Capture the trigger event and fall back to the safe date.
- Many district order sheets are handwritten or typed in Hindi on scanned pages. Show the OCR confidence on the 'last order' section and say 'order text unreliable' rather than extracting from a low-confidence scan.
- Briefs should honour ethical walls when shown in the board strip of an advocate not on the matter team.
- Order texts from provider_data may be links rather than text. Say how the order PDF is fetched and OCR'd (Tesseract; vision fallback per setting) before the AI step.

