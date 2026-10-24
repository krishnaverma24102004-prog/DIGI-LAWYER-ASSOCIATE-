# AI Legal Associate & B2B SaaS Platform — Master System Specification

This file is the single source of truth for Claude Code and any developers working on the repository.

---

## 1. System Vision & Operating Philosophy

* **Product Identity:** An Enterprise B2B AI Legal Associate and Copilot for law firms and corporate legal departments.
* **Core Value Proposition:** Real-time consultation intelligence, automated contract redlining, multi-jurisdictional legal research, evidence contradiction detection, and automated pleading generation.
* **Target Audience:** Law firms, senior partners, associates, and corporate legal teams.
* **Regulatory Stance (Non-UPL):** The system provides **legal information and structured draft analysis**, never binding legal advice to unrepresented consumers. Strict disclaimers are enforced when output phrasing leans toward legal directives.

---

## 2. End-to-End System Topology

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                      CLIENT LAYER                           │
                  │  Next.js 16 Frontend  │  WebRTC Audio  │  Twilio Telephone    │
                  └──────────────┬──────────────────┬─────────────────┬─────────┘
                                 │                  │                 │
                                 ▼                  ▼                 ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI API GATEWAY (Port 8000)                      │
│   Auth / JWT Check  │  Rate Limiting  │  Audit Logger  │  PII Redaction Filter  │
└──────┬─────────────────────────┬─────────────────────────┬────────────────────┘
       │                         │                         │
       ▼                         ▼                         ▼
┌──────────────┐         ┌──────────────┐          ┌────────────────────────────┐
│   DEEPGRAM   │         │  LANGGRAPH   │          │    DOCUMENT & OCR ENGINE   │
│  STT & TTS   │         │ AGENT GRAPH  │          │ PyPDFium2 / Tesseract /    │
│ Speech-Voice │         │ State Orchestrator      │ Claude Vision Fallback     │
└──────┬───────┘         └──────┬───────┘          └────────────┬───────────────┘
       │                        │                               │
       │                        ├───────────────────────────────┤
       ▼                        ▼                               ▼
┌───────────────────────────────────────┐      ┌────────────────────────────────┐
│           EXTERNAL SERVICES           │      │        SUPABASE DATABASE       │
│  Anthropic API (Sonnet/Haiku 5.5)     │      │  PostgreSQL + pgvector         │
│  Tavily Live Web Search API           │      │  Multi-Tenant RLS Enforcement  │
└───────────────────────────────────────┘      └────────────────────────────────┘

