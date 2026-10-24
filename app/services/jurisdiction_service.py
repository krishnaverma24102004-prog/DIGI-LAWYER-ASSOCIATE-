"""Multi-jurisdiction statutory frameworks: India, United States (federal + state), UK.

A jurisdiction code selects:
  * the statutory framework and practice notes injected into every agent prompt
    (prompt_engine.build_system), e.g. India's 2024 criminal-law codes replacing the IPC,
    CrPC and Evidence Act for offences on or after 1 July 2024;
  * the citation style used when the agents and the drafting engine cite authority
    (Indian SCC/AIR conventions, Bluebook, OSCOLA), with deterministic formatters here;
  * the knowledge-base filter: RAG search only returns passages tagged with an applicable
    jurisdiction (US-CA also matches US federal material) or untagged firm material.

Codes: "IN", "US" (federal), "US-XX" (a state, e.g. "US-CA"), "UK" (England & Wales).

The profiles describe frameworks and conventions; they are not a statement of the law.
Section correspondences (e.g. IPC 302 -> BNS 103) should be checked against the official
tables before being relied on in a filing.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

CitationStyle = Literal["indian", "bluebook", "oscola"]


@dataclass(frozen=True)
class JurisdictionProfile:
    code: str
    name: str
    citation_style: CitationStyle
    citation_style_name: str
    frameworks: list[str]
    guidance: list[str]
    citation_examples: list[str]
    # Knowledge-base tags this jurisdiction may use (most specific first).
    rag_codes: list[str] = field(default_factory=list)
    date_format: str = "%d %B %Y"
    currency: str = ""


INDIA = JurisdictionProfile(
    code="IN",
    name="India",
    citation_style="indian",
    citation_style_name="Indian citation (SCC / AIR / neutral citations)",
    frameworks=[
        "Bharatiya Nyaya Sanhita, 2023 (BNS): substantive criminal law, replacing the Indian Penal Code, 1860 (IPC)",
        "Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS): criminal procedure, replacing the Code of Criminal Procedure, 1973 (CrPC)",
        "Bharatiya Sakshya Adhiniyam, 2023 (BSA): evidence, replacing the Indian Evidence Act, 1872",
        "Indian Contract Act, 1872; Specific Relief Act, 1963; Code of Civil Procedure, 1908; Limitation Act, 1963",
        "Constitution of India; Consumer Protection Act, 2019; Negotiable Instruments Act, 1881 (s. 138 cheque dishonour)",
    ],
    guidance=[
        "The BNS, BNSS and BSA apply to offences and proceedings from 1 July 2024. Offences committed before that date "
        "generally remain under the IPC, CrPC and Evidence Act: check the date of the alleged offence before citing a code.",
        "When citing a new-code section, give the corresponding old section in brackets where it helps "
        "(e.g. 'Section 103 BNS (formerly Section 302 IPC)'). When the date of the offence is not known, give both "
        "and say which applies when (e.g. 'Section 103 BNS, or Section 302 IPC if the offence was before 1 July 2024').",
        "Bail: regular bail under ss. 480 and 483 BNSS (formerly ss. 437 and 439 CrPC); anticipatory bail under s. 482 BNSS "
        "(formerly s. 438 CrPC).",
        "Electronic records require the certificate under s. 63 BSA (formerly s. 65B Evidence Act).",
        "Limitation periods come from the Limitation Act, 1963 schedule; flag them when a claim may be time-barred.",
    ],
    citation_examples=[
        "<Party> v. <Party>, (<year>) <volume> SCC <page>",
        "<Party> v. <Party>, AIR <year> <court> <page>",
        "Section <number>, <Act name>, <year>",
    ],
    rag_codes=["IN"],
    currency="INR",
)

UNITED_STATES = JurisdictionProfile(
    code="US",
    name="United States (federal)",
    citation_style="bluebook",
    citation_style_name="The Bluebook",
    frameworks=[
        "U.S. Constitution; United States Code (U.S.C.); Code of Federal Regulations (C.F.R.)",
        "Federal Rules of Civil Procedure, Criminal Procedure and Evidence",
        "State law governs most contract, tort, property and family matters: identify the governing state",
    ],
    guidance=[
        "Identify whether federal or state law governs, and which state, before analysing; flag choice-of-law clauses.",
        "Distinguish binding authority (the governing state's courts or the relevant federal circuit) from persuasive authority.",
        "Statutes of limitation vary by state and claim type; flag possible time bars.",
    ],
    citation_examples=[
        "<Party> v. <Party>, <volume> U.S. <page>, <pinpoint> (<year>)",
        "<Party> v. <Party>, <volume> F.3d <page> (<circuit> Cir. <year>)",
        "<title> U.S.C. § <section>",
    ],
    rag_codes=["US"],
    date_format="%B %d, %Y",
    currency="USD",
)

UNITED_KINGDOM = JurisdictionProfile(
    code="UK",
    name="United Kingdom (England & Wales)",
    citation_style="oscola",
    citation_style_name="OSCOLA",
    frameworks=[
        "Common law of England and Wales; Senior Courts and county court practice (Civil Procedure Rules)",
        "Companies Act 2006; Insolvency Act 1986; Consumer Rights Act 2015; Misrepresentation Act 1967",
        "Limitation Act 1980; Unfair Contract Terms Act 1977; Housing Act 1988 (tenancies)",
    ],
    guidance=[
        "Scotland and Northern Ireland have separate legal systems: confirm the matter is governed by English law.",
        "Pre-action protocols under the CPR set out what a letter before claim must contain; follow them for notices.",
        "Cite neutral citations where available, then the law report.",
    ],
    citation_examples=[
        "<Party> v <Party> [<year>] AC <page> (HL) <pinpoint>",
        "<Party> v <Party> [<year>] UKSC <number>",
        "<Act name> <year>, s <section>",
    ],
    rag_codes=["UK"],
    currency="GBP",
)

PROFILES = {p.code: p for p in (INDIA, UNITED_STATES, UNITED_KINGDOM)}

_ALIASES = {
    "IN": "IN", "INDIA": "IN", "INDIAN": "IN", "BHARAT": "IN",
    "US": "US", "USA": "US", "UNITED STATES": "US", "FEDERAL": "US", "US FEDERAL": "US",
    "UK": "UK", "GB": "UK", "UNITED KINGDOM": "UK", "ENGLAND": "UK", "ENGLAND & WALES": "UK",
    "ENGLAND AND WALES": "UK", "E&W": "UK",
}


class UnknownJurisdiction(ValueError):
    pass


def normalize(value: str | None) -> str | None:
    """Map free text ("India", "California", "US-ca", "England & Wales") to a code, or None if unknown."""
    if not value or not value.strip():
        return None
    text = re.sub(r"\s+", " ", value.strip().upper())
    if text in _ALIASES:
        return _ALIASES[text]
    match = re.fullmatch(r"US[-_ ]([A-Z]{2})", text)
    if match and match.group(1) in US_STATES:
        return f"US-{match.group(1)}"
    for abbr, state in US_STATES.items():
        if text == state.upper():
            return f"US-{abbr}"
    return None


def get_profile(code: str | None) -> JurisdictionProfile | None:
    """The profile for a code (a state code gets the US profile specialised to that state)."""
    code = normalize(code) if code else None
    if code is None:
        return None
    if code.startswith("US-"):
        state = US_STATES[code[3:]]
        return JurisdictionProfile(
            code=code,
            name=f"United States: {state} (state) and federal",
            citation_style="bluebook",
            citation_style_name="The Bluebook",
            frameworks=[f"{state} statutes and case law", *UNITED_STATES.frameworks],
            guidance=[
                f"{state} law governs unless a federal question or a choice-of-law clause points elsewhere.",
                *UNITED_STATES.guidance[1:],
            ],
            citation_examples=UNITED_STATES.citation_examples,
            rag_codes=[code, "US"],
            date_format=UNITED_STATES.date_format,
            currency="USD",
        )
    return PROFILES[code]


def require_profile(code: str | None) -> JurisdictionProfile | None:
    """Like get_profile, but an unrecognised non-empty value is an error."""
    if code is None or not str(code).strip():
        return None
    profile = get_profile(code)
    if profile is None:
        raise UnknownJurisdiction(f"Unknown jurisdiction {code!r}. Use IN, US, US-<state>, or UK.")
    return profile


def rag_filter(code: str | None) -> list[str] | None:
    """Knowledge-base jurisdiction tags to search (untagged passages are always included)."""
    profile = get_profile(code)
    return profile.rag_codes if profile else None


def render_guidance(profile: JurisdictionProfile) -> str:
    lines = [f"Jurisdiction: {profile.name}.", "", "Applicable frameworks:"]
    lines += [f"- {f}" for f in profile.frameworks]
    lines += ["", "Practice notes:"] + [f"- {g}" for g in profile.guidance]
    lines += [
        "",
        f"Citation style: {profile.citation_style_name}. Format every citation in this pattern "
        "(fill the <placeholders> only from the authority you were given):",
        *(f"- {e}" for e in profile.citation_examples),
        "Never invent citations, reporters, volumes or page numbers: cite only authority you were given, "
        "and say when a point needs authority the lawyer should find.",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- citations


@dataclass
class CaseCitation:
    parties: str  # "Brown v. Board of Education"
    year: int
    reporter: str = ""  # "U.S.", "F.3d", "SCC", "AC", "AIR SC"
    page: int | str | None = None
    volume: int | str | None = None
    court: str = ""  # "9th Cir.", "HL", "SC"
    pinpoint: int | str | None = None
    neutral: str = ""  # "[2019] UKSC 41"


@dataclass
class StatuteCitation:
    title: str  # "Bharatiya Nyaya Sanhita", "Companies Act", "U.S.C."
    section: str
    year: int | None = None
    title_number: int | None = None  # 42 in 42 U.S.C.


def _parties(parties: str, style: CitationStyle) -> str:
    parties = re.sub(r"\s+v[s]?\.?\s+", " v ", parties.strip())
    return parties if style == "oscola" else parties.replace(" v ", " v. ")


def format_case(c: CaseCitation, style: CitationStyle) -> str:
    parties = _parties(c.parties, style)
    pin = f", {c.pinpoint}" if c.pinpoint and style == "bluebook" else ""
    if style == "bluebook":
        court = f"{c.court} " if c.court and c.reporter not in ("U.S.", "S. Ct.") else ""
        return f"{parties}, {c.volume} {c.reporter} {c.page}{pin} ({court}{c.year})"
    if style == "oscola":
        if c.neutral:
            report = f", [{c.year}] {c.volume + ' ' if c.volume else ''}{c.reporter} {c.page}" if c.reporter else ""
            return f"{parties} {c.neutral}{report}{f' [{c.pinpoint}]' if c.pinpoint else ''}"
        court = f" ({c.court})" if c.court else ""
        return f"{parties} [{c.year}] {c.volume + ' ' if c.volume else ''}{c.reporter} {c.page}{court}{f' {c.pinpoint}' if c.pinpoint else ''}"
    # Indian: SCC is cited by year in round brackets; AIR by year then court.
    if c.reporter.upper() == "SCC":
        return f"{parties}, ({c.year}) {c.volume} SCC {c.page}{f' at {c.pinpoint}' if c.pinpoint else ''}"
    if c.reporter.upper().startswith("AIR"):
        court = c.reporter[3:].strip() or c.court or "SC"
        return f"{parties}, AIR {c.year} {court} {c.page}"
    return f"{parties}, {c.year} {c.reporter} {c.page}".strip()


def format_statute(s: StatuteCitation, style: CitationStyle) -> str:
    if style == "bluebook":
        if s.title_number:
            return f"{s.title_number} {s.title} § {s.section}" + (f" ({s.year})" if s.year else "")
        return f"{s.title} § {s.section}"
    if style == "oscola":
        return f"{s.title}{f' {s.year}' if s.year else ''}, s {s.section}"
    return f"Section {s.section}, {s.title}{f', {s.year}' if s.year else ''}"


# Commonly cited correspondences between the old and new Indian criminal codes.
# Verify against the official correspondence tables before relying on them in a filing.
IPC_TO_BNS = {
    "34": "3(5)", "120B": "61(2)", "302": "103(1)", "304B": "80", "307": "109", "354": "74", "376": "64",
    "379": "303(2)", "406": "316(2)", "420": "318(4)", "498A": "85", "506": "351(2)",
}
CRPC_TO_BNSS = {
    "41": "35", "125": "144", "154": "173", "161": "180", "164": "183", "437": "480", "438": "482", "439": "483",
}
EVIDENCE_TO_BSA = {"25": "23", "65B": "63"}


CORRESPONDENCE_CAVEAT = "indicative correspondence: check the official table"
_REVERSE = {
    "BNS": ("IPC", IPC_TO_BNS), "BNSS": ("CrPC", CRPC_TO_BNSS), "BSA": ("Evidence Act", EVIDENCE_TO_BSA),
}


def old_code_section(code: str, section: str) -> str | None:
    """'BNS', '103' -> 'Section 302 IPC'; None if not in the table. The reverse of new_code_section."""
    entry = _REVERSE.get(code.upper())
    if entry is None:
        return None
    old_name, table = entry
    base = re.match(r"\d+[A-Z]*", section.upper())
    for old, new in table.items():
        if base and re.match(r"\d+[A-Z]*", new).group(0) == base.group(0):
            return f"Section {old} {old_name}"
    return None


def new_code_section(code: str, section: str) -> str | None:
    """'IPC', '302' -> 'Section 103(1) BNS (formerly Section 302 IPC)'; None if not in the table."""
    tables = {"IPC": (IPC_TO_BNS, "BNS"), "CRPC": (CRPC_TO_BNSS, "BNSS"), "IEA": (EVIDENCE_TO_BSA, "BSA"),
              "EVIDENCE ACT": (EVIDENCE_TO_BSA, "BSA")}
    key = code.upper().replace(".", "")
    if key not in tables:
        return None
    table, new_code = tables[key]
    new = table.get(section.upper())
    old_name = "Evidence Act" if new_code == "BSA" else code.upper().replace("CRPC", "CrPC")
    return f"Section {new} {new_code} (formerly Section {section.upper()} {old_name})" if new else None
