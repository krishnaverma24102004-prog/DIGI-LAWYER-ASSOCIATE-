# P07. New client enquiries go unanswered, especially after hours, so prospects hire whoever replies first

**Severity:** critical · **Size:** big · **Region:** Global (US measured); India (WhatsApp/phone intake, no front office)

**Who has it:** Solo practitioners and small firms (PI, family, criminal, consumer, property, cheque bounce) with no front office; prospective clients in urgent matters

## What goes wrong

A prospective client calls at 9 pm, emails, fills a form or sends a WhatsApp voice note in Hinglish about an arrest, a cheque bounce or an eviction. The solo advocate is in court all day and nobody owns intake, because the advocate is also the receptionist. Enquiries arrive on WhatsApp, Instagram DMs and a personal number and get lost. Nobody replies within the first hours with next steps or a fee indication, and by morning the person has hired someone else. US secret-shopper studies show most firms miss email and calls entirely, and responsiveness is getting worse. Revenue is lost before any conflict check or engagement letter, and urgent deadlines (e.g., the 30-day s.138 notice window) can run in the meantime.

## Evidence of scale

- Clio 2024 secret-shopper test (1,000 firms emailed, 500 called): 67% didn't respond to email; 48% didn't answer or call back; only 2% referenced similar legal situations or case law (27% in 2019). ([source](https://abovethelaw.com/2024/10/law-firms-failing-at-the-single-most-basic-lawyering-task/))
- Clio 2024: 33% responded to email (40% in 2019), 40% answered calls (56% in 2019), 12% of shoppers would recommend the firm they contacted. ([source](https://www.2civility.org/2024-clio-legal-trends-report-fixing-the-first-impression-problem-for-law-firms/))
- Clio 2019 secret shopper: 60% of firms contacted by email didn't respond and 27% didn't answer or return calls. ([source](https://www.ncbar.org/?p=10300))
- Clio secret-shopper test: 60% of firms did not respond to email; more than half didn't return voicemails within 72 hours; 64% of consumers had contacted a firm that never responded. ([source](https://www.2civility.org/clio-legal-trends-report-finds-law-firms-arent-responsive-to-potential-clients/))
- Clio 2019: 82% of consumers say timeliness is essential; 79% expect a response within 24 hours; 76% want a clear sense of cost. ([source](https://lawyersmutualnc.com/blog/survey-most-clients-shop-around-before-picking-a-lawyer))
- Martindale-Avvo: 78.9% of consumers who hired a lawyer contacted more than one attorney first. ([source](https://www.martindale-avvo.com/academy/learning/three-things-to-know-about-legal-consumers))
- Clio 2025: referrals are the top lead source for 59% of solo and small firms; firms combining referrals with digital intake report stronger conversion. ([source](https://www.canadianlawyermag.com/news/general/solos-and-small-firms-lag-with-ai-adoption-clio-report/392441))
- Clio 2025 Legal Trends: 14% of consumers have used AI for legal questions and another 43% would. ([source](https://www.2civility.org/2025-clio-legal-trends-report/))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI do no intake. Clio Grow, Lawmatics, intake chatbots and answering services are US web-form/email products in English, with no WhatsApp Business channel, no Hindi/Hinglish voice notes, no consent before data reaches an AI, and canned replies that can drift into unauthorised advice. None does PII-safe fact capture, automatic conflict check, deadline triage (s.138 notice window, default bail days) and a structured brief the lawyer accepts in one tap. In India, US-style marketing bots could breach BCI Rule 36, so the product must only reply to people who made contact and never solicit.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Making sure every enquiry that reaches the firm's WhatsApp or phone gets a correct, safe reply within a minute at any hour. The reply says when a lawyer will respond, computed from the firm's hours. The system turns the conversation into a structured brief, computes in code any statutory clock that may be running (s.138 notice/complaint windows, default-bail days) from the dates the person gave, wakes the lawyer only for real emergencies, and lets the lawyer accept, decline or refer in one tap. It also measures first-response time.

### What it can't fix

Enquiries sent to a lawyer's personal number or Instagram DMs never reach us. We won't scrape personal WhatsApp, and Instagram auto-replies risk breaching Rule 36. We can't make a lawyer actually take the matter, or take on more than they can handle. Proactive outreach to leads (ads, cold follow-ups) is out by design under Rule 36. Whether the person stays with the firm depends on the human follow-up.

### What the user sees

Prospect, 9:40 pm on WhatsApp: the existing consent prompt, then intake questions in their language (voice notes work), then a fixed acknowledgement: 'Thank you. The firm's lawyers work Mon-Sat 10am-7pm. A lawyer will reply by 11:00 am tomorrow (Sat 26 Oct).' If the person mentions an arrest or detention (detected by keywords in code, including Hindi and Hinglish: arrest, giraftar, गिरफ्तार, police station, custody), a fixed firm-approved message says a lawyer has been alerted now, and gives the NALSA helpline 15100 as a factual fallback. Lawyer: an 'Intake briefs' list in /inbox. Each brief card shows matter type, parties, key dates (each with the client's own quote as proof), urgency computed in code ('s.138: the 30-day notice window from the bank memo dated 3 Oct closes on 2 Nov, 8 days left'), a conflict-check result (from the P46 service), the language, the channel and time waiting. The buttons are Accept (opens a case thread with the brief and asks consent for AI processing), Decline (sends a fixed polite decline in the client's language with legal-aid/DLSA pointers) and Refer (to a named colleague in the org). A small 'first-response time' tile shows the median this week.

### What the system does

1) `org_settings` (migration 014): working hours, timezone IST, court holiday list, SLA hours, emergency alert numbers (lawyers' own phones, opted in). 2) `intake_hours.next_reply_by(now, settings) -> datetime` is pure code. The acknowledgement is a fixed template filled with that time, sent by the system sender. This avoids the AI entirely and passes intake_guard because it carries no legal substance. 3) Intake stays as it is in whatsapp_intake (consent first, masked, intake_guard on every AI reply). When the conversation goes quiet for 10 minutes, or the client says they're done, `intake_brief.build` runs one Haiku extraction over the masked history into a fixed JSON schema: matter_type from a closed enum matching workflow packs and practice areas, parties, events [{label, date, quote}], client_language and asks. 4) Verification in code: each event date must parse, and its quote must pass evidence_service.quote_found against the unmasked client messages; failures are dropped and counted, as in invariant 6. 5) Triage in code: if matter_type is cheque_bounce and a 'bank return memo received' date is verified, call workflow_service.evaluate('cheque_bounce', …) and put its deadlines and flags on the brief. The same goes for bail/default bail (arrest date, offence) and consumer packs. With no verified date the brief says 'date needed' and no deadline is shown. 6) Emergency: `intake_triage.is_emergency(text)` uses a regex list over the raw inbound text (the same list as the phone intake). If it matches, the lawyer gets an alert at once through the WhatsApp template `lawyer_alert` to the lawyer's own opted-in number, with no client PII beyond the first name and conversation link, regardless of hours. 7) Conflict check: party names from the brief go to the P46 conflict service. Until that exists, a fallback compares normalized names with court_cases.petitioners/respondents and case_threads in the org and shows possible matches, never auto-declining. 8) Accept/Decline/Refer are audited endpoints. Decline and refer send fixed templates. Accept creates a case_thread with ai_consent fields filled from the WhatsApp consent. 9) Metrics: a Prometheus histogram `intake_first_response_seconds{channel, by=system|lawyer}` and the /inbox tile computed from whatsapp_messages timestamps. 10) Phone: the Twilio after-hours flow reuses telephony_session. At call end the same brief builder runs on the masked transcript.

### Where it is built

Extend app/services/whatsapp_intake.py (acknowledgement after consent and on each quiet period; emergency branch; brief trigger), app/services/intake_guard.py (unchanged checks; HOLDING_MESSAGE gains the computed reply-by line), app/services/telephony_session.py (brief at call end), app/services/workflow_service.py (reused as-is for triage), app/services/evidence_service.py quote_found (reused), app/core/metrics.py (new histogram), app/routers/whatsapp.py (brief accept/decline/refer). New: app/services/intake_hours.py, app/services/intake_brief.py, app/services/intake_triage.py, migration 014 (org_settings, intake_briefs table: conversation_id, brief jsonb, verified counts, triage jsonb, decision, decided_by/at), app/data/intake_templates/{en,hi,...}.json, frontend/src/app/inbox/page.tsx (Briefs list and response-time tile).

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis+ AI do no intake. Clio Grow, Lawmatics and US intake bots work through web forms and email in English, with no WhatsApp Business, no Hindi or Hinglish voice notes, no consent before AI processing, and canned replies that drift into advice. None computes Indian statutory clocks. Answering services take messages but don't triage. Our intake already exists with consent first, PII masking and intake_guard. This adds a reply-by time that is always correct (code, not model), a brief whose dates are proven by the client's own words, and deadlines from the same deterministic workflow_service the lawyer already uses. So the urgent s.138 or default-bail matter is at the top at 10 am, not lost in a phone.

### Safeguards

Rule 36: replies only to people who wrote or called first; no follow-up marketing and no outbound to leads who went silent; decline and refer texts are factual. UPL: the AI only asks questions (intake_guard). Deadlines, acknowledgement times and emergency messages are code and fixed templates; deadlines go to the lawyer, not to the prospect, unless the lawyer sends them. DPDP: the existing YES consent before anything reaches the AI; brief retention follows the conversation; a declined prospect's data goes to the 30-day trash and is then erased (tombstone). PII masking before extraction. Public intake stays off until enabled through maker-checker (migration 013). Lawyer alerts carry minimal client data. Invariant 2: the WhatsApp webhook is an existing listed server job; accept/decline endpoints use RLS.

### Acceptance tests

- tests/test_intake_hours.py: Fri 21:40 IST with hours Mon-Sat 10-19 -> reply_by Sat 11:00 (10:00 plus 1h SLA); Sat 18:50 -> Mon 11:00; a court holiday on Mon -> Tue 11:00.
- test_ack_passes_intake_guard: each rendered acknowledgement template in each language -> intake_guard.check_reply-style substance check finds no legal substance (dates are allowed in the system template; the test documents that the template is system, not AI).
- test_brief_dates_verified: a mocked extraction returns events [{date: 2026-10-03, quote: 'bank ne 3 October ko memo diya'}] and [{date: 2026-09-01, quote: 'invented quote'}] -> the first is kept, the second dropped, discarded_unverified=1.
- test_triage_s138: a verified memo date of 2026-10-03 with today 2026-10-25 -> the brief has the deadline 'demand notice by 2026-11-02' with its basis string, equal to workflow_service.evaluate output.
- test_triage_no_date: matter_type cheque_bounce without a verified memo date -> triage shows 'date needed' and no deadline.
- test_emergency_keywords: 'mere bhai ko police ne giraftar kar liya' and 'गिरफ्तार' -> is_emergency True; 'my arrest of payment' fixture -> documented behaviour; the alert is sent to the lawyer number (mocked) within the same handle() call at 23:00.
- test_decline_template: decline sends the fixed hi/en template and contains no section, amount or prediction (intake_guard regexes).
- test_conflict_fallback: a brief party 'Ramesh Kumar Gupta' and an existing respondent 'R. K. Gupta' -> a 'possible match' is shown and the brief is not auto-declined.
- test_brief_pii: the extraction prompt receives masked text only (assert no phone number or Aadhaar from the fixture in the mocked Anthropic call).
- test_metrics: a sequence of messages -> intake_first_response_seconds observed with by=system < 60 in the simulated clock.

### Reviewers' minor notes

- When the decline is sent after the system has computed a running statutory clock, the template should add a neutral line, 'time limits may apply to your matter; please consult a lawyer promptly'. This is standard non-engagement practice and not advice.
- The emergency keyword list needs a documented false-positive policy (e.g. 'arrest' in 'arrears'). A lawyer woken at 23:00 too often will mute it.
- Send the emergency 'a lawyer has been alerted' text only when an opted-in alert number is configured and the send succeeded. Otherwise send the NALSA 15100 fallback without that claim.
- The declined-prospect tombstone should keep the names and matter type needed for later conflict checks (a prospect who disclosed facts can create a conflict). State this retention in the consent notice.
- The extraction model sees masked text, so its quotes may contain placeholders (<PHONE_1>). Verifying them with quote_found against the unmasked messages will drop valid events. Verify against the masked history (or unmask the quote via the session's PiiMasker first) and add a test.
- Keyword emergency detection will miss many phrasings. Record misses that a lawyer marks later, so the list can be extended.

