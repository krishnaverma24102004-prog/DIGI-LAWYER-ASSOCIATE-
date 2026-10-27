# P21. Shadow AI and paper policies: firms have no AI policy, clients want disclosure, and nobody can prove what was checked

**Severity:** high · **Size:** big · **Region:** Global (US/UK); India (Kerala HC policy, DPDP)

**Who has it:** Managing partners, GCs reviewing panel firms, risk and compliance teams, small and mid firms, clients, court registries

## What goes wrong

Most lawyers use AI but many firms have no AI policy, and lawyers paste client data into general chatbots. Where policies exist, they are breached (Butler Snow's lawyers used ChatGPT against policy and were disqualified anyway). Clients increasingly want disclosure of AI use and many distrust it. When a fake citation surfaces, the firm can't show who used which tool, what was verified or when. Courts are starting to require documentation (Kerala HC requires an audit of every AI use including verification). Supervising partners carry liability for work they can't audit, and in India this meets DPDP consent and purpose obligations.

## Evidence of scale

- Clio 2025: 79% of legal professionals use AI but 53% say their firm has no AI policy or don't know of one; 78% of clients want disclosure, 35% of professionals rarely or never disclose; 36% of clients would trust an AI-using lawyer less; legal-specific AI use fell to 40% from 58%. ([source](https://www.2civility.org/2025-clio-legal-trends-report/))
- Kerala HC policy (July 2025): bars district judges from using AI for findings or judgments, requires meticulous verification including citations and a detailed audit of every AI use. ([source](https://www.medianama.com/2025/07/223-kerala-hc-bars-ai-tools-chatgpt-deepseek/))
- Johnson v. Dunn: the ChatGPT use breached Butler Snow's own AI policy, yet three lawyers were disqualified, referred and ordered to disclose the sanction. ([source](https://edrm.net/2025/07/when-ai-policies-fail-the-ai-sanctions-in-johnson-v-dunn-and-what-they-mean-for-the-profession/))

## Why current tools don't solve it

Enterprise tools log prompts for IT, but none produces a filing-ready verification record (each citation, status, who checked, when) a partner can sign off or a court can accept, or a client-facing AI-use disclosure. Small firms can't afford enterprise governance and fall back on chatbots with no masking, audit log or matter scoping. Nothing stops a lawyer switching to a general chatbot when the firm tool is slow.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Turning an AI policy into enforced settings inside the firm's tool. Producing a filing-ready Verification Record (each citation, its machine status, who confirmed it and when) that a partner signs and that can be annexed or shown to a court. Generating a client AI-use disclosure from real usage data rather than boilerplate. Making the sanctioned tool the convenient one without opening a new unchecked answer path.

### What it can't fix

We cannot stop a lawyer opening ChatGPT on a personal phone. Shadow AI is reduced only by making the sanctioned tool convenient and safe, and by attestation, not by surveilling personal devices (which would itself raise DPDP and employment problems). Whether a court accepts our record format is up to that court. We do not decide whether a citation supports a proposition. That is P12's verifier and the lawyer's judgment, so the record states what was machine-checked and what a human confirmed, and never certifies correctness. We make no latency promise for Quick ask, because the check runs before the answer is shown.

### What the user sees

Owners get a 'Firm AI Policy' page (in /safety) with switches, not a PDF:
- which features are allowed (live consultation, drafting, web research, WhatsApp intake, Quick ask);
- whether client consent is required before AI (shared with P20);
- whether drafts with any citation not grounded / known_case / statute can be exported;
- whether paralegal-generated drafts need partner approval;
- who may export to a court.
Each member accepts the policy text once, and again on each new version, and the acceptance is recorded.

Every draft has a 'Verification' panel. It lists each citation found by citation_service with its status (grounded / known_case / statute / repealed / invalid / unverified), and a per-citation 'I have read this authority' tick that records the lawyer and time. Export and court-bundle buttons stay disabled until the policy conditions are met, with the exact reason shown. 'Download Verification Record' produces a one-page PDF/DOCX annexure.

Per matter, 'Client AI disclosure' produces a letter in English or Hindi. It lists which AI functions were used, the processors involved and what was masked, and states that a named advocate reviewed the output. The firm edits the letter and sends it themselves.

A 'Quick ask' box on every page is labelled 'Internal research aid, not for clients or court'. The answer appears once checked, with authorities already marked (green known_case / statute / grounded, amber repealed with the new-code equivalent, red [unverified]). A disclaimer is appended when the answer reads as advice or a guarantee. 'Copy' copies the annotated text, markers included. 'Open in Studio' moves it into a draft, where the full Verification panel applies.

### What the system does

1) New table `org_ai_policy` holds versioned policy JSON plus a text body; past versions are append-only. `policy_acceptances` records user, version and accepted_at. Policy changes go through the existing approvals flow (safety_service maker-checker).

2) Enforcement is deterministic, in FastAPI dependencies. `require_policy(feature)` is added to the drafting, consultation, research, WhatsApp and quick-ask routers. A disabled feature returns 403 with the policy clause. A member who has not accepted the current version gets 428 'accept policy'.

3) Verification state lives in a new table `citation_confirmations` (draft_id, citation_key normalized by citation_service, machine_status, confirmed_by, confirmed_at, note) together with the draft text hash. Confirmations lapse when the draft text changes, as approved_by does in migration 013.

