# P28. Contradictions across FIR, s.161/180 statements and depositions are found by hand, late or never

**Severity:** high · **Size:** big · **Region:** India (also global)

**Who has it:** Criminal defence and prosecution advocates, civil trial lawyers, US/UK litigators doing deposition prep

## What goes wrong

Criminal trials and civil evidence turn on material omissions and contradictions between a witness's earlier statements (FIR, s.161 CrPC/s.180 BNSS, s.164) and court testimony, or between testimony and documents. Counsel must confront the witness with the exact passage. Statements run to hundreds of pages, often vernacular, scanned or handwritten, and juniors cross-check the night before. Missed contradictions lose acquittals; overstated ones damage credibility.

## Evidence of scale

- Vinobhai v. State of Kerala (2025 INSC 1191): SC acquitted a murder convict who had served over 12 years, finding 'material omissions which amount to contradiction'. ([source](https://www.verdictum.in/court-updates/supreme-court/vinobhai-v-state-of-kerala-2025-insc-1191-murder-convict-material-omissions-contradiction-1566392))
- SC (May 2024) acquitted in a s.302/149 IPC case because material omissions affected witness reliability; the s.162(1) CrPC procedure must be followed. ([source](https://www.scconline.com/blog/post/2024/05/28/sc-acquits-offence-302-149-on-material-omissions-affecting-reliability-of-witnesses-legal-news/))
- Darshan Singh v. State of Punjab (2024 INSC 19): testimony implicating an accused not named in s.161 statements cannot be relied upon. ([source](https://www.verdictum.in/court-updates/supreme-court/darshan-singh-v-state-of-punjab-2024-insc-19-prosecution-witnesss-161-crpc-statement-1513633))
- NJDG (Sep 2024): 29,20,033 district court cases delayed for witness-related reasons. ([source](https://barandbench.com/news/66-lakh-cases-district-courts-delayed-unavailability-lawyers))

## Why current tools don't solve it

CoCounsel and Harvey offer English deposition prep for US-style transcripts; they don't produce contradiction findings with verified verbatim quotes across vernacular FIRs, s.161 statements and depositions, and can paraphrase or invent a quote, fatal in cross-examination. Indian research tools have no evidence analysis.

## Panel verdict

**Status:** solved (round 1)

**Effort:** M

### What software can fix

Producing a cross-examination sheet per witness: contradictions and material omissions between the FIR, s.161 CrPC / s.180 BNSS statements, s.164 / s.183 statements and the deposition, each with exact verified quotes and page/line references in the original language, ready to confront the witness, extending the existing contradiction analyzer.

### What it can't fix

Deciding whether an omission is 'material' in law (the lawyer decides), handwritten statements Tesseract can't read reliably, and translation accuracy for the lawyer's own reading (P23's area). Courtroom use of the sheet is the lawyer's.

### What the user sees

In /studio Evidence: create a witness, attach their statements by type and date (FIR, s.161/180, s.164/183, chief, cross), in any supported language. The result is a table by topic: what the witness said in court (quote, page/line), what they said before (quote, page/line, statement type), finding type (contradiction / omission candidate / improvement), and a confrontation note. Omission candidates are labelled 'not found in the earlier statement: confirm' with the search terms used. Quotes are in the original script with a translation alongside. Export to DOCX for the brief.

### What the system does

1. Statement types and dates added to EvidenceSource; the deposition is parsed into numbered lines (existing parse_statement_text).
2. OCR for scanned vernacular statements via Tesseract Indic packs (vision fallback per OCR_VISION_FALLBACK setting); per-page confidence shown.
3. Claude (PII-masked, cached system prompt) returns contradictions and omission candidates with quotes in the original language.
4. Verification, deterministic: both quotes of a contradiction must pass quote_match against their source (invariant 6); for an omission, the deposition quote must pass, and the earlier statement must NOT contain the claimed fact's key terms (normalized search including common transliterations and the model-supplied keywords, all shown); if any key term is found the candidate is downgraded to 'check'. Unverified findings discarded and counted.
5. Severity computed as today (SEVERITY_SCORE).
6. Export through drafting_engine.to_docx, marked unreviewed until a lawyer approves.

### Where it is built

app/services/evidence_service.py (quote_match, verify_findings, parse_statement_text), app/routers/evidence.py (new witness grouping), app/models/analysis.py (ContradictionFinding gains finding_type, statement_type, page_line, search_terms), ocr_service.py language packs, drafting_engine.to_docx; migration 017 adds witnesses and witness_statements; Studio UI.

### Why current tools fail and this won't

CoCounsel and Harvey do English US-style deposition prep and can paraphrase or invent a quote, which is fatal in cross-examination; Indian research tools have no evidence analysis. Ours already discards any finding whose quotes are not in the sources, and extends that to omissions with a negative check, in the original vernacular text.

### Safeguards

Statements are privileged and contain sensitive personal data: PII-masked before Claude (names kept per guardrails), OCR vision fallback honoured per firm setting, results internal, export marked unreviewed. Case memory under RLS.

### Acceptance tests

- tests/test_witness.py: a fixture witness (English FIR, Hindi s.161 statement, English deposition) with 5 planted contradictions and 3 planted omissions; a mocked model returning those plus 4 fabricated findings yields exactly the 8 real ones and discarded_unverified=4.
- test_omission_negative_check: an 'omission' whose key term appears in the earlier statement is downgraded to 'check'.
- test_devanagari_quote_match: a Hindi quote with matra and whitespace variations still matches via normalization; a quote with a changed word does not reach 85%.
- Existing evidence tests keep passing (invariant 6).
- Eval: scripts/run_evals.py gains 5 witness cases; with the real model, planted-finding recall at least 75% and zero unverified quotes in output.

### Reviewers' minor notes

- Label the translation shown beside each original-script quote as an unverified AI translation. Only the original quote is checked, and the lawyer confronts the witness with the original.
- Note on the sheet that statements under s.180 BNSS / s.161 CrPC can be used only to contradict the witness (s.148 BSA / s.162 CrPC), so omission candidates are prompts for the lawyer, not findings.
- In sexual-offence, POCSO and JJ matters, mask the victim's and child's names before Claude (s.72 BNS / s.23 POCSO / s.74 JJ Act sensitivity), even though names are normally kept. Force the OCR vision fallback off for these matter types.
- The export should note the s.181 BNSS / s.162 CrPC limit (statements usable only to contradict under s.148 BSA), so juniors don't treat the sheet as substantive evidence.
- evidence_service._normalize won't merge different matras or nukta forms. Add NFC normalization and a small Devanagari canonicalization (nukta, chandrabindu/anusvara) and test it, or the Hindi matching test may fail.
- The 'changed word below 85%' test only holds if the changed word is near the middle of a short quote. Fix the fixture so it is deterministic.

