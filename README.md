# Digi Lawyer API

Multi-tenant FastAPI backend for law firms, backed by Supabase (Postgres + Auth + pgvector):
live consultation transcription and AI analysis, contract cross-referencing, a legal knowledge
base (RAG), practice-area prompt templates, role-based access control and an audit trail.

## Structure

```
app/
  main.py                 FastAPI app, CORS, router registration, embedding warm-up
  database.py             Supabase clients (admin + per-user/org with RLS)
  core/config.py          Settings from environment / .env
  core/rbac.py            Roles, permissions, who-can-manage-whom
  core/guardrails.py      PII masking before LLM calls; output-safety disclaimer
  core/rate_limiter.py    Per-client rate limits (slowapi; Redis-backed when REDIS_URL is set)
  core/metrics.py         Prometheus metrics (Claude tokens, phone calls, sessions, DB connections)
  worker.py               ARQ background worker (PDF reports, n8n retries, document embedding)
  dependencies/auth.py    Bearer-token auth -> CurrentUser
  dependencies/org.py     X-Org-Id -> OrgContext (org + role), require_permission()
  routers/                transcripts, documents, organizations, practice-areas, knowledge,
                          case-threads, evidence, drafting, webhooks, live WebSocket, WebRTC,
                          billing (Stripe), telephony (Twilio), jobs
  models/                 Pydantic request/response schemas
  services/               agent_workflow (LangGraph), anthropic_service (Claude), prompt_engine,
                          rag_service, memory_service, ocr_service, audit_service, org_service,
                          live_session, web_search (Tavily), tts_service (Deepgram Aura),
                          webrtc_media (aiortc), jurisdiction_service, contract_diff_service,
                          evidence_service, drafting_engine, transcription (Deepgram), documents, PDF, n8n,
                          stripe_service, twilio_service, telephony_session, queue_service
frontend/                 Next.js client app (ChatRoom, WebRTC voice, live case file)
static/index.html         Browser test page for the WebSocket pipeline
Dockerfile, docker-compose.yml   API + ARQ worker image, with Redis
.github/workflows/deploy.yml     CI: pytest, frontend lint/build, image build -> ghcr.io
supabase/migrations/      SQL to run in Supabase, in order
tests/                    API tests; tests/db runs the migrations + RLS checks on a real Postgres
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # then fill in your keys
```