4) Export gate in the drafting_engine export:
- Every citation in the current text must have a machine_status in policy.allowed_statuses or a human confirmation.
- invalid citations can never be confirmed (a hard block, consistent with invariant 3).
- approved_by must be set by a role the policy permits.
- Otherwise export returns 409 with the list of blocking citations.

5) The Verification Record generator (pdf_service plus python-docx) is a pure template over citation_confirmations, citation_service statuses, approved_by and the P20 ledger rows for the draft. Its footer carries the P20 hash chain.

6) The disclosure letter is a fixed bilingual template filled from ai_use_ledger aggregates for the matter. No LLM writes it, so it cannot overstate or understate use.

7) Quick ask uses the same checked path as the drafter (fixes objection 1). A new shared function `services/reply_finalizer.finalize_reply(text, sources, lookup)`, extracted from node_drafter's post-processing so there is one implementation, runs in order:
- (a) citation_service.case_lookups + lookup_authorities;
- (b) citation_service.verify_text against Sources built from the RAG passages and web results actually given to the model;
- (c) annotate, so invalid and unverified authorities are marked [unverified] and repealed ones get their BNS/BNSS/BSA equivalent;
- (d) verify_output_safety, appending LEGAL_DISCLAIMER on directive or guaranteed-outcome patterns;
- (e) PiiMasker.unmask, last.
The Quick ask flow is: input masked → guarded_call (P20: ledger, consent and egress checks) → Haiku with retrieved RAG context → finalize_reply → response containing the annotated text plus the check list.
The response is not streamed before finalize_reply finishes, so no unchecked text ever reaches the screen or clipboard. Latency is measured (quick_ask_latency_seconds) but not promised.
A static test fails CI if any router returns model-generated text without passing it through finalize_reply. This covers the drafter, consultation summary, WhatsApp, telephony and Quick ask.

8) An owner report shows per-member AI use counts monthly. It gives counts only, as a prompt for a conversation, not a sanction.

### Where it is built

Extend:
- app/services/safety_service.py: approvals for policy changes.
- app/routers/drafting.py and app/services/drafting_engine.py: export gate.
- app/services/citation_service.py: a stable citation_key; check, annotate, verify_text and lookup_authorities are reused as they are.
- app/services/agent_workflow.py: node_drafter calls reply_finalizer.finalize_reply instead of inline post-processing.
- app/core/guardrails.py: verify_output_safety, reused unchanged.
- app/services/draft_check.py and app/services/pdf_service.py.
- frontend/src/app/safety/page.tsx and frontend/src/components/SafetyPage.tsx: policy editor.
- The studio draft view: Verification panel.
New:
- app/core/policy.py: require_policy dependency.
- app/services/reply_finalizer.py.
- app/services/quick_ask.py and app/routers/quick_ask.py: POST /api/v1/quick-ask with limit('llm').
- frontend/src/components/QuickAsk.tsx.
- supabase/migrations/015_ai_policy_and_verification.sql: org_ai_policy, policy_acceptances and citation_confirmations, with RLS.
- app/routers/policy.py.
Reuses the P20 ai_use_ledger and guarded_call.

### Why current tools fail and this won't

Enterprise tools log prompts for IT security, not for the supervising partner or the court. None produces a per-filing record of which citations were checked by whom, and none ties export to that record. Their quick-chat panes answer without any citation check, which is how fabricated authorities reach filings. Clio surveys show 53% of firms have no AI policy, because a policy is a document nobody can enforce.

Ours is settings that block actions, plus a record generated from the same checks that blocked or allowed them. Even the convenience box runs the same citation and UPL checks as the drafter, so the easiest path is also a checked one. Small Indian firms get this at chamber price, not as an enterprise governance add-on. Kerala HC-style audit expectations ('detailed record of every AI use including verification') map one-to-one onto the ledger plus the Verification Record.

