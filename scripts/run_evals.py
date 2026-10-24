"""Quality evals for the live agents: run evals/cases.json against the configured model.

Each case is replayed turn by turn through the real pipeline (PII masking, the LangGraph agents,
citation verification), using whichever model .env configures (Claude, or a gateway / Ollama
model for testing). A case passes when every expectation holds:

  language      the last reply is in the expected language (english / hinglish / hindi)
  keywords      each any-of group appears in the replies, risks or facts
  facts, risks  each any-of group appears among the extracted facts / legal risks
  forbidden     none of these phrases appear in a reply (guarantees, directives)
  never_sent    none of these identifiers reach the model (they must be masked)
  citations     no reply contains an invalid or unverified citation

Usage:  python scripts/run_evals.py [--case cheque_bounce_hindi] [--out evals/results]
Report: a table on stdout and a JSON file per run, for comparing models and prompt changes.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.guardrails import PiiMasker, mask_pii  # noqa: E402
from app.services import agent_workflow, anthropic_service, citation_service, jurisdiction_service  # noqa: E402
from app.services.agent_workflow import AgentContext  # noqa: E402

HINGLISH_WORDS = {"hai", "hain", "ka", "ki", "ke", "mein", "aap", "aapke", "nahi", "kya", "ko", "se", "bhi", "sakte", "karna", "kar"}


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if letters and sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters) > 0.3:
        return "hindi"
    words = re.findall(r"[a-z]+", text.lower())
    if words and sum(w in HINGLISH_WORDS for w in words) / len(words) > 0.08:
        return "hinglish"
    return "english"


def _has_any(text: str, group: list[str]) -> bool:
    text = text.lower()
    return any(k.lower() in text for k in group)


def _lookup():
    """The citation index (read-only), when Supabase is configured; else no lookups."""
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key):
        return None
    from app.database import get_supabase_admin

    async def lookup(keys, names):
        return await asyncio.to_thread(citation_service.lookup_authorities, get_supabase_admin(), keys, names)

    return lookup


async def run_case(case: dict) -> dict:
    masker = PiiMasker()
    profile = jurisdiction_service.get_profile(case.get("jurisdiction"))
    context = AgentContext(mode=case.get("mode", "copilot"), jurisdiction=profile, lookup_authorities=_lookup())
    history: list[str] = []
    state: dict = {}
    replies, citations, errors = [], [], []
    started = time.monotonic()
    for turn in case["turns"]:
        masked = mask_pii(turn, masker).text
        line = masked if re.match(r"^\w+:", masked) else f"Client: {masked}"
        history.append(line)
        state = {**state, "transcript_history": "\n".join(history), "current_chunk": line}
        result = await agent_workflow.process_audio_chunk_via_agent(state, context)
        state = {k: result[k] for k in ("extracted_facts", "rag_citations", "web_results", "legal_risks",
                                        "contract_observations", "follow_up_questions") if k in result}
        errors += result.get("errors", [])
        final = result.get("final_response") or {}
        if final.get("message"):
            replies.append(final["message"])
            citations += final.get("citations", [])
            if context.mode == "conversation":
                history.append(f"AI Assistant: {final['message']}")
    elapsed = time.monotonic() - started

    facts = " | ".join(f.get("fact", "") for f in state.get("extracted_facts", []))
    risks = " | ".join(" ".join(filter(None, [r.get("issue"), r.get("area_of_law"), r.get("rationale"), r.get("authority")]))
                       for r in state.get("legal_risks", []))
    everything = " ".join([*replies, facts, risks])
    expect = case.get("expect", {})
    checks: dict[str, bool] = {}
    if "language" in expect:
        checks["language"] = bool(replies) and detect_language(replies[-1]) == expect["language"]
    for i, group in enumerate(expect.get("keywords", [])):
        checks[f"keyword:{group[0]}"] = _has_any(everything, group)
    for group in expect.get("facts", []):
        checks[f"fact:{group[0]}"] = _has_any(facts, group)
    for group in expect.get("risks", []):
        checks[f"risk:{group[0]}"] = _has_any(risks, group)
    if expect.get("forbidden"):
        checks["no_forbidden"] = not any(_has_any(r, expect["forbidden"]) for r in replies)
    if expect.get("never_sent_to_model"):
        sent = "\n".join(history)
        checks["pii_masked"] = not any(value in sent for value in expect["never_sent_to_model"])
    flagged = [c for c in citations if c["status"] in ("invalid", "unverified")]
    if not expect.get("allow_flagged_citations"):  # some cases test that a bad citation IS flagged
        checks["citations_clean"] = not flagged
    checks["no_agent_errors"] = not errors
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "seconds": round(elapsed, 1),
        "reply": replies[-1] if replies else None,
        "language": detect_language(replies[-1]) if replies else None,
        "citations": citations,
        "flagged_citations": flagged,
        "errors": errors,
    }


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent quality evals")
    parser.add_argument("--cases", default=str(ROOT / "evals" / "cases.json"))
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument("--out", default=str(ROOT / "evals" / "results"))
    args = parser.parse_args(argv)

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    settings = get_settings()
    model = settings.anthropic_live_model
    results = []
    for case in cases:
        result = await run_case(case)
        results.append(result)
        failed = [name for name, ok in result["checks"].items() if not ok]
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {case['id']:<28} {result['seconds']:>6}s  {', '.join(failed)}")
    await anthropic_service.close_client()

    checks = [ok for r in results for ok in r["checks"].values()]
    summary = {
        "model": model,
        "structured_output": settings.anthropic_structured_output,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "cases_passed": f"{sum(r['passed'] for r in results)}/{len(results)}",
        "checks_passed": f"{sum(checks)}/{len(checks)}",
        "flagged_citations": sum(len(r["flagged_citations"]) for r in results),
        "avg_seconds_per_case": round(sum(r["seconds"] for r in results) / max(len(results), 1), 1),
    }
    print(json.dumps(summary, indent=2))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out / f"{stamp}-{re.sub(r'[^A-Za-z0-9.-]', '_', model)}.json"
    path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
