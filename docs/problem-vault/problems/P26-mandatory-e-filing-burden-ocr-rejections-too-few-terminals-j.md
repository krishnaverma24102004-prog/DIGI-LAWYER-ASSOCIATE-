# P26. Mandatory e-filing burden: OCR rejections, too few terminals, juniors losing whole days to uploads

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Trial-court advocates, especially rural and small practices; juniors and munshis; bar associations

## What goes wrong

With e-filing compulsory (Tamil Nadu trial courts, leading to a boycott from Dec 2025; Kerala HC for nearly all case types), advocates must produce OCR-readable, correctly formatted PDFs. One pen correction can get a page rejected and retyped. Complexes have 2-4 filing systems, so a junior can lose a day on one upload. Scanners, typists and internet are a new fixed cost for rural and first-generation practitioners; munshis say the rules ignore them, and bars have boycotted courts.

## Evidence of scale

- Tamil Nadu trial-court boycott (3 Dec 2025 to at least 7 Jan 2026): a missed pen correction means retyping; about 2-4 systems per complex; a junior can lose a day uploading one case; workload said to have tripled. ([source](https://www.barandbench.com/columns/trial-courts-offline-algorithms-online-tamil-nadus-dec-2025jan-2026-boycott))
- Kerala Advocate Clerks Association told the CJI that e-filing rules ignore clerks and put over 10,000 livelihoods at risk. ([source](https://barandbench.com/news/e-filing-and-loss-of-livelihood-kerala-advocate-clerks-association-writes-to-cji-nv-ramana-with-concerns))
- Kerala advocate clerks held a hunger strike against mandatory e-filing; Justice PV Kunhikrishnan spoke in support. ([source](https://www.livelaw.in/amp/news-updates/kerala-advocate-clerks-association-hunger-strike-mandatory-e-filing-onam-236556))
- KHCAA resolved not to file under the Kerala HC e-filing system; AILU said only 1,500 of 7,000 members had registered. ([source](https://livelaw.in/news-updates/kerala-high-court-bar-expresses-concerns-about-e-filing-rules-174233))

## Why current tools don't solve it

Global AI tools stop at drafting. None turns a typed or handwritten Indian pleading into a court-compliant e-filing bundle (OCR text layer, bookmarks, pagination, index, font/margin rules, size limits), runs a per-court pre-upload check, or lets a munshi prepare and queue a filing on a phone in Hindi or Tamil. Indian vendors sell e-filing services without AI compliance checks.

## Panel verdict

**Status:** solved (round 6)

**Effort:** L

### What software can fix

Turning a pleading into an e-filing bundle that is checked against the target court's own formatting rules. The bundle gets a searchable Unicode text layer, page numbers, an index, bookmarks, size splits, and page-size and resolution checks. Where a court prescribes them, it is also checked for font family, body size, line spacing and margins.

For courts that mandate a font (Supreme Court, Delhi HC, Bombay HC), the default input is the PDF the firm exports from Word on its own licensed machine. We check that PDF and assemble the bundle around it without re-rendering the body. Round 6 makes those checks match how Word actually lays out a page:
- Headers and footers that Word puts inside the margins are recognised and checked separately, not failed as margin breaches.
- Our own stamped page numbers are left out of the body checks.
- Neutral characters (spaces, punctuation, digits) inside Hindi or other non-Latin runs, and conjunct glyphs, are attributed to the script of their run.

Courts with no font mandate keep the DOCX path with metric-compatible free fonts. Also still covered: legacy Hindi DOCX conversion, replacing a single page, and a munshi preparing and queuing the bundle on a phone in Hindi or Tamil.

### What it can't fix

Things software can't fix:
- Court portals, terminals and internet access, and how many filing systems a court complex runs.
- OTP and credential steps, and clerks' livelihoods.
- We never log in to e-filing portals or upload to them.
- We can't ship Microsoft fonts, and we don't accept Windows or Office copies of them on our server.
- The Word export has to be done on a computer that has Word. A munshi on a phone uploads a PDF that a lawyer or an office computer exported.
- We can't decide whether a registry will accept a recorded deviation.
- We don't rewrite pleadings. We flag the problem and the fix is made in Word.
- Court rules change by notification. Profiles are data with a source and a review date, and overdue profiles are flagged, but we can't guarantee a profile is current on the day a court amends its rule.

Limits of the checks themselves (all reported, never hidden):
- With only a PDF, line spacing is measured within a tolerance.
- Header and footer detection on untagged PDFs is heuristic. Text in a margin that the detector can't classify is amber when it sits in only one place, and a failure, naming the page and text, when it is clearly body text. It is never silently passed.
- Quote-size findings are advisory.
- Some Indic glyphs carry no usable Unicode text in Word's output (the ToUnicode map is empty or points to the private-use area). Text copied from those glyphs may not be searchable, and we report that. We can't repair Word's ToUnicode map.
- Legacy-to-Unicode conversion flags unmapped glyphs and never guesses them.
- We don't check that a font Word embedded was licensed on the firm's machine.

### What the user sees

Steps 1 and 2 of /studio/bundle are as in round 5: choose the 'Filing in' court, then use the PDF-first card for courts that mandate a font. That card also accepts an optional .docx, shows Word export help, and offers the advanced licence-gated org-font route. Round 6 changes three things.

(a) Headers and footers. The formatting checklist has a separate item, 'Headers and footers (outside the margin rule)'. For example:
- Green, info: 'Pages 1-40: footer "Page N of 40" at 1.3 cm from the bottom edge, and running head "W.P.(C) No. __ of 2026" at 1.2 cm from the top edge. Recognised as Word headers and footers (tagged as pagination artifacts by Word).'
- On untagged PDFs the source reads '(repeats on 38 of 40 pages)' or '(page-number pattern)'.
- With the .docx supplied, it reads '(matches the document's footer)'.
The Margins item then reads 'Margins: body text starts 4.0 cm from the left edge and ends 2.6 cm above the bottom edge (rule: <value>): met'. If the profile has a header_footer_min_cm, the header/footer item also shows that value and passes or fails against it.
Genuine breaches still fail and name the text: 'Page 5: body text "...the respondent thereafter..." sits 1.4 cm from the bottom edge, inside the margin (rule: <value>).'
A single unclassifiable line in a margin is amber: 'Page 3: "Annexure P-2" in the top margin. Not recognised as a header. Check it.'

(b) Page numbering. If Word numbers are found on most pages, the 'Pages already numbered in Word' toggle is switched on automatically, with the line 'Word page numbers detected on 38 of 40 pages. We won't stamp numbers over them; we'll verify the sequence.' When we do stamp numbers, the preview shows where they go, and the post-assembly check states 'Our page numbers: checked for position and font only (not part of the body checks).'

(c) Bilingual pleadings. The font line reads, for example, 'Hindi runs on pages 3, 7 (including their spaces, punctuation and digits): Nirmala UI, allowed for Devanagari under this profile.'
- A real failure reads 'Page 9: English sentence "The petitioner states..." is set in Nirmala UI. The Supreme Court requires Times New Roman for English text.'
- A Western-digit-only line set in a Devanagari font, with no script around it, is amber.
- Glyphs that carry no Unicode text show as info: 'Page 7: 14 Hindi glyphs carry no copyable text in Word's export. Searching the PDF may miss them.'

Deviation acceptance and the final approval screen are unchanged.

### What the system does

1. Court profiles are as in round 5 (mandate_scope, overlay_fonts, script_fonts), with one new optional field. header_footer_min_cm is the minimum distance of header and footer text from the page edge, with its own source and reviewer, or null where the rule is silent. CI (scripts/check_court_profiles.py) validates it.

2. Region classification (new, in app/services/pdf_format_checks.py, deterministic). This runs before the margin and size checks. Every char from pdfplumber is labelled 'body', 'header_footer' or 'overlay'. The page has a top band and a bottom band, each running from the page edge to margin_cm + 0.3 cm. The first source that applies decides:

(i) Tagged PDF. A pikepdf.parse_content_stream walk records the marked-content property dict around every text-show operator, joined to pdfplumber chars in stream order. pdfplumber's char 'tag' is a cross-check. Chars inside /Artifact with /Type /Pagination (Subtype Header, Footer or absent) that lie within a band become header_footer. Pagination artifacts outside both bands stay body, so tagging can't hide body text from the checks. Other artifact types (Layout, Page, Background) also stay body.

(ii) DOCX supplied, and it passed the 0.98 token-overlap match. We read the text of word/header*.xml and footer*.xml, replacing PAGE, NUMPAGES and SECTIONPAGES fields with a digits pattern, along with sectPr w:pgMar header and footer distances. A line in a band whose normalised text matches a header or footer part becomes header_footer.

(iii) Untagged and no DOCX. A text line lying wholly within a band becomes header_footer if either:
- its text, normalised (whitespace collapsed, digit runs including Devanagari digits replaced by #), repeats at the same band position (within 0.5 cm) on at least 50% of pages and at least 2 pages; or
- it matches the page-number pattern set. That set covers 'N', '- N -', 'Page N', 'Page N of M', 'N/M', roman numerals, Devanagari and Tamil digits, and 'पृष्ठ N'.
Any other text in a band is unclassified.

(iv) Overlay. Chars inside bboxes recorded by our own assembly become overlay.

3. Margin and size checks use the labels:
- Margins: the per-page minimum and maximum of body chars only, compared with margins_cm. Body text inside a margin fails, naming the page and a text sample. Unclassified band text is amber when it is a single line under 12 words that doesn't repeat and isn't a sentence fragment that continues into the body. Otherwise it fails. Amber is never 'met' for the gate: it shows as advisory and doesn't block.
- Headers and footers: a separate checklist item. Where header_footer_min_cm is set, each header/footer line must be at least that far from the edge, or the item is unmet. Header/footer lines must also not overlap body bboxes.
- Font: header and footer chars are font-checked too. If mandate_scope is 'all_pages' they must use the mandated font M. If it is 'body', M or overlay_fonts is allowed.
- Body size and line spacing are computed from body chars only. Header and footer sizes are reported as info.

4. Script attribution (replaces round 5's per-char rule). We use fontTools.unicodedata.script_extension (UAX #24 Script_Extensions).
- A run is a maximal sequence of chars on one line with the same base fontname and x-gaps no larger than 1.5 x the space width.
- Each char's script set is its Script_Extensions. Chars whose set is only Zyyy (Common) or Zinh (Inherited) are neutral.
- For non-neutral chars, the allowed fonts are the union over scripts in its Script_Extensions: Latn maps to M's PostScript names, and any other script maps to its script_fonts list. So the danda (Deva, Beng, ...) passes in any of those scripts' fonts.
- A neutral char takes the strong script of its run: the nearest preceding strong char, else the nearest following one. If the run has none, it takes the strong script of the adjacent runs on the same line. Its font must then be allowed for that script. So spaces, commas, full stops, hyphens, brackets and Western digits inside a Hindi run may be in Nirmala UI or Mangal.
- A neutral-only line with no strong neighbour is accepted if its font is M. If its font is a script font, it is amber with the page named.
- Glyphs whose text is multi-codepoint (conjuncts) take the script of their first strong codepoint.
- Glyphs with empty, zero-width or private-use text from a font listed in some script_fonts entry belong to the run they sit in. They pass if that run's script allows the font. They are counted for the 'no copyable text' info line, and if they exceed 5% of a page's script glyphs, the text-layer item is amber.
- The same glyphs from any other font fail. The exception is the round 5 symbol-font bullet rule.
- A strong Latin char in a non-M font always fails. So an English sentence in Nirmala UI fails on its own page.

5. Assembly is as in round 5: the Word PDF's content streams are copied byte-identical, and pikepdf overlays add numbers, the index, bookmarks, splits and page replacement. Before stamping:
- If page-number-pattern header_footer lines exist on at least 80% of pages, 'already numbered' defaults on and the sequence is verified.
- Otherwise the stamp position is chosen in the bottom band so that it overlaps no body or header_footer bbox and respects header_footer_min_cm. If no such position exists, stamping is refused with the reason.
- mandate_scope 'all_pages' still refuses our stamping (number in Word) and sends the index out as a DOCX round-trip.

6. Post-assembly re-verification runs steps 2-4 on the whole bundle:
- Recorded overlay bboxes are excluded from the body margin, size and spacing checks.
- Overlay chars are checked separately: overlay_fonts only, inside a band, header_footer_min_cm respected, and no overlap with body or header_footer chars.
- A font outside the body allow-lists and the overlay list fails.
- Body pages must reproduce the same pre-assembly results.

7. The gate (409 court_format_unmet), deviations, the licence-gated org fonts, the no-mandate DOCX path, OCR, legacy Hindi conversion and profile pinning are all unchanged from round 5. There is no AI anywhere in this pipeline.

### Where it is built

Extend:
- app/services/pdf_format_checks.py: region classifier (tagged, DOCX, repetition/pattern, overlay), run-based script attribution, and header/footer and amber reporting.
- app/services/bundle_service.py: overlay placement and collision avoidance, auto 'already numbered', post-assembly scoped verification.
- app/services/format_checks.py: read the DOCX header/footer parts and the pgMar header/footer distances.
- app/data/court_profiles/*.json and schema.json: header_footer_min_cm with its source and reviewer.
- scripts/check_court_profiles.py.
- frontend/src/app/studio/bundle/page.tsx: the header/footer checklist item, amber rows, auto-toggle notice, and the bilingual font lines, with Hindi and Tamil strings.

New dependency: pdfplumber>=0.11, for marked-content tags on chars. fontTools is already used.

New fixtures:
- tests/fixtures/word_exports/: golden PDFs exported once by our team from Microsoft Word 365 on a licensed Windows machine. They are synthetic pleadings with no client data: tagged and untagged, with running head and footer page numbers, and Hindi+English. They are documents carrying font subsets under the fonts' own embedding permission, like any PDF a firm files, and no font file is extracted or committed. A README records the Word build and export settings.
- tests/fixtures/builders/: runtime generators for the synthetic cases (LibreOffice in the render image for shaped Devanagari; pikepdf for artifact tags and ToUnicode edits).

No migration change beyond round 5's 017.

### Why current tools fail and this won't

Global AI tools stop at drafting and don't know Indian registry formatting directions. Indian e-filing vendors and DTP shops check by eye, so rejections come after upload. Generic PDF preflight tools either flag every header as a margin breach or skip margins altogether, and they treat any non-mandated font as a failure, so they break on bilingual pleadings. Our checks model how Word lays out a page:
- Word's own pagination artifacts, its header and footer parts, and repeating band text are recognised and checked under their own rule, so body margins are measured only on body text.
- Neutral characters and conjuncts inside Hindi runs are attributed by Unicode Script_Extensions and their run. An English sentence in a Hindi font is still caught.
- Our stamps are checked only against their own rules.

We prove this on real Word exports, not only on our own renderer's output. So a correctly formatted Supreme Court, Delhi HC or Bombay HC filing reaches 'met' with no deviation, and a real breach is still named by page and text.

### Safeguards

Everything runs on our server with no AI, under org RLS. No font file is uploaded on the default path, and the golden fixtures contain no extracted font files. Amber findings are advisory and are never reported as 'met'. Unclassified text in a margin is never silently passed. Pagination tags can exclude text only inside the header and footer bands, so marking body text as an artifact can't evade the checks. Only an associate, partner or owner can accept a deviation, with a reason; it is audit-logged and listed to the final approver. The body content of the Word PDF is never altered. We never handle portal credentials, and court rules are cited with a reviewer and pinned per bundle.

### How the panel's objections were answered

Objections 1 and 2: Word's headers, footers and page numbers sit inside the margins and would fail the margin check, and our own stamps would too.
- Every char is now labelled body, header_footer or overlay before any margin or size check (step 2).
- header_footer comes from Word's tagged /Artifact /Pagination marked content, which the help panel's 'Document structure tags' setting produces. Failing that, it comes from the supplied DOCX's header/footer parts. Failing both, it comes from text in the top and bottom bands that repeats on at least half the pages or matches a page-number pattern.
- Body margins are measured only on body chars.
- Header and footer lines get their own checklist item, checked against a new sourced profile field, header_footer_min_cm. They are font-checked per mandate_scope.
- Our overlay bboxes are left out of the post-assembly body margin, size and spacing checks and verified against their own rules (step 6).
- Pagination tags outside the bands don't exempt text, so the fix can't hide breaches.
- On the fixture objection: tests cover tagged, untagged and DOCX-classified footers (test_word_footer_tagged_passes_margins, _untagged_repetition, _docx_parts), real breaches (test_margin_breach_still_fails), stamped bundles (test_assembled_bundle_with_stamps_passes), and real Word 365 exports (test_golden_word_exports).

Objection 3: neutral characters and conjuncts in bilingual pleadings.
- Script is resolved with UAX #24 Script_Extensions. Common and Inherited chars take the strong script of their run, then of adjacent runs (step 4), so neutrals inside a Hindi run may use that script's script_fonts.
- Multi-codepoint glyphs take their first strong codepoint. Empty or private-use glyphs from an allowed script font belong to their run, and they are counted and reported as a searchability info or amber.
- Strong Latin chars must always be in M.
- test_bilingual_neutrals_and_conjuncts uses shaped output with neutrals in the Devanagari font, conjuncts and edited ToUnicode entries, plus the golden Word bilingual export. test_bilingual_latin_in_script_font_fails proves that an English sentence in Nirmala UI fails.

### Acceptance tests

- tests/test_bundles.py::test_word_footer_tagged_passes_margins: a 14 pt, 1.5-spaced fixture with a 2.5 cm bottom margin. On every page a footer 'Page N of 40' sits at 1.25 cm from the edge inside /Artifact <</Type /Pagination /Subtype /Footer>>, with a running head inside /Subtype /Header. Margins are met, header_footer is met and lists both lines with source 'tagged', body size and spacing are met, and build returns 200 with no deviation.
- test_word_footer_untagged_repetition: the same fixture without tags. The cause-title running head, 'Advocate for the Petitioner' and the page numbers are classified by repetition and pattern, and margins are met. A 1-page variant with only 'Page 1' passes by pattern. A 1-page variant with 'Annexure P-2' in the band is amber, and the build is not blocked.
- test_word_footer_docx_parts: with the matching DOCX supplied, footer lines are classified from footer1.xml (the PAGE field becomes the digits pattern), with source 'docx'.
- test_margin_breach_still_fails: a body paragraph continuing into the bottom band on page 5 (a multi-line, non-repeating sentence) fails margins with page 5 and a text sample. A Pagination artifact placed mid-page is not excluded and is measured as body. A footer at 0.5 cm under a profile with header_footer_min_cm 1.0 makes the header_footer item unmet and build returns 409.
- test_golden_word_exports: every PDF in tests/fixtures/word_exports/ (real Word 365 exports, tagged and untagged, Supreme Court and Delhi HC layouts, numbered in Word, with running heads) gives margins met, mandated font met, body size met, and spacing met or amber within tolerance, under its profile, with no deviation.
- test_assembled_bundle_with_stamps_passes: a body numbered without Word gets our stamped numbers, and post-assembly verification passes. Overlay chars are excluded from body margin and size, and are checked for overlay font, band position and header_footer_min_cm. A stamp forced to overlap a Word footer is refused before stamping. A body already numbered in Word on 38 of 40 pages switches 'already numbered' on, and a gap at page 9 is flagged.
- test_bilingual_neutrals_and_conjuncts: a LibreOffice-shaped fixture has Hindi runs whose spaces, commas, full stops, hyphens, brackets, Western digits and danda are in a Noto Serif Devanagari stand-in renamed at run time to NirmalaUI. Its conjuncts map to multi-codepoint text, and 3 glyphs are edited by pikepdf to empty ToUnicode and 2 to private-use text. The 'Mandated font' gate is met and the no-copyable-text info lists 5 glyphs. The golden Word bilingual export passes too.
- test_bilingual_latin_in_script_font_fails: a full English sentence set in the NirmalaUI stand-in on page 9 fails 'Mandated font' with page 9 and the sentence sample. A line '12, 13' alone in the Devanagari font with no strong neighbour is amber. Empty-text glyphs from an unlisted font (Helvetica stand-in) fail.
- Carried over from round 5: test_word_export_pdf_meets_mandate (body streams byte-identical, no LibreOffice), test_word_export_wrong_font_pages, test_word_export_size_spacing_margins (now on body-labelled chars), test_unembedded_or_no_tounicode_fails, test_all_pages_scope_index_roundtrip (header and footer chars must use M under all_pages), test_replace_page_word_pdf, test_org_font_licence_refused, test_post_assembly_allowlist, test_profile_integrity (with header_footer_min_cm), and the round 3 and 4 suites including test_deviation_acceptance and the frontend build with Hindi and Tamil strings.

### Reviewers' minor notes

- The amber exemption for unclassified band text ('a single line under 12 words that doesn't repeat and isn't a sentence fragment that continues into the body') is not defined in code terms. The most common real filing error is a Word bottom margin set smaller than the court's rule. That puts each page's last body line inside the band, with different text on every page, so nothing repeats. Short paragraph-final lines would then come out amber page by page instead of failing. Define 'continues into the body' deterministically: the band line is in the body font and size and sits within 1.5x the body line pitch of the body line above it. Such a line is body and fails. Add a test where the bottom margin is 1.5 cm against a 2 cm rule and the last lines are short, and assert that margins fail.
- Joining the pikepdf marked-content walk to pdfplumber chars 'in stream order' is fragile when text sits inside Form XObjects or one TJ draws many glyphs. Assert that the walk and the char list agree on glyph counts per page. When they don't, fall back to the untagged path (iii) and note it in the report.
- The bands are only top and bottom. If a profile prescribes side margins and a stamp, line numbers or a marginal 'Annexure' label sits in a side margin, it gets measured as body and fails. Say so explicitly, or add left and right bands for unclassified text with the same amber/fail rule.
- The rule that a single unclassified margin line is amber (under 12 words, not repeating, not a 'sentence fragment that continues into the body') needs a precise definition and a test. One case must be covered: a short final line of a paragraph that Word pushed into the bottom margin is a real breach, and it must fail. It should not show as an advisory amber that lets the build through.
- Migration numbering clashes across proposals: P02 and P08 both claim 014, and this proposal relies on 017. Allocate migration numbers centrally before building so the Supabase versions don't collide.
- Golden fixtures: the README should record each embedded font's fsType embedding permission alongside the Word build. That backs up the statement that no extracted font file is committed.
- Joining pikepdf text-show operators to pdfplumber chars in stream order only works if you count glyphs per operator from each font's encoding (2-byte CIDs for Identity-H, 1-byte for simple fonts). Add a fixture with mixed simple and CID fonts on one page, and fall back to source (iii) for any page where the counts disagree. Never guess an alignment.
- Word puts watermarks ('DRAFT', 'CONFIDENTIAL') in the header part, usually in a non-mandated font, and draws them mid-page. Under the bands rule they become body text and fail the font check. That is probably the right outcome for a filing copy, but the message should say 'header-part watermark: remove it in Word', not 'English sentence in wrong font'.
- Word's 'Different first page' and 'Different odd and even' settings split a header into 2-3 variants, so each variant repeats on under 50% of pages. Group repetition by odd/even page and leave out page 1 before applying the 50% rule. Otherwise untagged exports go amber or red for no reason.
- A run currently breaks on any change of base fontname. A space Word sets in the Latin font between two Hindi words is then its own neutral-only run, and its script falls to the adjacent runs. Add a fixture for that case: Hindi word, Times New Roman space, Hindi word.
- Pin pdfplumber to a tested minor version (for example >=0.11,<0.12). Char 'tag' and 'mcid' are recent additions, and a later release could change their semantics.

