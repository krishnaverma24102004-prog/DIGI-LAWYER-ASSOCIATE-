# Final Build Plan: AI Legal Associate (India)

This plan covers 42 accepted solutions and 6 open problems. The panel is confident in the engineering: each accepted solution has deterministic checks, tests and safeguards that passed review. None of that proves anyone will buy or use the product. Every claim about demand below is a hypothesis to test with real users.

Effort key: S = small, M = medium, L = large, as each proposal stated it. The 42 accepted solutions break down into 1 S, 23 M and 18 L. The 6 open problems add 5 L and 1 M.

---

## 1. Build order (waves)

Waves group solutions that share infrastructure. Waves 1 and 2, and P19 from Wave 6, have no dependency on each other and can run in parallel with separate teams.

### Wave 0: Coordination and shared foundations (no new user features)

These are prerequisites that more than one proposal assumes. They have to be settled once, before any code is written.

| Item | Why | Proposals affected |
|---|---|---|
| **One central migration register** (013 is the last shipped migration) | About 20 proposals each claim `014`, and several also claim 015-018. P41 must also follow P36's migration. Numbers should be assigned in wave order, never by proposal. | All |
| **One `criminal_codes()` and one `_bail` rewrite** | P14, P22 and P03 each rewrite `workflow_service._bail` and add overlapping date fields (`fir_date`, `investigation_started_on`, `proceeding_instituted_on`). Unify these into one field set and one function. | P14, P22, P03 |
| **One court and holiday calendar, keyed per court** | P06 has `court_calendars`, P15 has `holiday_calendar`, and P39 and P13 need per-court closures. | P06, P13, P15, P16, P18, P39 |
| **Shared `judgment_text.py`** (page-aware cleaning) | Required by P02's quote matching, P12's paragraph parser and P26. | P02, P12, P26 |
| **DOCX extraction in `document_service`** | It rejects DOCX today. | P15, P42, P44 |
| **Shared `inbound_auth.py`** (SES/SNS signature checks) | P37 defines it. P42 must actually use it. | P37, P42 |
| **Shared `wa_templates` contract module and its test**, as a standalone PR | P24 is accepted, but its shared test calls P33's guard, which is still open. | P24, P33 and every WhatsApp sender |
| **Server-owned eCourts fields on `court_cases`** (trigger or HMAC; authenticated users currently have unrestricted insert/update from migration 011) | This is the root cause of open objections on both P33 and P46. Fixing it once unblocks both. | P33, P46, P01, P32 |
| **CTO sign-off on additions to the invariant-2 list** | New server-side jobs: cause-list fetch (P05), deadline sweep (P13), digests (P10, P30, P39), Razorpay webhooks (P09, P19), SES inbound (P37), timeline crons (P48), retention queue (P35), stamp loader (P17). | Many |
| **People, not code: name the signing advocates** | The rule tables only go live once named practitioners sign off: 60 limitation golden cases (P06), 30 custody golden cases (P14), stamp legal-content reviewers (P17), insolvency and tax signers (P18), registry checklists (P25), the independent labelling panel (P11), correspondence tables (P22), court profiles (P26), the stage glossary (P01), the legal glossary (P23). P17 raises a related problem: employed advocates are restricted under BCI Rule 49. | P06, P11, P14, P17, P18, P22, P23, P25, P26, P01 |

### Wave 1: Court calendar and deadline engine (3 L + 3 M)

Shared pieces: `cause_list_items` and the per-court parsers, `deadline_service` (ladder, escalation, blind check), court calendars, and the `/board` UI.

| Order | ID | Solution | Effort | Depends on |
|---|---|---|---|---|
| 1 | P05 | Nightly cause-list reconciliation and escalation | L | Wave 0 calendar |
| 2 | P06 + P13 | Limitation engine plus firm docket, reminder ladder and blind second check | L + L | Built together: P06 writes P13 deadlines |
| 3 | P14 | Custody board and default-bail / s.479 BNSS dates | M | P13, unified `criminal_codes()` |
| 4 | P04 | Clash board and reach estimates | M | P05 parser (bench headers, segments) |
| 5 | P47 | Hearing brief generated when a matter is listed | M | P05, P13, P04 |

