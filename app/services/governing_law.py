"""Which law a contract says governs it, and whether the analysis assumed the same one.

Redlines and review grids analyse a contract under the jurisdiction the lawyer picked. When the
contract's own governing-law clause names a different one (an English-law supply agreement reviewed
as Indian law, say), conclusions about validity and enforceability may not hold. This finds the
clause, maps it to a jurisdiction code, and produces the caveat shown with those conclusions.

Detection is a plain reading of the usual clause wordings ("governed by the laws of India",
"Governing Law: England and Wales", "courts at Mumbai shall have exclusive jurisdiction"): when no
clause is found, nothing is assumed.
"""

import re

from app.services import jurisdiction_service

_PLACE = r"(?P<place>[A-Z][\w.&'-]*(?:\s+(?:and\s+|of\s+|the\s+)?[A-Z][\w.&'-]*){0,5})"
_GOVERNED = re.compile(
    r"(?:governed\s+by|construed\s+(?:and\s+enforced\s+)?in\s+accordance\s+with|subject\s+to)\s+(?:and\s+construed\s+in\s+accordance\s+with\s+)?"
    rf"(?:the\s+)?laws?\s+(?:of|in\s+force\s+in)\s+(?:the\s+)?{_PLACE}",
    re.I,
)
_HEADING = re.compile(rf"governing\s+law\s*[:.\-–]\s*(?:the\s+)?(?:laws?\s+of\s+)?(?:the\s+)?{_PLACE}", re.I)
_COURTS = re.compile(
    rf"(?:exclusive\s+)?jurisdiction\s+of\s+(?:the\s+)?(?:competent\s+)?courts?\s+(?:at|of|in)\s+{_PLACE}"
    rf"|courts?\s+(?:at|of|in)\s+{_PLACE.replace('place', 'place2')}\s+(?:shall|will)\s+have\s+(?:exclusive\s+)?jurisdiction",
    re.I,
)

INDIA = {
    "india", "republic of india", "union of india", "delhi", "new delhi", "mumbai", "bombay", "maharashtra", "karnataka",
    "bengaluru", "bangalore", "chennai", "madras", "tamil nadu", "kolkata", "calcutta", "west bengal", "hyderabad",
    "telangana", "gujarat", "ahmedabad", "pune", "uttar pradesh", "noida", "gurugram", "gurgaon", "haryana", "kerala",
    "rajasthan", "jaipur", "punjab", "chandigarh", "goa", "madhya pradesh", "bihar", "odisha", "assam",
}
UK = {"england", "england and wales", "wales", "united kingdom", "uk", "u.k", "scotland", "northern ireland", "london"}
US = {"united states", "united states of america", "usa", "u.s", "u.s.a", "new york city"}
OTHER = {"singapore": "Singapore", "hong kong": "Hong Kong", "dubai": "the UAE", "united arab emirates": "the UAE",
         "uae": "the UAE", "switzerland": "Switzerland", "ireland": "Ireland", "germany": "Germany", "france": "France"}
_STATE_CODES = {name.lower(): abbr for abbr, name in jurisdiction_service.US_STATES.items()}

ENFORCEABILITY = re.compile(
    r"\b(?:un)?enforceab\w*|\bvoid(?:able)?\b|\b(?:in)?valid(?:ity)?\b|\b(?:not\s+)?binding\b|\billegal\b|\bunlawful\b"
    r"|\bstruck\s+down\b|\bsever(?:ed|able|ability)\b",
    re.I,
)


def _clean(place: str) -> str:
    place = re.split(r"\s+(?:and\s+the|without|excluding|shall|will|as|which|to|for|in\s+respect)\b", place, maxsplit=1, flags=re.I)[0]
    return place.strip(" .,;:")


def _code_for(place: str) -> tuple[str | None, str]:
    """(jurisdiction code or None, display name) for a place named in a contract."""
    key = re.sub(r"^(?:the\s+)?(?:state\s+of\s+)?", "", place.lower()).strip(" .")
    if key in INDIA or key.endswith(" india"):
        return "IN", "India"
    if key in UK:
        return "UK", "England and Wales" if key in ("england", "england and wales", "wales", "london") else place
    if key in _STATE_CODES:
        return f"US-{_STATE_CODES[key]}", f"the State of {jurisdiction_service.US_STATES[_STATE_CODES[key]]}"
    if key in US:
        return "US", "the United States"
    if key in OTHER:
        return None, OTHER[key]
    return None, place


def detect(text: str | None) -> dict | None:
    """The contract's governing law: {"code", "law", "quote", "basis": "clause" | "courts"}, or None."""
    if not text:
        return None
    for pattern, basis in ((_GOVERNED, "clause"), (_HEADING, "clause"), (_COURTS, "courts")):
        for match in pattern.finditer(text):
            place = _clean(match.groupdict().get("place") or match.groupdict().get("place2") or "")
            if len(place) < 2 or place.lower() in ("this", "such", "any", "applicable", "the parties"):
                continue
            code, law = _code_for(place)
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            quote = re.sub(r"\s+", " ", text[start : end if end != -1 else len(text)]).strip()[:300]
            return {"code": code, "law": law, "quote": quote, "basis": basis}
    return None


def _family(code: str | None) -> str | None:
    return code.split("-")[0] if code else None


def assess(found: dict | None, selected: jurisdiction_service.JurisdictionProfile | None) -> dict:
    """Whether the analysis assumed the contract's own law, and the caveat to show when it didn't."""
    if found is None or selected is None:
        return {"detected": found, "selected": selected.code if selected else None, "mismatch": False, "caveat": None}
    code = found.get("code")
    mismatch = (
        code is None
        or _family(code) != _family(selected.code)
        or ("-" in code and "-" in selected.code and code != selected.code)
    )
    caveat = None
    if mismatch:
        caveat = (
            f"The contract says it is governed by the law of {found['law']}, but this analysis applies "
            f"{selected.name} law. Conclusions about validity or enforceability may not hold under the contract's law."
        )
    return {"detected": found, "selected": selected.code, "mismatch": mismatch, "caveat": caveat}


def concerns_enforceability(text: str | None) -> bool:
    """Whether a conclusion turns on which law applies (valid, void, enforceable, binding...)."""
    return bool(text and ENFORCEABILITY.search(text))
