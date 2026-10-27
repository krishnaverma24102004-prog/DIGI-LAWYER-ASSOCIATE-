# P39. Lawyers burn out from billable pressure, long hours and being always on

**Severity:** high · **Size:** big · **Region:** Global (US, UK); India

**Who has it:** Associates (years 1-5), young advocates, small-firm partners, associates at Indian tier-1/2 firms

## What goes wrong

Lawyers work 10-12-hour days and then answer clients at night. Junior associates and young advocates carry the heaviest load and are most burnt out, leading to mistakes, missed deadlines, attrition and worse service while talent costs rise.

## Evidence of scale

- ALM/Law.com Compass 2023 (nearly 3,000 lawyers): about 71% reported anxiety; about 68% cited billable-hour pressure and 67% inability to disconnect. ([source](https://www.abajournal.com/news/article/mental-health-initiatives-arent-curbing-lawyer-stress-and-anxiety-new-study-shows))
- LawCare Life in the Law 2025 (UK): nearly 60% reported poor mental health; 78.7% regularly work beyond contracted hours; average burnout score 37.8, above the 34.8 high-risk threshold. ([source](https://www.lawcareers.net/Explore/News/Nearly-60-of-legal-professionals-report-poor-mental-health-LawCare-report-finds))
- Vahura study (1,450+ professionals, 300+ Indian firms): over 50% looking to move; about 45% of those working 10-12 hours routinely stressed; only 18% say their firm encourages work-life balance. ([source](https://www.barandbench.com/amp/story/news/prioritizing-mental-health-enabling-safe-spaces-regulating-work-hours-how-law-firms-in-india-can-curb-attrition-and-attract-talent))
- Thomson Reuters 2026: lawyer compensation spending rose 8.2% and technology investment 9.7%. ([source](https://www.thomsonreuters.com/en/press-releases/2026/january/legal-industry-experiencing-tectonic-shift-technology-talent-and-demand-prompting-law-firms-to-evolve))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI speed individual drafting and research, but the after-hours load is client messages, status questions, intake, timesheets and hearing prep, which they don't touch. No product measures and reduces out-of-hours load by handling routine client contact under supervision.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Reducing and measuring the after-hours load the product can see: client messages answered at night, timesheets rebuilt late, status questions, alerts. Office hours and quiet hours per lawyer; clients get an acknowledgement and factual status (next date, last order date) from records after hours; lawyer notifications are batched with a deterministic urgent-only exception list; timesheets are done by capture (P10); and each lawyer sees their own out-of-hours load trend.

### What it can't fix

Billable-hour targets, firm culture, court sitting hours, senior partners' expectations and pay are not software problems. We are not a mental-health service and won't infer anyone's wellbeing; we measure workload signals only. Work on personal phones outside the product is invisible to us.

### What the user sees

Settings: 'My office hours Mon-Sat 9:30-19:30, quiet hours 21:00-07:00, Sunday off'. After hours, a client asking 'kab hai date?' gets an instant factual reply from the case tracker ('Next hearing: 14 Nov 2026, Saket Court') and others get the firm's holding message; the lawyer's phone stays silent until morning, when a single 9:00 digest lists what came in. Only listed emergencies break through (hearing tomorrow newly listed, custody/bail matter, limitation or default-bail deadline within 48 hours, a partner's manual 'urgent' ping). A private 'My load' card: messages handled after hours this week vs last month, timesheet minutes confirmed after 21:00, weekends worked. Partners see team aggregates only.

### What the system does

1. Migration 019_work_hours.sql: member_schedules (user, timezone default Asia/Kolkata, office hours jsonb, quiet hours, days off, holidays), notification_queue (user, kind, payload, urgent bool, deliver_after), load_metrics_daily (user, date, after_hours_msgs, after_hours_confirmations, weekend_events).
2. services/schedule.py: is_office_hours(user, ts) and next_office_time() in code, with IST and court-holiday list.
3. Client side, after hours: whatsapp_intake routes messages for a lawyer-owned conversation (status 'lawyer') during that lawyer's off-hours to (a) a deterministic status answer when the message matches a fixed status-question pattern set (Hindi/English/Hinglish) and the conversation's matter has a court_case: reply built only from court_cases fields, no AI; (b) otherwise the existing intake_guard HOLDING_MESSAGE plus 'the lawyer will reply after <next office time>'. AI intake for new enquiries is unchanged (P07 owner).
4. Lawyer side: all notifications go through notification_queue; urgent = fixed rules evaluated in code (hearing within 24h newly added/changed, P14 default-bail or P06 limitation deadline within 48h, matter flagged custody, explicit partner urgent ping with reason); non-urgent waits until deliver_after = next office time and is sent as one digest.
5. Metrics computed nightly from existing timestamps (whatsapp_messages sender='lawyer', time_entries confirmed_at, work_events) by code; shown to the user; partner view aggregates teams of 3+ only.
6. The P10 and P30 digests honour quiet hours.

### Where it is built

Extend: app/services/whatsapp_intake.py and app/services/intake_guard.py (after-hours routing, holding message), app/services/ecourts_service.py data for status answers, app/worker.py cron (digest, metrics), app/routers/organizations.py/team page for schedules, frontend/src/components/TeamPage.tsx. New: supabase/migrations/019_work_hours.sql, app/services/schedule.py, app/services/notifications.py, app/services/status_reply.py, app/services/load_metrics.py, app/routers/wellbeing.py (my-load and team aggregate), frontend/src/components/MyLoadCard.tsx, tests/test_quiet_hours.py.

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis+ AI speed up drafting and research, but the night-time load is client messages, status questions, intake and timesheets, which they don't touch; practice-management tools push notifications at all hours and don't answer clients. We own the client channel and the case data, so routine status questions are answered from records without the lawyer, and the lawyer's alerts are gated by explicit, testable rules rather than an AI's sense of urgency.

### Safeguards

No AI text reaches clients after hours: status replies are templated from records, everything else is the fixed holding message; legal substance waits for a lawyer (intake_guard). Urgent rules are code, so deadline alerts (P06, P13, P14) are never suppressed by quiet hours. Employee data (DPDP): load metrics are workload counts, private to the individual; partners see aggregates of 3+ only; no wellbeing inference, no use in appraisals stated in the product terms; users can switch metrics off. Clients are told when the lawyer will reply, not left waiting silently.

### Acceptance tests

- test_status_reply_after_hours: at 22:30 IST, 'next date kab hai?' in a lawyer-owned conversation whose matter has next_hearing_date 2026-11-14 at Saket Court gets exactly the template reply with those values; the mocked model is not called; the lawyer gets no immediate notification.
- test_non_status_holds: at 22:30 'should I sign the settlement?' gets the holding message with the next office time and is queued for the 9:00 digest.
- test_urgent_breaks_through: a court_case newly listed for tomorrow at 21:45 sends an immediate notification; a routine new document at 21:45 waits until 09:30.
- test_office_hours_logic: schedule Mon-Sat 9:30-19:30 IST: Sunday 11:00 is off-hours, Saturday 19:29 is office, a configured court holiday is off; next_office_time from Saturday 20:00 is Monday 09:30.
- test_load_metrics: fixture week with 12 lawyer WhatsApp messages after 21:00 and 3 timesheet confirmations after 21:00 yields those counts in load_metrics_daily.
- test_team_aggregate_min_size: a partner requesting the load view of a 2-person team gets 'not enough people to show'; an individual's own metrics are visible only to that user.

### Reviewers' minor notes

- An after-hours status reply from court_cases can give a stale or past date when sync lags. Answer only when next_hearing_date is in the future and last_synced_at (or the manual edit) is recent. Otherwise send the holding message. Phrase it 'as per court records checked on <date>'.
- Court holiday and vacation calendars differ between the HC and district courts. Key the list per court.
- Partner aggregates of 3 or more can still identify people in small teams over time. Consider a minimum period too.
- Automated status replies should say they are automatic and give their source and date ('As per eCourts data fetched 24 Oct: next hearing 14 Nov. Your advocate will confirm.'), because provider data can be stale and the conversation may be in 'lawyer' status, where the client assumes the lawyer is replying.
- Workload metrics are employees' personal data. The no-appraisal-use promise belongs in the org's employee notice, not only in the product terms, and should be shown to members.
- Verified: the 'lawyer' conversation status exists, and conversation -> transcript -> thread -> court_cases.thread_id is a real path. Also match wa_id to court_cases.client_phone for conversations that have no thread.
- The status-question patterns must not match substantive questions that mention a date ('what will happen on the next date?'). Add negative fixtures.
- Migration 019 is fine. Note the dependencies on P06, P13 and P14 for urgency rules.

