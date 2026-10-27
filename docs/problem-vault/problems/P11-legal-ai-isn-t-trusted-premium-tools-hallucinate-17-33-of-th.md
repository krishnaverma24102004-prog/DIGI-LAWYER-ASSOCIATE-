# P11. Legal AI isn't trusted: premium tools hallucinate 17-33% of the time, checking eats the time savings, and paid seats go underused

**Severity:** critical · **Size:** big · **Region:** Global (US/UK benchmarks)

**Who has it:** Associates, knowledge-management and IT heads at mid-size and large firms, in-house teams, firm management and the clients paying for the work

## What goes wrong

Firms buy Lexis+ AI, Westlaw AI or Harvey because they are marketed as grounded, yet independent testing found roughly one answer in six to one in three hallucinated or misgrounded. Lawyers must re-verify everything, and longer answers take longer to check, so hours saved drafting go back into checking. Partners can't tell which answers are safe. Associates then use the licensed tools less (one says Harvey gets them '20% of the way'), firm-level use lags personal use, and firms pay heavily for little measurable output. Inaccuracy is now UK lawyers' top AI worry.

## Evidence of scale

- Stanford RegLab study: Lexis+ AI accurate 65% (about 17% hallucinated), Westlaw AI-Assisted Research 41-42% (about one-third hallucinated), Ask Practical Law AI 19-20% (62% incomplete); misgrounded answers require clicking through and reading every source. ([source](https://arxiv.org/html/2405.20362v1))
- Stanford found AI legal research tools hallucinate in 17% of queries; Thomson Reuters denied three access requests before granting it. ([source](https://www.lawnext.com/2024/05/stanford-will-augment-its-study-finding-that-ai-legal-research-tools-hallucinate-in-17-of-queries-as-some-raise-questions-about-the-results.html))
- LexisNexis UK survey of 543 legal professionals (2026): 83% worry about hallucinations, up from 57% at the start of 2024; 94% use AI; 81% prefer AI grounded in legal sources. ([source](https://www.legalcheek.com/2026/09/hallucinations-top-lawyers-ai-worry-list-research-finds/amp/))
- An academic 'verification-value paradox' argues GenAI efficiency gains are erased by verification time; Slaw's Mitch Kowalski disputes it. ([source](https://www.slaw.ca/2025/11/20/genai-the-verification-value-paradox-a-critique/))
- Thomson Reuters: 91% say AI should meet a higher accuracy standard than humans; 41% say output must be 100% accurate to use without review; accuracy is the top barrier to investment (50%). ([source](https://www.thomsonreuters.com/en/insights/articles/addressing-top-ai-concerns-what-you-really-want-to-know))
- Thomson Reuters: only 22% of firms have a visible AI strategy; 30% admit moving too slowly; 'adoption without integration' and hidden training/integration costs cause budget overruns. ([source](https://legal.thomsonreuters.com/blog/why-law-firms-are-struggling-with-ai-roi/))
- 2025 Legal Industry Report (MyCase, 2,800+ respondents): firm-level generative AI use 21% in 2024, down from 24%, while 31% used it personally, pointing to restrictive policies arising from accuracy and ethics concerns. ([source](https://www.abajournal.com/advertising/article/legal-industry-report-2025-2))
- Harvey's Reddit AMA: founders disputed an alleged former employee's low-usage claims by citing DAU/MAU and renewal rates. ([source](https://www.lawnext.com/2025/12/harvey-cofounders-answer-tough-questions-in-reddit-ama-valuation-competition-and-the-future-of-legal-ai.html))
- Fishbowl thread 'More and more lawyers at the firm are complaining about Harvey AI'; one associate says it gets them 20% of the way and they always catch errors; other replies are positive. ([source](https://www.fishbowlapp.com/post/more-and-more-lawyers-at-the-firm-are-complaining-about-harvey-ai-anyone-else-having-bad-experiences))

## Why current tools don't solve it

Vendors report no per-answer confidence or verification status, so every answer looks equally authoritative. None separates verified claims (quote found in source, authority exists and is in force) from unverified ones so a lawyer checks only the risky part. Incumbents sell a general assistant and leave workflows, verification and measurement to the firm, instead of packaged workflows whose output is checked by code (computed deadlines, verified quotes, citation status per authority). No independent accuracy benchmark exists for Indian law.

## Panel verdict

**Status:** solved (round 2)

**Effort:** M

### What software can fix

Make trust measurable and checking proportionate. Each answer shows which claims are verified by code and which need the lawyer's eyes, so the lawyer checks only the risky part. We publish honest, reproducible accuracy numbers for the checker on two separate sets. One is a synthetic regression set we build ourselves, labelled as such. The other is a held-out real-world set of actual fabricated and erroneous Indian citations, labelled by advocates who didn't write the checker. Each set is reported with its size, provenance and confidence interval.

### What it can't fix

The model's underlying error rate on legal reasoning (wrong analysis without any citation) can't be made zero, and we don't claim a hallucination-free product. The benchmark is ours, not an independent audit. We say so, and we invite external replication by publishing the method and the synthetic set (and the real-world set after it is retired from held-out use). We can't run competitors' tools without their licences, so we don't claim head-to-head numbers; the public Stanford figures are cited as context only. Adoption inside a firm (training, policy) is a management problem.

### What the user sees

At the top of every agent reply, draft and review grid: '12 authorities: 9 verified by code (identity + quote), 2 need reading (paras shown), 1 removed (not found)'. Clicking expands the ledger. Verified rows collapse; only amber and red rows stay open. Fact mismatches from draft_check count towards the same 'needs you' counter. A /about 'How well the citation check works' section shows two clearly separated tables per release, with the date and dataset version. 'Synthetic regression set (built by us, n=500, generated from SC Open Data)'. 'Real-world held-out set (n=<size>; <k> citations from public court orders reporting fake or wrong citations, <m> from LLM outputs on Indian legal prompts; labelled by two advocates independent of the engineering team, agreement kappa=<x>)'. Each table gives, per class, the share flagged, the share left 'needs reading', and the false-verified rate (a fabrication marked green), with 95% intervals. A line under the tables says what neither set covers well, e.g. HC cases outside the index and paraphrased quotes, which end up 'needs reading'. A /safety tile for partners shows firm-level counts: citations produced, share auto-verified, share removed, median time to clear a ledger.

### What the system does

1. citation_service.summarize is extended to ledger counts by overall status, attached to every agent response, draft checklist and review grid export. 2. Synthetic set: evals/citations_synthetic.jsonl (versioned, about 500 items), built by scripts/build_citation_benchmark.py from SC Open Data with a fixed seed. It contains real citations with real quotes and pins, synthetic fabrications, chimeras, out-of-range pins, altered quotes, wrong-code sections and the publicly reported incident strings. It is a regression test and is labelled 'synthetic' everywhere. 3. Real-world held-out set: evals/realworld/ manifest plus labels stored outside the main repo (private bucket, fetched in CI with a secret; only aggregate metrics are written to logs). Sources: (a) citations described as fake or wrong in public Indian court and tribunal orders (e.g. the Pooja Ramesh Singh, Bombay HC and ITAT incidents), extracted as the citation strings actually filed; (b) citations produced by public LLMs and Indian legal AI tools on a fixed prompt list of Indian legal questions (no client data), stored with model, date and prompt id; (c) our own pipeline's raw drafter output before filtering, from eval replays; (d) correct citations written by judges in SC and HC judgments (short forms, abbreviations), for false-flag measurement. Each item is labelled by two advocates from the knowledge team's panel who did not write or tune the checker: exists / citation matches parties / pin correct / quote verbatim, paraphrased or fabricated. A third advocate adjudicates disagreements, and Cohen's kappa is reported. Labelling uses a form that doesn't show the checker's output. 4. Held-out discipline: engineers tuning the checker never see item-level labels or failures from the held-out set. Each quarter a new batch is collected, and the oldest batch is retired into the public dev set, so the held-out set never becomes a training set. 5. scripts/run_citation_benchmark.py computes, per set and class: flagged recall, not-auto-verified rate, false-verified rate and false-flag rate on real items, with Wilson 95% intervals. A second mode replays evals/cases.json through the real pipeline and measures the agents' raw fabrication rate before filtering and the residual rate in delivered text. 6. CI gate in .github/workflows/deploy.yml on both sets. Synthetic: recall >= 0.99 on fabricated, chimera and fake-quote; false-flag <= 5% on real items. Real-world: false-verified rate <= 1% (a fabrication must not be marked green); false-flag <= 5% on judge-written correct citations; no drop in flagged recall greater than the interval width against the last release. Absolute recall floors for the real-world set are fixed after the first labelled baseline and recorded in the repo. The LLM replay runs nightly, not in CI. 7. Prometheus: citations_checked_total{status}, citation_ledger_clear_seconds. 8. Results are written to evals/results/<release>.json (set name, n, provenance counts, kappa, metrics, intervals); /about renders from that file only.

### Where it is built

app/services/citation_service.py summarize, app/services/draft_check.py, app/services/review_service.py (its verified quotes count as verified claims), scripts/run_evals.py and evals/cases.json, app/core/metrics.py, frontend/src/app/about/page.tsx, frontend/src/app/safety/page.tsx, .github/workflows/deploy.yml. New: scripts/build_citation_benchmark.py, scripts/run_citation_benchmark.py, scripts/collect_llm_citations.py (fixed prompt list, records outputs), evals/citations_synthetic.jsonl, evals/realworld/manifest.json (provenance only; labels held out), docs/benchmark/labelling-guide.md (labelling rules for the advocates).

### Why current tools fail and this won't

Vendors give no per-answer verification status, so every answer looks equally authoritative and lawyers re-check everything (the verification-value paradox). Thomson Reuters denied Stanford access three times. We separate code-verified claims from unverified ones per item, so checking time scales with the risky items, not the answer length. Our published numbers come from two sets, one synthetic and one real-world held out and labelled by advocates who didn't build the checker. Each is shown with its size, provenance and intervals, and the false-verified rate is gated in CI, so a regression on real fabrications can't ship quietly and the numbers can't be read as a circular self-test.

### Safeguards

No 'independent' or 'hallucination-free' claims. The two sets are never merged into one headline number. Method, synthetic set and labelling guide are public so the claims can be checked; real-world items are published after they leave held-out use. The real-world set contains only public court orders, public judgments and LLM outputs on synthetic prompts, never client data. Labelling advocates are paid for their time, named in the release notes with their consent, and are not on the engineering team. Firm dashboards are org-scoped (RLS) and visible to owners and partners only. Removed citations are shown to the lawyer, never silently dropped, in lawyer-facing text (client-facing text keeps the existing for_client drop rule).

### How the panel's objections were answered

The circularity objection is fixed as follows. (a) The word 'independent' is dropped everywhere, and a test asserts it isn't on /about. (b) A held-out real-world set is added: citations reported as fake or wrong in public Indian orders, real outputs from public LLMs and Indian legal AI tools on a fixed list of Indian prompts, our own raw drafter output, and judge-written correct citations (short forms) for false flags. It is labelled by two advocates who didn't write the checker, with third-party adjudication and kappa reported. The labels are kept out of the engineers' reach and the set is rotated quarterly. (c) The two sets are reported separately on /about with size, provenance and 95% intervals. Neither is called 'accuracy' alone; each shows flagged, needs-reading and false-verified rates, plus a stated list of what neither set covers. (d) CI and the /about numbers are gated on both sets, with false-verified <= 1% on real-world fabrications as the main gate.

### Acceptance tests

- pytest tests/test_citation_benchmark.py runs the checker on the synthetic set and asserts its thresholds
- CI job with the held-out set (fixture-mocked in unit tests): a checker change that marks one real-world fabricated item 'verified' pushes false-verified above 1% on a 100-item fixture and fails the build
- The benchmark builder is deterministic: the same seed and SC metadata give an identical jsonl (hash compared)
- The results JSON for each set contains n, provenance counts, kappa (real-world only) and Wilson intervals; the schema test fails if any is missing
- The /about page renders both tables from evals/results JSON; a test fails if the page contains a hard-coded percentage, the word 'independent', or a single combined accuracy number
- Held-out isolation: the benchmark runner's log output contains no item text or item ids from the real-world set (asserted on a fixture run)
- Judge-written short-form citations (fixture of 50 from SC judgments, e.g. 'Puttaswamy', 'Antil v. CBI') give false-flag <= 5%
- An agent reply fixture with 3 verified, 1 attest-needed and 1 invalid citation returns ledger counts {verified:3, needs_reading:1, removed:1}, and the delivered text contains no invalid citation
- citations_checked_total increments by status in a mocked pipeline run

### Reviewers' minor notes

- The test that fails /about if it contains the word 'independent' should be scoped to the benchmark section. The page may legitimately use the word elsewhere (for example 'seek independent legal advice').
- Collecting outputs from 'Indian legal AI tools' may breach their terms of service. Use only tools whose terms permit it, or public LLMs.
- With n near 100, a 1% false-verified gate is effectively 'at most one'. State that explicitly and report the interval next to it.
- Naming the labelling advocates publicly in release notes for a commercial product brushes against BCI Rule 36 (advocates lending their name to promotion). List them as contributors without designation, firm or contact details, and never on marketing pages.
- Collecting outputs from 'Indian legal AI tools' may breach those tools' terms of service. Use only tools whose terms allow benchmarking, or public LLMs.
- Collecting outputs from commercial Indian legal AI tools may breach their terms of service on benchmarking or reuse. Check each tool's terms, or limit source (b) to tools whose terms allow it.
- With few public incidents, the real-world fabricated class will be small and the 1% false-verified gate statistically weak. Report the Wilson interval next to the gate and don't advertise the point estimate alone.
- The held-out-set CI job must skip cleanly on fork PRs that have no secret.