```

---

## 3. Technology Stack Reference

| Layer | Component / Tool | Version / Details | Purpose |
| --- | --- | --- | --- |
| **Backend Runtime** | Python 3.12 + FastAPI | Uvicorn ASGI Server | High-concurrency Async API Gateway |
| **Database** | Supabase (PostgreSQL) | `pgvector` enabled | Relational storage + Vector Search + RLS |
| **Agent Orchestration** | LangGraph | `StateGraph` | Multi-step stateful reasoning pipeline |
| **LLM Provider** | Anthropic Claude | `claude-sonnet-5-5`, `claude-haiku-5-5`; direct or via an Anthropic-compatible gateway (`ANTHROPIC_BASE_URL`) | Legal analysis, drafting, and live extraction |
| **Speech-to-Text** | Deepgram Nova-3 | `nova-3` (configurable via `DEEPGRAM_MODEL`); live WebSocket / audio buffer | Real-time speech transcription & diarization |
| **Text-to-Speech** | Deepgram Aura | Low-Latency Streaming TTS | Conversational voice output in Talking Mode |
| **Web Search** | Tavily Search API | `tavily-python` | De-identified live web legal research |
| **Embeddings** | FastEmbed | `BAAI/bge-base-en-v1.5` | 768-dim local vector embeddings |
| **OCR Pipeline** | PyPDFium2 + Tesseract | Claude Vision Fallback | PDF text extraction & scanned image OCR |
| **Audio Transport** | `aiortc` (WebRTC) + WebSockets | Sub-100ms transport | Bi-directional voice streaming & data channel |
| **Frontend UI** | Next.js 16 + React 19 + Tailwind CSS | App Router | Split-screen ChatRoom & Interactive Studio |
| **Document Export** | ReportLab + `python-docx` | PDF & DOCX formatters | Professional report and pleading generation |

---

## 4. Completed Modules Architecture (Phases 1–7)

### Phase 1: Core Foundation & Database Security

* **Files:** `app/main.py`, `app/database.py`, `supabase/migrations/001_users_and_transcripts.sql`, `002_transcript_summary.sql`
* **Features:**
* Supabase client initialization supporting dual modes: `get_supabase_for_user(jwt)` for RLS-scoped user requests and `get_supabase_admin()` for trusted service-role background jobs.
* Base SQL schema establishing `users` and `transcripts` tables with active Row-Level Security (RLS).



### Phase 2: Live Audio Streaming & Anthropic Pipeline

* **Files:** `app/routers/audio_stream.py`, `services/anthropic_service.py`, `services/transcription_service.py`
* **Features:**
* Authenticated WebSocket endpoint (`/api/v1/ws/audio`) supporting JWT via subprotocol `["bearer", jwt]`.
* Real-time audio transcription via Deepgram with speaker labels ("Speaker 1", "Speaker 2").
* Structured JSON extraction powered by `claude-haiku-5-5` for low-latency live issue spotting and `claude-sonnet-5-5` for post-session summaries.



### Phase 3: Contract Ingestion & PDF Export

* **Files:** `app/routers/documents.py`, `services/pdf_service.py`, `supabase/migrations/003_documents.sql`
* **Features:**
* Document upload router (`POST /api/v1/documents/upload`) supporting PDF and plain text contracts up to 10 MB.
* Prompt-cached contract cross-referencing during live consultations using Anthropic `cache_control`.
* PDF report engine using ReportLab generating downloadable legal summaries (`GET /api/v1/transcripts/{id}/pdf`).



### Phase 4: Enterprise Multi-Tenant RAG & RBAC

* **Files:** `services/rag_service.py`, `services/prompt_engine.py`, `services/audit_service.py`, `supabase/migrations/004_enterprise_rag_and_rbac.sql`
* **Features:**
* Multi-tenant data model with `organizations` and `organization_members` (RBAC roles: `owner`, `partner`, `associate`, `paralegal`).
* Vector search over firm knowledge base (`legal_knowledge_base`) using `BAAI/bge-base-en-v1.5` (768 dimensions) via PostgreSQL RPC `match_legal_precedents`.
* Practice Area prompt engine supporting customizable domain templates (Personal Injury, Corporate/M&A, Criminal Defense, Real Estate).
* Append-only audit logging (`audit_logs`) tracking sensitive compliance actions.



### Phase 5: LangGraph Agents, OCR, Memory & PII Redaction

* **Files:** `services/agent_workflow.py`, `services/ocr_service.py`, `services/memory_service.py`, `core/guardrails.py`, `supabase/migrations/005_case_memory.sql`
* **Features:**
* **LangGraph Agent Workflow:** `StateGraph` (`node_intake_analyzer` $\rightarrow$ `node_legal_researcher` $\rightarrow$ `node_risk_evaluator` $\rightarrow$ `node_drafter`). Since Phase 6, `node_legal_researcher` routes conditionally through `node_external_researcher` (web search), and assessment is skipped when facts, citations and web results are unchanged.
* **OCR Engine:** Automated text extraction from scanned PDFs/images using PyPDFium2 and Tesseract, with automated fallback to Claude Vision (`claude-sonnet-5-5`) for low-confidence scans.
* **Persistent Case Memory:** Multi-session conversation threads (`case_threads` & `thread_messages`) injected into agent state.
* **PII Redaction Filter:** Presidio + spaCy masking (`PiiMasker`, consistent placeholders per session) of SSNs, Aadhaar, PAN, credit cards, bank accounts/IBAN, passports, emails, phone numbers, IPs and similar IDs (`PII_ENTITIES`) before text is sent to Anthropic or Tavily. Names, places and dates are kept.
* **UPL Safety Guardrail:** `verify_output_safety` appends `LEGAL_DISCLAIMER` to the drafter's message when it matches directive or guaranteed-outcome patterns.



### Phase 6: Web Search, Talking Mode, WebRTC, Multi-Jurisdiction & Document Studio

* **Files:** `services/web_search.py`, `services/tts_service.py`, `app/routers/webrtc.py`, `services/contract_diff_service.py`, `services/jurisdiction_service.py`, `services/evidence_service.py`, `services/drafting_engine.py`, `frontend/src/`
* **Features:**
* **Live Web Search Node:** `node_external_researcher` triggered when internal RAG confidence is low ($<0.65$). De-identifies research queries before sending to Tavily.
* **Deepgram Aura TTS:** Converts agent responses into low-latency audio streams, safely pronouncing masked placeholders (e.g., "the bank account you mentioned").
* **WebRTC Endpoint (`POST /api/v1/webrtc/offer`):** Peer-to-peer WebRTC connection via `aiortc` for real-time bi-directional voice streaming.
* **Contract Redlining Engine (`POST /api/v1/documents/compare`):** Clause-by-clause semantic diffing that isolates renumbered clauses and evaluates risk delta.
* **Multi-Jurisdiction Framework:** Dynamic switching across Indian (BNS/IPC/BSA/BNSS), US Federal/State, and UK Common Law with regional citation formatting (Bluebook, OSCOLA, SCC/AIR).
* **Deposition Contradiction Analyzer:** Cross-references witness audio/text transcripts against case contracts to flag factual contradictions. Both quotes of every finding are verified against the source texts (after normalization: verbatim substring, or a contiguous match covering ≥85% of the quote); unverified findings are dropped and counted in `discarded_unverified`.
* **Automated Pleading Generator:** Generates Legal Notices, Bail Applications, NDAs, and Affidavits exported to `.docx` and `.pdf` with missing information placeholders (`[●…●]`).
* **Next.js 16 Frontend App:** Full UI with a split-screen ChatRoom (`/`) and Interactive Document Studio (`/studio`).



### Phase 7: Production Infrastructure (Billing, Telephony, Jobs, Monitoring)

* **Files:** `services/stripe_service.py`, `app/routers/billing.py`, `services/twilio_service.py`, `services/telephony_session.py`, `app/routers/telephony.py`, `services/queue_service.py`, `app/worker.py`, `app/routers/jobs.py`, `core/rate_limiter.py`, `core/metrics.py`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/deploy.yml`, `supabase/migrations/007_billing_telephony_and_jobs.sql`
* **Features:**
* **Stripe Billing (per organization):** `POST /api/v1/billing/checkout-session` (owners; Starter/Pro/Enterprise plus an optional metered Price), `POST /api/v1/billing/webhook` (signature-checked, idempotent per event id via `stripe_events`; handles `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.payment_succeeded`, `payment_intent.succeeded`; keeps `billing_accounts` and `organizations.plan_tier` in sync), `GET /api/v1/billing/usage` (owners/partners, RLS).
* **Usage Metering:** every live session that streamed audio to speech-to-text (`websocket`, `webrtc`, `telephony`) records the seconds of audio actually streamed in `audio_usage` when it ends (pauses over 1.5 s don't count; every started minute billed; typed-only sessions aren't metered). WebRTC audio is only forwarded to Deepgram while the push-to-talk button is held (plus a 0.5 s tail), so silence is neither transcribed nor billed and reports it to the Stripe meter (`STRIPE_METER_EVENT_NAME`, de-duplicated by session id). Sessions are **not** blocked when included minutes run out; overage is billed by the metered Price.
* **Twilio Phone Intake:** `POST /api/v1/telephony/voice/incoming` verifies `X-Twilio-Signature` (URL from `PUBLIC_BASE_URL`), looks up the dialled number in `telephony_numbers`, and answers with `<Connect><Stream>` carrying a short-lived HMAC stream token. `WS /api/v1/ws/telephony` checks the token against the call SID, decodes 8 kHz G.711 mu-law to PCM for Deepgram, runs the live session in conversation mode, and streams Aura TTS back as mu-law frames (barge-in sends `clear`). Numbers are managed with `GET/POST/DELETE /api/v1/telephony/numbers`.
* **Background Jobs (ARQ + Redis):** `task_generate_pdf_report` (Storage bucket `reports`, downloaded via a signed URL from `GET /api/v1/jobs/{job_id}`), `task_trigger_n8n_webhook` (exponential backoff), `task_batch_embed_documents` (`POST /api/v1/knowledge/from-document`). Without `REDIS_URL`, synchronous fallbacks are used.
* **Rate Limiting:** `RateLimitMiddleware` applies `RATE_LIMIT_DEFAULT` to every `/api/` route (Stripe and Twilio webhooks exempt); `limit("llm")` and `limit("billing")` dependencies on expensive routes. Keyed by hashed bearer token or IP; counters in Redis when configured. (slowapi's own middleware is not used: it can't find routes under FastAPI 0.147's included routers.)
* **Monitoring:** Prometheus at `/metrics` (optional `METRICS_TOKEN`): HTTP metrics, `claude_tokens_total`, `telephony_response_latency_seconds`, `telephony_calls_total`, `telephony_active_calls`, `live_sessions_active`, `db_connections_open`.
* **Shared Indian Law Corpus (migration 008):** `legal_knowledge_base` rows with `org_id NULL` are a shared corpus every org searches alongside its own material (read-only for users); `legal_authorities` indexes every Supreme Court judgment (1950 onwards: title, parties, S.C.R. report and INSC neutral citations) for the citation check. Loaded by `scripts/ingest_sc_judgments.py` from the public AWS Open Data bucket `indian-supreme-court-judgments` (index for all years; full text for chosen years).
* **Quality Evals:** `evals/cases.json` (Indian matters in English, Hinglish and Hindi) and `scripts/run_evals.py`, which replays each case through the real pipeline against the configured model and checks language, key points, facts, risks, forbidden guarantees, PII masking and citation cleanliness.
* **Self-serve sign-up & invitations (migration 009):** the app's sign-up form sends `full_name` and `firm_name`; the sign-up trigger names the workspace after the firm. `POST /organizations/{id}/members` adds people who have an account and *invites* those who don't (`organization_invitations`, 14 days); on sign-up with an invited email the trigger joins them to the firm with that role instead of creating a personal workspace. `GET/DELETE /organizations/{id}/invitations`. Team page at `/team`.
* **Bulk Review Grid (migration 010, `services/review_service.py`, `/reviews`):** up to 50 documents x 15 questions (presets for Indian commercial contracts, leases / leave and licence, employment, NDAs). Each document is PII-masked and answered in one call; every answer carries a verbatim source quote that is checked against the document (`verified`), stored per cell (`review_cells`) as it finishes, exportable as CSV. Page at `/review`.
* **Indian Workflow Packs (`services/workflow_service.py`, `/workflows`):** cheque bounce (s. 138/142 NI Act), consumer complaint (CPA 2019 s. 69, Commission by consideration paid), bail (BNSS or CrPC by offence date; default bail s. 187(3) BNSS / s. 167(2) CrPC; undertrial release s. 479 BNSS / s. 436A CrPC). Deadlines are computed in code from the dates given, with their statutory basis; the only AI step is the suggested draft (via `/drafting/generate`). Page at `/workflows`.
* **Court case tracker (migration 011, `services/ecourts_service.py`, `/cases`):** cases by CNR with hearing dates, synced from the eCourtsIndia API when `ECOURTS_API_KEY` is set (no official eCourts API exists; the portal's captcha is never bypassed), or entered by hand. The worker's daily cron (`task_hearing_reminders`, 7:00 IST) refreshes upcoming hearings, sends clients a WhatsApp template reminder once per hearing date, and posts each org's agenda to n8n.
* **Indian Kanoon (`services/indiankanoon_service.py`, `GET /caselaw/search`):** case-law search, and the citation check's fallback for cases the SC index doesn't know (party-name lookup, max 3 per check, cached). Attribution "powered by IKanoon" on the About page is required by its terms.
* **WhatsApp intake (migration 012, `services/whatsapp_service.py`, `services/whatsapp_intake.py`, `/whatsapp`, `/inbox`):** Meta Cloud API webhook (signature-checked, de-duplicated by message id, processed in the background). Consent first (nothing reaches the AI before YES); then the agent team in conversation mode, PII-masked, in the client's language, with voice notes transcribed (Deepgram `multi`); the chat is saved as a transcript owned by the number's lawyer. LAWYER hands off; lawyers reply, take over, hand back or close from the inbox. Service role, scoped to the number's org (listed in invariant 2 as a server-side job).
* **About page (`/about`):** not-legal-advice notice, data handling, and the CC BY 4.0 attribution required for the Supreme Court corpus.
* **Safety rails for customers (migration 013, `services/safety_service.py`, `app/routers/safety.py`, `/safety`):** the product never lets the tool's mistakes, or one person's slip, leave the firm unchecked.
  * **Trash:** every Delete (consultations, documents, drafts, review grids, court cases, case threads, knowledge sources) calls `public.trash_item()`, which snapshots the record and its dependent rows into `trash_items` and removes it; direct `DELETE` on those tables is revoked from `authenticated`. Restorable for 30 days (`restore_trash_item`, re-links threads/documents); then the worker's daily cron (`task_purge_expired_trash`, 02:00 IST) erases the snapshot and keeps a tombstone (who requested, deleted, approved, erased, and a SHA-256 of the content) with a PDF erasure certificate (`GET /trash/{id}/certificate`). Endpoints return 200 `trashed` or 202 `approval_requested`.
  * **Approvals (maker-checker, `approval_requests`):** associates/paralegals deleting client records (consultations, documents, court cases, case threads, knowledge sources) create a request; a partner/owner approves (`POST /approvals/{id}/approve` carries it out as the approver) or rejects. Turning on public intake, making someone an owner and erasing from the Trash early need a second senior; a firm's only owner/partner decides alone. Requesters can't decide their own requests (DB check).
  * **Legal hold** (`PUT /legal-hold`, owners/partners) on case threads and court cases blocks deleting them and the records linked to them (409 `legal_hold`); hold columns change only through `set_legal_hold()`.
  * **Public intake** (`organizations.public_intake_enabled`, default off, `GET/PUT /intake`): until on, WhatsApp chats go straight to the lawyer and calls hear a recorded message. When on, the AI runs in intake mode (`AgentContext.intake_only`, `INTAKE_DRAFT_PROMPT`) and `services/intake_guard.py` sends only safe intake questions; replies with legal substance (law, sections, deadlines, amounts, directives, predictions) are held (`whatsapp_messages.status = pending`, `hold_reasons`) for a lawyer to send, edit or discard (`POST /whatsapp/conversations/{id}/held/{message_id}`) while the client gets a holding message; on the phone the caller hears a holding line and the draft is kept in the transcript metadata (`held_replies`).
  * **Consent before a consultation:** without the client's recorded consent (`consent` on the WebRTC offer / WebSocket, or `case_threads.ai_consent_at` within 12 months) a live session keeps typed notes only: no AI analysis, no speech-to-text (`CONSULTATION_CONSENT_REQUIRED`). Phone calls announce the AI and recording in the greeting.
  * **Drafts:** exports of unapproved drafts are marked "AI DRAFT · UNREVIEWED" on every page; `POST /drafting/{id}/approve` records who and when (a DB trigger stamps it and clears it on any edit). `GET /drafting/{id}/checklist` (`services/draft_check.py`) lists unresolved citations, amounts/dates/cheque numbers not in the draft's recorded `fact_basis` (lawyer's inputs, case facts, documents) and unfilled placeholders; export is never blocked (`unresolved=keep|remove`), and the choice is audited.
  * **Governing law** (`services/governing_law.py`, `documents.governing_law`): redlines and review grids show when a contract's own governing-law clause names a different jurisdiction than the one analysed, and tag enforceability conclusions with that caveat.
  * **Production model gate:** with `ENVIRONMENT=production` the API and worker refuse to start unless every model is a Claude model, the gateway isn't a local one and structured outputs are native (`anthropic_service.production_model_problems`).
* **Containers & CI:** multi-stage `Dockerfile` (non-root uid 10001, Tesseract included); `docker-compose.yml` runs `api`, `worker` and `redis`; GitHub Actions runs pytest (with a Redis service), frontend lint/build, and builds/pushes the image to GHCR on `main`.



---

## 5. Non-Negotiable Architectural Invariants

1. **PII Masking Order:** All text (transcripts, documents, memory, research queries) MUST pass through `core/guardrails.py` (`PiiMasker` / `mask_pii`) before it is sent to Anthropic or Tavily. Known exceptions:
   * Raw audio goes to Deepgram unmasked, because speech-to-text needs the audio. Masking applies to the transcript Deepgram returns.
   * The OCR vision fallback sends page images to Claude, and images can't be masked. Set `OCR_VISION_FALLBACK=false` to keep scanned documents on the server.
   * TTS receives speakable phrases ("the account number you mentioned"), never unmasked values.
2. **Database Security (RLS):** User-facing queries use `get_supabase_for_user(jwt, org_id)`, which sends the `x-org-id` header used by `public.active_org_id()`. `X-Org-Id` is optional: without it, the user's active organization is used, and membership is always checked. The service role (`get_supabase_admin()`) is used only for:
   * JWT verification (`auth.get_user`)
   * the health check
   * audit-log inserts
   * `find_user_id_by_email`, after the caller has been authorized to add members
   * the `save_live_session` fallback, when the JWT expires during a long consultation
   * server-side jobs with no user session, each scoped explicitly to one organization: Stripe webhooks and usage metering, phone calls and WhatsApp chats (the number's org, saved as the number's owner), hearing reminders, the ARQ worker (which re-checks the job user's role before acting), and the `db_connection_count()` metrics sample

   The trash/approval/intake/hold functions of migration 013 are `SECURITY DEFINER` with their own role checks, called as the user; `purge_expired_trash()` is service-role only (the worker).

   Don't add other service-role uses in user-facing paths. Billing tables (`billing_accounts`, `audio_usage`, `stripe_events`) are written only by the server.
3. **Citation Grounding:** Prompts tell the agents to cite only authority they were given, **and** `services/citation_service.py` checks every statute and case they write, in the risk evaluator (legal issues' `authority`), the drafter (the reply) and the saved session summary. Statuses: `grounded` (in the RAG passages, web results, document, case memory or jurisdiction notes; not the conversation, where a case the client names is a claim, not authority), `known_case` (a real judgment in the `legal_authorities` citation index), `statute` (the act is in the registry and the section exists), `repealed` (IPC/CrPC/Evidence Act, with the BNS/BNSS/BSA equivalent), `invalid` (the section doesn't exist: fabricated) and `unverified`. Invalid and unverified citations are removed from an issue's authority and marked `[unverified]` in replies and summaries. Each check carries a plain `label` saying what was and wasn't checked. BNS/BNSS/BSA sections note the pre-1 July 2024 IPC/CrPC/Evidence Act section, and old-code sections the new one (an indicative table). Text for clients (conversation and intake modes) drops sentences with unverified citations instead of flagging them, and speech never recites citations. Prompt examples show citation *formats* with `<placeholders>`, never real-looking citations. The registry checks that a section exists, not what it says.
4. **No Direct Legal Advice (UPL Prevention):** Agent responses keep an informational tone. `verify_output_safety` appends `LEGAL_DISCLAIMER` to the drafter's message when it matches directive or guaranteed-outcome patterns, in every mode.
5. **Prompt Caching Discipline:** Fixed system instructions, practice area rules, and attached contract texts must be placed in cached prompt blocks (`cache_control`, via `prompt_engine.build_system`) to optimize latency and cost.
6. **Contradiction Verification:** Both quotes of every contradiction finding are verified against the source texts by `evidence_service.quote_found`. A quote passes after normalization if it appears verbatim, or if a contiguous match covers at least `QUOTE_MATCH` (85%) of it. Findings that fail are discarded and counted in `discarded_unverified`. `quote_match` reports `exact` or `close` (with the quote's words that differ), on contradiction findings and review cells, so the lawyer can see a near-match.

---

## 6. Verification & Testing Protocol

Before committing any code modifications, run the complete test suite:

```powershell
# Run full backend unit and database test suite
pytest

# Verify Next.js frontend linting and production build
cd frontend
npm run lint
npm run build

```

* **Database Tests:** Ensure embedded/local Postgres tests pass for RLS policy isolation across multi-tenant organizations.
* **Agent Tests:** Ensure LangGraph node transitions, PII masking, and WebRTC streaming pass all mocked assertions.