P13's minor fix lands in this wave: replace the reversible `sha256(inputs)` in audit rows with an HMAC.

### Wave 2: Citation and authority stack (2 L + 3 M + 1 S)

Shared pieces: the `legal_authorities` corpus, the statutes table, the `party_names` matcher, the P12 Verification Ledger, and the Indian Kanoon budget.

| Order | ID | Solution | Effort | Depends on |
|---|---|---|---|---|
| 1 | P22 | HC index, India Code statutes, date-aware codes | L | Wave 0 `criminal_codes()` |
| 2 | P29 | Indian Kanoon spend ledger and the Authorities panel | S | Nothing in this wave |
| 3 | P12 | Identity, pin and quote checks; authority tokens | L | P22, P29 |
| 4 | P03 | India pre-filing check (cause title and prayer charge codes) | M | P12 `party_names`, P22 |
| 5 | P18 | Audit of incoming orders and remedy dates | M | P12, P06 calendar |
| 6 | P11 | Per-answer ledger counts and the published benchmark | M | P12 statuses |

The "filing copy" export gate for P03 and P18 waits on **P02**, which is still open.

### Wave 3: Matter record and firm governance (1 L + 4 M)

| Order | ID | Solution | Effort | Depends on |
|---|---|---|---|---|
| 1 | P37 | Self-filing matter file (WhatsApp, SES email, eCourts) | L | Wave 0 `inbound_auth` |
| 2 | P36 | Offboarding and erasure registry | M | Nothing in this wave |
| 3 | P41 | Electronic evidence vault and s.63 BSA certificate | M | Its migration must follow P36's |
| 4 | P21 | AI policy as enforced settings; Verification Record | M | P12; also needs P20's ledger and `guarded_call` (see section 3) |
| 5 | P40 | Full export and fair billing rules | M | Merge its export with P43's `task_export_org` |

### Wave 4: Client channel (2 L + 6 M); every outbound send is gated on P33

The approval UIs, templates and drafts can be built now. Nothing is sent to a client until P33 closes.

| ID | Solution | Effort | Notes |
|---|---|---|---|
| P24 | Clause-anchored explanations in the client's language | M | Uses P23 invariants; template contract |
| P01 | Client updates built from the court record | L | Writes `matter_events` (P48) |
| P48 | Tamper-evident timeline | L | Panel advice: ship the timeline and share page first, add RFC 3161 anchoring later |
| P07 | After-hours intake brief and triage | M | Conflict check uses the fallback until P46 closes |
| P39 | Quiet hours and status replies from records | M | Urgency rules come from P06, P13 and P14 |
| P34 | Claim check for social-media legal claims | M | Uses the citation stack |
| P32 | Duration ranges (delayed-entry Kaplan-Meier) | M | Needs Wave 0 server-owned eCourts fields |
| P35 | DPDP kit (retention, requests, breach register) | L | Sends depend on P33; the leak guard depends on P46's party index |

### Wave 5: Litigation work product (3 L + 2 M)

| ID | Solution | Effort | Depends on |
|---|---|---|---|
| P27 | s.138 NI Act cheque pack | M | P06, P13 (as stated) |
| P25 | Registry pre-scrutiny and defect tracker | L | P06, P13 |
| P26 | E-filing bundle that conforms to court formats | L | `judgment_text` (Wave 0) |
| P28 | Witness contradiction and omission sheet | M | Existing `evidence_service` |
| P23 | Vernacular record translation with review gate | L | Shares invariants with P24 |

### Wave 6: Money and pricing (2 L + 4 M)

| ID | Solution | Effort | Notes |
|---|---|---|---|
| P19 | INR plans, cost ledger, Razorpay/GST, verification gate | L | **Must ship before public launch.** Can run in parallel from Wave 1. Merge its `ai_usage` ledger with P20's ledger. |
| P09 | Fee terms and BCI Rules 25-30 ledger | L | Separate Razorpay routes and secrets from P19 |
| P10 | Work capture | M | `/log` command needs P33's member-phone verification |
| P31 | Stage-wise fee estimate | M | P32 statistics, P09 |
| P38 | OCG pre-bill check and LEDES 1998BI export | M | P10, P09 |
| P30 | Junior's run-sheet and contribution report | M | P01, P06, P09, P10; needs an internal-template category in P33 |

