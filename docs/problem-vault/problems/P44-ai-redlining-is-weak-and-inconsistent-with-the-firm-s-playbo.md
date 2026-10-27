# P44. AI redlining is weak and inconsistent with the firm's playbook, so redline rounds and re-checking continue

**Severity:** high · **Size:** big · **Region:** Global

**Who has it:** Associates and partners doing commercial work at Indian and global firms; in-house counsel

## What goes wrong

Negotiation runs many redline rounds by email, and different associates accept different positions on the same clause (liability cap, indemnity, governing law and seat, non-compete, payment terms). AI tools insert standard text instead of the nuanced change the playbook calls for and handle formatted tracked changes poorly, so lawyers redo the redline. Foreign governing law or unusual seats slip through under time pressure.

## Evidence of scale

- Vals Legal AI Report (VLAIR): on redlining the lawyer baseline (79.7%) beat every AI tool (Harvey 65.0%/59.4%, Vincent AI 53.6%); tools struggled with formatted redlines and inserted standard text. ([source](https://www.vals.ai/vlair))
- LegalOn 2025: 79% cite time savings; many want pre-built playbooks or to turn their own into AI review. ([source](https://www.legalontech.com/resources/2025-state-of-contracting))
- Stanford RegLab/HAI: purpose-built legal AI research tools hallucinated on more than 17% (Lexis+ AI) and 34% (Westlaw) of queries, so output must be re-verified. ([source](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries))

## Why current tools don't solve it

Harvey and Vincent AI score below lawyers on redlining; CoCounsel wasn't tested. Spellbook and LegalOn apply US/UK-tuned playbooks without Indian fallbacks (s.27 non-competes, s.74 liquidated damages, stamp-duty-sensitive clauses, seat vs venue, PASL on foreign seats). None verifies each suggested change quotes the exact source clause or tracks which playbook positions each reviewer accepted.

## Panel verdict

**Status:** solved (round 1)

**Effort:** L

### What software can fix

Making every redline follow the firm's or legal team's own written positions, the same way every time: (1) the playbook is data the partners write and approve: preferred clause text, ordered fallbacks and walk-away for each clause topic, plus machine-checkable rules; (2) the inserted wording is the playbook's approved text, copied character for character, never text the model writes; (3) every suggested change quotes the counterparty clause it touches, and that quote is checked; (4) proper Word tracked changes are produced and read; (5) each reviewer's accept/reject decision on each position is recorded, so inconsistent reviewers show up. Indian points ship as a default pack: s.27 Contract Act non-competes, s.74 liquidated damages, seat vs venue, foreign seat/law for two Indian parties (PASL), stamp-duty-sensitive clauses, and indemnity vs cap carve-outs.

### What it can't fix

Commercial judgment on which fallback to concede in a live negotiation, and the counterparty's leverage. The quality of a firm's own playbook: we ship a default Indian pack, but a weak playbook produces consistent weak redlines. Clauses on topics the playbook doesn't cover still need a lawyer; we flag them rather than invent a position. Complex formatting such as tables inside tracked changes, moved-text markup and comments threads gets a best-effort round trip; the plain-text clause diff stays authoritative.

### What the user sees

A Playbooks page (/playbooks): a list of clause topics (limitation of liability, indemnity, governing law, seat, non-compete, payment terms, termination, assignment, confidentiality term, IP, data protection, stamp duty and costs). For each topic: preferred text, Fallback 1, Fallback 2, walk-away, and rules in plain form ('cap must not exceed 1x annual fees', 'governing law must be India', 'seat must be one of Mumbai, Delhi, Bengaluru', 'payment within 45 days or less'). Partners edit; a second senior approves each version, and the version number and approver are shown. In Studio > Redline, after uploading the counterparty's paper (PDF, DOCX or a DOCX with their tracked changes), the lawyer sees each clause with a badge: Matches preferred / Within Fallback 1 / Within Fallback 2 / Breaches walk-away / Not in playbook. Each suggested change shows the counterparty quote (a green tick means it was found in the document), the playbook text that would replace it, and why (the rule that fired, for example 'cap = 3x fees > 1x'). Buttons: Accept, Use other fallback, Reject, Escalate to partner. 'Download tracked-changes DOCX' produces a Word file with real insertions and deletions authored by the reviewer's name. A Consistency report (owners/partners) shows, for each position, how often each reviewer conceded it, for example 'Liability cap Fallback 2 accepted 9/10 by A, 1/12 by B'.

### What the system does

1. New migration 014_playbooks.sql: playbooks(id, org_id, name, contract_type, version, status draft|approved, approved_by, approved_at), playbook_positions(playbook_id, topic, preferred_text, fallbacks jsonb [{rank, text, variables}], walk_away text, rules jsonb), redline_decisions(org_id, document_id, playbook_version, topic, position_suggested, decision accepted|other_fallback|rejected|escalated, reviewer_id, decided_at). RLS like review_grids; approval goes through the existing approval_requests maker-checker (new action 'approve_playbook'), and editing an approved version creates a new draft version (the same lapse-on-change pattern as stamp_draft_approval). 2. Ingest: DOCX with tracked changes is parsed in new services/docx_redline.py (python-docx plus raw OOXML: w:ins, w:del, w:moveFrom/w:moveTo) into an 'original' and a 'revised' text, so contract_diff_service.compare runs on the real before/after instead of on flattened text. 3. Clause-to-topic mapping: deterministic keyword and heading rules first (headings such as 'Limitation of Liability' or 'Governing Law'); Claude (PII-masked through PiiMasker, playbook in a cached system block via prompt_engine.build_system) maps only the clauses left over, returning topic plus a verbatim quote of the clause. The quote must pass evidence_service.quote_found or the mapping is dropped and the clause is marked 'Not in playbook - lawyer review'. 4. Rule evaluation is deterministic code (services/playbook_rules.py): the existing governing_law.detect for law, seat and courts; regexes for money and multiples ('three times the fees', 'INR 50,00,000', 'aggregate fees paid in the preceding 12 months'); day counts for payment and notice; non-compete after term (post-termination restraint, flagged under s.27); a liquidated damages or penalty clause, flagged under s.74 with a note that compensation must be reasonable; arbitration seat outside India with both parties Indian (PASL flag); indemnity outside the cap. If a rule can't parse its input, the result is 'cannot evaluate', never a pass. 5. Position selection: the highest-ranked playbook text whose rules the counterparty clause already meets is 'within'. Otherwise the suggestion is the preferred text, or the next fallback the reviewer picks. The replacement is the playbook text with only its declared variables filled (party names, amounts from the deal sheet); a test asserts the replacement equals the template after variable substitution, byte for byte. Free-form AI edits are allowed only as a separate 'AI suggestion (not playbook)' card that needs explicit lawyer acceptance and is tagged in the export. 6. Export: services/docx_redline.py writes w:del (original runs) and w:ins (replacement) produced from a word-level diff-match-patch of the original clause against the replacement, with w:author set to the reviewer and w:date set to now; risk_delta still comes from contract_diff_service's deterministic score. 7. Every decision writes redline_decisions and an audit_logs row; the consistency report is a SQL aggregate. 8. Citations in explanations (s.27, s.74, Interplay) go through citation_service as usual. 9. Nothing goes to the counterparty from the system: the lawyer downloads the DOCX and sends it.

### Where it is built

Extend app/services/contract_diff_service.py (alignment, inline diff, risk score), app/services/governing_law.py, app/services/evidence_service.quote_found, app/services/prompt_engine.build_system (cached playbook block), app/services/anthropic_service.REDLINE_PROMPT (add playbook-mapping prompt), app/routers/documents.py /compare (add playbook_id), approval_requests in supabase/migrations/013. New: supabase/migrations/014_playbooks.sql, app/services/playbook_service.py, app/services/playbook_rules.py, app/services/docx_redline.py, app/routers/playbooks.py, data/playbooks/india_default.json, frontend/src/app/playbooks/page.tsx, a Redline tab update in frontend/src/app/studio, tests/test_playbooks.py, tests/test_docx_redline.py, evals/redlines/ (20 Indian MSAs/NDAs with expected badges).

### Why current tools fail and this won't

On the VLAIR redlining task, Harvey and Vincent scored below lawyers because the model writes standard text and loses formatted redlines. Here the model never writes the inserted text: it only maps clauses to topics, the replacement is the firm's approved wording, rule checks are code, and tracked changes are parsed and written as real OOXML. Spellbook and LegalOn apply US/UK-tuned playbooks; ours ships Indian defaults (s.27, s.74, seat vs venue, PASL, stamp) and lets the firm override them. None of them records which reviewer conceded which position; we do, and that is what fixes inconsistency between associates.

### Safeguards

Text goes through PiiMasker before Claude; the playbook is firm work product, kept in the org's RLS scope and never in the shared corpus. Playbook versions need two seniors (maker-checker, existing approval_requests). Nothing is sent to the counterparty by the system; the lawyer downloads and sends. Inserted text is human-approved playbook language, and AI-written alternatives are labelled. Citations go through citation_service, and verify_output_safety applies to explanations. Every decision is audit-logged. The document text is treated as data (prompt-injection line already in the prompts).

### Acceptance tests

- tests/test_playbook_rules.py: a fixture clause 'aggregate liability shall not exceed three (3) times the Fees paid in the preceding twelve months' against a rule cap<=1x gives a breach with parsed multiple 3; 'shall not exceed the Fees paid' gives within preferred; an unparseable cap gives 'cannot evaluate' and never 'within'.
- Governing law 'laws of England and Wales' with seat London, both parties with Indian addresses: the walk-away rule fires even when a mocked Claude mapping labels the clause acceptable (deterministic rule wins).
- A non-compete clause 'for 24 months after termination' fires the s.27 flag; the same clause limited to the term does not.
- The replacement text for an accepted Fallback 1 equals playbook fallback text with variables substituted (byte equality); a mocked model response that alters one word of the fallback is rejected.
- A mocked Claude topic mapping whose quote isn't in the document is dropped and the clause shows 'Not in playbook'; the count of dropped mappings is returned.
- tests/test_docx_redline.py: export a redline, re-open it with python-docx, count w:ins and w:del elements equal to the changed clauses, w:author equals the reviewer's name, and accepting all changes (programmatically removing w:del and unwrapping w:ins) yields text identical to the expected revised contract.
- Parse fixtures/counterparty_tracked.docx (made in Word with insertions, deletions and a move): the reconstructed original and revised texts match hand-made expected files.
- DB test: an associate cannot set playbooks.status='approved'; approval needs a second senior via approval_requests; editing an approved version's text produces a new draft version and leaves the old one approved.
- Consistency report SQL on seeded redline_decisions returns per-reviewer acceptance rates for each topic/position.
- evals/redlines: on 20 labelled contracts, topic mapping precision >= 0.9 and zero inserted texts that differ from the playbook.

### Reviewers' minor notes

- PASL Wind (2021) held that two Indian parties may choose a foreign seat. The flag text must say that is permitted and explain the consequences (Part II enforcement, s.9 interim relief available), not imply that it is invalid. A walk-away rule is the firm's policy, not the law.
- The s.74 note should reflect Kailash Nath: the stated sum is a ceiling and reasonable compensation is awarded. It's informational, not 'penalty void'.
- w:author with the reviewer's real name leaks the identity to the counterparty. Allow a firm-level author name option.
- Migration 014 collision.
- The exported tracked-changes DOCX goes to the counterparty. Make sure internal rule explanations, the badges and 'why' notes are not embedded as w:comment or hidden text, and that docProps or custom XML do not carry playbook names. Add a test that the export contains no comments part.
- The PASL default should be informational (two Indian parties may choose a foreign seat), while a foreign substantive governing law for two Indian parties stays walk-away. Keep the two rules separate in the pack.
- The 'PASL flag' label must be legally accurate. PASL Wind Solutions (2021) allows two Indian parties to choose a foreign seat. The concern is foreign substantive governing law between Indian parties and Part II enforcement. Word the default rule and its explanation so they don't misstate PASL.
- risk_delta is computed deterministically from Claude's per-clause severities, so it is not model-free. Don't present it as deterministic.
- document_service has no DOCX support today. docx_redline.py must also feed the normal upload path.
- Name SpotDraft VerifAI and LegalOn as near incumbents. The differentiators are byte-exact playbook insertion and the per-reviewer consistency report.
- Migration 014 collides.

