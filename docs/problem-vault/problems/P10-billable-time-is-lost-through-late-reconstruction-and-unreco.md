# P10. Billable time is lost through late reconstruction and unrecorded calls, WhatsApp advice and appearances

**Severity:** critical · **Size:** big · **Region:** Global (US, UK); India

**Who has it:** All hourly-billing firms (solo to BigLaw); Indian firms billing per appearance or retainer; associates under hours targets

## What goes wrong

Lawyers do the work but don't record it: quick calls, WhatsApp advice, emails, reviewing a draft at night. Timesheets are rebuilt from memory at the end of the day, week or month, so short tasks disappear and durations are guessed. Only a fraction of the workday is billable, and part of that is never invoiced or collected. Indian firms billing per appearance or stage see the same leak as appearances, drafts and conferences that are never invoiced.

## Evidence of scale

- Access Legal/Censuswide (April 2026, 200 UK legal professionals): fee earners lose 4.16 billable hours a week, just under GBP 2m a year for a 50-fee-earner firm; 71% say admin burden makes accurate time capture difficult; switching between disconnected apps is a top frustration for 26%. ([source](https://www.legalfutures.co.uk/associate-news/uk-law-firms-losing-nearly-2m-a-year-to-legal-tech-that-frustrates-fee-earners/print/))
- Research attributed to Ann Guinn for the ABA: recording time at day's end loses about 10-15% of billable hours, next day about 25%, end of week about 50% (quoted secondhand by a vendor). ([source](https://minutedock.com/academy/the-real-cost-of-late-time-entry-why-reconstructed-timesheets-kill-law-firm-revenue))
- Clio Legal Trends (2017): lawyers spend about 2.3 hours a day on billable work, collect about 1.6 hours, and firms collect 86% of what they bill. ([source](https://www.clio.com/about/press/second-annual-legal-trends-report-dives-deeper-state-legal-industry/))

## Why current tools don't solve it

Passive time capture (Clio, Smokeball, Intapp Time, Laurel) records desktop and email activity, missing court appearances, phone and WhatsApp advice and Indian per-appearance work; narratives are still hand-written. Harvey, CoCounsel and Lexis+ AI never turn work into a billable entry. Nothing drafts time entries or appearance invoices from the hearing calendar, call transcripts, WhatsApp threads and drafts produced, with OCG-compliant narratives.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Capturing work at the moment it happens, from the systems the lawyer already uses in this product, so nothing has to be reconstructed later. Sources: live consultations (wall-clock, typed or spoken), phone calls (call start to end), WhatsApp messages the lawyer sends from the inbox, drafts generated and finalised, documents reviewed, and hearings in the case tracker. Work done outside the app (a call on a personal phone, a WhatsApp from a personal number) goes in a 10-second manual log. Durations come from code with a stated basis. Only the narrative wording is AI, and the lawyer confirms each entry.

### What it can't fix

Work done entirely outside the product (personal-phone calls, personal WhatsApp, thinking time in the car) cannot be captured passively; we can only make the manual log fast and prompt for it the same evening. We do not read the lawyer's personal device, email or screen: no desktop surveillance. Whether a session window was all billable work (for example, a session left open over lunch) is for the lawyer to decide; we flag idle gaps but don't decide. Whether a client will pay for a captured entry is a commercial matter.

### What the user sees

A 'Today' panel and an 8 pm WhatsApp/app digest, for example: 'You did 9 things today that aren't on a timesheet: 41-min consultation with Sharma (session wall-clock 10:02-10:43; speech time 12 min), 4 WhatsApp replies to Mehta (about 12 min, estimate), bail application draft finalised, appearance at Saket Court item 14. Confirm all / edit.'

Each suggestion shows:
* its source, with a link to open the transcript or chat
* the computed duration and its basis ('session wall-clock', 'call start-end', 'estimate')
* the metered speech time as secondary information, where there is one
* an amber note when the session had a long idle tail ('no activity after 10:31; session ended 11:55; use 10:02-10:31?'), with a one-tap trim
* the matter and a short narrative

One tap confirms. A floating 'Log' button records outside work, and so does texting '/log 20m Sharma settlement call' to the firm's WhatsApp number from the lawyer's own registered number. A weekly view shows captured vs confirmed vs invoiced hours and appearances per matter.

### What the system does

1. Migration 015_work_capture.sql adds:
   * work_events (org_id, user_id, thread_id nullable, source_kind in live_session|phone_call|whatsapp_reply|draft|review|hearing|manual, source_id, started_at, ended_at, computed_seconds, basis in wall_clock|call_span|estimate|unit|manual, speech_seconds nullable, last_activity_at nullable, unique(source_kind, source_id))
   * time_entries (status suggested|confirmed|rejected|invoiced, duration_minutes, rounding_rule, narrative, narrative_ai bool, rate_paise, billable bool, confirmed_by/at, work_event_ids uuid[])
2. Consultations: a hook in live_session.finalize(), called after _save_transcript succeeds (so typed-only sessions are included, because they save a transcript too), writes a work_event:
   * computed_seconds = metadata.ended_at - metadata.started_at, basis 'wall_clock', for every transport (websocket, webrtc, typed)
   * speech_seconds = self.audio_seconds if audio was received, else null, shown only as 'speech time'
   * last_activity_at = the time of the last segment (from _segment_offsets)
   If ended_at - last_activity_at exceeds 10 minutes (a firm setting), or end_reason is a disconnect or timeout, the suggestion is flagged amber with an option to trim to last_activity_at. Nothing is trimmed automatically. audio_usage is not used as the duration source. Sessions with no segments save no transcript and create no event.
3. Telephony: duration is the call span, from the Twilio stream 'start' event to 'stop' or hang-up (basis 'call_span'), with speech_seconds alongside.
4. WhatsApp: consecutive lawyer messages in one conversation sent less than 15 minutes apart are grouped into a 'burst'. Duration = last - first + a per-message allowance (firm setting, default 2 min), basis 'estimate'.
5. Drafts: an event is written on approve/final, with the editing span from the drafts' updated_at history, capped at a firm-set maximum and labelled 'estimate'.
6. The review grid writes an event on completion. Hearings from court_cases become appearance events, counted in appearances, not hours.
7. Matter assignment is done in code: transcript.thread_id; WhatsApp conversation -> transcript -> thread; draft.thread_id; court_case.thread_id. Unassigned events go to an 'Unassigned' tray and are never guessed.
8. Rounding is applied in code per firm or client setting (6-min, 15-min or actual), in time_entries only; the raw seconds are kept.
9. Narrative: claude-haiku-5-5 receives the PII-masked transcript summary or draft title (mask_pii first) and returns a narrative of at most 25 words in the client's OCG style. The output is checked: it must contain no amount, no duration different from the computed one, and no names not in the matter. If a check fails or the call fails, a template narrative is used ('Conference with client re <matter title>').
10. The '/log' parser uses a regex grammar, '/log <n>(m|h) <matter hint> <text>', and only from a number matched to an org member's registered phone, never a client's. The matter hint is resolved by exact thread title or CNR prefix; otherwise the reply asks 'Which matter? 1) ... 2) ...'.
11. The worker task_daily_time_digest runs at the lawyer's chosen hour (default 20:00 IST) and builds the digest from unconfirmed events.
12. Only confirmed entries can go on invoices (P09) or into the OCG check (P38).

### Where it is built

Extend:
* app/services/live_session.py: a work-capture hook in finalize() after _save_transcript, reading self.started_at, ended_at, audio_seconds and _segment_offsets()
* app/services/telephony_session.py (call start/stop)
* app/routers/whatsapp.py (lawyer send path)
* app/services/whatsapp_intake.py (route '/log' from member numbers before the client flow)
* app/routers/drafting.py (approve path)
* app/services/review_service.py (completion)
* app/worker.py cron

New:
* supabase/migrations/015_work_capture.sql
* app/services/work_capture.py, app/services/time_entries.py
* app/routers/time.py
* frontend/src/components/TodayPanel.tsx, frontend/src/app/time/page.tsx
* tests/test_work_capture.py

### Why current tools fail and this won't

Passive capture tools (Clio, Smokeball, Intapp Time, Laurel) watch the desktop and email, so court appearances, phone advice and WhatsApp advice, which make up most of an Indian litigator's day, never appear, and narratives are still hand-written. Harvey, CoCounsel and Lexis+ AI never turn work into a time entry. Our product is where the consultation, the call, the WhatsApp reply, the draft and the hearing date already live. Capture is therefore a by-product with exact source links. Durations are computed from the real session or call window with a visible basis (not guessed by an AI, and not taken from billing-metered speech seconds that would under-bill), and idle gaps are flagged for the lawyer rather than silently counted.

### Safeguards

PII: everything sent to the model for narratives passes mask_pii (invariant 1).

Privilege: narratives stay inside the firm until an invoice is approved, and invoice narratives follow P09's generic default.

Human control: the lawyer confirms every entry, nothing is billed from a suggestion, and idle-gap trimming is the lawyer's choice. Each duration shows its basis, so no estimate is presented as a measurement.

Employee monitoring: a user's work events are visible to that user, and to owners/partners for billing purposes only. There is no keystroke, screen or location tracking.

RLS: work_events and time_entries follow the court_cases pattern (own matters plus seniors). The digest worker reads across users server-side, scoped per org; it is to be added to CLAUDE.md invariant 2's list of server-side jobs. audio_usage stays a billing table written only by the server; work capture reads its own copy of the session timing and does not write billing tables.

### How the panel's objections were answered

Both blocking objections (the same point) are fixed as proposed.
* The consultation duration is now the session's wall-clock span: metadata.started_at to metadata.ended_at, which live_session.finalize() already saves in the transcript metadata. It is recorded as computed_seconds with basis 'wall_clock'. For telephony, the call's stream start to stop is used (basis 'call_span').
* Metered audio (self.audio_seconds, from the same source as audio_usage) is kept only as secondary 'speech time' and is never the billed basis.
* The hook runs after the transcript is saved, not in _meter_audio, so typed-only sessions (which _meter_audio skips) now create events too.
* So that wall-clock doesn't over-bill a session left open, the last-activity time is stored and a long idle tail is flagged amber with a one-tap trim. The lawyer decides; nothing is trimmed automatically.
* Tests: test_live_session_creates_event now asserts the wall-clock basis (2700 s with speech_seconds 720). New tests: test_typed_only_session_captured, test_empty_session_no_event, test_idle_tail_flagged_not_trimmed and test_telephony_call_span.

### Acceptance tests

- test_live_session_creates_event_wall_clock: a mocked WebRTC session started 10:00:00 and ended 10:45:00, with audio_seconds=720 and thread T, creates one work_event with computed_seconds=2700, basis='wall_clock' and speech_seconds=720. With 6-minute rounding, the suggested entry is 48 minutes (45 rounded up to the next increment, 0.8h). A second finalize for the same session creates nothing.
- test_typed_only_session_captured: a typed-only session (audio_received False, 3 typed segments, 18 minutes wall-clock) creates a work_event with computed_seconds=1080, speech_seconds null, and no audio_usage row.
- test_empty_session_no_event: a session with no segments saves no transcript and creates no work_event.
- test_idle_tail_flagged_not_trimmed: a session whose last segment is at 10:31 and which ended at 11:55 creates an event with computed_seconds equal to the full span, last_activity_at=10:31, and an amber flag. trim() applied by the user sets the entry to 10:02-10:31; nothing is trimmed without that call.
- test_telephony_call_span: a call with stream start 14:00:05 and stop 14:21:35 gives computed_seconds=1290, basis='call_span'.
- test_whatsapp_bursts: lawyer messages at 10:00, 10:04, 10:09 and 11:30 in one conversation give two events, 10:00-10:09 (+allowance) and 11:30 (allowance only), both with basis='estimate'.
- test_unassigned_not_guessed: a WhatsApp conversation with no transcript or thread produces an event in the Unassigned tray with thread_id null.
- test_hearing_appearance_units: a passed hearing creates an appearance event with unit 'appearance' and no hours.
- test_narrative_guard: a model narrative claiming '1.5 hours' for a 24-minute event, or naming a person absent from the matter, is replaced by the template narrative. The prompt sent to the model contains no unmasked phone numbers (asserted on the mocked client payload).
- test_log_command: '/log 20m sharma settlement call' from a registered member number creates a confirmed manual entry of 20 minutes on the matter titled 'Sharma v ...'. The same text from a client's number is treated as a normal client message and logs nothing.
- test_only_confirmed_invoiced: an invoice build for the matter includes confirmed entries only and marks them 'invoiced'; afterwards they cannot be confirmed or edited without an adjustment.
- test_capture_rate_report: a fixture day with 9 events, 7 of them confirmed, returns capture metrics 9/7/0 per matter.

### Reviewers' minor notes

- Most Indian litigators bill per appearance or per stage, not hourly. Make the hours view optional per firm, so it doesn't add confirmation work for chambers that will never invoice by time.
- The 8 pm digest on WhatsApp to the lawyer's number should use P33's member_phones/internal template path, and say so.
- Migration 015 collides with P23, P16 and P21.
- Work events are employee personal data. Give members a short DPDP notice explaining what is captured and why (billing), and keep the 'counts only' stance used in the P21 owner report.
- The '/log' path from member numbers should rely on P33's member_phones verification, so the two proposals don't each verify member numbers their own way.
- Migration 015 collides with P16, P21 and P23.
- Migration 015 collides with P23, P16 and P21.
- The '/log' command depends on P33's member_phones verification. Ship them together or include the inbound-code verification here.
- The narrative guard's 'no names not in the matter' needs a defined name source (P46 party index or court_cases parties). Without one, the check can't be implemented deterministically.