### Wave 7: In-house and contracts (4 L + 2 M); repository-dependent parts are gated on P42

| ID | Solution | Effort | Notes |
|---|---|---|---|
| P44 | Playbook redlining with byte-exact inserted text | L | Independent of P42 |
| P17 | State stamp-duty lookup from a shared sourced table | L | Independent of P42 |
| P15 | Contract intake triage (Green/Amber/Red lanes) | L | Needs P44 and P17; email intake needs P42 |
| P16 | Obligation windows and reminders | L | Ship with a stub `execution_status` until P42 closes |
| P45 | Stamp exposure audit | M | Needs P17 and the P42 repository |
| P43 | Zero-configuration contract onboarding and adoption metrics | M | Fully dependent on P42 |

---

## 2. Per-solution confidence and what only real users can confirm

**General caveat:** every row below establishes that the solution is buildable and safe. None of it is evidence that customers will pay for it.

| ID | Why the panel is confident | What only real users can confirm |
|---|---|---|
| P04 | The pace model is fully specified (printed position, sitting minutes, floor of 3, quantiles without interpolation) and tested against an independent reference implementation. Steps 1-8 use no AI. Thin data shows amber, never red. The system never suggests seeking an adjournment. | Whether juniors log enough "called" taps to reach W ≥ 20 in a week. Whether windows are narrow enough to act on when a heavy-tailed list can take a whole morning. Whether firms actually take up the reassignment suggestions. |
| P05 | Parsers are deterministic, with 20 labelled PDFs per court. Matching runs exact, then probable, then "possibly ours". Escalation is tested under freezegun. A static check proves no captcha path exists. | Coverage beyond the fixture PDFs. Lists published after 21:00 (the escalation clock should start at ingestion). Whether munshis forward lists. Whether firms value this over court-run advocate-wise alerts and Provakil, which already exist. |
| P06 | Rules are data, signed off by two advocates and checked against 60 golden cases. Missing inputs always produce the earlier (safe) date. Property tests cover the arithmetic. | Whether the sign-off advocates are actually recruited (none are named yet). Whether clerks enter copy-ready dates. How often ad hoc closures occur. One property test needs restating once s.4 shifts are involved. |
| P13 | The second check is blind at the database level (selects revoked, masking RPCs). Blindness never withholds a reminder. Content-free messages to non-members are tested across 200 randomised matters. | Small firms' eligible-checker pool will run out once partners have viewed the docket, so fallback to self-check will be common. Whether reminders get acknowledged or ignored. |
| P14 | It fixes real bugs in the existing `_bail` pack: a "max ≥ 10" test that should give 60 days, the procedural code chosen by offence date instead of FIR date, and s.479 denied to pre-July-2024 cases. It adds a statute table and golden cases. | Whether firms and DLSAs keep custody files current (chargesheet dates, interrupted custody). The quality of legal-aid CSVs. The criminal team's ruling on the BNSS 60/90-day wording. |
| P25 | Checks are deterministic against per-court checklists signed off by two advocates. An uncertain detection becomes "needs human", never "pass". The same bundle always produces a byte-identical report. | How many results come back "needs human". Whether actual registry objections match the published checklists. |
| P26 | It took six rounds. Every character is classified as body, header/footer or our own overlay, using Word's tags, the DOCX parts or repetition. Scripts are attributed with UAX #24 Script_Extensions. It is tested on real Word 365 exports. | Whether real firm exports pass without a recorded deviation. Whether registries accept the bundles. The "unclassified margin line" rule still needs a deterministic definition (minor). |
| P27 | When the service date is uncertain, it brackets the filing window between the earliest and latest plausible service. A property test proves no displayed date is later than the safe one. Notices are fixed templates. It is honestly re-scoped beside CredGenics and Legodesk. | Whether law firms (rather than lenders) adopt it. How often the default 30-day bound produces an empty window. Whether checking 10% of notices is enough diligence. |
| P28 | It extends the existing quote verification (invariant 6) with a negative check for omissions. A fixture with 8 real and 4 fabricated findings keeps exactly the 8. | Tesseract accuracy on scanned vernacular statements. Recall on more than the 5 planned evaluation cases. The Devanagari normalisation gap (minor). |
| P41 | One owner ledger plus triggers on the live row, the trash snapshot and the restore insert record every owner change exactly once. The successor guard is tested. | Whether courts accept the certificate pack. Whether firms hash evidence at the moment they receive it. The hash proves only the integrity of the copy the firm received. |
| P47 | Most sections come straight from data. The AI section is verified against quotes from the order, and dates are computed in code. | How often orders are available and readable (district orders are often scanned Hindi). Whether lawyers read the brief. |
| P03 | It segments the document, identifies the matter's own parties, and applies a fixed precedence order. Red is reserved for the matter's own charge under the wrong code. Hindi fixtures are included. | Cause titles with FIR numbers will mostly come out amber, so red will be rarer than the headline example suggests. Attestation friction. Uptake among solos. |
| P11 | It reports two sets separately: a synthetic regression set, and a held-out real-world set labelled by advocates independent of the engineers. The false-verified rate is gated in CI. | The real-world fabricated class will be small, so intervals will be wide. Whether per-answer ledger counts actually cut checking time (median time to clear a ledger). |
| P12 | The name matcher handles Indian cause titles. Pin and quote checks run against full text. Authority tokens mean agents never type a citation string. False flags are gated at ≤1% on 300 judge-written citations. | Mismatches between SCC/AIR and court paragraph numbering. Whether lawyers tick the proposition box honestly. |
| P18 | The IBC trigger is correct (pronouncement). Remedy rules need a signer from the matching practice field. The worked date arithmetic was checked by the panel. | How often firms have incoming orders worth auditing. False "misquote" grounds until P02's fragment matcher exists (P02 is open). |
| P22 | It builds on open data (the CC BY HC bucket, India Code). An exact statutes table replaces `max_section`. Code selection is date-aware and fixes the existing bail bug. | Coverage varies by High Court. India Code has no API, so scraping is fragile. Correspondence tables need sign-off. |
| P29 | The budget is enforced in the database under a per-org lock. Every paid call requires a budget argument, enforced by an AST guard. The public-intake sub-cap defaults to Rs 0. | Whether owners set caps sensibly. Whether Indian Kanoon's terms allow merging its results with ours. |
| P36 | Owner foreign keys become RESTRICT. A classified registry drives a sweep that includes trash snapshots, with post-conditions that roll back on failure. | How firms actually handle departures, and clients following a lawyer out. The erasure confirmation must list the records that are retained. |
| P01 | Facts come from the eCourts diff and go into fixed, pre-translated templates. A lawyer approves each update, and only verified, consented contacts receive them. | Whether lawyers approve every evening. Provider data accuracy for auto-sent dates. Whether clients value this over eCourts' own SMS. |
| P07 | The reply-by time is computed in code. Dates in the brief are verified against the client's own words. Triage reuses `workflow_service`. | Emergency keyword false positives (a lawyer woken too often mutes it). Enquiry volume on firm numbers compared with personal phones. |
| P31 | Arithmetic is in integer paise. A BCI contingency-fee validator and an approval gate apply. | Whether firms will commit to fee cards. How prospects react. GST presentation (minor). |
| P32 | The delayed-entry Kaplan-Meier estimator is checked against the Channing House reference. Estimates are suppressed below fixed thresholds. `tracking_started_at` cannot be changed. | Most (case type, court) pairs will show "not enough data" for a long time. Whether clients understand ranges conditioned on their case's age. |
| P34 | Deterministic citation and guarantee checks run first. The AI explainer cannot override them, and post-checks run on its output. | Tesseract on reel screenshots. How often lawyers actually face these claims. |
| P48 | The hash chain is append-only with serialised appends. Source labels are HMAC-attested. The daily root is externally timestamped (RFC 3161), and a verifier works offline. | Demand is unproven; the panel itself suggests building the timeline first and anchoring later. Record-check codes may confuse clients. |
| P23 | The segmenter is lossless, deterministic and meets F1 ≥ 0.97 on gold data. Invariant checks cover numbers, negation and sections. A named human must review every segment. | Translator time actually saved. Which certification format each court accepts. Urdu quality has not been evaluated. |
| P24 | One template contract module and one linter. Each explanation is anchored to its clause, checked by the P23 invariants and approved by a lawyer. | Whether clients read and reply. Meta's template approvals. The "first outstanding item only" rule slows delivery. **Sending is blocked on P33.** |
| P09 | The ledger is append-only and hash-chained, with fee and client money kept separate (BCI Rules 25-30). The earned fee is computed only where the agreement makes it computable; otherwise the advocate records an assessment. The claim formula gives identical results in SQL and Python. | Whether advocates record direct-UPI payments. Bank statement formats. Whether clients reply AGREE on WhatsApp. |
| P10 | Durations come from wall-clock or call span, with the basis shown. Idle tails are flagged, not trimmed. The lawyer confirms every entry. | Most Indian litigators bill per appearance, so the hours view may go unused. The actual capture rate. |
| P30 | The run-sheet is assembled deterministically from existing data. Only the argument paragraph is AI, and it is citation-checked. | Whether juniors use it. It conflicts with P35's goal of getting data off personal phones (minor). It needs a P33 internal-template category. |
| P37 | Delivery is SES via signed SNS. Verdicts come only from the signed payload. Matter tokens are 128-bit, read from the envelope recipient. Everything else is quarantined. | SES receiving is likely outside India, so a cross-border disclosure is needed. Email versus WhatsApp habits. The workload of the quarantine tray. |
| P38 | Rules come only from a closed set of types, each tied to a verified quote. A split never increases the bill (property test). LEDES 1998BI is checked against a golden file. | Few domestic clients use LEDES. The output has not been tested against a real e-billing portal's validator. |
| P39 | After-hours replies are templated from records. Urgency rules in code never suppress deadline alerts. Partners see aggregates only for teams of 3 or more. | Replies based on stale sync data. Whether lawyers actually keep quiet hours. |
| P15 | Green signs only our own generated, hash-pinned file with typed and validated variables. Counterparty files always go to a lawyer. A file inspector surfaces hidden content. The executed copy is hash-checked. | Most e-sign flows re-save PDFs, so "unverified" plus a paralegal comparison will be the common case. Rejections of legitimate entity names. Whether GCs will sign a standing approval. |
| P16 | Obligations are two-sided windows: the latest opening reading and the earliest closing reading. A pure reminder planner can't fire before the window opens. A DB constraint forbids confirming an inverted window. | Recall measured on only 30 contracts. The lawyer confirmation backlog. The deemed-service gap (minor). |
| P17 | Rates come from a sourced shared table that CI verifies against two advocates per row. Formulas use a safe expression language. No amount is final before a person confirms the classification. | Dependence on a legal-content team and a gazette-checking cadence. The BCI Rule 49 issue if those advocates are employees. |
| P43 | Counts are honest. Exposure is shown only from confirmed assessments. Export is tested by re-import. | Backfill throughput ("within a day") hasn't been measured. **Fully blocked on P42.** |
| P44 | The model never writes inserted text; replacements are byte-exact playbook text. Rules are deterministic code. Tracked changes are written as real OOXML. | The quality of firms' own playbooks. Whether the reviewer consistency report gets used. The PASL wording needs correcting (minor). |
| P45 | It is mostly code: stamp evidence by regex, duty from P17, penalty by formula, and fixed consequence text with checked citations. | OCR of stamp pages. Fake e-stamps. Privilege for in-house audits. **Needs the P42 repository.** |
| P21 | The policy is enforced settings, not a document. Export is gated on citation statuses. A single `reply_finalizer` is enforced by an AST test. | Whether firms adopt a policy. How courts view the Verification Record. It depends on P20's ledger. |
| P35 | The return notice is neutral and guarded in code, sent only after the contact is reconfirmed. Documents are released only after identity re-verification, via a single-use link bound to a code. Nothing is erased automatically. | Whether lawyers will do a multi-step retention flow. **Sends depend on P33; the leak guard depends on P46.** |
| P40 | Export and re-import are tested in CI. Billing rules are code with tests. | Whether this export is what departing firms actually need. The Stripe reminder assumption needs fixing (minor). |
| P19 | The published INR catalog is the same code that enforces it. A per-attempt cost ledger tracks AI spend. The verification gate is enforced by a route walk. Non-lawyers are sent only to institutional routes. | Whether the price points cover cost (`cost_report` has run only on a fixture month). The "1 working day" verification depends on staffed reviewers. Willingness to pay. Impostors with forged certificates. |

