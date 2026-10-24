"""Self-check of a draft before it leaves the firm: what in it isn't backed by the confirmed facts.

A generated draft records the facts it was built from (`drafts.fact_basis`): the values the lawyer
typed, the automatic ones (today's date, the place), the lawyer's notes, the key facts of the case
thread's consultations and the attached documents. The check reads the draft's text and lists:

  * amounts, dates and cheque/account-style numbers that appear nowhere in those facts (the AI may
    have filled them in, misread them, or got a digit wrong)
  * values the lawyer gave that the draft no longer contains (edited away, or a different value)
  * every citation, with its verification status (services/citation_service.py)
  * placeholders still to fill

Nothing here blocks an export: the lawyer sees the list, fixes or keeps each item, and the choice
is logged.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date

from app.services import citation_service, drafting_engine

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9

_AMOUNT = re.compile(r"(?:₹|\bRs\.?|\bINR|\brupees)\s*([\d,]+(?:\.\d{1,2})?)(?:\s*/-)?|\b([\d,]{4,}(?:\.\d{1,2})?)\s*(?:/-|rupees\b)", re.I)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_WORDS = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_DATE_WORDS_US = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_REFERENCE = re.compile(
    r"\b(cheque|check|account|a/c|transaction|utr|invoice|receipt|policy|fir|complaint)\s*(?:no\.?|number|bearing\s+(?:no\.?|number))?\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{3,})",
    re.I,
)


@dataclass
class Finding:
    kind: str  # amount | date | reference | provided_value
    value: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _digits(value: str) -> str:
    return re.sub(r"[^\d.]", "", value).rstrip(".").removesuffix(".00")


def amounts(text: str) -> set[str]:
    found = set()
    for m in _AMOUNT.finditer(text):
        raw = m.group(1) or m.group(2)
        digits = _digits(raw)
        if digits and len(digits.replace(".", "")) >= 3:
            found.add(digits)
    return found


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dates(text: str) -> set[date]:
    found: set[date] = set()
    for d, m, y in _DATE_NUMERIC.findall(text):  # Indian order: day first
        if parsed := _safe_date(int(y), int(m), int(d)):
            found.add(parsed)
    for y, m, d in _DATE_ISO.findall(text):
        if parsed := _safe_date(int(y), int(m), int(d)):
            found.add(parsed)
    for d, month, y in _DATE_WORDS.findall(text):
        if month.lower() in MONTHS and (parsed := _safe_date(int(y), MONTHS[month.lower()], int(d))):
            found.add(parsed)
    for month, d, y in _DATE_WORDS_US.findall(text):
        if month.lower() in MONTHS and (parsed := _safe_date(int(y), MONTHS[month.lower()], int(d))):
            found.add(parsed)
    return found


def references(text: str) -> set[tuple[str, str]]:
    return {(kind.lower(), number.upper().strip("/-")) for kind, number in _REFERENCE.findall(text) if any(c.isdigit() for c in number)}


def draft_text(draft: dict) -> str:
    content = draft.get("content") or {}
    parts = [draft.get("title") or ""]
    for section in content.get("sections") or []:
        parts += [section.get("heading") or "", *section.get("paragraphs", [])]
    parts += content.get("signature_block") or []
    return "\n".join(p for p in parts if p)


def basis_text(basis: dict, documents: list[str] | None = None) -> str:
    """Everything the draft's facts may come from, as one text."""
    parts = [f"{k}: {v}" for k, v in (basis.get("variables") or {}).items() if v]
    parts += [basis.get("notes") or "", *(basis.get("case_facts") or []), *(documents or [])]
    return "\n".join(p for p in parts if p)


def self_check(draft: dict, documents: list[str] | None = None) -> list[Finding]:
    """Values in the draft the confirmed facts don't contain, and given values the draft lost."""
    basis = draft.get("fact_basis") or {}
    text = draft_text(draft)
    if not basis:
        return []
    facts = basis_text(basis, documents)
    findings: list[Finding] = []
    known_amounts, known_dates = amounts(facts), dates(facts)
    known_numbers = {re.sub(r"\D", "", n) for _, n in references(facts)} | set(re.findall(r"\d{4,}", facts))
    for value in sorted(amounts(text) - known_amounts):
        findings.append(Finding("amount", value, "This amount isn't in the facts you gave or the case documents"))
    for value in sorted(dates(text) - known_dates):
        findings.append(Finding("date", value.strftime("%d %B %Y"), "This date isn't in the facts you gave or the case documents"))
    for kind, number in sorted(references(text)):
        if re.sub(r"\D", "", number) not in known_numbers:
            findings.append(Finding("reference", f"{kind} {number}", f"This {kind} number isn't in the facts you gave or the case documents"))
    lowered = text.lower()
    for name, value in (basis.get("provided") or {}).items():
        if value and value.strip().lower() not in lowered:
            findings.append(Finding("provided_value", value, f"You gave {name.replace('_', ' ')} as \"{value}\" but the draft doesn't contain it"))
    return findings


def checklist(draft: dict, sources: citation_service.Sources, documents: list[str] | None = None) -> dict:
    """What a lawyer should look at before exporting or approving the draft."""
    text = draft_text(draft)
    checks = citation_service.check(text, sources)
    findings = self_check(draft, documents)
    unresolved = [c.as_dict() for c in checks if c.flagged or c.status == "repealed"]
    return {
        "approved": bool(draft.get("approved_at")),
        "approved_by": draft.get("approved_by"),
        "approved_at": draft.get("approved_at"),
        "missing": [m.group(0)[2:-2] for m in drafting_engine.PLACEHOLDER.finditer(text)],
        "citations": [c.as_dict() for c in checks],
        "unresolved_citations": unresolved,
        "mismatches": [f.as_dict() for f in findings],
        "fact_basis_recorded": bool(draft.get("fact_basis")),
        "clear": not unresolved and not findings,
    }


UNRESOLVED_PLACEHOLDER = "[●citation to be confirmed●]"


def without_unresolved(draft: dict, sources: citation_service.Sources) -> dict:
    """A copy of the draft with each unverified or invalid citation replaced by a placeholder."""
    def clean(text: str) -> str:
        for c in sorted((c for c in citation_service.check(text, sources) if c.flagged), key=lambda c: c.start, reverse=True):
            text = text[: c.start] + UNRESOLVED_PLACEHOLDER + text[c.end :]
        return text

    content = draft.get("content") or {}
    return {
        **draft,
        "title": clean(draft.get("title") or ""),
        "content": {
            "sections": [{"heading": clean(s["heading"]) if s.get("heading") else s.get("heading"),
                          "paragraphs": [clean(p) for p in s.get("paragraphs", [])]} for s in content.get("sections") or []],
            "signature_block": [clean(line) for line in content.get("signature_block") or []],
        },
    }
