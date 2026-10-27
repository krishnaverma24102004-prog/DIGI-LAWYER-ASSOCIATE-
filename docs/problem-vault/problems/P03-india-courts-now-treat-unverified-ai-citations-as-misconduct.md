# P03. India: courts now treat unverified AI citations as misconduct, fake precedents are reaching Indian filings and orders, and practitioners have no cheap pre-filing check

**Severity:** critical · **Size:** big · **Region:** India

**Who has it:** Indian advocates at every level, especially solo and district-court practitioners and junior associates; litigants in person; in-house tax and insolvency teams; tribunals and the district judiciary

## What goes wrong

Indian advocates (often solos or juniors using free ChatGPT), tribunal members and trial judges are relying on SCC, AIR or INSC judgments that don't exist. The Supreme Court has declared 'zero tolerance', held that citing AI-generated precedents without verifying them is advocate misconduct, said a decision based on fake judgments is misconduct and not an error, and asked the BCI to frame norms. Benches have recorded matters where every precedent cited was non-existent, and the Bombay HC imposed costs on a litigant over one. Repealed IPC/CrPC/Evidence Act sections are also cited after the BNS/BNSS/BSA changeover. Verifying means searching SCC Online, Manupatra or Indian Kanoon one citation at a time, and many district-level advocates don't subscribe to the paid databases.

## Evidence of scale