---

## 3. Open problems and exactly what blocks them

| ID | Blocking objection(s) | Fix the panel would accept | Downstream impact |
|---|---|---|---|
| **P02** (filing gate and quote checking) | (1) The `translation_by_counsel` exit lets the Supreme Court's restricted-use translation reach a filing, attributed to counsel. That attestation is false whenever the quote matches the Court's translation word for word. (2) Join equivalence anywhere in a span makes "any one"/"anyone", "may be"/"maybe" and "cannot"/"can not" pass as green "verified word for word". | (1) Make `add_english_original` the only exit for `official_translation_restricted`. Add a test: a verbatim match plus `translation_by_counsel` alone gives `filing_ready` false. (2) Allow join equivalence only where the token boundary falls in a layout zone. Elsewhere it is hard red, or amber at most when the pair is on a checksummed, lawyer-signed compound list. Add tests for both cases. | The filing-copy export gate for P03 and P18. P18's quote-based grounds against a bench. P21's export path. |
| **P08** (legal-aid triage, minor safety) | (1) The late age question reverses the gate's key mapping, and a single keypress triggers an irreversible hard delete. (2, 3) Regex bugs: the Marathi alternation is ungrouped, so any "वर्षांची आहे" matches with no age, and masculine past markers होतो/होती are missing. The Hindi pattern ends in `\b` after a matra, so "मेरी उम्र अभी 17 है" never matches and the proposal's own positive test fails. | Use the same polarity as the gate, add a confirmation step before purge, and test the key mapping across all languages and DTMF. Group the alternation and replace `\b` with a lookahead. CI should run the shipped pattern file against positive and negative fixtures, and every pattern must capture an age of 10-17. | Nothing else depends on P08. P19's non-lawyer path deliberately doesn't use it. |
| **P42** (contract repository) | Trash restore can't work. `restore_trash_item` re-inserts the classified snapshot, and P42's own guard trigger raises 42501. Nothing re-queues the restored row. The foreign-key behaviour of `execution_confirmations` is unspecified (either cascade destroys them or restrict blocks trashing). `contract_fields` confirmations aren't snapshotted. | Add `contract_document` branches to `trash_item` and `restore_trash_item`: snapshot the fields as children, reset the classification columns to pending defaults, and insert an outbox row in the same transaction. Keep `execution_confirmations` with no FK. The round-trip test should assert no 42501 and an outbox row. | P43 entirely. P45. P15's email intake. P16's `execution_status` (stub meanwhile). |
| **P20** (AI-use ledger and general-research scope) | (1) `key_resolved` can't succeed for real citations: `legal_authorities` holds only SC rows with S.C.R. and INSC keys, so SCC never matches and no High Court judgment resolves. That pushes unrelated research into client matters and corrupts the per-matter record. (2, 3) The own-matter test relies on CNR and case-number columns that don't exist. Its date condition lets the judgment a client is appealing (decided before the matter opened) through into general research without consent. | Add a content-free Indian Kanoon lookup by document id. Correct the citation hint to formats that resolve. Until then, treat these hits with an attestation. Drop the date condition, or downgrade pre-opening matches to attestation. Tag `ik_documents` rows with the thread that stored them. Either add CNR and case-number columns or delete rule 4(i). Rewrite fixtures to match the real ingest format. | P21 and P19 rely on its ledger and `guarded_call`. The objections concern only the research lane, so the panel could accept building the ledger first. That is a decision to make, not a given. |
| **P33** (Rule 36 outbound guard) | (1) The existing AI reply paths (`whatsapp_intake._reply` and held AI replies) bypass the Rule 36 check, so "AI text never goes out free-form" is false. (2) `case_title_from_matter` trusts `court_cases` rows marked `source='ecourtsindia'`, which any authenticated user can write. That reopens a free-text slot. | (1) Add `send_reviewed_ai_reply(message_id)`, bound to the message hash and the reviewer. Run intake replies through the Rule 36 profile and the contact/solicitation guard, and add tests. (2) Make eCourts fields server-owned (HMAC, or definer/worker writes plus a trigger), with a DB test for forged rows. | Every client send: P24, P01, P07, P35, P39, P48. Internal sends: P10, P13, P16, P30. Fix (2) is the same root cause as P46's. |
| **P46** (conflict index) | `case_type_firm` lets one associate re-type the enquirer's claimed role and unlock "cleared" on a hard same-FIR link. That bypasses the countersigned corroboration path. The trigger trusts the stored `role_source` instead of re-deriving it. `case_type_source` and `source` on `court_cases` can be forged through PostgREST. | On hard links, a firm-set case type counts only if it is tied to an eCourts-confirmed filed proceeding, or goes through the countersigned corroboration flow. The trigger re-derives the source in SQL from `court_cases`. A BEFORE INSERT/UPDATE trigger derives `case_type_source` from `auth.uid()` and role. Tests cover a forged PATCH and a single associate's case type (Decline only). | P07's conflict check (fallback meanwhile). P35's party-name leak guard. |

