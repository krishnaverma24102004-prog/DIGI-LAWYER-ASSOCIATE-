# P20. Confidentiality and privilege: client data in AI tools may be unprivileged, outside DPDP compliance, and restricted by courts

**Severity:** high · **Size:** big · **Region:** Global (US privilege ruling, ABA); India (DPDP/BCI, Kerala HC)

**Who has it:** Every firm handling client confidences (white-collar, M&A, disputes), Indian firms under DPDP, in-house counsel, clients using chatbots before engaging a lawyer, courts and staff

## What goes wrong

Lawyers and clients paste facts, contracts and strategy into AI tools that process raw client text in vendor clouds. In US v. Heppner (SDNY, Feb 2026) a defendant's chats with Claude were held neither privileged nor work product. ABA Opinion 512 requires informed client consent before confidential data goes into self-learning tools. In India, BSA privilege, BCI confidentiality and the DPDP Act apply: the firm is the data fiduciary and needs processor contracts, insurers may view claims less favourably without vendor due care, and sharing privileged material with an AI vendor is untested. The Kerala HC bars generative AI like ChatGPT for judicial work and warns that cloud AI may breach confidentiality. Firms either ban AI (and lawyers use it anyway) or accept the risk.

## Evidence of scale

- US v. Heppner (SDNY, 17 Feb 2026): a defendant's chats with Claude (31 documents) were not protected by privilege or work product. ([source](https://news.bloomberglaw.com/business-and-practice/heppner-shows-attorney-client-privileges-fragility-in-ai-era))
- 53% of UK legal professionals worry about confidential data leaking through AI (LexisNexis 2026 survey of 543). ([source](https://www.legalcheek.com/2026/09/hallucinations-top-lawyers-ai-worry-list-research-finds/amp/))
- Under DPDP a firm using AI is usually the data fiduciary and the vendor the processor, requiring a valid contract, sub-processor disclosure and cross-border clarity; insurers may take a less favourable position without due care. ([source](https://www.bharatlaw.ai/blog/using-ai-for-client-work-under-dpdp-what-legal-teams-should-contract-for/))
- Kerala HC policy prohibits generative AI such as ChatGPT and DeepSeek for district judiciary work, warns cloud AI may breach confidentiality, and requires a detailed record of all AI use. ([source](https://www.medianama.com/2025/07/223-kerala-hc-bars-ai-tools-chatgpt-deepseek/))
- ABA Formal Opinion 512: investigate a GAI tool's security, get informed client consent before entering confidential information into self-learning tools (boilerplate isn't enough), verify output. ([source](https://technologylaw.fkks.com/post/102jwnl/aba-issues-comprehensive-formal-ethics-opinion-on-lawyers-use-of-generative-ai))

## Why current tools don't solve it

Harvey, Thomson Reuters and Lexis tools offer zero-retention enterprise contracts but still process raw client text and don't mask identifiers before the model sees them; they give no artifact showing work was done at counsel's direction (the Heppner gap). Consumer models used by small firms offer no such terms. None ships India-specific DPDP consent records, on-shore processing or pre-model masking of Aadhaar, PAN, bank and phone numbers, or the per-matter, per-user AI-use record court policies now expect.

## Panel verdict

**Status:** open (round -)

**Effort:** L

### What software can fix

Proving, matter by matter and user by user, four things:
- (a) client identifiers never left the firm unmasked, except raw audio, which is disclosed and gated;
- (b) every call to an outside AI or speech processor (Anthropic, Tavily, Indian Kanoon, Deepgram STT and Aura TTS) was made by a named lawyer, or under their supervision, for a named matter or for a named user's general research, with a stated purpose;
- (c) where the firm requires client consent, it was recorded before any client data, audio included, reached a processor;
- (d) each processor is recorded with its region, its retention and what it receives.

This is the DPDP data-fiduciary evidence and the record of work done at counsel's direction (the Heppner gap).

General research stays usable for ordinary Indian research, which names governments, banks, insurers and reported cases. The party scan exists to attribute work to the right matter; it does not protect confidentiality, because names are deliberately not masked.

Changed this round: a private firm party is exempt only inside a citation that resolves by a citation key to a reported judgment, and only when that judgment is not the firm's own matter. An unresolved case title that names a private firm party is refused and moved to the matter, whatever sits on the other side of the 'v.'.

### What it can't fix

Untested law: whether an Indian court will treat AI-assisted work as protected under BSA ss.132-134 or BCI Rule 17. Software can produce evidence, not privilege.

Raw audio and images from the OCR vision fallback cannot be masked. We gate them behind a matter and consent, ledger them and disclose them; we cannot remove them.

What vendors do with the data rests on their contracts. We record those contracts; we cannot enforce them.

Names, places and dates are not masked, by design.

General-research attribution is best effort, and its limits are these:
- The party scan only knows parties already in the firm's index.
- An institutional litigant (government, PSU, bank, insurer, listed company) that is also a firm client is logged in general research, not refused, unless the firm marks it 'private for research'.
- A case title naming a private firm party is exempt only when it carries a reporter or neutral citation, or a stored Indian Kanoon document reference, that resolves to a reported judgment which is not the firm's own matter. This is stricter than before: a lawyer researching a High Court judgment cited only by name, where a party shares a name with a firm client, must add the citation or run the question in a matter. We accept that friction.
- A misspelling below the Strong band is not refused. It needs an attestation, which is recorded and reported (see step 4).
Choosing the right scope stays the lawyer's professional responsibility. Per-user reporting makes misuse visible, not impossible.

A database superuser can still tamper with rows. The hash chain makes that detectable, not impossible. We will not claim 'privileged by design'.

### What the user sees

Unchanged from round 4:
- the 'AI use' tab on every matter, with the downloadable PDF;
- mic and push-to-talk disabled until consent is recorded;
- the DTMF consent notice on the phone line;
- WhatsApp voice notes sent before consent are not processed;
- the 'Link to a matter' dialog;
- the /compliance page and its party-class page.

Research box and case-law search:
- Questions naming only institutional bodies ('State of Punjab', 'Union of India v. <non-firm party>', 'SBI', 'LIC') go through, with a grey note 'Mentions an institutional party on firm matters (logged)'.
- Changed: 'In State of Rajasthan v. Ramesh Kumar Sharma, can we argue default bail?', where Ramesh is a firm client and no citation key is given, shows 'This names a party in <matter title>. Run it in that matter?' with 'Move to matter'. The same refusal applies to 'Ramesh Kumar Sharma v. XYZ Traders'. A second line reads: 'Researching a reported judgment? Add its citation, e.g. (<year>) <vol> SCC <page> or <year> INSC <no>.'
- With a citation key that resolves to a reported judgment not in a firm matter, the question goes through, with the note 'Cites a reported judgment naming a firm party (logged)'.
- If the cited judgment is the firm's own matter, the user sees 'This judgment is in <matter title>. Run it in that matter?'.
- A Possible-band look-alike inside a case title asks for one confirmation: 'Does this concern a firm matter? No, this is not a firm matter / Move to matter'. 'No' is recorded and appears on the partner's research report.
- If the user cannot see the matter, the refusal names the responsible lawyer only, never the title.

### What the system does

Steps 1-3 and 5-8 from round 4 are unchanged: the guarded_call and open_stream choke points, the StreamPermit, the CI grep, the ai_route resolvers, the speech consent gate, firm_internal, segment tagging, the hash-chained ledger and ALLOWED_AI_HOSTS. The scope resolution of /caselaw/search?thread_id=T from round 5 is also unchanged.

4) General-research pre-checks, revised. They run in this order; any refusal makes 0 processor calls.
- (a) Limits: one typed prompt of at most 1,500 characters (200 for a case-law query). document_id, attachments and memory return 422.
- (b) assert_masked on the raw prompt. Any identifier refuses with 'unmasked_identifier'.
- (c) citation_spans(db, text), local only. It reuses citation_service._extract and case_lookups to find every 'X v. Y' / 'vs' / 'versus' / 'बनाम' span and every reporter or neutral citation. Each span gets a resolution:
  - key_resolved=true when a reporter or neutral citation inside or immediately after the span matches legal_authorities.citation_keys, AND that row's name_tokens contain the tokens of both sides of the span;
  - or when an Indian Kanoon document id or URL in the span is present in the persisted table ik_documents (doc_id, title_tokens, court, decision_date). Rows in that table are written only by earlier thread-scoped searches and citation checks, and the stored title must contain both sides;
  - name_resolved=true for a name-only match (the existing subset match).
  The live Indian Kanoon call in lookup_authorities is not used here: a new lookup_authorities_local() reads only the local tables, and a test patches the socket to prove it.
- (d) conflict_service.scan_text(org_id, text) gives each hit with its band (exact, strong or possible), party_class, matter ids and the span it falls in.
- (e) Decision table, in code (research_scope.decide, pure and table-tested):
  1. An Exact identifier hit anywhere refuses with names_party.
  2. An institutional hit allows, counted in institutional_hits, unless research_private is set.
  3. A Strong hit of class individual or private_company:
     - outside any span, refuses with names_party;
     - inside an unresolved or name_resolved span, refuses with names_party, whatever the class of the other side. This is the fix: name-only resolution is not enough, because common Indian names collide with unrelated reported cases;
     - inside a key_resolved span, allows, counted in citation_hits, unless the resolved judgment is the firm's own matter (rule 4).
  4. Own-matter test for a key_resolved span: the judgment is treated as firm matter M if (i) its CNR, or its case number and court, equals a court_cases row of M; or (ii) its party pair equals M's party pair (same normalisation as conflict matching) and its decision date is on or after M's opening date. Then it refuses with names_party, citing M (own_matter_judgment).
  5. A Possible-band private hit:
     - inside any span, requires attest_not_firm_matter=true on a re-submit. The ledger stores possible_attested=true and the hit's party_index id (never the text), and the partner's research report lists every attestation by user;
     - outside spans, allows, counted in possible_party_hits.
  The refusal names the matter title only if the caller can SELECT that thread; otherwise it names the responsible lawyer.
- (f) No consent check in general research, because refusal keeps firm matters out of it. The ledger row records matter_kind='general_research', user_id, institutional_hits, citation_hits, possible_party_hits, possible_attested and refusal_reason.

Refused rows are written with no prompt text. 'Move to matter' creates a new request under the thread scope, with T's RLS check and consent rule; it never re-labels the refused row.

Party classes, classify_party, data/institutional_parties.yaml, research_private and party_class_history are unchanged from round 5. Research answers are never written to thread memory.

### Where it is built

Unchanged from round 5: ai_ledger.py, matter_resolver.py, research.py, compliance.py, the migration 014 and 017 columns, caselaw.py with its thread_id scope, conflict_service.classify_party and scan_text, and data/institutional_parties.yaml.

Changed this round:
- app/services/citation_service.py:
  - new lookup_authorities_local(db, keys, names), with no Indian Kanoon network call;
  - new citation_spans(db, text), returning spans with key_resolved and name_resolved, side tokens and the matched authority id.
- app/services/indiankanoon_service.py: find_cases and the thread-scoped search persist hits to ik_documents. The existing lru_cache stays for speed but is never used for scope decisions.
- app/services/research_scope.py (new): the pure decide() table and the own-matter test against court_cases (cnr, case_number, court_name, petitioners/respondents) and the P46 party pairs.
- Migration 017 (with P46):
  - ik_documents;
  - ledger columns possible_attested and own_matter_judgment;
  - refusal_reason values names_party and own_matter_judgment.
- frontend: the refusal text with the citation hint, the attestation prompt, and the attestation column on the partner's research report.

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis+ AI send raw client text under zero-retention contracts. Nothing ties a call to a lawyer, a matter and a consent, and they do no Indian identifier masking. Transcription tools record from the first second. Indian legal-GPT apps have no processor register, no consent gate and no per-user research record.

Ours puts every processor, speech included, behind one scope resolver, consent check and hash-chained ledger. The research lane follows how Indian research actually reads ('Union of India v. ...', 'State of ...', SBI, LIC, cited reported judgments) without opening a back door: a firm's own unreported case title, which is the commonest shape ('State of <S> v. <our client>'), is steered back to its matter, and so is a reported judgment that is the firm's own matter. The exemption is a deterministic citation-key match, not a name guess.

### Safeguards

Every processor call, text or speech, has a resolved scope, purpose and user, or it does not happen. Consent is checked before the first audio frame. Only the ledger can mint speech permits.

General research:
- per user, with no documents or memory;
- refused on identifiers;
- refused on any Strong private firm party unless it sits in a key-resolved reported judgment that is not the firm's own matter;
- look-alikes inside case titles need a recorded attestation;
- matter titles are never revealed to someone who cannot see the matter;
- the scope decision is a pure, table-tested function that uses only local data.

Party classes are rule-set, and every manual change is audited. The ledger is server-written, content-free and hash-chained, and is listed in invariant 2. The record says 'prepared at the direction of counsel', never 'privileged'.

### How the panel's objections were answered

Objection 1 and 2 (the unresolved-span exemption lets the firm's own matters into general research, and the out_of_scope text did not match the behaviour):
- The exemption for unresolved spans is removed. A Strong private firm party inside an unresolved span is refused with names_party and the move-to-matter offer, whatever the class of the other side. 'State of Rajasthan v. Ramesh Kumar Sharma' and 'Ramesh Kumar Sharma v. XYZ Traders' are both refused.
- Going further than asked: name-only resolution no longer counts either, because the existing subset match lets a common name hit an unrelated reported case. Only a key_resolved span counts: a reporter or neutral citation in legal_authorities, or a stored Indian Kanoon document, whose title contains both sides.
- Even a key_resolved span is refused when the judgment is the firm's own matter (a CNR or case-number match, or the same party pair on or after the matter's opening date).
- Possible-band look-alikes inside spans need a recorded attestation that appears on the partner report.
- The out_of_scope now states this rule exactly, and a test asserts the decision table matches it.
- Tests added: the unresolved State v. client title is refused with 0 model calls; the same text with a resolving citation key is allowed; the own-matter reported judgment is refused; the unresolved private-v-private title is refused; name-only resolution never exempts.

### Acceptance tests

- Unit (objection): Ramesh Kumar Sharma is the accused client on thread T against the State. '/research/ask: In State of Rajasthan v. Ramesh Kumar Sharma, can we argue default bail? <1,200 characters of facts>', with no citation key, is refused with names_party and T's title, makes 0 model calls, and writes a ledger row with no prompt text.
- Unit (objection): the same text plus '(2019) 4 SCC 123', where a legal_authorities fixture row has that key and name_tokens containing both sides, and with no CNR or party-pair match to T after T's opening date, is allowed with citation_hits=1 and one model call.
- Unit (objection): the same reported citation, where the fixture authority's CNR equals T's court_cases.cnr, is refused with own_matter_judgment and T's title.
- Unit (objection): 'Ramesh Kumar Sharma v. XYZ Traders', unresolved, is refused with names_party. 'SBI v. Ramesh Kumar Sharma' resolved by name only (no key) is refused. With a matching key it is allowed.
- Unit (objection): a name-only resolution never exempts a Strong private hit. A parametrised test over 30 Strong-hit spans with only name_resolved=true gives 30 refusals.
- Unit: 'Union of India v. Rajesh Traders' (Rajesh Traders not indexed; Union of India institutional on 3 firm matters) is allowed with institutional_hits>=1. GET /caselaw/search?q=State of Punjab with no thread_id is allowed, with one Indian Kanoon call.
- Unit: a Possible-band look-alike ('Ramesh Kumaar Sharmaa') inside 'State v. Ramesh Kumaar Sharmaa' returns 428 attestation_required with 0 model calls. Re-submitting with attest_not_firm_matter=true is allowed, the row has possible_attested=true, and the partner research report lists it under the associate.
- Unit: citation_spans and lookup_authorities_local make 0 network calls (socket patched to raise). An Indian Kanoon id not in ik_documents gives key_resolved=false. ik_documents rows are written only by thread-scoped calls: a test asserts that general_research case-law search never inserts.
- Unit: research_scope.decide is a pure function; a table test covers every (band, class, span resolution, own-matter) combination, and the out_of_scope text is asserted to match the table: only key_resolved, non-own-matter spans exempt private Strong hits.
- Round-5 tests retained: classify_party fixtures at 100%; research_private set by a partner (an associate gets 403); thread-scoped case-law search with consent_missing returning 409 and 0 calls; 'Move to matter' creates a new row and leaves the refused row unchanged (chain verifies); the speech consent gate, WebRTC, telephony DTMF, the WhatsApp voice note before YES, TTS blocked; PermitRequired, the StreamPermit sentinel and the CI grep; the identifier refusal, the length limits and the 422 cases; research-row visibility; and every round-3 resolver, masking, ledger-immutability and verify test.

### Still blocking

- The only way to exempt a Strong private firm-party hit inside a case title is key_resolved. In this repository, key resolution cannot succeed for the citations Indian lawyers actually use. legal_authorities holds only Supreme Court judgments, and scripts/ingest_sc_judgments.py writes citation_keys only from the dataset's S.C.R. report citation and INSC neutral citation (authority_row: keys from `citation` and `case_id`). Three consequences follow. (1) An SCC citation, the dominant way SC judgments are cited, never matches. The hint 'add its citation, e.g. (<year>) <vol> SCC <page>' and the acceptance-test fixture '(2019) 4 SCC 123' describe an exemption that does not exist in production. (2) INSC neutral citations exist only from 2023 onwards. (3) No High Court judgment can be key-resolved at all, whether cited as AIR, SCC OnLine or an HC reporter. The ik_documents path works only after a thread-scoped search has already stored that document. In practice, a lawyer researching an unrelated reported judgment whose party shares a common name with a firm client (Ramesh Kumar, Sunil Sharma) is left with one option: 'Move to matter'. That files unrelated research under a client's matter, which corrupts the per-matter AI-use record this proposal sells as DPDP and counsel's-direction evidence. Fix I would accept: (a) add a content-free resolution step, an Indian Kanoon lookup by document id or URL only (no prompt text) that writes ik_documents, available from general research, and/or ingest SCC/AIR/SCC OnLine keys where a licensed source exists; (b) correct the hint to the formats that actually resolve (SCR, INSC, an Indian Kanoon link); (c) until then, handle a Strong hit inside a span that carries a court and year like the Possible band: an attestation ('not a firm matter') recorded on the partner's research report, with the own-matter test still applied; (d) add an acceptance test run against the real ingest's key format, not a hand-made SCC fixture.
- The own-matter exemption leaks the firm's own client litigation into general research, which skips the consent check. Test (i), 'CNR, or case number and court, equals a court_cases row of M', has no data to run on. legal_authorities (migration 008) has no CNR or case-number column (only title, citation, neutral_citation, decision_date, citation_keys and name_tokens), and the proposed ik_documents stores only doc_id, title_tokens, court and decision_date. In practice the only own-matter test is (ii), the same party pair with a decision date on or after M's opening date. The commonest Indian engagement pattern is a client who arrives after losing below. The firm opens appeal matter M after the High Court or Sessions judgment 'State of Rajasthan v. Ramesh Kumar Sharma' was decided. That judgment is key_resolved (in legal_authorities, or in ik_documents because the associate had already searched it inside M), and its party pair equals M's. It predates M's opening, so it is treated as not the firm's matter. A Strong hit on the client is then allowed in general research, with no matter attribution and no consent check: exactly the gap (b) and (c) are meant to close. Fix I would accept: (a) drop the date condition, so any key_resolved judgment whose party pair matches a firm matter's pair is own-matter; or downgrade a pre-opening pair match to the Possible-band attestation flow, recorded on the partner report. (b) Tag every ik_documents row with the thread that persisted it, and treat a doc first persisted from matter M as own-matter for M. (c) Either add cnr and case_number columns where the data exists, or delete test (i) and its acceptance test, which needs a CNR column on the fixture authority that the schema doesn't have.
- The own-matter test and the advertised citation remedy depend on data the index does not contain. legal_authorities (008) has no cnr, case_number or court-case columns, and scripts/ingest_sc_judgments.py writes citation_keys only from the S.C.R. citation and the INSC neutral id. No SCC key ever exists in production. Three consequences follow. (1) Rule 4(i), a CNR or case number plus court equal to the matter's court_cases row, can never fire on real data. Own-matter detection then rests only on rule 4(ii), an exact party-pair match plus a date rule. A firm's own reported judgment whose title normalises differently ('& Ors', a different State instrumentality, a transposed order) is therefore exempted into general research, which is the leak this round claims to close. (2) The refusal hint tells lawyers to add '(<year>) <vol> SCC <page>', the commonest reporter. That key never resolves, so the remedy the UI offers silently fails. (3) The acceptance test passes only because its fixture inserts an SCC key and a CNR into legal_authorities, which production ingestion never does. Fix I would accept: either add case_number, court and cnr columns to legal_authorities and ik_documents with a stated source that populates them, or drop rule 4(i) and make rule 4(ii) fail closed: any key-resolved judgment whose name_tokens include a Strong firm-party hit and share any token set with that matter's opposing party is treated as own matter. Change the hint to the formats that actually resolve (S.C.R., INSC neutral citation, or an Indian Kanoon link already in ik_documents). Rewrite the fixtures to use keys in the form the ingest script produces.