Run the migrations in `supabase/migrations/` in order (001 → 012) in the Supabase SQL Editor.
Install Tesseract for scanned documents (see [OCR](#ocr-for-scanned-documents)).

## Run

```bash
uvicorn app.main:app --reload
```

Interactive docs: http://localhost:8000/docs. Test page: http://localhost:8000.

Background jobs need Redis and a worker:

```bash
docker run -d --name digi-redis -p 6379:6379 redis:7-alpine   # then REDIS_URL=redis://localhost:6379/0
arq app.worker.WorkerSettings
```

Or run everything (API, worker, Redis) with Docker: `docker compose up --build`. Inside the containers `localhost` is the container itself: point
`ANTHROPIC_BASE_URL` at `http://host.docker.internal:11434` to reach Ollama on your machine. The image runs
as a non-root user and includes Tesseract; the embedding model is cached in a volume.

## Organizations and roles

Every user belongs to one or more organizations (firms). Sign-up creates a personal workspace the
user owns; migration 004 does the same for existing users and moves their data into it.

Send `X-Org-Id: <org id>` to act in a specific organization; without it, requests use the user's
active org (`POST /api/v1/organizations/{id}/activate`). The database enforces this: RLS only exposes
rows whose `org_id` is the caller's active org, and only if they are a member.

| | owner | partner | associate | paralegal |
|---|:-:|:-:|:-:|:-:|
| Run consultations, upload contracts | ✓ | ✓ | ✓ | ✓ |
| See **all** org transcripts/documents (others: only their own) | ✓ | ✓ | | |
| Add to the knowledge base | ✓ | ✓ | ✓ | |
| Delete knowledge, manage practice areas, read the audit log | ✓ | ✓ | | |
| Add/remove associates and paralegals | ✓ | ✓ | | |
| Grant owner/partner, rename the org | ✓ | | | |

`plan_tier` can only be changed with the service role (billing). An org always keeps one owner.

Endpoints: `GET/POST /api/v1/organizations`, `PATCH /organizations/{id}`,
`GET/POST /organizations/{id}/members`, `PATCH/DELETE /organizations/{id}/members/{user_id}`,
`GET /organizations/{id}/audit-logs`.

## Practice areas

Per-org templates that steer live analysis: a custom system prompt plus risk rules (what counts as
high/medium/low severity, red flags, facts to capture, deadlines).
`POST /api/v1/practice-areas/install-templates` adds built-ins for Personal Injury, Corporate/M&A,
Criminal Defense and Real Estate, which firms can then edit (`PATCH /practice-areas/{id}`). The
templates describe what to look for, not any jurisdiction's law: add your own limitation periods.

## Legal knowledge base (RAG)

`POST /api/v1/knowledge/upload` (multipart: `title`, and `content` or a PDF/txt `file`; optional
`citation`, `jurisdiction`, `source_url`) chunks the text, embeds it and stores it in
`legal_knowledge_base`. `POST /knowledge/search` runs the same retrieval live sessions use.

Embeddings are computed **locally** with fastembed (`BAAI/bge-base-en-v1.5`, 768 dimensions), so
client conversations are never sent to a third-party embedding API. The model (~210 MB) downloads on
first use; the server warms it up at startup. Search is pgvector cosine similarity via the
`match_legal_precedents` SQL function, which runs with the caller's RLS so it can only search their
own org.

## Live consultation WebSocket

`ws://localhost:8000/api/v1/ws/audio?org_id=<id>&practice_area_id=<id>` (both optional). The full
message protocol is in [app/routers/audio_stream.py](app/routers/audio_stream.py).

Pipeline: browser mic → 16 kHz PCM → Deepgram speech-to-text → every few seconds, Claude Haiku updates
the analysis (key facts, legal issues, follow-up questions, contract cross-references) using the
practice area's rules, the attached contract, and knowledge-base passages retrieved for the recent
conversation. Matched passages are pushed to the client as `citations`. On `end`: Claude Sonnet
summary → saved to `transcripts` → n8n post-consultation webhook.

1. Connect with the Supabase access token. From a browser, use the subprotocol so the token stays
   out of URLs and logs: `new WebSocket(url, ["bearer", accessToken])`. The connection is refused
   unless the user is a member of the organization.
2. Send `{"type": "start", "document_id": "...", "audio": {"encoding": "linear16", "sample_rate": 16000, "channels": 1}}`,
   then stream raw audio as binary frames (or send `transcript_chunk` text).
3. Receive `transcript_interim`, `chunk_received`, `analysis` and `citations`.
4. Send `{"type": "end"}`; the reply `session_ended` carries the `transcript_id`. A dropped connection
   is finalized the same way.

Contracts (`POST /api/v1/documents/upload`) up to ~150k characters are sent whole and prompt-cached;
longer ones are cut to the clauses most relevant to the conversation. Scanned PDFs need OCR, which
is not supported yet.

## Agent pipeline (LangGraph)

Live analysis is a team of agents ([app/services/agent_workflow.py](app/services/agent_workflow.py)),
run on each batch of new speech:

```
intake_analyzer → legal_researcher ─(knowledge base weak/empty)→ external_researcher ─┐
                                   │                                                  │
                                   ├─(something new)→ risk_evaluator → drafter ◀──────┘
                                   └─(nothing new)──────────────────→ drafter
```

- **intake_analyzer** keeps the case's key facts (Claude Haiku).
- **legal_researcher** searches the knowledge base with the facts and new speech (pgvector, rate-limited).
- **external_researcher** runs when the knowledge base has no match above `WEB_SEARCH_RAG_THRESHOLD`:
  Claude writes up to two *generic* legal research queries (no names, places or identifiers), and
  only those go to Tavily. Results are passed to the risk evaluator and drafter as untrusted
  sources, shown with their URLs, and limited by `WEB_SEARCH_MIN_INTERVAL_SECONDS` /
  `WEB_SEARCH_MAX_PER_SESSION`.
- **risk_evaluator** cross-references facts with citations, practice-area rules and the contract.
  Skipped when nothing changed, to save a model call.
- **drafter** writes the note and follow-up questions shown to the lawyer, then passes it through
  the output-safety guardrail.

Each agent's start is streamed as `agent_status` so the UI can show what the AI is doing; the
drafter's note arrives as `agent_response`. A failing agent keeps the previous results. Expect a
pass to take a few seconds (up to three sequential model calls).

## Conversation and talking mode

`mode=conversation` (WebSocket query parameter, or the WebRTC offer) makes the drafter reply *to the
user* in short, speakable sentences; replies become chat turns the agents see next time. With
talking mode (`voice=1`), each reply is also spoken with Deepgram Aura (`TTS_MODEL`):

- over the WebSocket, as an MP3 buffer in an `agent_audio` event;
- over WebRTC, streamed into the outbound audio track as it is synthesized.

Speech never reads out identifiers: placeholders become phrases ("the account you mentioned"). The
on-screen reply restores the user's own details. `{"type":"ptt","state":"start"|"stop"}` implements hold-to-talk
(pressing interrupts the AI; releasing finishes the utterance at once), and `{"type":"interrupt"}`
stops playback.

## WebRTC voice sessions

`POST /api/v1/webrtc/offer` (Bearer token) takes the browser's SDP offer (one audio track plus a
data channel named `events`) and returns the answer. Microphone audio goes to Deepgram and the agents;
the AI's voice comes back on the audio track; JSON events use the same protocol as `/ws/audio` over
the data channel. Body: `{sdp, type, org_id?, practice_area_id?, thread_id?, mode, voice}`.

WebRTC removes transport latency (UDP media with jitter buffering instead of a TCP socket); the time
to an answer is still mostly speech recognition, the agents and speech synthesis. For users behind
strict NATs or firewalls, add a TURN server (`WEBRTC_STUN_URLS` covers STUN only).

## Client app (`frontend/`)

Next.js 16 + Tailwind CSS. Two screens: the consultation room (`/`) and the **Document Studio**
(`/studio`): a redline viewer (side-by-side diff, AI risk cards, accept / reject / counter-clause /
AI-revise per clause, then save the negotiated version), a clause editor for drafts (edit, AI revision
with accept/reject, placeholders flagged, .docx/PDF export), a jurisdiction picker, and a one-click
pleading generator that can draw on the current case. The ChatRoom splits the screen: on the left, the conversation (typing or a
hold-to-talk mic button) with a live "thinking" indicator; on the right, the case file (legal risks,
knowledge-base citations, web sources, key facts, open questions). It connects over WebRTC and plays
the AI's voice automatically. Without a microphone it still works for typing and listening.

```bash
cd frontend
copy .env.local.example .env.local   # set NEXT_PUBLIC_API_URL and the Supabase URL/anon key
npm install
npm run dev                          # http://localhost:3000 (the API's CORS_ORIGINS must include it)
```

The old `static/index.html` test page still works for the WebSocket pipeline.

## Jurisdictions

Pick a framework per request or session: `IN` (India), `US` (federal), `US-<state>` (e.g. `US-CA`) or
`UK` (England & Wales): the `jurisdiction` field on the REST endpoints, `?jurisdiction=` on
`/ws/audio`, or the WebRTC offer. It sets ([app/services/jurisdiction_service.py](app/services/jurisdiction_service.py)):

- **the statutory framework and practice notes** in every agent prompt, e.g. India's BNS / BNSS / BSA
  replacing the IPC / CrPC / Evidence Act for offences from 1 July 2024 (with a table of commonly
  cited section correspondences, which should be checked against the official tables);
- **the citation style**: Indian (SCC / AIR), Bluebook, OSCOLA, with deterministic formatters;
- **the knowledge-base filter**: tag uploads with a jurisdiction (`IN`, `US-CA`, ...) and searches return
  matching passages plus untagged firm material (`US-CA` also matches federal `US`).

## Contract redlining

`POST /api/v1/documents/compare` `{original_document_id, revised_document_id, jurisdiction?, our_side?}`
aligns clauses deterministically (identical → renumbered → most similar by word overlap; leftovers are
added/deleted), produces a character-level redline per changed clause, and has Claude Sonnet assess
each changed clause from the client's side (risk impact, severity, categories, counter-clause). The
response has `clauses`, `additions`, `deletions`, `modifications`, `recommended_counter_clauses` and
`risk_delta` (Increased / Decreased / Neutral), which is **computed** from the per-clause assessments
(±1/2/3 by severity) rather than asked of the model, so it's consistent.

## Evidence contradictions

`POST /api/v1/evidence/analyze-contradictions` compares a witness statement (text, a saved transcript, or
a document) against documents, other transcripts and a case thread's memory. Every finding has the
statement line and timestamp, the conflicting source quote, a severity score and cross-examination
questions. **Both quotes are verified against the actual texts**: findings that can't be verified are
dropped and counted in `discarded_unverified`. `POST /api/v1/evidence/transcribe` turns a deposition
recording into timestamped, speaker-labelled lines (Deepgram) and saves them as a document. Live
sessions now record per-line timing, so saved consultations work as timestamped statements too.

## Drafting

`POST /api/v1/drafting/generate` drafts a legal notice, bail application, cease and desist letter, NDA
or affidavit, with jurisdiction-specific templates (e.g. Indian notice, US demand letter, English letter
before claim; BNSS bail application). Facts come from the case thread (memory and recent sessions),
attached documents and the lawyer's notes; values the lawyer types always win, and nothing unknown is
invented: it becomes a highlighted `[●…●]` placeholder listed in `missing`. Drafts are stored (RLS like
transcripts), editable (`PATCH`), revisable clause by clause (`POST /drafting/revise-clause`) and
exportable as editable **.docx** or **PDF** (`GET /drafting/{id}/export?format=docx|pdf`).

## Sign-up and team

Firms sign up in the app (name, firm name, email, password): the firm's workspace is created with them
as owner. Owners and partners add colleagues on the Team page (`/team`): people with an account join
at once; others get an invitation and join with that role when they sign up with the invited email.

## Bulk review

`/review` asks the same questions of up to 50 documents and shows a grid: every answer has the passage
it rests on, checked against the document (✓ verified, or ⚠ check), filling in as each document is
done. Ready-made question sets cover Indian commercial contracts, leases / leave and licence,
employment agreements and NDAs; add columns any time, retry failed documents, export to CSV.
API: `POST /api/v1/reviews`, `GET /api/v1/reviews/{id}`, `POST .../questions`, `GET .../export`.

## Workflows

`/workflows` runs matter packs for common Indian matters. The statutory deadlines are computed in
code, not by the AI: cheque bounce (notice within 30 days of the return memo, 15 days to pay,
complaint within a month, ss. 138/142 NI Act), consumer complaints (two-year limitation, which
Commission by amount paid) and bail (BNSS or CrPC by offence date, default-bail and undertrial-release
dates). Each pack adds a checklist, next steps and a one-click draft (notice or bail application).

## Cases and hearings

`/cases` is the firm's hearing diary. Add a case by CNR (with `ECOURTS_API_KEY`, the court, parties,
status and hearing dates come from the eCourtsIndia API and stay in sync) or by hand. There is no
official public eCourts API, and the eCourts portal is captcha-protected, so case data comes from a
provider or from the lawyer. Every morning (7:00 IST) the worker refreshes hearings in the next
`HEARING_REMINDER_DAYS` days, sends clients a WhatsApp reminder (approved template
`WHATSAPP_REMINDER_TEMPLATE`, once per hearing date), and posts each firm's agenda to n8n
(`hearings-agenda` webhook) for email or Slack.

