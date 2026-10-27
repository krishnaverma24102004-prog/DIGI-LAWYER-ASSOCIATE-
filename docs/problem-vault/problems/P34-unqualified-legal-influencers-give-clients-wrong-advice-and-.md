# P34. Unqualified 'legal influencers' give clients wrong advice and fake certainty

**Severity:** high · **Size:** big · **Region:** India (global pattern)

**Who has it:** Clients and prospects on Instagram and YouTube; genuine lawyers who must undo misinformation

## What goes wrong

Clients arrive having watched reels promising 'guaranteed bail', 'instant divorce' or 'sure acquittal', or after advice from accounts run by non-enrolled students soliciting WhatsApp consultations. They distrust their real lawyer, act on wrong law (often repealed IPC/CrPC provisions) or miss limitation periods. The BCI and Delhi Bar Council issued warnings in 2025-2026.

## Evidence of scale

- BCI (17 Mar 2025): concern over unqualified self-styled legal influencers spreading misinformation; directed an end to unauthorised advice by non-enrolled individuals. ([source](https://www.livelaw.in/amp/top-stories/bci-prohibits-advocates-using-actors-influencers-for-promotion-cautions-against-soliciting-legal-work-through-social-media-286663))
- BCI circular (17 July 2026) warns fake judgments and misleading summaries misguide litigants and prohibits clickbait promising 'guaranteed bail', 'instant divorce' or 'sure acquittal'. ([source](https://theprint.in/judiciary/no-court-reels-memes-bar-council-draws-red-line-for-social-media-use-by-lawyers-law-students/2990445/))
- @legal.baatein (over 633,000 followers), 'Top Legal Influencer in India', invites WhatsApp messages for advice and is run by a non-enrolled final-year LLB student. ([source](https://www.storyboard18.com/special-coverage/how-legal-influencers-are-breaching-bci-rules-49293.htm))
- Delhi Bar Council (4 Aug 2025): soliciting online breaching Rule 36 is serious misconduct and can lead to suspension. ([source](https://www.verdictum.in/news/delhi-bar-council-issues-caution-against-lawyers-advertising-legal-services-on-social-media-1587620))

## Why current tools don't solve it

No legal-AI product checks claims clients bring from social media. Harvey, CoCounsel and Lexis+ AI serve lawyers. Generic chatbots repeat repealed IPC sections and guarantee outcomes. Rule 36 limits lawyers countering it. Missing: a citation-grounded, non-advice, vernacular explainer a firm can give clients that flags repealed or fabricated provisions and states no outcome is guaranteed.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Giving the firm a quick 'Claim check' for things clients bring from reels, YouTube or forwards. Code finds every section and case the claim mentions and labels each repealed (with the BNS/BNSS/BSA equivalent), non-existent, unverified or valid. Code also finds guaranteed-outcome phrases ('guaranteed bail', 'instant divorce', 'sure acquittal', Hindi and Hinglish forms). A grounded, plain-language explainer is drafted in the client's language and the lawyer approves it before it goes to their own client.

### What it can't fix

We can't take down influencer content, police non-enrolled advisers, or stop clients watching. We won't download or scrape Instagram/YouTube media. The input is text the client or lawyer pastes, a screenshot (OCR), or a voice note (transcribed). We don't publish counter-content publicly (Rule 36 limits lawyers' public posting, and it's the firm's decision). Whether a legal proposition is right for this client's facts needs the lawyer; the section registry checks that a section exists, not what it says.

### What the user sees

Lawyer: in /inbox or a case thread, 'Check a claim', with paste, screenshot or voice. Example result: 'Claim: "Section 498A IPC lagao, 24 ghante me guaranteed bail milegi". Found: s.498A IPC — REPEALED for offences from 1 Jul 2024; equivalent ss. 85-86 BNS. Phrase "guaranteed bail" — no outcome can be guaranteed (BCI circular 17 Jul 2026 prohibits such claims). Section 999 BNS — DOES NOT EXIST.' Below that is a draft explainer for the client in Hindi: what the video said, what the law currently says (only verified citations), what depends on their facts, and that no outcome is guaranteed. The lawyer edits it and sends it to the client through WhatsApp (held-message path) or as a PDF. Client: a calm, short explainer from their own lawyer that names no influencer.

### What the system does

1) Input: pasted text; a screenshot goes through ocr_service, then the text; a voice note through whatsapp_service.transcribe_voice_note. A client's forwarded WhatsApp message can be turned into a claim check by the lawyer from the inbox. 2) Deterministic checks first: citation_service.check(text, Sources(empty grounding)) returns per-citation status (repealed with equivalent, statute, invalid, known_case, unverified). `claim_check.guarantees(text)` is a regex list in en/hi/Hinglish ('guarantee', 'pakka', '100%', 'sure shot', 'instant divorce', 'zaroor milegi', 'गारंटी', 'पक्का') plus guardrails' guaranteed-outcome patterns. Limitation phrasing ('kabhi bhi case kar sakte ho', 'no time limit') is flagged 'check limitation'. 3) Grounding: RAG over the firm and shared corpus (rag_service) using the masked claim, and the jurisdiction notes. 4) AI step: claude-sonnet-5-5 with a fixed cached system prompt (prompt_engine.build_system) gets the masked claim, the deterministic findings as facts it must not contradict, and the retrieved passages. It returns the explainer in a fixed JSON {said, current_law[], depends_on[], no_guarantee}. 5) Post-checks in code: citation_service.verify_text on the explainer (invalid/unverified marked or removed per invariant 3); verify_output_safety (disclaimer appended); a check that every repealed citation in the claim is mentioned with its equivalent; and a check that the explainer itself contains no guarantee phrase. Failures hold the draft with reasons. 6) Stored in `claim_checks` (org_id, thread or conversation id, input_masked, findings jsonb, draft, status, approved_by/at trigger). Sent only after approval, through the P01/P07 approved-send path; audited (CLAIM_CHECK, SEND_CLAIM_EXPLAINER). 7) The repealed-code mapping and guarantee regexes are shared with intake_guard so public-facing replies benefit as well.

### Where it is built

app/services/citation_service.py (check, verify_text, the repealed mapping), app/core/guardrails.py (verify_output_safety, mask_pii; guaranteed-outcome patterns extended with a Hinglish/Hindi list), app/services/rag_service.py, app/services/prompt_engine.py (cached system block), app/services/ocr_service.py, app/services/whatsapp_service.py transcribe_voice_note, app/services/jurisdiction_service.py. New: app/services/claim_check.py, app/routers/claims.py (POST /api/v1/claims/check, POST /claims/{id}/approve, POST /claims/{id}/send) with limit('llm'), migration 014 (claim_checks with RLS), and a 'Check a claim' panel in frontend/src/app/inbox/page.tsx and the case thread view in frontend/src/app/page.tsx.

### Why current tools fail and this won't

No legal-AI product checks claims clients bring from social media. Harvey, CoCounsel and Lexis+ AI serve lawyers for drafting and research, not for undoing misinformation, and are weak on BNS/BNSS transitions. Generic chatbots repeat IPC sections and guarantee outcomes. Ours puts deterministic checks first: the statute registry knows IPC to BNS, which sections exist, and the SC citation index. The AI only writes an explanation around findings it can't override, and post-checks plus lawyer approval stop it repeating the misinformation. It runs in Hindi and Hinglish, where the reels are.

### Safeguards

UPL: deterministic findings plus an informational explainer; LEGAL_DISCLAIMER via verify_output_safety; a lawyer approves every client-facing explainer. BCI Rule 36: sent only to the firm's own clients, never published or used to solicit; the explainer names no influencer (defamation risk). Invariant 1: masked before Anthropic. Invariant 3: every citation checked; prompt examples use placeholders. Invariant 5: the system prompt is cached. DPDP: the claim text is stored masked and erased with the matter. Rate limited with limit('llm').

### Acceptance tests

- tests/test_claim_check.py::test_repealed_ipc: 'Section 302 IPC me case karo' (offence date unknown) -> finding status repealed with BNS s.103 equivalent, no model call needed.
- test_nonexistent_section: 'Section 999 BNS' -> status invalid.
- test_guarantee_phrases: 'guaranteed bail', '100% acquittal', 'pakka divorce 1 hafte me', 'जमानत की गारंटी' -> each flagged; 'the bail application was listed' -> not flagged.
- test_explainer_must_cover_repealed: a model mock whose explainer omits the BNS equivalent -> the draft is held with reason 'repealed citation not addressed'.
- test_explainer_no_guarantee: a model mock including 'you will surely get bail' -> held, verify_output_safety triggered, status draft.
- test_explainer_fabricated_citation_marked: a model mock citing 'Section 1000 BNSS' -> marked [unverified] or removed per invariant 3.
- test_masking: a claim containing a phone number and an Aadhaar fixture -> the model mock receives placeholders only.
- test_no_send_without_approval: POST /send on an unapproved check -> 409.
- test_ocr_path: a PNG fixture of the text -> the same findings as the pasted text (OCR mocked to return the text).
- Eval cases added to evals/cases.json: 5 Hinglish reel-style claims with expected findings, run by scripts/run_evals.py.

### Reviewers' minor notes

- A client's matter may involve a pre-July-2024 offence, where s.498A IPC still applies. The explainer must keep the date condition ('repealed for offences on or after 1 July 2024') and never say 'repealed' flatly.
- The BCI circular of 17 July 2026 is about lawyers' own social-media posts. Cite it in the lawyer-facing finding only, not as a rule binding the influencer.
- The BCI circular of 17 July 2026 governs advocates' social media. In the lawyer-facing finding, cite it only where the source is an advocate, and otherwise say 'no outcome can be guaranteed' without the circular.
- The 'guarantee' regexes will false-positive on ordinary words ('pakka' in other contexts, '100%' in amounts). Keep the flag informational and add negative fixtures.
- OCR of reel screenshots (stylised fonts over video frames) will be poor with Tesseract. State the expected failure and fall back to asking for pasted text.

