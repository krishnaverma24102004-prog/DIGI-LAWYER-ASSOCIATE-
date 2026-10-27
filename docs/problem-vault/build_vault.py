"""Builds the problem vault's Markdown pages from problems.json (and meeting.json, once the panel has met).

    python docs/problem-vault/build_vault.py
"""

import json
import re
from pathlib import Path

VAULT = Path(__file__).parent


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main() -> None:
    problems = json.loads((VAULT / "problems.json").read_text(encoding="utf-8"))["problems"]
    meeting_path = VAULT / "meeting.json"
    verdicts = {}
    if meeting_path.exists():
        verdicts = {v["id"]: v for v in json.loads(meeting_path.read_text(encoding="utf-8")).get("solutions", [])}

    pages = VAULT / "problems"
    pages.mkdir(exist_ok=True)
    rows = []
    for n, p in enumerate(problems, 1):
        pid = f"P{n:02d}"
        name = f"{pid}-{slug(p['title'])}.md"
        lines = [
            f"# {pid}. {p['title']}",
            "",
            f"**Severity:** {p['severity']} · **Size:** {p['size']} · **Region:** {p['region']}",
            "",
            f"**Who has it:** {p['who']}",
            "",
            "## What goes wrong",
            "",
            p["description"],
            "",
            "## Evidence of scale",
            "",
            *[f"- {e['claim']} ([source]({e['source_url']}))" for e in p["scale_evidence"]],
            "",
            "## Why current tools don't solve it",
            "",
            p["current_tools_gap"],
            "",
        ]
        v = verdicts.get(pid)
        if v:
            lines += ["## Panel verdict", "", f"**Status:** {v['status']} (round {v.get('round', '?')})", ""]
            lines += [v.get("solution_markdown", ""), ""]
        (pages / name).write_text("\n".join(lines), encoding="utf-8", newline="\n")
        status = verdicts.get(pid, {}).get("status", "open")
        rows.append(f"| [{pid}](problems/{name}) | {p['title']} | {p['severity']} | {p['size']} | {p['region']} | {status} |")

    index = [
        "# Problem vault",
        "",
        "Problems law firms, lawyers and their clients face, small and big, in India and worldwide,",
        "with evidence of scale and why today's tools (Harvey, CoCounsel, Lexis+ AI, Clio, Indian",
        "trackers) don't solve them. Researched on the web by eight parallel agents, each fact-checked",
        "by a second agent (claims without a confirmable source were dropped), plus social signals",
        "from X, YouTube and Instagram ([sources/social-signals.md](sources/social-signals.md)).",
        "",
        "The panel's solutions for each problem are in [meeting/](meeting/) and on each page.",
        "",
        "| ID | Problem | Severity | Size | Region | Panel |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
    ]
    (VAULT / "README.md").write_text("\n".join(index), encoding="utf-8", newline="\n")
    print(f"{len(problems)} problem pages written")


if __name__ == "__main__":
    main()