## WhatsApp intake

Clients message the firm's WhatsApp Business number (Meta Cloud API; connect it on `/inbox`, point
Meta's webhook at `/api/v1/whatsapp/webhook`). The first message gets the firm's greeting and a
consent request in English and Hindi; nothing reaches the AI before the client replies YES. Then
the agent team takes the intake in the client's language (text or voice notes, transcribed with
Deepgram's multilingual model), PII-masked as in a live consultation, and the chat is kept as a
transcript with facts and risks, downloadable as a PDF intake report. The client can type LAWYER
at any time; a lawyer can take over from the inbox (the AI then stays quiet), hand back, or close.
Webhook calls are signature-checked (`WHATSAPP_APP_SECRET`) and de-duplicated by message id.

## Safety rails (approvals, trash, legal hold, public intake)

Nothing the AI gets wrong, and nothing one person does by mistake, should leave the firm unchecked
(migration 013, `app/services/safety_service.py`, `app/routers/safety.py`, page `/safety`):

- **Trash.** Delete anywhere moves the record (and its messages, review cells, links) to the Trash:
  restorable for 30 days, then erased by the worker's daily job, which keeps an erasure record and a
  PDF certificate (`GET /api/v1/trash/{id}/certificate`). Direct deletes on those tables are revoked
  in the database. Delete endpoints answer 200 `{"status": "trashed"}` or 202 `{"status": "approval_requested"}`.
