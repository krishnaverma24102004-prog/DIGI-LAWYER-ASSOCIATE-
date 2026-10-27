# P18. Fabricated authority in incoming orders: courts', tribunals' and tax officers' orders now cite AI-invented cases

**Severity:** high · **Size:** big · **Region:** India

**Who has it:** Tax, insolvency and litigation teams at Indian firms, in-house tax and legal departments, appellate counsel

## What goes wrong

Indian orders have relied on non-existent authority: a trial court order upheld by the AP HC, an ITAT order involving a Rs 669-crore trust, a Rs 27.91-crore faceless tax assessment, and NCLT/NCLAT orders. The firm receiving such an order must audit every citation by hand, under limitation pressure, to build grounds for rectification (s.254(2)), appeal or writ. Clients pay for litigation to undo orders resting on fabricated law.

## Evidence of scale

- Gummadi Usha Rani (SLP (C) 7575 of 2026): a trial court relied on fake AI judgments and the AP HC upheld it; the SC called it misconduct and issued notice to the AG, SG and BCI. ([source](https://www.verdictum.in/court-updates/supreme-court/cognizance-using-fake-ai-generated-precedents-trial-court-judgments-1609159))
- Buckeye Trust v. PCIT-1 Bangalore: an ITAT order (Dec 2024) cited three SC and one Madras HC judgment that couldn't be found, reportedly ChatGPT-generated; retracted about a week later. ([source](https://lawtrend.in/bengaluru-tax-tribunal-withdraws-order-based-on-non-existent-case-law-cited-by-chatgpt/))
- Buckeye Trust involved a trust worth about Rs 669 crore and was recalled under s.254(2); Bombay HC set aside a Rs 27.91 crore assessment on three fictitious precedents; Pooja Ramesh Singh called such decisions 'no decision in the eyes of the law'. ([source](https://blog.ipleaders.in/ai-hallucinated-case-law-fake-citations-india/))
- KMG Wires v. NFAC (Bombay HC, Oct 2025): quashed a Rs 27.91-crore assessment (returned income Rs 3.09 crore) resting on non-existent decisions. ([source](https://www.livelawbiz.com/high-court/bombay-high-court/dont-blindly-trust-ai-bombay-hc-quashes-income-tax-assessment-passed-on-unverified-ai-generated-case-laws-307866))

## Why current tools don't solve it

Westlaw Quick Check, Lexis Brief Analysis and Clearbrief check the user's own draft against mainly US authority. None takes an incoming Indian court, tribunal or tax order, flags every non-existent citation, fabricated quote or repealed provision, and turns them into ready grounds for rectification, appeal or writ with limitation dates.

## Panel verdict

**Status:** solved (round 3)

**Effort:** M

### What software can fix

Audit an incoming order (court, tribunal, faceless assessment, NCLT/NCLAT) for non-existent cases, wrong-case citations, out-of-range paragraphs, fabricated quotes, and repealed or wrong-version provisions. Turn the findings into neutral, evidence-backed draft grounds. Compute remedy limitation dates in code from versioned, date-aware rules, each keyed on its correct statutory trigger: pronouncement for IBC s.61, copy made available for Companies Act s.421(3), receipt or service for the tax remedies. The rules include the switch from the Income-tax Act, 1961 to the Income-tax Act, 2025 on 1 April 2026.

### What it can't fix

Choosing the remedy, and deciding whether a defect is material, is the lawyer's call. The dates of pronouncement, knowledge, certified-copy application, copy availability, receipt and service are physical facts the lawyer enters. We can't read them reliably from the order. Whether a party 'not present' can count from its date of knowledge is fact-dependent and contested at NCLAT, so we compute it only with a warning. How the 2025 Act's savings provisions apply to a proceeding can be contested; we show a 'transition: verify' note. A rule that hasn't been signed off by a practitioner in its field never yields a date. Unreadable scans with the vision fallback off need manual entry. We don't judge the officer or judge.

### What the user sees

'Audit an order' on /verify. The lawyer uploads the order and picks the forum (ITAT, CIT(A)/JCIT(A)/AO, NCLT, NCLAT, HC, district court). The date fields shown depend on the chosen remedy:
- IBC s.61 appeal: 'Date of pronouncement' (required), a 'Was the appellant present or represented at pronouncement?' toggle, a 'Date of knowledge' field when the answer is no, 'Certified copy applied on' and 'Copy ready on'.
- Companies Act s.421: 'Date the copy was made available'.
- Tax remedies: order date, receipt and service.
For tax orders the Act version and year are detected and must be confirmed.

The ledger maps each relied-on authority to the order paragraph where it appears. The 'Grounds' tab holds one neutral draft ground per defect. The 'Remedies' panel lists each route with its basis (Act, version, section), its trigger ('30 days from pronouncement, s.61(2) IBC'), the computed last date and condonable window, and the working ('pronounced 15-04-2026; certified copy applied 20-04-2026 (within limitation), ready 28-04-2026: 8 days excluded under s.12(2) Limitation Act'). Two warnings can appear:
- 'Copy applied after limitation: no exclusion'.
- 'Computed from date of knowledge you entered: NCLAT may count from pronouncement if you were represented; verify'.
The date of receipt is never used for IBC s.61, and the panel says so. Rules not yet signed off show 'Rule not yet reviewed by our insolvency/tax advisers: no date computed'. Everything stays an unreviewed draft until a lawyer approves it.

### What the system does

1. Upload goes through document_service and ocr_service, with masked text for any LLM step.

2. citation_audits with kind=incoming_order. Paragraphs are parsed so every item has an order_para. The order's own cause title is excluded from lookups.

3. The ledger is the same as P12/P02/P03.

4. Statute registry: ITA_1961 and ITA_2025 are added to citation_service ACTS with exact section sets from India Code. The ambiguous bare 'IT Act' alias is resolved by section existence or by tax-order context, and flagged ambiguous_act otherwise. IBC and Companies Act section sets come from the P22 statutes table.

5. Act-version detection is deterministic and must be confirmed by the lawyer.

6. Remedy rules are data (app/data/remedy_rules/*.yaml, checksummed). Each rule has:
- (statute, version, remedy, forum), applies_from/applies_to, and a transition flag;
- a trigger enum: pronouncement | knowledge | copy_made_available | receipt | service | order_date;
- the period and the condonation window;
- an exclusions list, e.g. {kind: limitation_s12_2, condition: copy_applied_within_limitation, counting: <convention>};
- the basis section, resolved through the registry;
- a sign-off record (signer name, enrolment number, practice_domain, date).
The loader requires that the signer's practice_domain matches the rule family: 'insolvency' for ibc.yaml and companies.yaml, 'direct_tax' for ita_*.yaml, 'civil' for cpc.yaml. Otherwise the rule is refused.

7. IBC s.61 (ibc.yaml):
- trigger: pronouncement; period 30 days; condonable 15 days; basis s.61(2) IBC, V. Nagarajan v. SKS Ispat (2021) and Sanjay Pandurang Kalate (2023).
- Exclusion: s.12(2) Limitation Act, only when certified_copy_applied_on is on or before the last day of the 30 days. The excluded period runs from the application to copy_ready_on, using the counting convention in the signed-off rule.
- Alternative trigger 'knowledge': used only when the lawyer marks the appellant as not present or represented and enters the knowledge date. It produces the amber 'verify' warning, and the pronouncement-based date is shown alongside it as the conservative date.
- Receipt is not an input for this rule.

8. Companies Act s.421(3) (companies.yaml): trigger copy_made_available, 45 days, plus 45 condonable.

9. Tax rules: s.254(2) (six months from the end of the month the order was passed), s.260A (120 days from receipt), s.249 (30 days from service). The 2025 Act equivalents are used only after sign-off. CPC Order 47 review: 30 days (Art. 124). Art. 226: 'promptly', no date.

10. compute_remedy(rule, dates) is a pure function. Days are counted with s.12(1) Limitation Act (the trigger day is excluded). If any required date is missing, no date is shown. The conservative earliest date is always shown first. When a date falls on a holiday, an info note mentions s.4 Limitation Act and the forum's holiday list from the P06/P13 calendar, but the date is not extended automatically.

11. select_rules(order_act_version, year, order_date, remedy_date) works as in round 2.

12. Grounds come from per-status templates filled only from ledger fields. The optional 'expand' step goes through /drafting/generate with the citation checker and draft_check.

13. Approval uses the existing draft approval, and a filing copy uses the P02 gate.

### Where it is built

Extend:
- app/services/citation_service.py ACTS (ITA_1961, ITA_2025, IT Act disambiguation)
- the P22 statutes table
- app/services/workflow_service.py (deadline rules with statutory basis; the remedy rules are shared with the P06/P13 deadline engine and holiday calendar)
- app/services/drafting_engine.py and draft_check.py
- app/services/ocr_service.py and document_service.py
- the P12 ledger (migration 014)
- frontend/src/app/verify/page.tsx and /studio

New:
- app/services/order_audit.py
- app/services/remedy_rules.py (loader with checksum and practice_domain sign-off check; compute_remedy; select_rules)
- app/data/remedy_rules/{ita_1961,ita_2025,ibc,companies,cpc}.yaml
- tests/fixtures/remedies/

### Why current tools fail and this won't

Westlaw Quick Check, Lexis Brief Analysis and Clearbrief check your own draft against mostly US law. Indian research tools (Taxmann, CaseMine, IBC Laws) search case law but don't ingest an order and return defects mapped to its paragraphs plus limitation dates. Generic limitation calculators count from receipt, the intuitive but wrong trigger for IBC s.61, and an IBC appeal filed past 45 days from pronouncement can't be saved. Each of our rules names its statutory trigger and exclusion conditions, is signed off by a practitioner in that field, and shows its working. The conservative pronouncement-based date is always shown first.

### Safeguards

Templates use neutral language and impute nothing to the judge or officer. A lawyer approves before any use. Every computed date shows its trigger, exclusions, basis, Act version and 'verify before relying'. The conservative date always comes first, and contested triggers (date of knowledge) carry a warning. A rule computes nothing until a named practitioner in the matching field signs it off: insolvency for IBC and Companies, direct tax for income tax. The trigger and condition logic is code, tested against fixtures that encode the Supreme Court's rule. Client documents are org-scoped, and LLM steps get masked text. Approvals are audit-logged.

### How the panel's objections were answered

Both objections say the IBC s.61 trigger was wrong. Fixed:
- The rule now has trigger 'pronouncement' (s.61(2); V. Nagarajan v. SKS Ispat 2021; Sanjay Pandurang Kalate 2023). Receipt is not an input for it, and the API refuses a receipt-only request.
- The s.12(2) Limitation Act exclusion applies only when a certified-copy application date on or before day 30 is entered, running to the copy-ready date. A late application gives no exclusion and a warning.
- A 'party not present: date of knowledge' input exists, but its date carries an amber 'verify' note and is always shown beside the conservative pronouncement-based date.
- Companies Act s.421(3) stays keyed on the date the copy is made available.
- The IBC and Companies rule files must be signed off by a practitioner whose practice_domain is insolvency. The loader refuses other signers.
The acceptance test now counts from pronouncement (15-04-2026 gives 15-05-2026, plus 15 days to 30-05-2026) and asserts that no receipt-based date appears. Added tests cover pronouncement before receipt, the exclusion, a late copy application, the knowledge path and a wrong-domain sign-off.

### Acceptance tests

- Fixture ITAT order with 4 authorities (2 real, 1 non-existent, 1 real citation with wrong parties) gives 2 grounds (not_found, name_citation_mismatch), each naming the order paragraph
- Grounds text is byte-identical across runs with the LLM disabled
- IBC, pronouncement before receipt: pronounced 2026-04-15, copy received 2026-05-01, no certified-copy application gives a last date of 2026-05-15 and a condonable window to 2026-05-30. No date derived from receipt (such as 2026-05-31) appears anywhere in the output
- IBC exclusion: pronounced 2026-04-15, certified copy applied 2026-04-20 and ready 2026-04-28 gives the last date extended by the excluded period under the fixture rule's counting convention (2026-05-23 with the fixture convention), with the working shown
- IBC late application: pronounced 2026-04-15, copy applied 2026-05-20 (after day 30) gives no exclusion, a last date of 2026-05-15 and the 'applied after limitation' warning
- IBC knowledge: 'not present' with knowledge on 2026-04-25 shows the knowledge-based date with the amber 'verify' warning and the pronouncement-based 2026-05-15 next to it as the conservative date
- The IBC s.61 rule has no receipt input: the API rejects a request with only a receipt date for remedy ibc_s61 (422 'date of pronouncement required')
- Companies Act s.421(3): copy made available 2026-05-01 gives 2026-06-15 plus a condonable window to 2026-07-30
- Sign-off domain: ibc.yaml signed by a signer with practice_domain direct_tax is refused at load, and no IBC date is computed
- Tax (from round 2): a 1961-Act ITAT order dated 2026-03-10 gives a s.254(2) last date of 2026-09-30 with the transition note; s.260A counts 120 days from receipt
- A 2025-Act order uses the 2025 rule family; with the shipped unsigned rule it shows 'not yet reviewed' and no date
- A 1961-Act order dated 2026-06-15 for AY 2024-25 uses the saved 1961 rule with the transition note; an undetermined Act computes no date
- Registry: 's. 143(3) of the Income-tax Act, 1961' is statute; 's. 260A IT Act' resolves to ITA_1961; 's. 43A IT Act' without tax context gives ambiguous_act; 's. 999 of the Income-tax Act, 1961' is invalid; the 's. 61(2) IBC' basis is graded statute
- A rule file with an altered checksum is refused
- The order's cause-title parties are never sent to Indian Kanoon (the mocked client asserts the payloads)
- Exporting the grounds draft as a filing copy is blocked until approved (P02 gate)

### Reviewers' minor notes

- The 'fabricated quote' finding for an incoming order uses the same matcher as P02. Orders quote judgments with ellipses and bracketed edits, so without P02's fix this would draft a ground accusing the bench of misquoting. Apply the same fragment matcher, and never make fabricated_quote a ground unless it fails on every fragment.
- s.249 ITA 1961 counts 30 days from service of the notice of demand (for assessment or penalty appeals), not from service of the order. Name that trigger exactly.
- The most common remedy against a CIT(A) order, an ITAT appeal under s.253 (two months from communication of the order), is missing from the rule list. Add it or show it as 'rule not yet available'.
- The s.249 appeal trigger is stated as '30 days from service'. It is the date of service of the notice of demand for assessment and penalty appeals, and the date of communication of the order for other cases. The rule file should key the trigger on the order type, or name both triggers.
- Ground templates alleging that an order relies on a non-existent authority should carry a fixed wording review by a signed-off litigator. Neutral phrasing ('the authority cited at para N could not be located in ...') avoids any imputation that could be read as scandalising the court.
- The 'fabricated quote' check against an incoming order uses the same quote_match, which doesn't handle ellipses or brackets. Judges also quote with elisions, so the tool will draft false 'quote not in judgment' grounds about a court. The lawyer's approval catches this, but reuse P02's fragment-based quote parser before any quote ground is generated.
- I checked the dates in the acceptance tests and they are arithmetically right: IBC 15-04 gives 15-05 and 30-05; with the exclusion, 23-05; s.421(3) 01-05 gives 15-06 and 30-07; s.254(2) gives 30-09. Keep them as golden fixtures in the remedy_rules tests.