- In Pooja Ramesh Singh v. J&K Bank (reported 2 July 2026) the SC said courts must take a zero-tolerance approach to AI-generated precedents cited without verification, held that an advocate citing them commits misconduct, and asked the BCI to frame norms. ([source](https://www.barandbench.com/news/litigation/supreme-court-declares-zero-tolerance-to-citing-fake-ai-generated-judgments-asks-bci-to-frame-norms))
- Pooja Ramesh Singh: the SC directed the Bar Council of India to form a committee to prescribe guiding principles and disciplinary action. ([source](https://www.freepressjournal.in/mumbai/supreme-court-declares-zero-tolerance-for-ai-generated-fake-legal-precedents-directs-bar-council-to-act))
- Pooja Ramesh Singh (Civil Appeal 11950/2025): the SC set aside NCLT and NCLAT orders influenced by several non-existent or AI-fabricated precedents and restored the Section 7 proceedings. ([source](https://desikaanoon.in/supreme-court-warns-courts-against-blind-reliance-on-ai-generated-case-law/))
- On 17 Feb 2026 a bench led by CJI Surya Kant called lawyers' unchecked AI drafting 'alarming'. In one matter before Justice Dipankar Datta none of the precedents cited existed; Justice Nagarathna flagged a fictitious case, 'Mercy vs Mankind'. ([source](https://organiser.org/2026/02/18/340579/bharat/precedents-cited-never-existed-supreme-court-flags-alarming-ai-use-in-court-filings/))
- Greenopolis Welfare Association v. Narender Singh (Delhi HC, 25 Sept 2025): the petition cited a non-existent case (Chitra Narain v. DDA) and quoted paras 73-74 of a 27-paragraph judgment; dismissed as withdrawn. ([source](https://lawbeat.in/amp/news-updates/delhi-high-court-allows-withdrawal-of-plea-citing-non-existent-judgments-and-ai-generated-content-1532103))
- Gummadi Usha Rani v. Sure Mallikarjuna Rao (SC order 27 Feb 2026): a trial court relied on four AI-generated judgments; the SC said a decision based on them 'would be a misconduct' and issued notice to the AG, SG and BCI. ([source](https://www.verdictum.in/pdf_upload/gummadi-usha-rani-anr--1772891.pdf))
- Bombay HC (Justice MM Sathaye) ordered Heart & Soul Entertainment to pay Rs 50,000 costs, citing its reliance on a non-existent AI-generated judgment. ([source](https://moneylife.in/article/fake-case-law-ai-submissions-bombay-hc-imposes-rs50000-cost-on-litigant/79395.html))
- Bombay HC imposed Rs 50,000 costs on a party-in-person for relying on a non-existent AI-generated judgment in written submissions (Jan 2026). ([source](https://www.freepressjournal.in/amp/mumbai/bombay-hc-fines-litigant-50000-for-citing-fake-ai-generated-judgment-in-written-submissions))
- Manupatra's sponsored article says a senior lawyer had to apologise in the SC because a rejoinder contained many fake cases. ([source](https://www.barandbench.com/law-firms/view-point/beyond-generic-ai-tools-built-for-the-law))
- As of June 2026 the BCI had issued no AI-specific rule for advocates; existing duties of confidentiality, competence, verification and candour apply. ([source](https://lawsikho.com/blog/ai-ethics-for-lawyers-in-india-bci-dpdp-privilege/))

## Why current tools don't solve it

Harvey (partnered with SAM) and CoCounsel are priced for large firms and built on US/UK law, not grounded in a complete index of SCC, AIR, INSC and High Court reporters. SCC Online, Manupatra and CaseMine AMICUS retrieve from their own corpora but don't audit a draft written elsewhere (an associate's draft, ChatGPT output, an opponent's filing). None checks citations against an authoritative index, flags repealed IPC/CrPC provisions, or confirms a quoted paragraph exists. Free ChatGPT verifies nothing. No tool produces a per-citation verification record an Indian advocate could show a bench as proof of due diligence.

## Panel verdict

**Status:** solved (round 4)

**Effort:** M

### What software can fix

A cheap, India-specific pre-filing check that knows Indian reporters (SCC, AIR, SCR, INSC, SCC OnLine, HC neutral citations) and checks transition-era code citations correctly. Red 'wrong code' is reserved for the matter's own charge, stated under a code that is wrong for the offence date. The cause title and prayer count as the matter's own charge even though they name the matter as 'State v. X'. Precedent discussion, dual 'IPC (now BNS)' citations and descriptions of what an FIR says never go red. The output is a per-citation due-diligence record the advocate can keep or show a bench. The target users are solos and district-court advocates without SCC or Manupatra.

### What it can't fix

We can't confirm an SCC or AIR page number, because they are proprietary with no open concordance. We say 'reporter page not checked; parties and year match <judgment>'.

Which procedural code governs a straddling matter is law to be argued (s.531 BNSS, s.170 BSA, divergent High Court views). We show it as a note; we don't decide it.

Cause-title and prayer detection uses headings and phrases. A pleading with no recognisable headings and no parties recorded on the matter falls back to phrase-only detection, and the record says 'own parties not identified; add them on the matter panel'.

Unusual drafting may be missed. It then gets an info note, never a false red.

The BCI's AI norms are still being framed, so the record is a diligence aid, not a certified compliance instrument. Judgments in no open index stay unverified until they are uploaded or attested (P02).

### What the user sees

'Check before filing' on /verify, plus the lawyer-side 'check this PDF' command on the firm's WhatsApp number. The ledger is plain English: green, amber and red as before.

The matter panel holds:
- the offence date (and an end date for continuing offences);
- the date the proceeding began, and its kind;
- charge or FIR sections;
- new: 'Parties in this matter' (for example State / Ramesh Kumar), prefilled from court_cases or detected from the document's cause title and confirmed by the lawyer.

The document view shades the parts the checker treated as the cause title and the prayer, so the lawyer can see why a section went red. A section mention in the cause title such as 'State v. Ramesh Kumar … u/s 302 IPC', in a 2024-offence matter, shows red: 'The cause title states the offence as s. 302 IPC, but the offence date is 3 Sept 2024: the offence provision is s. 103(1) BNS'.

The other labels are unchanged: precedent info, dual info or amber, FIR-description amber, procedural amber. A precedent that happens to share the client's name, but carries its own reporter citation, is labelled as a precedent. The record downloads with Hindi or English fixed labels.

### What the system does

1-3. Same engine (/citations/audits); deterministic reporters; migration 014 adds offence_date, offence_end_date, proceeding_instituted_on, proceeding_kind and charge_sections. NEW: it also adds own_parties jsonb ({side_a:[names], side_b:[names], source: court_case|manual|cause_title_confirmed}) to case_threads, with court_cases' petitioner and respondent used as the default. /verify accepts the same fields.

NEW 4a. segment_document(text) -> Structure is a pure function. Markers live in charge_phrases.yaml (checksummed). It finds:
- title_blocks: from the document start, and every later repeat (index pages, annexure covers), until the first body-start marker. The markers are 'MOST RESPECTFULLY SHOWETH', 'RESPECTFULLY SHEWETH', 'The humble application of', 'The applicant above-named', 'SYNOPSIS', 'INDEX', 'BRIEF FACTS', 'सविनय निवेदन है' or the first numbered paragraph. A repeat is recognised by a 'versus|v.|vs.|बनाम' line whose parties match own_parties.
- prayer_blocks: from 'PRAYER', 'प्रार्थना', 'It is therefore most respectfully prayed' or 'It is, therefore, prayed' until 'PLACE', 'DATE', 'Through', 'Advocate for', 'VERIFICATION', 'सत्यापन' or the end of the document.

NEW 4b. own_case(case_name_span, matter, structure) is a pure function. The parties are own_parties, or, if none is recorded, the parties parsed from the first title block's versus line (shown for confirmation). Names are normalised with P12's party_names classification, so generic litigants such as State, Union of India or the Government are ignored for matching. A span counts as the own case when its non-generic party tokens contain the own non-generic party (a full name, or a 2-token sub-name), AND the clause attaches no reporter or neutral citation, year bracket or 'reported in' to it. 'State v. Ramesh Kumar (2019) 3 SCC 100' is therefore a precedent even when our client is also a Ramesh Kumar.

NEW 4c. citation_role(mention, sentence, structure, matter) uses a new precedence order:
1. Position first. If the mention is inside a title_block or prayer_block:
   (i) the clause contains a foreign case reference (a case citation span, or a v.-name that is not own_case) -> precedent_context;
   (ii) a dual pattern -> dual;
   (iii) an 'FIR No.', 'Crime No.', 'Case Crime No.' or 'प्राथमिकी सं.' token on the same line or clause -> fir_description;
   (iv) otherwise -> charge_assertion.
2. Elsewhere, precedent_context. Own-case names are excluded from the v.-name marker. Forum self-references are excluded from 'the Court' markers: 'this Court', 'this Hon'ble Court', 'the Hon'ble Court below', 'the learned Trial Court' in a present or future-tense request ('may be pleased', 'pray'). The verb markers ('held', 'observed', 'it was laid down', 'in that case') still apply.
3. Then dual, then fir_description.
4. charge_assertion by charging phrase, or by a section recorded in matter.charge_sections.
5. other.

5. Transition rules (app/data/transition_rules.yaml, checksummed, lawyer-signed) and code_status are unchanged:
- substantive sections are keyed on offence_date: red only for charge_assertion in the wrong code; amber for a span over 1 July 2024, for fir_code_note and for a dual mismatch; info for precedent and other;
- procedure and evidence are never red, with the s.531 and s.170 notes;
- the s.479 BNSS exception;
- a recorded charge_sections data-entry check.

6. Only red wrong_code_for_date blocks the P02 filing copy, until edited or attested with a reason (for example, the charge sheet genuinely uses that code).

7. Catch-all format_unrecognised; bare case names resolved by name.

8. Metering through P19; Indian Kanoon spend through the P29 budget.

### Where it is built

Extend:
- app/services/citation_service.py (_CASE_PATTERNS, catch-all, case-citation spans reused by citation_role and own_case, the code_status hook)
- app/services/jurisdiction_service.py (P22 correspondence)
- migrations 005 case_threads and 011 court_cases (014 adds the date fields, charge_sections and own_parties)
- app/services/whatsapp_intake.py
- app/services/ocr_service.py and document_service.py (FIR 'u/s' extraction for confirmation)
- the P12 party_names classification (generic_litigant / common_name / distinctive, shared with P36's leak check)
- the P02 record PDF

New:
- app/services/document_structure.py (segment_document; shared with P18's own-cause-title exclusion)
- app/services/citation_role.py (own_case, citation_role)
- app/data/charge_phrases.yaml (charging phrases, title and prayer markers, forum self-references, in English and Hindi)
- app/services/transition_rules.py and app/data/transition_rules.yaml
- tests/fixtures/transition/ golden pleadings (bail application, discharge application, quashing petition) in English and Hindi

### Why current tools fail and this won't

Harvey and CoCounsel are grounded in US/UK law. SCC Online, Manupatra and CaseMine search their own databases but don't audit a draft written elsewhere or produce a per-citation record, and district advocates often don't subscribe. Free ChatGPT verifies nothing and routinely mixes IPC and BNSS.

A naive 'IPC after July 2024 = error' rule floods every criminal draft with false reds. A naive 'any v. name = precedent' rule misses the most important place a wrong code appears: the pleading's own cause title and prayer.

We read the document's structure first. We know which parties are ours, from the matter record or the confirmed cause title. So 'State v. Ramesh Kumar … u/s 302 IPC' in our own title is our charge, and 'Bachan Singh v. State of Punjab … s. 302 IPC' is a precedent. A record shown to a bench neither calls a correct precedent wrong nor misses a wrong charge. Checks run on open SC/HC data plus pay-per-call Indian Kanoon, so they cost paise per citation.

### Safeguards

Labels state exactly what was checked; an SCC or AIR page is never marked verified. Red is reserved for code-provable errors: a nonexistent section, or the matter's own charge (cause title, prayer, charging phrase or recorded charge) under the wrong code for the offence date. Precedent, dual and FIR-description mentions can't be red, by a tested precedence order. Own parties come from the matter record or are confirmed by the lawyer. The structure shading shows the lawyer what was treated as the title and prayer. Contested transitional questions are amber or info and never block. The rules and phrase files are lawyer-signed and checksummed. FIR extraction is lawyer-confirmed. Only citation strings leave the server for Indian Kanoon. Advocates keep responsibility for the filing (BCI duties of competence and candour). No scraping of SCC Online or Manupatra.

### How the panel's objections were answered

Objection: the cause-title rule could never fire, because any 'v.' name made a mention precedent_context first.

Fixed in three parts:
(1) A deterministic segment_document finds title blocks (including repeats) and prayer blocks from checksummed English and Hindi markers. Position is evaluated before precedent_context. Inside the title or prayer, a mention is charge_assertion unless the clause cites a different case (foreign case, giving precedent), is a dual form, or describes an FIR by number.
(2) own_case() identifies the document's own parties, from own_parties on the matter (defaulting to court_cases' parties) or from the first title block's versus line once the lawyer confirms it. It matches them with P12's party_names classification (generic litigants ignored) and excludes that case name from the v.-name precedent marker, the same exclusion P18 uses for an order's own cause title. A same-named case carrying a reporter citation is still a precedent.
(3) Forum self-references ('this Hon'ble Court may be pleased') no longer count as precedent markers.

Tests added exactly as requested: the cause title 'State v. Ramesh Kumar … u/s 302 IPC' is red; the prayer 'in State v. Ramesh Kumar, the applicant charged under s. 302 IPC' is red; 'In Bachan Singh v. State of Punjab … s. 302 IPC' stays info. Also added: the same-name precedent with a citation, an FIR number in the title, and the Hindi title.

### Acceptance tests

- Cause title: offence_date 2024-09-03, own_parties State / Ramesh Kumar, and a document starting 'IN THE COURT OF SESSIONS JUDGE … State v. Ramesh Kumar … u/s 302 IPC … MOST RESPECTFULLY SHOWETH' give red wrong_code_for_date suggesting s. 103(1) BNS
- Prayer naming the matter: 'PRAYER … in State v. Ramesh Kumar, the applicant charged under s. 302 IPC may be released on bail' gives red
- Cause title with no own_parties recorded: parties are detected from the versus line and shown for confirmation; the same cause-title mention is red
- Precedent stays info: 'In Bachan Singh v. State of Punjab, the Court, considering s. 302 IPC, held…' in the body gives precedent_context info
- Precedent inside the prayer: 'following Bachan Singh v. State of Punjab, s. 302 IPC' inside the prayer gives precedent_context (foreign case), not red
- Same-name precedent: own party Ramesh Kumar, body text 'In State v. Ramesh Kumar (2019) 3 SCC 100, s. 302 IPC was considered' gives precedent_context, because a reporter citation is attached
- Forum self-reference: 'this Hon'ble Court may be pleased to release the applicant charged under s. 302 IPC' in a body paragraph is charge_assertion (red), not precedent
- FIR in cause title: 'FIR No. 123/2024, u/s 420 IPC, P.S. Saket' in the title block of a 2024-offence matter gives amber fir_code_note, not red
- Dual in cause title: 'u/s 420 IPC (now s. 318(4) BNS)' in the title gives info
- Repeated cause title on an index page and an annexure cover: each title-block mention is evaluated, with one red per mention and no duplicates in the counter
- Correct code: a cause title 'State v. Ramesh Kumar … u/s 103(1) BNS' in a 2024-offence matter gives no flag
- Hindi: cause title 'राज्य बनाम रमेश कुमार … धारा 302 भा.दं.सं.' with prayer heading 'प्रार्थना' gives red in a 2024-offence matter; a Hindi precedent sentence is info
- Round-3 tests still pass: precedent info; dual info or amber; charge phrase inside a precedent is info; FIR description amber; recorded charge red; zero reds for the 30-page bail application with 25 IPC precedents; reverse direction (2023 offence, s. 103 BNS) red; straddling golden cases; continuing offence amber; amber and info don't block; checksum refusal; format_unrecognised; incident strings flagged; Hindi labels not passed through an LLM; Indian Kanoon budget
- charge_phrases.yaml with altered title, prayer or forum markers fails its checksum at load

### Reviewers' minor notes

- When police or the court have registered a post-July-2024 matter under IPC, the cause title has to match the court record, so the red flag will be correct but must be attested every time. Make 'title reproduces the court's registration' a preset attestation reason so this costs one click.
- Body-start markers should also include 'LIST OF DATES' and 'MEMO OF PARTIES' used in SLPs and High Court petitions. Otherwise the title block can run on into the synopsis.
- Migration number 014 is also claimed by P02, P36 and P08.
- The shading of the parts treated as title and prayer is essential. Also show it in the downloaded record, so a bench sees why a mention went red.
- Standard Delhi and UP cause titles put the FIR details on separate lines ('FIR No. 123/2024' / 'P.S. Saket' / 'U/s 302 IPC'). Rule (iii) only looks for an FIR token on the same line or clause, so a correctly reproduced FIR section would go red. Treat a contiguous FIR/PS/U/s field group in the title block as one clause, and add that fixture. Red stays attestable, but the 'never a false red' claim should match what is built.
- Where police registered a 2024 FIR under the IPC, the red message should say the pleading reproduces the FIR, not only that the provision is wrong, so the record shown to a bench reads fairly.
- Indian cause titles usually carry the FIR number on the same line as the sections ('FIR No. 123/2024 u/s 302/34 IPC, P.S. Saket'). Rule (iii) will therefore turn most cause-title mentions amber (fir_description), and red will mainly come from the prayer or a charging phrase. That is defensible, because it accurately describes what the FIR says, but the headline example will rarely fire in practice. Say so.
- own_case needs a full name or a 2-token sub-name, so single-token party names ('State v. Ramesh') fall through to precedent and info. That is a false negative, and safe.
- Migration 014 is also claimed by P02, P36 and P08. Coordinate the numbering.

