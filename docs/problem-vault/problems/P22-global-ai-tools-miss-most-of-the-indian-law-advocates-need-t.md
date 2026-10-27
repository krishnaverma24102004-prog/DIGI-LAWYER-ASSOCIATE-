# P22. Global AI tools miss most of the Indian law advocates need: trial courts, tribunals, state law and the IPC/CrPC to BNS/BNSS changeover

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Indian district-court and High Court litigators, criminal and tax practitioners, mid-size Indian firms

## What goes wrong

Harvey, CoCounsel, Lexis+ AI and Westlaw are built on US/UK law; Harvey's Indian users are top-tier firms. Most Indian matters run in district courts, tribunals and High Courts under state rent, stamp and land laws, and since 1 July 2024 under BNS/BNSS/BSA alongside IPC/CrPC for older offences, with High Courts diverging on straddling proceedings. General models default to IPC/CrPC sections, FIRs and charge sheets cite repealed provisions, and an advocate drafting a bail or cheque-bounce matter gets SC-level answers and fixes section numbers by hand.

## Evidence of scale

- Shardul Amarchand Mangaldas announced a firm-wide Harvey rollout across seven offices on 3 June 2025. ([source](https://www.amsshardul.com/sam-leads-indian-legal-market-with-rollout-of-harvey-ai/))
- Harvey announced a Bengaluru office; the Indian firms named are SAM, S&A Law Offices and CAM, all top tier. ([source](https://www.barandbench.com/news/corporate/harvey-ai-announces-opening-of-bengaluru-office))
- Punjab & Haryana, Rajasthan and Kerala HCs took different approaches to IPC/BNSS co-existence around the changeover; Delhi HC left it open. ([source](https://www.barandbench.com/columns/confusion-at-the-midnight-hour-can-the-ipc-and-the-bnss-co-exist))
- LawSikho: district court reports showed FIRs under wrong sections and charge sheets citing repealed provisions; several HCs issued IPC-to-BNS clarificatory circulars (secondary, no dates). ([source](https://lawsikho.com/blog/ipc-to-bns-conversion))

## Why current tools don't solve it

Global tools have little Indian primary law and no date-aware IPC to BNS or CrPC to BNSS logic. Indian databases focus on SC and HCs and their AI only searches; it doesn't compute limitation, determine applicable law from the offence date, or draft to state-specific court practice.

## Panel verdict

**Status:** solved (round 2)

**Effort:** L

### What software can fix

Indian coverage where checks and drafting actually happen. Index High Court judgments from open data and tribunal orders through Indian Kanoon. Recognise Indian HC and tax reporter formats. Replace the 22-row IPC/CrPC/IEA correspondence table and the max_section counts with the official correspondence tables and exact section lists from India Code. Add priority state acts and the 1961/2025 Income-tax Acts. Make code defaults date-aware the right way: substantive defaults from the offence date, procedural and evidence defaults from the date the proceeding was instituted.

### What it can't fix

Most district court judgments are not published in any open corpus, and there is no official eCourts API (we never bypass the captcha). Divergent High Court views on straddling IPC/BNSS proceedings are law to be argued, not a lookup: we surface them as notes from the knowledge base, not as a rule. State law is added act by act, not 'all of it' at once.

### What the user sees

Citations to HC judgments ('2024:DHC:1234', 'AIR 2019 Bom 12', '2023 SCC OnLine Del 456', 'ILR', '(2019) 414 ITR 1', '[2020] 117 taxmann.com 45') appear in the ledger instead of slipping through. 'Section 3 of the Maharashtra Rent Control Act' shows 'known act, section exists' instead of 'not checked'. A criminal matter has two dates: 'Date of offence' and 'Date the FIR, complaint or proceeding began'. Drafts then default to the offence code (BNS or IPC) from the first date and the procedure and evidence codes (BNSS/CrPC, BSA/IEA) from the second. When the second date is missing, or the dates straddle 1 July 2024, the draft shows the note 'Transition: check s.531 BNSS; High Courts differ on straddling cases' instead of silently picking a code. The bail workflow asks for both dates. /about states coverage: which courts and acts are indexed, and as of when.

### What the system does

1. scripts/ingest_hc_judgments.py indexes metadata from the AWS Open Data bucket indian-high-court-judgments (Dattam Labs, 25 HCs, CC BY 4.0, Parquet metadata, quarterly) into legal_authorities: court, neutral citation keys, name_tokens, and separate petitioner and respondent fields for P12. Full text for chosen courts and years goes into judgment_texts. The script is resumable via external_id. 2. Tribunals: an Indian Kanoon doctypes filter (ITAT, NCLAT, CESTAT, NCDRC and others) in authority_resolver, with the cache. 3. New citation_service patterns for HC neutral citations (court-specific regexes from a data table), state reporters, ILR and ITR/taxmann/GSTL, plus the P03 catch-all. 4. scripts/ingest_india_code.py pulls each registry act's section list from India Code (government text), including the priority state acts and ITA_1961/ITA_2025, into a shared statutes table: act key, section ids including lettered and omitted ones, and section text. max_section becomes a fallback only. 5. Correspondence: the official MHA/BPR&D BNS-IPC, BNSS-CrPC and BSA-IEA tables are loaded into checksummed data files that jurisdiction_service reads. CORRESPONDENCE_CAVEAT stays until a lawyer signs off on the files. 6. Dates: migration 014 adds offence_date, offence_end_date, proceeding_instituted_on and proceeding_kind (fir|complaint|chargesheet|trial|appeal|other) to case_threads and court_cases. A single pure function, criminal_codes(dates), shared with P03's transition_rules, returns {substantive, procedural, evidence, notes}. substantive = BNS if offence_date is on or after 1 July 2024, else IPC, with a note when the offence spans the date. procedural = BNSS and evidence = BSA if proceeding_instituted_on is on or after 1 July 2024. If it is earlier, procedural = CrPC and evidence = IEA, with the s.531(2) BNSS / s.170(2) BSA savings note. If it is missing, there is no procedural default: drafts use the placeholder [●procedure code: enter FIR/complaint date●] and show the 'check s.531' note. Where the offence is before and the proceeding after 1 July 2024, the default is BNSS with a note on divergent HC views. The exceptions table (s.479 BNSS for all undertrials, SC Aug 2024) overrides. 7. workflow_service bail is changed to use criminal_codes(): it asks for proceeding_instituted_on as well as offence_date, and the CrPC/BNSS choice of bail, default-bail and undertrial provisions follows the proceeding date, not the offence date. Today it keys the whole procedure on offence_date (CRIMINAL_CODES_START at line 21 and around line 245), which is the bug the objection describes.

### Where it is built

scripts/ingest_sc_judgments.py (pattern for the HC script), supabase/migrations/008_shared_legal_corpus.sql (legal_authorities, shared corpus), app/services/citation_service.py ACTS and patterns, app/services/jurisdiction_service.py IPC_TO_BNS and related tables, app/services/workflow_service.py bail (switch to criminal_codes(); add the proceeding_instituted_on Field). New: scripts/ingest_hc_judgments.py, scripts/ingest_india_code.py, app/data/correspondence/*.csv, app/services/criminal_codes.py (shared with P03), migration 014 statutes table (shared, read-only) and the date columns.

### Why current tools fail and this won't

Harvey, CoCounsel and Lexis have little Indian primary law, and their Indian users are top-tier firms doing SC/HC work. SCC Online and Manupatra cover SC/HC well, but their AI only searches: it doesn't do date-aware code selection or check a draft. Generic AI picks a single 'new code or old code' by one date and gets straddling matters wrong. We build on open government and CC BY data (India Code, SC and HC open buckets), which is cheap to keep current, and wire coverage straight into the citation checker. Code selection follows the statutory structure: substantive by offence date, procedure and evidence by proceeding date, with the savings provisions and SC exceptions as notes.

### Safeguards

The shared corpus and statutes table are written only by service-role ingest scripts (invariant 2) and are read-only to users. CC BY 4.0 attribution for the HC data is added to /about beside the SC credit. Government statute text is public; no proprietary reporter content is copied. The correspondence and transition data files stay labelled indicative until a named lawyer signs them off, with the sign-off recorded in the repo. When the procedural code is uncertain, drafts show a placeholder rather than guessing a code into a filing.

### How the panel's objections were answered

offence_date and proceeding_instituted_on (with proceeding_kind) are now stored separately. One shared function, criminal_codes(), picks substantive defaults (BNS/IPC) from offence_date only, and procedural and evidence defaults (BNSS/CrPC, BSA/IEA) from proceeding_instituted_on. With no proceeding date, it gives no procedural default: drafts get a [●…●] placeholder and a 'transition: check s.531' note. Straddling dates get the savings or divergent-HC notes, and s.479 BNSS is applied to all undertrials through an exceptions table. Tests cover both straddling cases (2023 offence with a 2024 FIR, and 2023 offence with a 2023 FIR) and the missing-date case. I also found that the existing workflow_service bail pack picks the whole procedure by offence date (CRIMINAL_CODES_START, around line 245), the bug the objection describes. This proposal switches it to criminal_codes() and adds the proceeding-date field, with bail tests for both straddling cases.

### Acceptance tests

- Extraction recall: a fixture of 80 Indian citation strings across SC, HC, tribunal and tax reporters is 100% extracted (each yields a ledger item, resolved or flagged)
- HC ingest: a fixture Parquet row gives a legal_authorities row with the correct neutral key and petitioner/respondent fields; re-running inserts no duplicates
- Statutes table: 'Section 124B IPC' is invalid even though 124 <= 511; 'Section 498A IPC' is valid; 'Section 3 Maharashtra Rent Control Act' is statute, not 'not checked'
- Correspondence checksum: jurisdiction_service refuses a modified file without an updated checksum; IPC 420 maps to BNS 318(4) from the file
- criminal_codes straddle 1: offence 2023-11-10, FIR 2024-08-14 gives substantive IPC, procedural BNSS, evidence BSA, with a divergent-HC note
- criminal_codes straddle 2: offence 2023-11-10, FIR 2023-11-12 gives IPC/CrPC/IEA with the s.531(2)/s.170(2) savings note
- Offence 2024-09-03 with no proceeding date gives substantive BNS, no procedural default, and the 'check s.531' note; a generated draft contains the [●procedure code…●] placeholder, not a CrPC or BNSS section
- Bail workflow: offence 2023-11-10 with FIR 2024-08-14 suggests s. 480/483/482 BNSS and s. 187(3) BNSS (not CrPC); offence 2023-11-10 with FIR 2023-11-12 suggests CrPC provisions with the savings note; s. 479 BNSS is offered for an undertrial in either case (exception table)
- A Kerala HC neutral citation resolves against the fixture HC index; an unknown one is flagged, not passed

### Reviewers' minor notes

- Both P14 and this proposal rewrite workflow_service._bail. Implement one shared criminal_codes() plus the P14 punishment-table fix once.
- The HC open-data bucket's coverage and licence per court should be recorded per row on /about, since coverage varies widely by High Court.
- Record the India Code terms of use and the date each act was pulled on /about, next to the CC BY credits.
- India Code has no API. The ingest script depends on scraping its HTML, so pin the parser to fixtures and alert when an act page changes shape.
- Unify proceeding_instituted_on with P14's fir_date/investigation_started_on before both change _bail.