**Priority:** fix server ownership of eCourts fields in Wave 0. That one change removes part of the blocker on both P33 and P46. P33 then has the widest unblocking effect, because every client-channel feature waits on it.

---

## 4. The five changes that most differentiate us from Harvey

These are drawn from each solution's own competitor analysis. We have not independently checked Harvey's current product; the comparisons are as the proposals state them.

1. **An Indian court-operations layer, which Harvey doesn't have** (P05, P04, P47, P13, P14, P30). The product reconciles the whole firm's matters against tonight's cause lists, shows each advocate's clashes across courtrooms, builds a hearing brief once a matter is listed, and runs a docket whose second check is blind at the database level. P04 states that Harvey, CoCounsel and Lexis+ AI have no scheduling layer, and P13 that they don't docket.

2. **Statutory dates computed in code under signed rules, never in prose** (P06, P14, P18, P27, P16). Limitation, default bail and s.479, IBC/Companies/tax remedies, s.138 filing windows and contract option windows are all computed from versioned rule tables that named practitioners sign off. Each shows its working, and missing inputs produce the safe date. P06 notes that Harvey and CoCounsel "will produce a plausible date in prose, which is exactly what must not be trusted."

3. **Verification that blocks unchecked output, with load-bearing text the model never writes** (P12, P03, P22, P11, P21, P44; the P02 gate is still open). Citations are checked for identity, pin and quote against Indian cause titles and the transition-era codes. Agents cite through authority tokens, so they can't type a citation string. Accuracy is published on a held-out real-world set. Playbook redlines insert byte-exact approved text. P02 points out that Harvey generates citations but doesn't stop an unchecked draft being exported, and P44 cites Harvey scoring below lawyers on the VLAIR redlining task.

4. **A client-facing channel in the client's language, with consent and lawyer approval** (P01, P07, P24, P23, P48). Court-record updates, after-hours intake briefs and clause-by-clause explanations go out over WhatsApp in Hindi and other languages, through fixed templates and lawyer approval. Vernacular records are translated with per-segment checks and a human-signed certificate. P01 notes that Harvey only faces the lawyer and has no client channel. This depends on closing P33.

5. **Self-serve INR pricing for a solo practice, with a professional-verification gate** (P19, supported by P09's BCI-native fee ledger). Published INR plans with no seat minimum, a per-matter pass, UPI AutoPay, GST invoices, and prices set from a measured per-org cost ledger. Self-serve doesn't mean selling to consumers: a Bar Council enrolment check replaces the sales gate, and non-lawyers are sent only to legal-aid institutions. P19 describes Harvey's model as "quote-based, 12-month, 20-25 seat USD contracts with no self-serve". Whether Indian small firms will pay at our price points is unproven, and is the first thing to test with real customers.