- **Approvals.** Associates and paralegals deleting a client record (consultation, document, court
  case, case thread, knowledge source) send a request; a partner or owner approves it in
  `/safety` (`POST /api/v1/approvals/{id}/approve`) and it is carried out as them. Turning on public
  intake, making someone an owner and erasing from the Trash early need a second senior, unless the
  firm has only one. Nobody approves their own request.
- **Legal hold** (`PUT /api/v1/legal-hold`, owners and partners) on a case thread or court case
  blocks deleting it and the records linked to it.
- **Public intake** is off until a firm turns it on (`GET/PUT /api/v1/intake`). When on, the AI only
  asks intake questions on WhatsApp and the phone; a reply with legal substance (law, sections,
  deadlines, amounts, advice, predictions) is held for a lawyer to send, edit or discard from the
  inbox, and the client is told a lawyer will reply (`app/services/intake_guard.py`).
- **Consent.** A consultation's AI analysis and speech-to-text start only once the client's consent
  is recorded (remembered on the case for 12 months); without it, typed notes only.
- **Drafts** export with an "AI DRAFT · UNREVIEWED" mark until a lawyer approves them; the export
  checklist (`GET /api/v1/drafting/{id}/checklist`) lists unverified citations, amounts and dates
  not in the confirmed facts, and blanks. Export is never blocked; the choice is logged.
