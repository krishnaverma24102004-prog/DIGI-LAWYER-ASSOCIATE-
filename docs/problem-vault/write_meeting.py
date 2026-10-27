"""Turns the meeting-room workflow's output into meeting.json, meeting/minutes.md and meeting/final-plan.md.

    python docs/problem-vault/write_meeting.py <workflow output file>
"""

import json
import sys
from pathlib import Path

VAULT = Path(__file__).parent

FIELDS = [
    ("solvable_part", "What software can fix"),
    ("out_of_scope", "What it can't fix"),
    ("what_the_user_sees", "What the user sees"),
    ("what_the_system_does", "What the system does"),
    ("build_on", "Where it is built"),
    ("why_incumbents_fail_and_this_wont", "Why current tools fail and this won't"),
    ("safeguards", "Safeguards"),
    ("answers_to_objections", "How the panel's objections were answered"),
]


def solution_markdown(state: dict) -> str:
    p = state.get("proposal") or {}
    lines = [f"**Effort:** {p.get('effort', '?')}", ""]
    for key, label in FIELDS:
        if p.get(key):
            lines += [f"### {label}", "", str(p[key]), ""]
    if p.get("acceptance_tests"):
        lines += ["### Acceptance tests", "", *[f"- {t}" for t in p["acceptance_tests"]], ""]
    if state.get("status") == "open" and state.get("objections"):
        lines += ["### Still blocking", "", *[f"- {o}" for o in state["objections"]], ""]
    if state.get("minor"):
        lines += ["### Reviewers' minor notes", "", *[f"- {m}" for m in state["minor"]], ""]
    return "\n".join(lines)


def main(path: str) -> None:
    result = json.loads(Path(path).read_text(encoding="utf-8"))["result"]
    state, minutes, plan = result["state"], result["minutes"], result["plan"]
    solutions = [
        {"id": pid, "status": s["status"], "round": s.get("round") or "-", "solution_markdown": solution_markdown(s), "proposal": s.get("proposal"),
         "objections": s.get("objections") if s["status"] == "open" else [], "minor": s.get("minor", [])}
        for pid, s in sorted(state.items())
    ]
    (VAULT / "meeting.json").write_text(json.dumps({"solutions": solutions, "minutes": minutes}, ensure_ascii=False, indent=1),
                                        encoding="utf-8", newline="\n")
    meeting = VAULT / "meeting"
    meeting.mkdir(exist_ok=True)
    (meeting / "final-plan.md").write_text(plan, encoding="utf-8", newline="\n")

    out = [
        "# Meeting room minutes",
        "",
        "Eight department heads (litigation, research, client experience, languages, finance and operations,",
        "contracts, risk and ethics, strategy) proposed solutions for the problems they own and sent notes on",
        "the others. Six critics (practitioner, ethics and law, engineering and market, each over two batches)",
        "tried to refute every proposal. A problem was marked solved only when all three lenses reviewed it and",
        "none had a blocking objection; otherwise the objections went back to its owner for the next round.",
        "",
        "| Round | Solved this round | Still open |",
        "| --- | --- | --- |",
    ]
    for m in minutes:
        still = ", ".join(f"{o['id']} ({o['objections']})" for o in m["still_open"]) or "none"
        out.append(f"| {m['round']} | {', '.join(sorted(m['resolved'])) or 'none'} | {still} |")
    solved = sum(s["status"] == "solved" for s in solutions)
    out += ["", f"**Result:** {solved} of {len(solutions)} solved; numbers in brackets are blocking objections left that round.", ""]
    (meeting / "minutes.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"{solved}/{len(solutions)} solved")


if __name__ == "__main__":
    main(sys.argv[1])