### Safeguards

Policy changes need maker-checker approval and are audited. invalid citations are a hard block regardless of policy (invariant 3). Quick ask is not an exception path: it goes through PII masking, the P20 ledger and consent gate, citation_service and verify_output_safety via the same finalize_reply the drafter uses, and is labelled as an internal aid. The disclosure letter is a draft for the advocate to send, never auto-sent. No monitoring of personal devices or browsers. The per-member usage report shows counts only. Every output reaching court or client passes approved_by by a lawyer.

### How the panel's objections were answered

Objection (Quick ask is an unchecked answer path):
- Quick ask now goes through the same reply_finalizer.finalize_reply as the drafter. The function is extracted from node_drafter, so there is one implementation.
- finalize_reply runs citation_service lookup, verify_text and annotate, so invalid and unverified authorities are marked [unverified], then verify_output_safety, then unmask. Quick ask also passes the P20 guarded_call (masking, ledger, consent).
- The 3-second promise is dropped. The answer is returned only after the check completes, so no unmarked text reaches the screen or clipboard, and latency is measured, not promised.
- Tests added: a fabricated BNS section in a mocked Quick ask reply is marked [unverified] with status invalid; an unknown case is marked; a guarantee phrase gets the disclaimer.
- A static test ensures no route returns model text without finalize_reply.

### Acceptance tests

- Unit: a policy with drafting disabled makes POST /drafting/generate return 403 naming the clause, with 0 model calls.
- Unit: a member who has not accepted policy v2 gets 428 on any AI route, including /quick-ask. After POST /policy/accept the call proceeds and policy_acceptances has the row.
- Unit: a mocked Quick ask reply 'This is punishable under Section 999 of the BNS' (beyond the registry's last section) is returned with that citation marked [unverified]. The check list shows status 'invalid', and the raw unmarked sentence appears nowhere in the response body.
- Unit: a mocked Quick ask reply citing an unknown case 'Ramesh v. State of Nowhere (2019)' is marked [unverified]. A reply citing 's. 302 IPC' shows status repealed with the BNS equivalent.
- Unit: a mocked Quick ask reply 'You will definitely get bail, file tomorrow' has LEGAL_DISCLAIMER appended by verify_output_safety.
- Unit: Quick ask input containing a PAN reaches the mocked model masked, and a ledger row with purpose='quick_ask' exists (P20).
- Static test: every route that returns model text calls reply_finalizer.finalize_reply (an AST scan of routers and services). It fails CI if a new path skips it.
- Unit: a draft containing one 'invalid' citation (a fabricated BNS section) makes export return 409 listing that citation, and confirming it returns 422 'invalid citations cannot be confirmed'.
- Unit: a draft with one 'unverified' case citation blocks export. After an associate confirms it, export is allowed only after partner approval when policy.requires_partner_approval=true. Editing one character of the draft clears confirmations and approval, and export is blocked again.
- Unit: the Verification Record for the fixture draft contains every citation_key, status, confirmer name and timestamp, and its hash verifies via /compliance/verify.
- Unit: the disclosure letter for a matter with 3 ledger rows (summary, draft, web search) mentions exactly those three functions and the processors Anthropic and Tavily, and does not mention Deepgram when no audio was used.
- DB test: org B cannot read org A's citation_confirmations or policy. Updating a past policy version raises 42501.

### Reviewers' minor notes

- The AST rule 'every route returning model text passes finalize_reply' will hit live-session issue-spotting pushed over WebSocket and structured review-grid answers. Define the exemptions explicitly (structured fields already checked by the risk evaluator, or quote-verified cells), so CI doesn't force awkward workarounds.
- The Kerala HC AI policy governs the district judiciary's own use of AI, not advocates' filings. Don't market the Verification Record as meeting a court requirement for advocates; present it as voluntary evidence of supervision.
- Migration 015 collides with P23, P10 and P16.
- If a Verification Record is annexed to a filing, it can disclose work product: which authorities were considered and rejected. Offer a 'court version' that lists only the citations in the filed text, and keep the full record internal.
- require_policy and the 428 acceptance check on WhatsApp and telephony AI paths: no member JWT is present there. Specify that the number owner's acceptance of the current version is what's checked.
- The static finalize_reply test must define 'model text'. Review-grid cells, contradiction findings and redline suggestions return structured output; say whether citation annotation applies to them, or the AST scan will be noisy.
- Migration 015 collides with P10, P16 and P23.