- **Governing law.** Redlines and review grids warn when a contract's own governing-law clause names
  a different jurisdiction from the one analysed, and tag conclusions about enforceability.
- **Production model gate.** With `ENVIRONMENT=production`, the API and worker refuse to start on a
  non-Claude model or a local gateway.

## Court desk (cause lists, docket, limitation, custody, hearings)

Built from the problem vault's panel-accepted solutions (`docs/problem-vault/`). Every date is
computed in code from rule tables; no statutory date comes from the AI.

- `/board`: tonight's cause lists (Supreme Court and Delhi High Court parsers; forwarded PDFs for
  other lists) reconciled against the firm's matters, with appearance confirmation and escalation.
- `/deadlines`: the firm docket. Each deadline is checked blind by a second member (they re-enter
  the inputs without seeing the date); reminders escalate to the backup and a partner.
- `/limitation`: limitation calculator with a worked computation (s.12 copy time, s.4 closures,
  s.14, hard outer limits) and a certified-copy tracker.
- `/custody`: default-bail and s.479 BNSS dates for every undertrial, with the procedural code
  chosen by when the investigation began (s.531 BNSS).
- `/hearings`: likely call windows per bench from the firm's own logs, clash warnings across
  courtrooms, and hearing briefs whose directions are verified against the order's text.
- `/rules`: the limitation and punishment tables ship as drafts; a rule is used in a firm only
  after two of its advocates check and sign it. The worked examples in `tests/fixtures/` were
  written from the statutes by engineering and still need advocates' sign-off.

