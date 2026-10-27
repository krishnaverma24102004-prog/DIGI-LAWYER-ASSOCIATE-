# P02. Fabricated AI case citations in filings bring sanctions, disqualification and bar referrals, and paid legal AI tools still produce them

**Severity:** critical · **Size:** big · **Region:** Global (US-heavy; also UK, Canada, Australia, India)

**Who has it:** Litigators at every firm size, from solos to large firms (Butler Snow, K&L Gates, Latham); supervising partners who sign briefs drafted by others; judges and clients who rely on filings

## What goes wrong

An associate or partner asks an AI tool for supporting authority, pastes the result into a brief, and files it without opening each case. Opposing counsel or the judge can't find the case, and the lawyer faces a show-cause hearing, fee awards (USD 110,204.38 against two lawyers in one Oregon case), disqualification and bar referral. Each incident is reported publicly under the firm's name. Using paid tools is no defence: in Lacey v. State Farm the fake citations came from research done with CoCounsel, Westlaw and Gemini, and the judge nearly put them into an order. The number of reported decisions has grown from about 712 at end-2025 to over 2,200 by October 2026, and these are only the cases where someone was caught.

## Evidence of scale

- The Charlotin AI Hallucination Cases database lists 2,207 cases (last updated 23 Oct 2026): 877 involve lawyers and 16 are from India. ([source](https://www.damiencharlotin.com/hallucinations/))
- By 10 October 2026 Charlotin's database listed 2,184 decisions worldwide, 1,492 in US courts. US decisions involving a lawyer: 14 in 2024, 207 in 2025, 361 in the part of 2026 counted. Sanctions include Couvrette v. Wisnovsky (D. Or.) USD 110,204.38 against two lawyers, Whiting v. City of Athens (6th Cir.) USD 15,000 each plus fees and double costs, ByoPlanet v. Johansson fee awards of USD 85,567.75, Lacey v. State Farm USD 31,100. ([source](https://vaquill.ai/blog/ai-hallucination-sanctions-tracker))
- Charlotin's database page reported '1,545 legal cases so far' and said it is actively updated. ([source](https://tinyapps.org/blog/ai-hallucinations-in-court.html))
- About 1,058 US cases as of early June 2026 (about 720 federal, 340 state), roughly 60% pro se and 40% attorneys; Westlaw created Key Number 46Hk789, 'Use of artificial intelligence'. ([source](https://library.law.unc.edu/2026/06/handling-hallucinations-a-reflection/))
- AFP (June 2026): Charlotin's database holds about 1,600 court documents with AI hallucinations from 35 countries (1,116 US, 173 Canada, 74 Australia, 59 UK); hallucinations in filings rose eightfold over the past year. ([source](https://www.malaymail.com/news/tech-gadgets/2026/06/16/do-your-job-global-courts-face-rising-tide-of-ai-generated-fake-cases-and-quotes/223865))
- Bloomberg Law (29 Dec 2025): about 712 rulings worldwide had addressed hallucinated content in court filings, about 90% of them issued in 2025. ([source](https://news.bloomberglaw.com/in-house-counsel/ai-faked-cases-become-core-issue-irritating-overworked-judges))
- Johnson v. Dunn (N.D. Ala., July 2025): three Butler Snow lawyers were disqualified and referred to the Alabama State Bar over ChatGPT-generated citations, in breach of the firm's AI policy, and the order was to be shared with clients, opposing counsel, every lawyer at the firm and judges in their pending cases. ([source](https://edrm.net/2025/07/when-ai-policies-fail-the-ai-sanctions-in-johnson-v-dunn-and-what-they-mean-for-the-profession/))
- Lacey v. State Farm: USD 31,100 in sanctions against Ellis George and K&L Gates; Judge Wilner said he almost included the fake citations in a judicial order. ([source](https://getcoai.com/news/sloplaw-and-disorder-ai-generated-citations-nearly-fool-judge-in-court-ruling))
- AI Vortex case brief lists CoCounsel, Westlaw Precision and Google Gemini as the tools used in Lacey and describes a 'systemic failure in verification and supervision' (the site's summary). ([source](https://www.aivortex.io/legal-ai-risk/cases/lacey-v-state-farm-general-insurance-2025-05-06/brief))
- Stanford RegLab/HAI benchmark: Lexis+ AI and Ask Practical Law AI gave incorrect answers on more than 17% of queries, Westlaw AI-Assisted Research on more than 34%, despite 'hallucination-free' marketing. ([source](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries))
- Stanford RegLab/HAI 'AI on Trial': legal AI research tools from LexisNexis and Thomson Reuters hallucinated on at least 1 in 6 benchmark queries. ([source](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-queries))

## Why current tools don't solve it

Harvey, CoCounsel and Lexis+ AI generate text with citations, but none blocks a draft from being exported or filed until every authority has been checked against a primary source. In US v. Farris (6th Cir.) counsel drafted with CoCounsel and was removed and referred; in Gauthier v. Goodyear a Lexis AI check didn't flag the fabricated cases. Citators (KeyCite, Shepard's) say whether a case is still good law, not whether the propositions in an AI-written paragraph are supported. They don't check citations a lawyer pastes in from elsewhere or that an opponent files.

## Panel verdict

**Status:** open (round -)

**Effort:** L

### What software can fix

Stop unchecked authority from leaving the firm in a filing. A 'filing copy' export stays blocked until every citation is either verified by code or attested by a named lawyer, and each export carries a per-citation verification record. The check also runs on text we didn't write: an associate's Word draft, pasted ChatGPT output, a senior's brief. Sanctions follow the signer whatever tool produced the citation.

New this round:
- The judgment side is cleaned deterministically before any word matching. Line-end hyphens are joined, running headers and footers, page numbers and footnote markers are stripped, and offsets back to the original PDF page are kept. A correctly copied quote that crosses a page break or a hyphenated line therefore verifies.
- A difference that falls in a layout zone downgrades to amber, never hard red.
- An official court translation is never green. It is an amber 'restricted use' reading aid, bound to the English paragraph it mirrors, and the record prints the Court's own disclaimer word for word next to the English paragraph.

### What it can't fix

Limits of the gate:
- We can't stop a lawyer copying text out of the app, or filing something that never went through it. The gate covers our export path and is evidence of diligence.
- An external_source row records what the lawyer says they read. We can't confirm that reading.
- We can't prove an uploaded copy is a certified copy.

Limits of quote checking:
- We check that each fragment is the court's exact words, in order and close together. Negations and qualifiers next to omissions are flagged. Whether an elision distorts the meaning stays the signing advocate's duty of candour.
- Layout cleaning is rule-based. A PDF with an odd layout (two columns, a header the rules don't recognise, scanned pages) can leave artefacts. When an unexplained difference sits in a layout zone, we say 'layout unclear, check page 7' (amber) rather than guess. We never call it fabricated.

Limits on translations:
- We can't check counsel's own translation against the English by code, so the lawyer attests it.
- The Supreme Court's SUVAS/vernacular translations are published for the litigant's restricted use, with the English version authentic. We therefore never treat them as a verification source or as quotable authority.
- Whether even storing them as a reading aid is within the Court's terms is a legal question. scripts/ingest_sc_translations.py ships disabled (INGEST_SC_TRANSLATIONS=false) until the firm's or our counsel's review of the terms clears it. Until then, only translations a lawyer uploads for their own matter are used, labelled lawyer-supplied.

Other limits:
- We don't index US/UK judgments, so those rows read 'unverified: jurisdiction not indexed'.
- Whether a court excuses an error is for the court.

### What the user sees

Unchanged from earlier rounds:
- In /studio the export menu has 'Working copy' (never blocked, watermarked until approved) and 'Filing copy'.
- 'Filing copy' opens the Verification Ledger and stays disabled while a counter such as '3 citations need you' shows.
- The three ways to attest, rebind, carry-forward, the record PDF and /verify work as before.
- The round-5 statuses are unchanged: green 'Verified word for word' (also 'elided, n parts'), red 'Not the court's exact words' with a word diff and negations highlighted, amber 'Omission next to a qualifier', amber 'Translation by counsel', amber 'Corrected to the court's words, now confirm', and 'Make it a paraphrase'.

New this round:
- A quote that crosses a page break, a hyphenated line end or a footnote marker in the S.C.R./INSC PDF shows plain green 'Verified word for word'. A small 'layout' note lists what the cleaner joined or skipped, for example 'joined discre-|tion (p. 6-7); skipped running header "SUPREME COURT REPORTS [2019] 5 S.C.R." and page no. 412; skipped footnote marker 12'. Clicking it opens the original page image with those spots outlined.
- Amber 'Layout unclear on p. 7: check the page'. This appears when the only differences between quote and judgment sit at a page edge or line end the cleaner couldn't explain. The judgment pane shows the cleaned text above the original page image, and the lawyer clears the row in_app after looking. It is never red.
- The 'Use the court's words' candidates show cleaned text only. A candidate that spans an unexplained layout artefact is greyed out with 'Layout unclear on p. 7; open the page image'. It can't be inserted, so a header or 'discre tion' can never reach the pleading.
- Amber 'Matches the Court's translation (restricted use)' replaces last round's green official-translation status. The panel shows three things side by side: the Hindi quote, the Court's translated para 14 and the English para 14. The English para is pre-selected because the translations mirror its numbering, and the lawyer must confirm it. The Court's disclaimer is shown verbatim above the translation. Two exits:
  - 'Add the English original to the draft' inserts English para 14 as a block quote or footnote in a new version. The English quote is then checked like any other quote and must come out green.
  - 'I adopt this as my translation of para 14' records translation_by_counsel.
  The row is filing-ready only after one of these, plus the lawyer's confirmation of the English para binding.

### What the system does

Unchanged: steps 1-3 (audit endpoint, binding_method, disambiguation, text_quality), 4a parse_quote, 4a' normalize_words, 4b' script_of, 4d elision_polarity, 4f/4g correction and paraphrase flows, and steps 5-11 except as noted below. The checksummed quote_conventions.yaml gains a judgment_layout section and a translation_disclaimer_markers list.

NEW 0. Judgment text cleaning: app/services/judgment_text.py, shared with P12. Pure and deterministic, versioned as CLEANER_VERSION.

(i) Extraction keeps pages. ingest_sc_judgments.pdf_text currently joins pages with '\n'. It is replaced by pdf_pages() -> list[str], one string per page with line breaks kept. The RAG chunker receives the cleaned text, which also improves retrieval.

(ii) Running headers and footers. For each page take the first 3 and last 3 lines. Mask digits to '#' and collapse whitespace. A masked line that recurs at the same edge on at least 30% of pages (and at least 2 pages) is a running header/footer. Examples: 'SUPREME COURT REPORTS [####] # S.C.R.', '###'. So are lines matching the fixed judgment_layout patterns: a bare page number, '[YYYY] n S.C.R. nnn', 'YYYY INSC nnn' alone on a line, 'Digital Supreme Court Reports', 'REPORTABLE', 'NON-REPORTABLE', a 'Signature Not Verified' stamp block. These lines are removed and recorded as artefacts {page, kind, original_offset, text}.

(iii) Footnotes. On a page whose bottom block, after an optional rule line, has lines starting with a number n, that block is moved to a separate footnotes stream tagged (page, n). A quote taken from a footnote is still matchable there, but running text never crosses it. A glued marker is stripped from running text when a footnote n exists on the same page: 'liberty12' becomes 'liberty', recorded. Superscript digits ('liberty¹²') are always stripped. A glued digit with no matching footnote is left alone and marked as an unresolved artefact.

(iv) Line-end hyphens. 'X-\nY', where X ends in a letter and Y starts with a lowercase letter, is joined. The joined form drops the hyphen if it occurs elsewhere in the same judgment, or in the bundled legal lexicon app/data/lexicon_en.txt. It keeps the hyphen ('self-incrimination') if only the hyphenated form occurs. Otherwise it is joined both ways and marked hyphen_ambiguous; the matcher accepts either form.

(v) Ordinary line breaks inside a paragraph become spaces. Paragraph numbers at line start become para indices, via the P12 parser.

(vi) Offsets. Output is CleanText {text, offset_map: list of (clean_start, clean_end, page, orig_start), artefacts, cleaner_version, layout_zones}. layout_zones are clean-text character ranges within 2 tokens of a page join, a removed line, a hyphen join or an unresolved artefact.

(vii) text_quality also becomes 'layout_uncertain' when unresolved artefacts exceed 1 per 2 pages, or when more than 2 edge lines per page fit neither the header rules nor body text. Under rule 2, that alone removes every hard status for this judgment.

The result is stored in judgment_text_cache: raw_sha256, clean_text, offset_map, artefacts, cleaner_version. A cleaner_version bump re-cleans lazily. The carry-forward key now includes cleaner_version.

CHANGED 4c'. match_fragment(frag_words, clean, conventions) runs on CleanText.
- Join equivalence: a run of 1-3 fragment tokens equals a run of 1-3 judgment tokens when their concatenations are identical after removing hyphens and soft hyphens. Examples: 'discre tion' / 'discretion', 'non-bailable' / 'non bailable', 'cannot' / 'can not'. Only letters are compared, so this can't change a word. Each use is recorded as join_equivalence and printed in the record.
- Results are 'exact', 'exact_layout' or 'differs'.
  - 'exact': an exact contiguous match modulo join equivalence and spelling_equivalents, with no unresolved artefact inside the matched span.
  - 'exact_layout': the same, but an unresolved artefact or hyphen_ambiguous join lies inside the span.
  - 'differs': the existing opcode diff, with each non-equal opcode tagged in_layout_zone = (its judgment-side range intersects layout_zones).

CHANGED 4e quote_status. New step (3a) is inserted before the hard steps. If a fragment is 'exact_layout', or 'differs' where every non-equal opcode has in_layout_zone and none changes a polarity word, the result is quote_layout_soft (amber, in_app). The lawyer clears it after viewing the original page image, rendered from the stored PDF at offset_map's page. quote_differs (hard) now requires at least one non-equal opcode outside every layout zone, or a polarity change anywhere. A real one-word change in body text stays hard, and so does a 'not' hidden at a page break.

CHANGED 4f closest_passages and use_court_words. Candidates come from clean_text, and are rendered from clean spans with hyphen joins in their resolved form. A candidate whose span contains an unresolved artefact or hyphen_ambiguous join has insertable=false. A post-condition assertion runs on every insertion: the inserted string contains none of the judgment's artefact texts, no bare page-number token at a page join, and no footnote marker. If the assertion fails, the insertion is refused (500 and an audit event), never applied.

CHANGED translation path, 4e(1).
- A translated-script fragment is matched with match_fragment against a held judgment_translations row for the same authority_id and language.
- A match gives official_translation_restricted (amber), never verified.
- The system proposes the English binding: English para p for translated para p. Translations mirror the para numbering, and this is confirmed when both texts have the same para count; otherwise the lawyer picks the para.
- No match gives quote_translation_soft, as before.
- Neither status is ever hard.

NEW attestation and exit rules for official_translation_restricted. The row is filing-ready only when (a) the lawyer has confirmed the English para binding (an in_app attestation naming the para indices, fetched in the pane) AND (b) one of the following holds:
- add_english_original has inserted that para into the draft as a new version, and the English quote then checks exact by code; or
- translation_by_counsel is recorded naming the same para.
external_source returns 422 for this status. Audit events: TRANSLATION_ENGLISH_BOUND and ENGLISH_ORIGINAL_ADDED.

CHANGED 12. judgment_translations gains disclaimer_text (NOT NULL), disclaimer_sha256 and use_terms='restricted_reading_aid'.
- The disclaimer is extracted verbatim from the translation document itself: the block found by translation_disclaimer_markers, e.g. 'Disclaimer', 'अस्वीकरण', on the first or last page.
- A translation without a captured disclaimer is stored with usable=false, and is never used for matching or display.
- The record PDF prints, with no LLM, in this order:
  1. the English para in full as the authority;
  2. the Court's translated para labelled 'Court's translation, restricted use';
  3. disclaimer_text verbatim;
  4. the binding attestation.
- scripts/ingest_sc_translations.py is disabled by default (a flag plus a refusal message pointing to the terms review). Lawyer uploads use the same disclaimer extraction and identity check as uploaded_copy.

### Where it is built

Extend:
- scripts/ingest_sc_judgments.py: pdf_text() is replaced by pdf_pages(), chunks are built from judgment_text.clean(), and per-page text and the source PDF sha are stored so page images can be re-rendered.
- app/services/evidence_service.py: read-only. quote_match, _normalize and quote_found are unchanged (invariant 6).
- app/routers/drafting.py: export_draft purpose=filing, plus use_court_words, make_paraphrase and add_english_original.
- app/services/citation_service.py
- app/services/draft_check.py
- app/services/safety_service.py: partner approval.
- app/services/pdf_service.py: the record, layout notes and the verbatim disclaimer.
- app/services/audit_service.py
- app/services/document_service.py and ocr_service.py: page-image rendering for the layout view.

New:
- app/services/judgment_text.py: pdf_pages, detect_running_lines, split_footnotes, join_hyphens, clean -> CleanText, page_image. Shared with P12 and P26.
- app/data/lexicon_en.txt: a checksummed legal and English word list for hyphen resolution.
- app/services/citation_audit.py: match_fragment with join equivalence and layout zones, quote_status with quote_layout_soft and official_translation_restricted, closest_passages with insertable, and allowed_modes.
- app/data/quote_conventions.yaml: adds judgment_layout patterns and translation_disclaimer_markers.
- app/routers/citations.py
- scripts/ingest_sc_translations.py: disabled by default.
- tests/fixtures/judgments/: ReportLab-generated two- and three-page judgment PDFs with a running header 'SUPREME COURT REPORTS [2019] 5 S.C.R.', page numbers, a hyphenated 'discre-/tion', a footnote marker 'liberty12' with footnote 12, superscript markers, a non-recurring odd header, and their committed pypdf extractions. Also a fixture Hindi translation PDF carrying a disclaimer block, and one without.
- Migration 014_citation_ledger.sql adds:
  - judgment_text_cache: clean_text, offset_map jsonb, artefacts jsonb, cleaner_version;
  - judgment_translations: disclaimer_text, disclaimer_sha256, usable, use_terms;
  - citation_audit_items: layout_notes and english_binding;
  - attestation mode values english_binding_confirmed (alongside translation_by_counsel and court_words_confirmed).
- frontend/src/app/verify/page.tsx and the studio ledger panel: the layout note, a page-image viewer with outlined spots, greyed non-insertable candidates, and a three-column translation view with the disclaimer.

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis+ AI generate citations but don't stop an unchecked draft being exported. The Lacey sanctions involved CoCounsel/Westlaw output, and Gauthier shows an AI checker missing fabricated cases. SCC Online, Manupatra and Indian Kanoon find judgments but don't check a draft, and are English-only.

Quote checkers fail in one of four ways:
- Whole-string comparison flags every elided quote.
- Fuzzy matching passes a quote whose last clause turned 'shall' into 'may'.
- Exact matching on raw PDF text flags every correct quote that crosses a page break. Lawyers learn to ignore red, and the gate becomes busywork.
- Treating a court's vernacular translation as quotable authority contradicts the Court's own disclaimer.

Ours works differently:
- Layout artefacts are removed by recorded, reversible rules before exact word matching.
- Token splits and merges are equal only when the letters are identical.
- Anything the cleaner can't explain goes to amber with the page image, never red and never into the pleading.
- Translations are reading aids tied to the English paragraph, which is the text the bench is shown.
- Green still means only one thing: the court's exact words in its authoritative English text, checked by code.

### Safeguards

A lawyer is always the last step:
- Green comes only from an exact word match by code against the cleaned authoritative English text, and every cleaning step is listed in the record and traceable to the original page.
- An unexplained layout difference is amber, with the original page image shown, never red and never inserted into a pleading.
- Every automatic correction or form change needs the signing lawyer to read the inserted words, and junior drafts then also need partner approval.

Translations:
- Court translations are used only as restricted-use reading aids, never labelled verified, and always printed below the English paragraph with the Court's disclaimer verbatim.
- Ingesting them stays off until a terms review.
- Counsel's own translation is attested and printed beside the English text.

Rules and records:
- All rules (layout patterns, the lexicon, polarity words, spelling equivalents, editorial markers, disclaimer markers) are checksummed, lawyer-signed data, never an LLM.
- The record never says 'guaranteed accurate'.
- Every attestation, correction, paraphrase, English insertion and filing export is audit-logged.

Data handling:
- The working copy is never blocked.
- Only citation strings go to Indian Kanoon.
- Any LLM hint uses masked text (invariant 1).
- Uploaded copies and translations stay org-scoped, with no service-role use in user paths (invariant 2).

### How the panel's objections were answered

Objection 1 (exact matching on uncleaned corpus text gives false hard blocks):

(a) Clean the judgment side, deterministically, with offsets kept. I confirmed the gap: scripts/ingest_sc_judgments.py's pdf_text() just joins pypdf page text with '\n', with no cleaning. The new app/services/judgment_text.py, shared with P12:
- keeps pages;
- removes running headers and footers, detected by digit-masked recurrence at page edges on at least 30% of pages, plus fixed checksummed patterns for S.C.R./INSC/page-number/REPORTABLE lines;
- moves footnote bodies to a separate stream;
- strips glued footnote markers only when footnote n exists on that page (superscripts always);
- joins line-end hyphens, resolved against the same judgment and a bundled lexicon, with ambiguous joins accepted both ways.
Every removal is an artefact with page and original offset. The offset_map maps clean text back to the PDF page, and the record lists what was joined or skipped.

(b) Token splits and merges, and downgrade instead of block:
- match_fragment treats 1-3 token runs as equal when their letter concatenations are identical ('discre tion' = 'discretion'), recorded as join_equivalence.
- A match that spans an unresolved artefact is 'exact_layout'.
- A diff whose every change sits in a layout zone, with no polarity change, becomes quote_layout_soft (amber, in_app with the page image), never quote_differs.
- Hard red now needs a change outside layout zones or any polarity change.
- A judgment whose layout is too noisy gets text_quality layout_uncertain, which removes hard statuses entirely.

(c) Insertion uses clean text only:
- closest_passages and use_court_words render from clean_text with resolved hyphen joins.
- A candidate spanning an unresolved artefact is not insertable.
- A post-insert assertion refuses any insertion that would contain an artefact string.

Fixtures: a page break with a running header and page number, a hyphenated line end (both resolution cases), a glued footnote marker and a superscript marker each give verified. An unrecognised header gives layout soft, not hard. A removed 'not' at a page break is still hard.

Objection 2 (the official-translation match was green although the Court restricts its use): the green status is gone.
- A word-for-word match with a held translation is now official_translation_restricted (amber), 'Matches the Court's translation (restricted use)'.
- It is filing-ready only after the lawyer confirms the paragraph-aligned English original. The para is proposed by mirrored numbering and confirmed only when para counts agree, otherwise picked.
- Then either 'Add the English original to the draft' is used (the English para is inserted and must check exact by code, so the bench has the authentic text), or translation_by_counsel is recorded naming that para.
- The record prints the English para in full first, then the translation labelled 'Court's translation, restricted use', then the Court's disclaimer byte-for-byte. The disclaimer is taken from the translation document itself (NOT NULL; a translation without a captured disclaimer is unusable).

I also accept the reading that ingestion 'where its terms allow' could ingest nothing. ingest_sc_translations.py now ships disabled pending a terms review, and until then only lawyer-uploaded translations, labelled lawyer-supplied, are used.

Test: a Hindi quote matching the fixture official translation is not filing-ready after only the binding confirmation. It is filing-ready after add_english_original or translation_by_counsel. The record contains the English para, the disclaimer verbatim and no 'Verified' label on that row.

### Acceptance tests

- Page break with a running header: a 30-word quote from fixture 2019 INSC 512 that runs from the foot of p. 6 to the top of p. 7, where pypdf output has 'SUPREME COURT REPORTS [2019] 5 S.C.R.' and '412' between, gives verified. layout_notes lists the skipped header and page number, and offset_map points to pages 6 and 7
- Hyphenated line end: a quote containing 'discretion', where the fixture text has 'discre-\ntion', gives verified with a join_equivalence note. A quote containing 'self-incrimination', where the fixture has 'self-\nincrimination' and the hyphenated form occurs elsewhere, also gives verified
- Footnote marker: a quote '... the right to personal liberty is ...' against fixture text 'personal liberty12 is' with footnote 12 on the same page gives verified. A quote copied from footnote 12 itself verifies against the footnotes stream, and running text never crosses into the footnote body
- Superscript marker: 'liberty¹²' in the judgment and 'liberty' in the quote gives verified
- Unrecognised layout: a fixture with a one-off header line, not recurring and matching no pattern, inside the quoted span gives quote_layout_soft (amber), never quote_differs. in_app clears it, and the page-image endpoint returns the rendered p. 7
- A polarity change still bites at a page break: the same cross-page quote with 'not' removed at the page join gives quote_differs (hard) with the polarity flag, not layout soft
- A body change is still hard: changing 'shall' to 'may' in mid-page text, outside any layout zone, of a cleaned fixture gives quote_differs (hard). The round-5 tail-change and added-'not' tests are unchanged
- Join equivalence can't change a word: 'discre tion' against 'discretion' passes, while 'discrete ion' against 'discretion' (different letters) gives differs
- Clean insertion: use_court_words on a cross-page candidate inserts text that contains no artefact string ('SUPREME COURT REPORTS', '412', '12' as a marker) and contains 'discretion', not 'discre tion'. A candidate spanning an unresolved artefact has insertable=false, and the route returns 409
- Cleaner determinism: the same PDF bytes give a byte-identical CleanText 100 times. A CLEANER_VERSION bump invalidates carry-forward for rows bound to that judgment and nothing else. Mapping every clean span back through offset_map reproduces the original substrings
- layout_uncertain: a fixture with dense unclassified edge lines sets text_quality to 'layout_uncertain', and no row bound to it can be hard
- Official translation is restricted: a Hindi quote matching the fixture judgment_translations row word for word gives official_translation_restricted (amber), and filing_ready is false. After english_binding_confirmed for para 14 alone it is still false. After add_english_original (the English para 14 inserted and checked exact by code) or translation_by_counsel naming para 14, it becomes true. external_source returns 422
- The record prints the disclaimer and the English text: for that row the record PDF contains English para 14 in full, the label 'Court's translation, restricted use', and disclaimer_text byte-equal to the fixture's disclaimer block. It never contains the word 'Verified' on that row
- No disclaimer, no use: a fixture translation without a disclaimer block is stored with usable=false, and a matching Hindi quote falls back to quote_translation_soft
- Translation ingestion is off: ingest_sc_translations.py without INGEST_SC_TRANSLATIONS=true exits non-zero and writes nothing
- Para mismatch: when the translation and the English judgment have different para counts, no English binding is proposed automatically, and the lawyer must pick the para
- Round-5 tests still pass: the Hindi translation_by_counsel test, romanised Hindi, mixed quote, bracket_hides_polarity, elision_polarity, negation-flip correction with partner approval, make_paraphrase, and normalize_words keeping Devanagari vowel signs. The evidence_service._normalize output is byte-identical on the contradiction fixtures
- Round-3 and round-4 tests still pass: the elided, '* * *', bracket and emphasis-marker tests, the checksum tamper test, the 500-quote property test, the same-name trap, ambiguous_match, rebind, upload identity 422, s. 124B IPC invalid, 40-citation carry-forward, byte-identical record PDFs and RLS isolation

### Still blocking

- The 'I adopt this as my translation of para 14' exit for official_translation_restricted lets the Supreme Court's restricted-use vernacular translation reach a court inside a pleading, attested as counsel's own translation. The status only arises when the Hindi quote matches the Court's translation word for word, so the attestation is false on its face. It is also exactly the 'other purpose' that the Court's disclaimer prohibits. The internal record prints the disclaimer, but the filed pleading carries only the Hindi text, which is attributed to counsel. Fix I would accept: for official_translation_restricted, make add_english_original (the authentic English para inserted and checked exact by code) the only exit that makes the row filing-ready. Offer translation_by_counsel only after the lawyer has replaced the Hindi with their own rendering, which then no longer matches the Court's translation verbatim and falls to quote_translation_soft, or in addition to the English insertion and never instead of it. Add a test: a verbatim match plus translation_by_counsel alone gives filing_ready false.
- Join equivalence is not 'can't change a word', so green no longer means 'the court's exact words'. As specified, any run of 1-3 tokens anywhere in the span counts as equal when the letters concatenate to the same string. The proposal's own 'cannot' / 'can not' example is one case, and others are 'may be' / 'maybe', 'any one' / 'anyone', 'every one' / 'everyone', 'a part' / 'apart', 'in to' / 'into' and 'some times' / 'sometimes'. These are different words with different meanings in legal text ('any one of the accused' vs 'anyone of the accused'). Yet a mid-page quote that swaps them, nowhere near a line break, would be 'Verified word for word'. Fix I would accept: allow join equivalence only where the judgment-side token boundary falls in a layout zone (a line end, a page join, or a recorded hyphen or soft-hyphen join). Anywhere else, a split or merge is a non-equal opcode outside the layout zones. It is hard red, or amber at most if the pair is listed in a checksummed, lawyer-signed compound list such as 'cannot' / 'can not'. Also add tests: 'may be' against mid-page 'maybe' is not green, while 'discre tion' against 'discre-\ntion' is green.

