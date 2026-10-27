# P12. The harder hallucination: real case, fake quote, wrong paragraph or unsupported proposition

**Severity:** critical · **Size:** big · **Region:** Global, with acute recent instances in India

**Who has it:** Litigators drafting written submissions and appeals, judges and law clerks checking them, opposing counsel

## What goes wrong

The cited judgment exists, so a quick existence check or citator passes it. But the quoted paragraph isn't in the judgment, the pin cite points to a paragraph that doesn't exist (para 73 of a 27-paragraph judgment), or the case doesn't support the proposition. Supreme Court of India judges report real SC cases cited with non-existent quotes, and tribunals have relied on genuine cases padded with AI-written paragraphs. Catching this means reading each cited passage against the claim, the slowest part of verification and the part existing checkers skip.

## Evidence of scale

- Stanford RegLab (arXiv 2405.20362) counts 'misgrounded' answers (real source misread or inapplicable) as hallucinations; checking requires reading every cited source against the claim. ([source](https://arxiv.org/html/2405.20362v1))
- Justice Nagarathna (Feb 2026): some lawyers cite real SC cases, but the quoted portions don't exist in the judgment. ([source](https://organiser.org/2026/02/18/340579/bharat/precedents-cited-never-existed-supreme-court-flags-alarming-ai-use-in-court-filings/))
- Greenopolis (Delhi HC, Sept 2025): paras 73-74 of Raj Narain v. Indira Nehru Gandhi were quoted although the judgment has 27 paragraphs. ([source](https://lawbeat.in/amp/news-updates/delhi-high-court-allows-withdrawal-of-plea-citing-non-existent-judgments-and-ai-generated-content-1532103))
- Pooja Ramesh Singh (2026 INSC 668): NCLT and NCLAT relied on non-existent cases and on genuine citations carrying AI-generated paragraphs never in the judgments; the SC set the orders aside. ([source](https://blog.ipleaders.in/ai-hallucinated-case-law-fake-citations-india/))
- Concord v. Anthropic (May 2025): a Latham & Watkins attorney declared Claude gave a real article an inaccurate title and authors, and the firm's manual check missed it. ([source](https://www.theregister.com/2025/05/15/anthopics_law_firm_blames_claude_hallucinations/))

## Why current tools don't solve it

KeyCite and Shepard's check treatment, not whether a quoted sentence appears at the pin cite. Lexis+ AI and Westlaw AI link to sources but leave the passage-level comparison to the user, and the Stanford study found misgrounding among their errors. No mainstream tool does verbatim quote matching against full judgment text plus a proposition-support check for every citing sentence, which Indian benches now demand.

## Panel verdict

**Status:** solved (round 2)

**Effort:** L

### What software can fix

Deterministic passage-level checking for every case citation. (1) The citation and the party names belong to the same real judgment, using a matcher that tolerates how Indian lawyers actually write case names (short forms, abbreviations, 'Justice ... (Retd.)'). This catches 'real citation, wrong case', one of the three failure types in Pooja Ramesh Singh. (2) A pin cite exists in that judgment (catches 'para 73 of a 27-paragraph judgment'). (3) A quoted passage appears in the judgment, at the cited paragraph. Software also finds the paragraphs most likely relevant to the citing sentence, so the lawyer reads 2-3 paragraphs instead of the whole judgment. Whether a case supports a proposition is a legal judgement: code never decides it, a lawyer attests it.

### What it can't fix

Proving that a judgment supports a proposition, or is still good law (overruled, distinguished, per incuriam), cannot be done deterministically. We show candidate paragraphs and a clearly labelled AI hint, and the lawyer decides. A KeyCite/Shepard's-style treatment history for India is not in this proposal. SCC and AIR paragraph numbers can differ from the court's own, and older judgments are unnumbered, so the pin check then reports 'not checked'. Judgments we have no text for can only be existence-checked until a lawyer uploads a copy or attests from an outside source (P02). The abbreviation table will never be complete; an unknown abbreviation makes the name check amber, not red.

### What the user sees

Every citation in a draft, agent reply or uploaded document becomes a row in a Verification Ledger, with columns Exists / Name / Pin / Quote / Proposition. Example rows: 'Exists: 2024 INSC 735 (SC index)'; 'Name: matches Satender Kumar Antil v. Central Bureau of Investigation (CBI = Central Bureau of Investigation)'; 'Name: does not match; this citation belongs to Arnesh Kumar v. State of Bihar' (red); 'Name: partly matches (Puttaswamy found; "Kumar" not found); check' (amber); 'Pin: para 73 cited, judgment has 27 paragraphs (FAIL)'; 'Quote: not found in the judgment (FAIL)'; 'Quote: found at para 14, not at cited para 12'; 'Quote: close; words that differ: shall/may'; 'Proposition: read paras 14, 15, 22 (shown beside your sentence), then tick Confirmed'. Each AI hint is labelled 'AI suggestion, not verification'. Each row links to the source text used: SC Open Data PDF, HC Open Data, an Indian Kanoon doc, or the firm's uploaded copy.

### What the system does

1. New services/authority_resolver.py resolves each citation found by citation_service._extract to one judgment record. It tries a legal_authorities row (SC, plus HC rows from P22) by citation key, then party tokens plus year, then Indian Kanoon (search, then doc fetch by tid) within the per-audit budget (P29 reservation RPC). 2. Name matcher (services/party_names.py, deterministic; replaces the Jaccard rule). (a) Normalise both the cited name and the indexed title (and the index's separate petitioner and respondent fields where present). Lowercase; remove dots, so 'C.B.I.' becomes 'cbi' and 'K.S.' becomes 'ks'. Split into parties on v./vs./versus. Drop honorifics and noise (justice, retd, hon'ble, dr, shri, smt, sri, kumari, m/s, mr, ms, mrs, late, through, lrs, and anr, ors, etc.). (b) Expand abbreviations from app/data/litigant_abbreviations.csv, a lawyer-reviewed table covering UOI, CBI, DDA, MCD, NDMC, NCT, GNCTD, LIC, SBI, RBI, SEBI, ONGC, BSNL, MTNL, NHAI, UPSC, CIT, DCIT, ACIT, ITO, PCIT, ED, NIA, CCI, TRAI, IOC, BHEL, NTPC, GAIL, DGFT, CESTAT and others. Both the abbreviation and its expansion count as present. (c) Classify tokens. Initials (1-2 letters, or joined initials like 'ks') are kept but are never required. Generic litigant tokens (state, union, india, government, commissioner, authority, corporation, bank, municipal, the state names, company-form words) are not distinctive. All other tokens are distinctive. (d) Rule. Take the cited first party's distinctive tokens; if there are none, take the second party's. Measure containment of those tokens in the whole indexed title, ignoring party order, because appeals reverse titles. One edit allowed for tokens of 6+ letters, for spellings like Satender/Satinder, noted 'spelling differs'. All present: name_match. Some present: name_partial (amber, needs reading). None present: name_citation_mismatch (red), and only when at least one distinctive token was available. No distinctive tokens on either side ('State v. State of X'): name_unchecked, and the key match alone stands. (e) The legacy subset rule in _name_match stays as an accept-path, so nothing that matches today starts failing. 3. Year check: an INSC or SCR year must equal the decision year; an SCC or AIR year must be on or after the decision year. 4. Judgment text: migration 014 adds judgment_texts (shared, org_id NULL, loaded by ingest scripts with the service role, read-only to users) and judgment_text_cache (org-scoped, written with the user's JWT for on-demand Indian Kanoon fetches and uploaded copies). 5. Paragraph parser (services/judgment_paragraphs.py): splits on line-initial 'N.' numbering, accepting paragraph N+1 only after N, so lists inside a paragraph aren't counted. It stores paragraphs[], numbered and paragraph_count. If the sequence breaks more than twice, numbered=false and pins report 'not checked'. 6. Pin extraction: 'para(s) 73(-74)', 'at para', '¶' or 'paragraph' in the same citation span or sentence, giving pin_ok / pin_out_of_range / pin_unchecked. 7. Quote extraction and matching with evidence_service.quote_match against the full text, then against the pinned paragraph ±1: quote_exact, quote_close, quote_not_at_pin, quote_not_in_judgment. 8. Candidate paragraphs: BM25 plus bge embeddings over that judgment's paragraphs against the citing sentence; the top 3 are shown. An optional Haiku hint sees only the PII-masked citing sentence and the paragraphs, and never changes a status. 9. Overall status is computed in code: verified = exists AND name not mismatched AND pin not failed AND (quote_exact at pin OR lawyer attestation). Anything failed is flagged and annotated '[unverified]' as today. 10. Authority tokens in generated text: agents get authorities as [A1..An] and write [A3 ¶14] or [Q A3 ¶14: "..."]. The renderer substitutes the formatted citation from the DB row (jurisdiction_service.format_case), so the model never types a citation string. Free-typed citations still go through the checker.

### Where it is built

app/services/citation_service.py (new statuses; CitationCheck gets name/pin/quote fields; the existing _name_tokens and _name_match stay as the accept-path), app/services/evidence_service.py (quote_match, _normalize), app/services/indiankanoon_service.py (fetch_doc(tid), year-aware match, per-audit budget instead of MAX_LOOKUPS_PER_CHECK=3), scripts/ingest_sc_judgments.py (judgment_texts and paragraphs; also stores petitioner and respondent separately), app/services/agent_workflow.py and drafting_engine.py (authority tokens and renderer), app/services/prompt_engine.py (token instructions, placeholders only). New: app/services/authority_resolver.py, app/services/party_names.py, app/data/litigant_abbreviations.csv (with sign-off record), app/services/judgment_paragraphs.py, supabase/migrations/014_citation_ledger.sql, app/routers/citations.py, frontend/src/app/verify/page.tsx.

### Why current tools fail and this won't

KeyCite and Shepard's answer whether a case is still good law, not whether the quoted sentence is at the pin. Lexis+ AI and Westlaw link to sources and leave the passage comparison to the user, and Stanford counted misgrounding among their errors. SCC Online and Manupatra AI search their own corpora but don't audit a paragraph written elsewhere. We do the three mechanical checks (identity, pin, verbatim quote) in code against full judgment text from openly licensed sources. The identity check is built for Indian cause titles: abbreviations, honorifics, initials and reversed appellate titles. It is measured against how judges actually cite, so it doesn't cry wolf on Puttaswamy. The one human check (proposition) is narrowed to 2-3 paragraphs placed beside the claim, and authority tokens mean our own agents can't type a fabricated citation string.

### Safeguards

Invariant 3 is extended, not replaced. Statuses are computed in code, and the AI hint is labelled and can't upgrade a status. Red name mismatches need a distinctive token to be absent; uncertainty is amber. The abbreviation table is a reviewed data file with a sign-off record, and changes go through review. Invariant 1: the citing sentence is PII-masked before any Anthropic call. Only cited case names and citation strings go to Indian Kanoon, never the surrounding text or the matter's own cause title. Invariant 2: shared judgment_texts are written only by ingest scripts; on-demand fetches go to the org-scoped cache with the user's JWT. Copyright: court judgment text only (s.52(1)(q)); no reporter headnotes or editorial paragraphing (Eastern Book Co. v. D.B. Modak). A copy a firm pastes from its own subscription stays org-scoped. CC BY 4.0 attribution stays on /about.

### How the panel's objections were answered

The Jaccard rule is removed. The new deterministic matcher (party_names.py): normalises dots and honorifics (Justice, Retd., Shri, M/s, Anr./Ors.); expands a lawyer-reviewed table of Indian litigant abbreviations (UOI, CBI, DDA, MCD, NCT, LIC, SBI, CIT and others); keeps initials but never requires them; treats generic litigant words as non-distinctive; measures containment of the cited first party's distinctive tokens in the whole indexed title, ignoring party order, with one-edit tolerance. It flags red only when none of the first party's distinctive tokens are present (amber when some are, and name_unchecked when there are no distinctive tokens). The existing subset rule stays as an accept-path, so nothing that passes today regresses. Fixtures cover the cited examples: Antil v. CBI, K.S. Puttaswamy/(Retd.)/UOI, DDA, LIC, reversed titles and spelling variants. The chimera class's false-flag rate is measured on 300 judge-written correct citations from SC judgments in the P11 real-world set and gated at 1% or less.

### Acceptance tests

- tests/test_party_names.py short forms: 'Satender Kumar Antil v. CBI' against 'Satender Kumar Antil versus Central Bureau of Investigation' gives name_match
- 'K.S. Puttaswamy v. UOI' and plain 'Puttaswamy' against 'Justice K.S. Puttaswamy (Retd.) and Anr. v. Union of India and Ors.' both give name_match
- 'DDA v. Skipper Construction' against 'Delhi Development Authority v. Skipper Construction Co. (P) Ltd.' and 'LIC v. Consumer Education & Research Centre' against 'Life Insurance Corporation of India v. Consumer Education and Research Centre' give name_match
- Reversed appellate title: 'Ramesh Kumar v. State of Haryana' against 'State of Haryana v. Ramesh Kumar' gives name_match; 'Satinder Kumar Antil v. CBI' gives name_match with 'spelling differs'
- Real chimera: a correct neutral citation of judgment X written with the parties of unrelated judgment Y gives name_citation_mismatch, and the note contains X's indexed title
- 'State v. State of Punjab' style titles with no distinctive tokens give name_unchecked, never mismatch; an unknown abbreviation ('XYZCL v. Ramesh') gives name_partial (amber), never red
- Benchmark false-flag gate: on 300 correct citations written by judges in SC judgments (P11 real-world set, class 'judge-written correct'), name_citation_mismatch fires on <= 1%
- Everything the existing _name_match accepts is still accepted (regression over the current test fixtures)
- A fixture judgment with 27 numbered paragraphs cited at 'paras 73-74' gives pin_out_of_range with 'has 27 paragraphs'
- A quote copied from para 14 and cited at para 14 gives quote_exact + pin_ok; cited at para 12 gives quote_not_at_pin naming para 14; an absent sentence gives quote_not_in_judgment and is flagged
- Paragraph parser: an inner list (1. 2. a. b. 3.) keeps paragraph_count=3; broken numbering gives numbered=false, and pins are pin_unchecked
- A mocked AI hint saying 'supports' never changes a status
- Drafter output with [A1 ¶3] renders the DB citation; a [Q A1 ¶3: "..."] token with a quote not in A1 is removed and its sentence flagged; a freely typed fake citation is caught
- Year check: '(2010) 4 SCC 1' for a judgment decided in 2015 is flagged
- DB test: a user cannot write judgment_texts; org A's judgment_text_cache rows are invisible to org B

### Reviewers' minor notes

- Pin checks against the court's own numbering should be limited to INSC, SCR and neutral citations (and SCC pins only where the corpus is known to follow the court's numbering). Otherwise SCC or AIR pins should default to pin_unchecked, which avoids false pin_out_of_range on renumbered reports.
- Very common surname tokens (kumar, singh, devi, sharma) should count as weakly distinctive, so a chimera sharing only 'kumar' isn't reported as a partial match by accident.
- Caching on-demand Indian Kanoon doc fetches in judgment_text_cache should sit behind the same IK-terms retention flag defined in P29; otherwise the two proposals conflict.
- Storing Indian Kanoon doc text in judgment_text_cache conflicts with P29's rule that IK caching stays behind a flag until the terms review. Make P12's cache writes for IK-sourced text obey the same flag.
- Popular-name citations ('ADM Jabalpur', 'Aadhaar case') should get an alias table entry rather than relying on token containment. Add such names to the 300 judge-written fixtures.