The worker runs the cause-list fetch (every 30 min, 17:00-10:00 IST), appearance escalation,
the hourly docket sweep (08:00-21:00 IST), the custody recompute (07:00 IST) and hearing briefs
(19:00 IST). Delhi High Court lists aren't fetched automatically: its terms forbid systematic
downloading, so firms forward them.

## Citation verification

Everything the agents cite is checked in code (`app/services/citation_service.py`), not only by the
prompt: statute sections against a registry of Indian acts (BNS, BNSS, BSA, IPC, CrPC, Evidence Act,
Constitution, Contract Act, NI Act, CPC and more, with section counts), and cases against the
sources the agents were given plus a citation index of every Supreme Court judgment. Fabricated
sections ("Section 600 BNS") and cases nobody can find are removed from a risk's authority and
marked `[unverified]` in replies and summaries (and left out of what clients read or hear); old-code
sections are labelled with their 2023-code equivalent and new-code sections with the old one for
offences before 1 July 2024. Each check says plainly what was and wasn't checked. The case file shows which authorities are in the sources, real but not among them,
or removed.

With `INDIANKANOON_API_TOKEN` set, a case the Supreme Court index doesn't know (most High Court and
tribunal judgments) is looked up on Indian Kanoon by its parties' names before being marked
unverified (at most 3 lookups per check, results cached), and `GET /api/v1/caselaw/search?q=` searches
judgments across Indian courts. Indian Kanoon's terms require "powered by IKanoon" attribution,
shown on the About page.

## Shared Indian law corpus

Migration 008 adds a corpus every organization searches alongside its own knowledge base, and a
citation index. Load it from the public Supreme Court judgments dataset (AWS Open Data):

```bash
python scripts/ingest_sc_judgments.py --years 1950-2026                      # citation index only (fast)
python scripts/ingest_sc_judgments.py --years 2024 --full-text 2024 --limit 50  # + full text, embedded locally
```

## Quality evals

`evals/cases.json` holds Indian matters (deposit, cheque bounce, bail, consumer, cyber fraud,
divorce, motor accident...) in English, Hinglish and Hindi with what a good answer must contain.
`python scripts/run_evals.py` replays them through the real pipeline against the configured model
and reports language, key points, facts, risks, forbidden guarantees, PII masking and citation
checks per case, saving a JSON report in `evals/results/` for comparing models and prompt changes.

## Guardrails

- **PII masking** ([app/core/guardrails.py](app/core/guardrails.py)): every finalized piece of speech,
  and any attached contract, is masked with Presidio before it can reach an LLM. SSNs, card and bank
  numbers, IBANs, Aadhaar, PAN, passport and voter IDs, emails and phone numbers become placeholders
  like `[CLIENT_SSN]` or `[BANK_ACCT_2]`, consistent within a session (a number repeated later is
  masked again even without context). Names, places and dates are kept because the analysis needs
  them. Summaries and case memory are generated from masked text. The database keeps the original
  transcript. If masking fails, AI analysis stops for the session rather than sending unmasked text.
  Raw audio still goes to Deepgram for transcription.
- **Output safety**: drafted notes that read as legal directives or outcome guarantees ("you should
  sue", "you will win", "do not sign") get a standard legal-information disclaimer appended.

## OCR for scanned documents

Document uploads accept PDFs, images (PNG, JPEG, TIFF, WebP) and text. PDF pages without a text layer
(scanned contracts, wet-ink FIRs) and images are read with **Tesseract**, a system dependency:

- Windows: install from https://github.com/UB-Mannheim/tesseract/wiki (auto-detected in
  `C:\Program Files\Tesseract-OCR`), or set `TESSERACT_CMD`.
- macOS: `brew install tesseract` · Debian/Ubuntu: `apt-get install tesseract-ocr`
- Other languages need their packs, e.g. `tesseract-ocr-hin`, then `OCR_LANGUAGES=eng+hin`.

Pages Tesseract can't read reliably (mean confidence below `OCR_MIN_CONFIDENCE`, e.g. handwriting)
are transcribed by Claude vision (`ANTHROPIC_VISION_MODEL`, up to `OCR_VISION_MAX_PAGES` per
document). **Images can't be PII-masked**: set `OCR_VISION_FALLBACK=false` to keep scans on your
server. The upload response's `extraction` field says how each page was read. OCR runs during the
upload request (a few seconds per scanned page).

