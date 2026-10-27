# P29. Reliable Indian legal research is costly and split across subscriptions, so solos borrow logins, use free sites or ChatGPT and risk fake citations

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Junior and solo advocates, district-court practitioners, small chambers

## What goes wrong

A newly independent advocate often can't afford SCC Online (often over Rs 30,000 a year) or Manupatra, so they pick one, share a senior's subscription, use bar library terminals in 30-45 minute slots, or use free Indian Kanoon plus ChatGPT. Incumbents now layer credit-based AI on firm-tier subscriptions costing lakhs, with unannounced prices. Research, citation checking, drafting and court tracking sit in separately paid tools; some lawyers reverse-engineer subscription APIs in breach of terms. The risk is unverified or repealed citations (IPC instead of BNS) in filings.

## Evidence of scale

- Legally India thread: a newly independent lawyer can't afford both SCC and Manupatra; replies suggest Indian Kanoon, a senior's subscription, court e-libraries or eSCR. ([source](https://www.legallyindia.com/convos/topic/291466-scc-or-manupatra-subscription-for-a-newly-independent-lawyer))
- SCC Online annual subscriptions often exceed Rs 30,000; starter package subsidised up to 60%; bar library slots typically 30-45 minutes; Rs 50 per TruePrint download. ([source](https://jurigram.com/advocates/resources/legal-research/scc-online-free-access-advocates))
- 2026 guide: SCC Online and Manupatra 'still expensive at firm tier' and 'now layered with credit-based AI', firm tier at 'Multiple lakhs / year'. ([source](https://blog.ipleaders.in/ai-tools-for-lawyers-in-india-the-2026-definitive-guide/))
- SCC Online announced 'AI Pro' on 26 Jan 2026 as 'Coming soon', with no pricing. ([source](https://www.scconline.com/blog/post/2026/01/26/scc-online-ai-pro-republic-day-announcement/))
- A Legally India commenter reverse-engineered SCC Online and Westlaw APIs into MCP connectors, admitting it is 'kind of violating ToS'. ([source](https://www.legallyindia.com/convos/topic/479871-h))
- iManage research: the average Indian legal professional loses about 37-40 minutes a day searching for information. ([source](https://legaltechnology.com/indias-legal-tech-market-homegrown-ambition-and-global-inroads/))

## Why current tools don't solve it

SCC Online and Manupatra sell content subscriptions with early AI layers; Indian Kanoon is free but not an authenticated reporter; ChatGPT invents Indian citations. None bundles research, IPC-BNS mapping, citation checking against the SC index, drafting and deadline tracking in one INR-priced seat for a single advocate built on free sources (SC open data, Indian Kanoon, India Code).

## Panel verdict

**Status:** solved (round 3)

**Effort:** S

### What software can fix

The search-and-cite surface for P12/P22 authority tokens inside /studio and /verify. A lawyer finds or pastes an authority, from our open corpus, from Indian Kanoon, or as a citation found in SCC Online, CaseMine or Jhana. It enters the draft as a resolved, pre-verified token. Indian Kanoon spend is capped per org by a tamper-proof, server-recorded ledger. The cap covers every path that can call Indian Kanoon: user requests, WhatsApp and phone intake, and worker jobs. Public channels get their own small sub-cap.

### What it can't fix

We don't compete on corpus size or search quality with SCC Online, Manupatra, CaseMine, Jhana or Indian Kanoon itself. We can't replace headnotes or SCC/AIR page numbers. Pricing belongs to the P19 head. Whether Indian Kanoon's terms allow merging its results into our results is a contract question; until it is confirmed in writing, its results stay in a separate attributed list. When a public-channel budget is exhausted, citations in intake replies that only Indian Kanoon could have confirmed stay unverified and are removed or marked, per invariant 3. That is the safe outcome, but it means those replies get fewer confirmed authorities.

### What the user sees

In /studio, an 'Authorities' panel with three tabs:
- 'Search': results from the shared corpus, plus a separate 'Indian Kanoon results (powered by IKanoon)' list.
- 'Paste a citation': anything found in another tool. It is resolved, or shown red and not inserted.
- 'Section': India Code text with the BNS/IPC correspondence.
'Cite this' inserts a green token.

On /billing the owner sees the month's Indian Kanoon spend, split by channel (in-app, WhatsApp intake, phone intake, background jobs). There are two caps: an org cap, and a public-intake sub-cap that defaults to Rs 0 until the owner sets it, with a per-conversation daily limit. When a cap is reached, in-app users see 'Monthly Indian Kanoon budget reached; ask your owner to raise it', and cached results still work. In WhatsApp or phone intake the client sees nothing different. The lawyer's inbox view of the chat shows 'citation not checked against Indian Kanoon (intake budget reached)' beside any citation that was marked unverified.

### What the system does

1. GET /caselaw/search gains a shared-corpus mode (hybrid BM25 + bge over judgment_texts). Indian Kanoon results are returned separately.

2. POST /authorities/resolve runs the P12 resolver. 'Cite this' adds the authority id to the draft.

3. GET /statutes/{act}/{section} reads the P22 statutes table.

4. Spend ledger (migration 014): ik_tariff; ik_budget (org_id, monthly_cap_paise, public_intake_cap_paise default 0, per_conversation_daily_calls default 5); ik_spend (org_id, user_id nullable, channel in_app|whatsapp|telephony|worker, scope_key, call_kind, paise, cache_key, created_at). ik_spend is append-only by trigger, and anon and authenticated have no insert, update or delete grants.

5. One internal function, _ik_reserve(p_org, p_user, p_channel, p_scope_key, p_kind, p_cache_key), does all reservations. It is security definer, and execute is revoked from public, anon and authenticated. It:
- takes pg_advisory_xact_lock(hashtext('ik:'||p_org));
- reads the price from ik_tariff;
- checks the org monthly cap;
- for whatsapp and telephony, also checks public_intake_cap_paise and the per-scope_key daily call limit;
- inserts the row and returns true, or returns false.

6. Two callable wrappers:
(a) reserve_ik_call(p_org, p_kind, p_cache_key) is granted to authenticated. It requires p_org = active_org_id() and membership, sets channel in_app and the user to auth.uid(), and is used in user-JWT paths.
(b) reserve_ik_call_for_org(p_org, p_channel, p_scope_key, p_kind, p_cache_key) is granted only to service_role, and p_channel must be whatsapp, telephony or worker. It is used only from the server jobs already listed in invariant 2, each scoped explicitly to one organisation: WhatsApp intake (the number's org_id, with the conversation id as scope_key), phone sessions (the number's org, with the call SID), and the ARQ worker (the job's org, after its existing role re-check, with the job id).

7. In code:
- citation_service.lookup_authorities(db, keys, names, *, ik_budget) and indiankanoon_service.find_cases(names, ik_budget) and search(..., ik_budget) take a required IkBudget protocol argument. Implementations are UserIkBudget(db, org_id), which calls the rpc through the user's JWT client, and OrgIkBudget(admin, org_id, channel, scope_key), which calls reserve_ik_call_for_org. NoIkBudget makes zero calls.
- There is no default, so a call site that forgets its budget fails at type-check and test time rather than spending without limit.
- The process lru_cache becomes an explicit cache (dict plus an optional ik_lookup_cache table of name-token tuples and existence booleans, with no client data). It is checked before reserving, so cache hits cost nothing.
- whatsapp_intake.py:245 passes OrgIkBudget(admin, number['org_id'], 'whatsapp', conversation_id). live_session and telephony_session pass the user's or the number's budget. drafting.py:283 and the caselaw router pass UserIkBudget.
- If a reservation returns false, the lookup stops. Unresolved names stay unverified and invariant 3 removes or marks them.

8. set_ik_budget(org, cap, public_cap, per_conversation) is owner-only and audit-logged.

9. Query rewriting uses mask_pii first.

10. The Indian Kanoon terms review is recorded in docs/compliance/indiankanoon-terms.md. Merge and retention stay behind feature flags that are off by default.

### Where it is built

Extend:
- app/services/indiankanoon_service.py (required ik_budget parameter; explicit cache replacing lru_cache)
- app/services/citation_service.py lookup_authorities (required ik_budget)
- app/services/whatsapp_intake.py (line 245), app/services/telephony_session.py, app/services/live_session.py (_lookup_authorities), app/routers/drafting.py (line 283), app/worker.py (pass budgets)
- app/routers/caselaw.py
- app/services/rag_service.py
- the P12 resolver and drafting_engine tokens
- the P22 statutes table
- frontend/src/app/studio/page.tsx and the billing page (spend by channel, caps)

New:
- app/services/ik_budget.py (the IkBudget protocol, UserIkBudget, OrgIkBudget, NoIkBudget)
- migration 014: ik_tariff, ik_budget (with the public sub-cap), ik_spend (channel, scope_key), _ik_reserve, reserve_ik_call, reserve_ik_call_for_org, set_ik_budget, ik_lookup_cache
- docs/compliance/indiankanoon-terms.md
- tests/test_ik_budget_paths.py and tests/db/test_ik_spend.sql

### Why current tools fail and this won't

This is not a better research tool; CaseMine, Jhana and Indian Kanoon search more. What they don't do is take a citation found anywhere, check it inside the firm's own draft and filing record, and feed the P02 gate. Our version of that runs at a cost that is capped, visible and attributable across every channel, including unauthenticated public intake, which no per-seat research product has to deal with. The budget is enforced in the database under a lock, priced from a server-side tariff, and required by the type signature of every function that can make a paid call. Forgetting to apply it is a test failure, not a bill.

### Safeguards

Licensed or open sources only. Indian Kanoon attribution is shown wherever its results appear. Merge and retention follow the recorded terms review. Spend is append-only, priced from the server, locked per org, and capped for every channel. Public unauthenticated intake has its own sub-cap (default zero) and a per-conversation daily limit, so an anonymous WhatsApp user can't drain the firm's credit. The service-role wrapper is granted only to service_role and is used only in the server jobs listed in invariant 2, each scoped to one organisation, with no new service-role use in user paths. An exhausted budget fails safe: citations stay unverified and are marked or removed. Masking applies before any LLM or Tavily call. Owners set caps, and every change is audit-logged.

### How the panel's objections were answered

Fixed for non-user paths. One internal _ik_reserve (same tariff, same advisory lock) sits behind two wrappers. reserve_ik_call is for user-JWT paths. reserve_ik_call_for_org(p_org, p_channel, p_scope_key, ...) is executable only by service_role, and it is called from WhatsApp intake (the number's org, with the conversation id), phone sessions (the number's org, with the call SID) and the ARQ worker (the job's org, after its existing role re-check). Those are exactly the server jobs invariant 2 already lists.
In code, lookup_authorities, find_cases and search now take a required ik_budget argument with no default, and whatsapp_intake.py:245 passes OrgIkBudget(admin, org_id, 'whatsapp', conversation_id). An AST test fails the build if any call site omits it.
Public channels also get their own public_intake_cap_paise, default Rs 0, plus a per-conversation daily limit, so public intake can't spend without limit even inside the org cap.
The requested test is added: a WhatsApp-intake citation check at the cap makes zero Indian Kanoon calls (asserted on the mocked transport) and the citation is marked unverified. Further tests cover the zero default, the per-conversation limit, telephony and worker spend, and the grants on the service-only wrapper.

### Acceptance tests

- Search: a fixture query returns a corpus paragraph with its neutral citation; mocked Indian Kanoon results come back in a separate attributed list, not merged while the merge flag is off
- Paste-a-citation: '2024 INSC 735' resolves and renders green; '(2026) 99 SCC 9999' returns not_found and can't be inserted
- In-app cap: with a Rs 5 cap and a Rs 0.50 tariff, the 11th reserve_ik_call returns false; cached repeats call no rpc
- WhatsApp at cap: an org with public_intake_cap_paise reached receives an inbound WhatsApp message whose agent reply cites an HC case the SC index doesn't know. The mocked httpx transport for api.indiankanoon.org receives zero requests, the reply marks the citation [unverified] or drops it from authority, and no ik_spend row is added
- WhatsApp default: a new org (public cap Rs 0) makes zero Indian Kanoon calls from intake; after the owner sets Rs 10, the same message makes one reserved call recorded with channel 'whatsapp' and the conversation id as scope_key
- Per-conversation limit: one WhatsApp conversation is refused after 5 reservations in a day, even with the org budget remaining; a second conversation still succeeds
- Telephony and worker: a phone session and a batch job reserve through reserve_ik_call_for_org with channels telephony and worker, and both count against the org monthly cap
- Concurrency: two parallel reservations at cap minus one call: exactly one succeeds (advisory lock shared by both wrappers)
- DB security: authenticated users can't execute reserve_ik_call_for_org or _ik_reserve; service_role can execute reserve_ik_call_for_org; direct insert, update or delete on ik_spend is denied for members and owners; a non-member calling reserve_ik_call for another org is refused; no caller can pass an amount
- Static guard: an AST test asserts that every call to indiankanoon_service.search, find_cases or citation_service.lookup_authorities in app/ passes an ik_budget argument, and that no IkBudget is constructed with a service-role client outside whatsapp_intake.py, telephony_session.py and worker.py
- set_ik_budget by an associate is refused; by an owner it writes an audit_logs row
- Hinglish query: only the masked query reaches the mocked Anthropic client
- GET /statutes/BNS/103 returns the India Code text with the 'formerly s. 302 IPC' note

### Reviewers' minor notes

- ik_lookup_cache is shared across orgs. Party-name tuples drawn from intake conversations could reveal that some org searched for a client's name. Either scope the cache per org, or only cache names already present in a public citation string.
- Show the owner the expected monthly spend at the current tariff when they set the caps, not only the spend so far.
- Migration 014 collides with other proposals. Renumber it.
- Record in the docs/compliance note that the per-conversation scope_key for WhatsApp, the conversation id, is retained in ik_spend. Purge it, or replace it with a hash, on the same schedule as the intake conversation, so spend rows do not outlive the client's data.
- Python has no type-check step in CI, so 'fails at type-check' really means a runtime TypeError plus the AST guard. Rely on the AST test and say so.
- A reservation counts even when the Indian Kanoon call then fails. That is conservative and fine, but the billing view should show failed calls separately so owners don't think the spend is a leak.
- Choose the migration number together with the five other proposals claiming 014.