## Case memory

Create a case thread (`POST /api/v1/case-threads`) and connect with
`/api/v1/ws/audio?thread_id=<id>`. The agents receive summaries of the thread's earlier sessions
(`CASE_MEMORY_MAX_SESSIONS`), so they remember what the client said last week; when the session
ends, its summary, facts and open questions are added to the thread. `GET /case-threads/{id}`
returns the history. Visibility follows transcripts (migration 005).

## Audit trail

Logged automatically to the append-only `audit_logs` table (a trigger blocks updates and deletes,
even by the service role): `START_CONSULTATION`, `END_CONSULTATION`, `VIEW_TRANSCRIPT`,
`UPLOAD_CONTRACT`, `EXPORT_PDF_REPORT`, `DELETE_SESSION`, plus knowledge, membership, practice-area
and organization changes, with user, org, resource, IP and timestamp. Owners and partners read it
via `GET /organizations/{id}/audit-logs`. By default auditing is fail-open (an audit write failure
is logged and the action proceeds); set `AUDIT_FAIL_CLOSED=true` to refuse audited actions instead.
Behind a reverse proxy, set `TRUST_FORWARDED_FOR=true` to record client IPs from `X-Forwarded-For`.

## Billing (Stripe)

Billing is per organization. `POST /api/v1/billing/checkout-session` `{tier: starter|pro|enterprise}`
(owners only) returns a Stripe Checkout URL for that tier's Price, plus the metered audio-minutes Price
when `STRIPE_METERED_PRICE` is set. Point a Stripe webhook at `POST /api/v1/billing/webhook` with
`checkout.session.completed`, `customer.subscription.created|updated|deleted`, `invoice.payment_succeeded`
and `payment_intent.succeeded`; events are signature-checked, applied once each, and keep
`billing_accounts` and `organizations.plan_tier` in sync.

Every WebSocket, WebRTC or phone session that streamed audio is **metered** when it ends: the seconds
of audio actually sent to speech-to-text (every started minute counts; typed-only sessions are free) go
to `audio_usage`. In WebRTC sessions, microphone audio only goes to Deepgram while the mic button is
held, so the silence the browser sends the rest of the time is neither transcribed nor billed. For orgs
with a Stripe customer, the minutes also go to the Stripe meter `STRIPE_METER_EVENT_NAME`
(de-duplicated by session id). `GET /api/v1/billing/usage` (owners and
partners) shows the tier, status, included / used / remaining / overage minutes for the period.
Sessions are not blocked when minutes run out; overage is billed by the metered Price.

## Phone intake (Twilio)

Add a number with `POST /api/v1/telephony/numbers` `{phone_number, owner_user_id?, practice_area_id?,
jurisdiction?, greeting?}` and set its Twilio Voice webhook to
`<PUBLIC_BASE_URL>/api/v1/telephony/voice/incoming`. A call is answered with `<Connect><Stream>` to
`wss://.../api/v1/ws/telephony` (signature-checked webhook, then a short-lived signed stream token).
The caller's 8 kHz mu-law audio is decoded to PCM for Deepgram, the agents run in conversation mode
(PII-masked as usual), and replies are spoken with Aura at 8 kHz, encoded to mu-law and streamed back;
the caller can talk over the AI (barge-in). The call is saved as a transcript of the number's owner,
and its minutes are metered.

## Background jobs

With `REDIS_URL` set and a worker running:

- `POST /api/v1/transcripts/{id}/pdf/jobs` renders the PDF report in the background into the private
  Supabase Storage bucket `reports`; `GET /api/v1/jobs/{job_id}` then returns a 5-minute signed link.
- `POST /api/v1/knowledge/from-document` `{document_id, title?, citation?, jurisdiction?}` chunks and
  embeds an uploaded document (e.g. a long statute PDF) into the knowledge base.
- The post-consultation n8n webhook is delivered by the worker, retried with exponential backoff.

Jobs are visible only to the user who queued them. Without Redis, the PDF stays available
synchronously (`GET .../pdf`), documents are indexed inline and n8n is called directly.

## Rate limits and monitoring

Every `/api/` route is limited per client (`RATE_LIMIT_DEFAULT`), keyed by a hash of the bearer token
or by IP; routes that call Claude, Deepgram or Tavily have a stricter `RATE_LIMIT_LLM`, billing has
`RATE_LIMIT_BILLING`. Over the limit: `429` with `Retry-After`. Stripe and Twilio webhooks are exempt.
Counters are shared through Redis when it is configured.

`GET /metrics` (Prometheus; set `METRICS_TOKEN` to require a bearer token) has per-route HTTP metrics
plus `claude_tokens_total{model,kind}`, `telephony_response_latency_seconds`, `telephony_calls_total`,
`telephony_active_calls`, `live_sessions_active{transport}` and `db_connections_open` (sampled from
`public.db_connection_count()`).

## Configuration

See `.env.example`. Models default to `claude-haiku-5-5` (live) and `claude-sonnet-5-5` (summary).

To call Claude through an Anthropic-compatible gateway (e.g. a LiteLLM proxy) instead of
api.anthropic.com, set `ANTHROPIC_BASE_URL` and the gateway's key in `ANTHROPIC_API_KEY` (sent as
`x-api-key`) or `ANTHROPIC_AUTH_TOKEN` (sent as `Authorization: Bearer`). The `ANTHROPIC_*_MODEL`
names must be ones the gateway serves, and the gateway must support the Messages API with structured
outputs. If it rejects the server-side fallback beta, set `ANTHROPIC_SERVER_FALLBACK=false`.

For gateways or local models that ignore structured outputs (e.g. Ollama's Anthropic-compatible API at
`http://localhost:11434`), set `ANTHROPIC_STRUCTURED_OUTPUT=prompt`: the JSON schema is put in the
prompt and the reply is validated (with up to two corrective retries). Use this for testing only; output
quality depends on the model.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/db` applies every migration to an embedded Postgres + pgvector (via `pgserver`) and checks
tenant isolation, roles and vector search as different users; it is skipped if `pgserver` isn't
installed. `RUN_EMBEDDING_TESTS=1 pytest` also runs a check against the real embedding model.
Background-job tests use an in-memory Redis (`fakeredis`); set `TEST_REDIS_URL=redis://localhost:6379/15`
to run them against a real one (CI does).

## Security notes

- User-facing requests use a Supabase client carrying the caller's JWT and `x-org-id`, so RLS
  enforces tenant isolation and roles in the database, not only in the API.
- `get_supabase_admin()` uses the service role key and **bypasses RLS**. It is used for audit writes,
  looking up users by email when adding members (after the role check), saving a transcript
  whose session outlived the user's JWT (with the user and org verified at connect time), and the
  server-side jobs that have no user session: Stripe webhooks and usage metering, phone calls
  and WhatsApp chats (scoped to the number's org), and the ARQ worker (which re-checks the job's user
  role, and runs the Trash retention purge).
- Trash, approvals, legal hold and the public-intake switch are `SECURITY DEFINER` database functions
  with their own role checks, called as the user; records can't be deleted around them.
- Contracts and knowledge-base text are passed to Claude as reference material it is told never to
  take instructions from; practice-area prompts are written by owners/partners and treated as
  operator instructions.

## Data sources and attribution

- Supreme Court of India judgments: "Indian Supreme Court Judgments" (Dattam Labs), accessed from
  https://registry.opendata.aws/indian-supreme-court-judgments, licensed CC-BY-4.0. Attribution
  must also appear in the product (e.g. its About page) wherever this corpus is used.
- Not used yet, but checked for testing: the High Court judgments bucket (CC-BY-4.0, 25 High
  Courts), the Indian Kanoon API (paid per call; its terms allow RAG use with prominent "powered by
  IKanoon" attribution), and IL-TUR / LegalEval benchmarks (IL-TUR is CC BY-NC-SA: non-commercial,
  so get permission before using it even for internal evaluation).
