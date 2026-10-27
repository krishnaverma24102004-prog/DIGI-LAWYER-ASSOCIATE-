"""Citation verification: what the agents cite is checked in code, not only by the prompt.

Every statute section and case the agents write is extracted and given a status:

  grounded      it appears in the sources the agent was given: knowledge-base passages, web
                results, the attached document, the conversation or the case history
  known_case    not in the sources, but a real judgment in the citation index (legal_authorities)
  statute       not in the sources, but the act is in the registry below and the section exists
  repealed      an IPC / CrPC / Indian Evidence Act section: valid only for offences and
                proceedings before 1 July 2024 (the note gives the BNS / BNSS / BSA equivalent)
  invalid       the section doesn't exist in that act (e.g. Section 600 BNS): fabricated
  unverified    a case, or an act the registry doesn't know, that the sources don't contain

Invalid and unverified citations are flagged in the text ("[unverified]") and removed from a legal
issue's supporting authority, so nothing fabricated is presented as authority. In text meant for
clients (`for_client`), sentences with such a citation are dropped instead, and spoken replies name
no citations at all (`spoken`).

The criminal codes changed on 1 July 2024: a BNS / BNSS / BSA section gets a note naming the old
section for earlier offences, and an IPC / CrPC / Evidence Act section the new one (from a table of
common correspondences: indicative, to be checked against the official table).

Each check carries a plain `label` for the lawyer saying exactly what was and wasn't checked.

The registry checks that a section *exists*, not that it says what the agent claims. Section
counts are of the enacted texts; lettered sections (498A, 65B) were inserted by amendment into the
older acts, so letters are accepted there but not in the 2023 codes.
"""

import re
from dataclasses import asdict, dataclass, field

from app.services import jurisdiction_service

FLAG = " [unverified]"


@dataclass(frozen=True)
class Act:
    key: str
    name: str
    aliases: tuple[str, ...]
    max_section: int | None  # None: the act is known, its sections aren't checked
    unit: str = "Section"
    lettered: bool = True
    replaced_by: str | None = None  # the 2023 code that replaced it


ACTS: tuple[Act, ...] = (
    Act("BNS", "Bharatiya Nyaya Sanhita, 2023", ("Bharatiya Nyaya Sanhita", "BNS"), 358, lettered=False),
    Act("BNSS", "Bharatiya Nagarik Suraksha Sanhita, 2023", ("Bharatiya Nagarik Suraksha Sanhita", "BNSS"), 531, lettered=False),
    Act("BSA", "Bharatiya Sakshya Adhiniyam, 2023", ("Bharatiya Sakshya Adhiniyam", "BSA"), 170, lettered=False),
    Act("IPC", "Indian Penal Code, 1860", ("Indian Penal Code", "Penal Code", "IPC", "I.P.C."), 511, replaced_by="BNS"),
    Act("CRPC", "Code of Criminal Procedure, 1973", ("Code of Criminal Procedure", "CrPC", "Cr.P.C.", "Cr. P.C."), 484, replaced_by="BNSS"),
    Act("IEA", "Indian Evidence Act, 1872", ("Indian Evidence Act", "Evidence Act", "IEA"), 167, replaced_by="BSA"),
    Act("CONSTITUTION", "Constitution of India", ("Constitution of India", "Constitution"), 395, unit="Article"),
    Act("CPC", "Code of Civil Procedure, 1908", ("Code of Civil Procedure", "CPC", "C.P.C."), 158),
    Act("ICA", "Indian Contract Act, 1872", ("Indian Contract Act", "Contract Act"), 238),
    Act("NIA", "Negotiable Instruments Act, 1881", ("Negotiable Instruments Act", "N.I. Act", "NI Act"), 147),
    Act("SRA", "Specific Relief Act, 1963", ("Specific Relief Act",), 44),
    Act("LIMITATION", "Limitation Act, 1963", ("Limitation Act",), 32),
    # "Article 116 of the Schedule to the Limitation Act": the periods themselves, numbered as articles.
    Act("LIMITATION_SCHEDULE", "Schedule to the Limitation Act, 1963", ("Schedule to the Limitation Act",), 137,
        unit="Article", lettered=False),
    Act("COMMERCIAL_COURTS", "Commercial Courts Act, 2015", ("Commercial Courts Act",), 23),
    Act("TPA", "Transfer of Property Act, 1882", ("Transfer of Property Act", "TPA"), 137),
    Act("CPA", "Consumer Protection Act, 2019", ("Consumer Protection Act",), 107),
    Act("ARBITRATION", "Arbitration and Conciliation Act, 1996", ("Arbitration and Conciliation Act", "Arbitration Act"), 87),
    Act("COMPANIES", "Companies Act, 2013", ("Companies Act",), 470),
    Act("IT_ACT", "Information Technology Act, 2000", ("Information Technology Act", "IT Act"), 94),
    Act("HMA", "Hindu Marriage Act, 1955", ("Hindu Marriage Act", "HMA"), 30),
    Act("HSA", "Hindu Succession Act, 1956", ("Hindu Succession Act",), 31),
    Act("SMA", "Special Marriage Act, 1954", ("Special Marriage Act",), 51),
    Act("ISA", "Indian Succession Act, 1925", ("Indian Succession Act",), 391),
    Act("DV_ACT", "Protection of Women from Domestic Violence Act, 2005",
        ("Protection of Women from Domestic Violence Act", "Domestic Violence Act", "DV Act"), 37),
    Act("MVA", "Motor Vehicles Act, 1988", ("Motor Vehicles Act", "MV Act"), 217),
    Act("PARTNERSHIP", "Indian Partnership Act, 1932", ("Indian Partnership Act", "Partnership Act"), 74),
    Act("SOGA", "Sale of Goods Act, 1930", ("Sale of Goods Act",), 66),
    Act("RERA", "Real Estate (Regulation and Development) Act, 2016",
        ("Real Estate (Regulation and Development) Act", "RERA"), 92),
    Act("IDA", "Industrial Disputes Act, 1947", ("Industrial Disputes Act",), 40),
    Act("GRATUITY", "Payment of Gratuity Act, 1972", ("Payment of Gratuity Act", "Gratuity Act"), 15),
    Act("DPDP", "Digital Personal Data Protection Act, 2023", ("Digital Personal Data Protection Act", "DPDP Act"), 44),
    Act("IBC", "Insolvency and Bankruptcy Code, 2016", ("Insolvency and Bankruptcy Code", "IBC"), 255),
    Act("POCSO", "Protection of Children from Sexual Offences Act, 2012", ("Protection of Children from Sexual Offences Act", "POCSO Act", "POCSO"), 46),
    Act("NDPS", "Narcotic Drugs and Psychotropic Substances Act, 1985", ("Narcotic Drugs and Psychotropic Substances Act", "NDPS Act", "NDPS"), 83),
    Act("UAPA", "Unlawful Activities (Prevention) Act, 1967", ("Unlawful Activities (Prevention) Act", "UAPA"), 53),
    # State rent laws: known acts, sections not checked here.
    Act("MH_RENT", "Maharashtra Rent Control Act, 1999", ("Maharashtra Rent Control Act",), None),
    Act("DL_RENT", "Delhi Rent Control Act, 1958", ("Delhi Rent Control Act",), None),
)

_BY_ALIAS = {alias.lower().replace(" ", ""): act for act in ACTS for alias in act.aliases}
_ALIAS_RE = "|".join(
    re.escape(alias).replace(r"\ ", r"\s+") for alias in sorted({a for act in ACTS for a in act.aliases}, key=len, reverse=True)
)
# A generic act title, for acts the registry doesn't know ("the Kerala Buildings (Lease and Rent Control) Act, 1965").
_GENERIC_ACT = r"(?:[A-Z][\w()&'.-]*\s+){1,9}(?:Act|Code|Sanhita|Adhiniyam)"
_SECTION = r"\d{1,3}[A-Z]{0,2}(?![\w])"
_SECTIONS = rf"{_SECTION}(?:\s*\(\w{{1,4}}\))*(?:\s*(?:,|and|&|/|or)\s*{_SECTION}(?:\s*\(\w{{1,4}}\))*)*"
_SECTION_WORD = r"(?i:sections?|secs?\.?|ss?\.|u/s\.?|articles?|arts?\.)"

_STATUTE_PATTERNS = [
    # Section 138 of the Negotiable Instruments Act, 1881 / ss. 480 and 483 BNSS / Article 21 of the Constitution
    re.compile(rf"\b(?P<word>{_SECTION_WORD})\s*(?P<secs>{_SECTIONS})\s*,?\s*(?:of\s+)?(?:the\s+)?(?P<act>{_ALIAS_RE})\b(?:,?\s*\d{{4}})?", re.I),
    # BNS Section 103 / IPC s. 420
    re.compile(rf"\b(?P<act>{_ALIAS_RE})\s*,?\s*(?:\d{{4}}\s*,?\s*)?(?P<word>{_SECTION_WORD})\s*(?P<secs>{_SECTIONS})", re.I),
    # 420 IPC / 302/34 IPC / 138 NI Act (abbreviations only, so plain numbers before prose aren't caught)
    # (two or more digits, so "2 IPC officers" isn't a citation; not "Order 37 CPC")
    re.compile(r"(?<![\w(/])(?<!Order\s)(?<!Rule\s)(?P<secs>\d{2,3}[A-Z]{0,2}(?![\w])(?:\s*\(\w{1,4}\))*(?:\s*/\s*" + _SECTION + r")*)\s+(?P<act>IPC|BNS|BNSS|BSA|CrPC|Cr\.P\.C\.|CPC|N\.I\.\s+Act|NI\s+Act|IT\s+Act|POCSO|NDPS|IBC)\b"),
    # Section 3 of the Kerala Buildings (Lease and Rent Control) Act, 1965: an act the registry doesn't know
    re.compile(rf"\b(?P<word>{_SECTION_WORD})\s*(?P<secs>{_SECTIONS})\s*,?\s*of\s+(?:the\s+)?(?P<generic>{_GENERIC_ACT})(?:,?\s*\d{{4}})?"),
    # Article 21 (in India, the Constitution)
    re.compile(rf"\b(?P<word>articles?|arts?\.)\s*(?P<secs>{_SECTIONS})(?!\s*(?:of|,)\s+(?:the\s+)?[A-Z])", re.I),
]

_CASE_PATTERNS = [
    re.compile(r"\(\s*\d{4}\s*\)\s*\d{1,3}\s*S\.?\s*C\.?\s*C\.?\s+\d{1,4}"),  # (2019) 5 SCC 123
    re.compile(r"\b\d{4}\s+SCC\s+OnLine\s+[A-Z][A-Za-z]{1,10}\s+\d{1,6}"),  # 2021 SCC OnLine SC 123
    re.compile(r"\bAIR\s+\d{4}\s+[A-Z][A-Za-z]{1,10}\s+\d{1,5}"),  # AIR 1973 SC 1461
    re.compile(r"\b\d{4}\s+INSC\s+\d{1,5}"),  # 2023 INSC 456 (neutral)
    re.compile(r"\[\s*\d{4}\s*\]\s*\d{1,3}\s*S\.?\s*C\.?\s*R\.?\s+\d{1,5}"),  # [1973] 1 SCR 1
]
# A party: capitalized words, allowing "of", "and", "the", "for" inside ("State of Punjab").
_PARTY = r"[A-Z][\w.&'-]*(?:\s+(?:(?:of|and|the|&|for)\s+)?[A-Z][\w.&'-]*){0,6}"
_CASE_NAME = re.compile(rf"(?P<name>{_PARTY}\s+(?:v\.|vs\.?|versus)\s+{_PARTY})")
_SENTENCE_STOP = re.compile(r"(?<!\bLtd)(?<!\bCo)(?<!\bPvt)(?<!\bInc)(?<!\bAnr)(?<!\bOrs)(?<!\bBros)(?<!\bCorp)(?<!\bSt)(?<!\bM/s)\.\s+(?=[A-Z])")
_LEADING_WORDS = re.compile(r"^(?:(?:In|As|See|Per|Under|Following|Cf\.?|Also|And|The|Held|In\s+re)\s+)+")


@dataclass
class CitationCheck:
    text: str
    kind: str  # "statute" | "case"
    status: str  # grounded | statute | repealed | invalid | unverified
    note: str | None = None
    start: int = 0
    end: int = 0

    @property
    def flagged(self) -> bool:
        return self.status in ("invalid", "unverified")

    @property
    def label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def as_dict(self) -> dict:
        return {**{k: v for k, v in asdict(self).items() if k not in ("start", "end")}, "label": self.label}


# What each status does and doesn't establish, in the lawyer's words.
STATUS_LABELS = {
    "grounded": "In this matter's sources",
    "known_case": "Real judgment (case-law index) · whether it still holds and fits isn't checked",
    "statute": "Section exists · its wording isn't checked",
    "repealed": "Old criminal code · applies only before 1 July 2024",
    "invalid": "No such section",
    "unverified": "Not found in the sources or indexes",
}


@dataclass
class _Found:
    kind: str
    key: str
    text: str
    start: int
    end: int
    act: Act | None = None
    section: str | None = None
    act_name: str | None = None  # an act the registry doesn't know
    name: str | None = None  # a report citation's case name, when written with it


def _sections(raw: str) -> list[str]:
    raw = re.sub(r"\(\w{1,4}\)", "", raw)
    return [s.upper() for s in re.findall(_SECTION, raw)]


def _case_key(text: str) -> str:
    return re.sub(r"[\s.()\[\]]", "", text).upper()


def _name_tokens(name: str) -> tuple[str, ...]:
    name = re.sub(r"\b(?:vs?\.?|versus)\b", " ", name.lower())
    stop = {"the", "of", "and", "state", "union", "india", "ltd", "pvt", "co", "anr", "ors", "another", "others"}
    return tuple(t for t in re.findall(r"[a-z]{3,}", name) if t not in stop)


def mentions_authority(text: str | None) -> bool:
    """Whether the text cites any statute section or case."""
    return bool(text) and bool(_extract(text))


def _extract(text: str) -> list[_Found]:
    found: list[_Found] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in taken)

    for pattern in _CASE_PATTERNS:
        for m in pattern.finditer(text):
            if free(m.start(), m.end()):
                taken.append((m.start(), m.end()))
                found.append(_Found("case", _case_key(m.group(0)), m.group(0), m.start(), m.end()))
    for m in _CASE_NAME.finditer(text):
        raw = m.group("name")
        # A full stop before "v." ends the previous sentence ("...Section 103 BNS. Kumar v. State"):
        # the name starts after it, unless it's an abbreviation that belongs to a party name.
        versus = re.search(r"\s(?:v\.|vs\.?|versus)\s", raw)
        cut = 0
        for stop in _SENTENCE_STOP.finditer(raw, 0, versus.start() if versus else len(raw)):
            cut = stop.end()
        lead = _LEADING_WORDS.match(raw[cut:])
        skip = cut + (lead.end() if lead else 0)
        name = raw[skip:].rstrip(" ,")
        if name.endswith(".") and not re.search(r"\b(?:Ltd|Co|Pvt|Inc|Anr|Ors|Bros|Corp)\.$", name):
            name = name[:-1]  # the sentence's full stop, not part of the name
        start = m.start() + skip
        end = start + len(name)
        if not _name_tokens(name):
            continue
        # Written with its report ("X v. Y, (2019) 5 SCC 123"): one citation.
        report = next((f for f in found if f.kind == "case" and 0 <= f.start - end <= 3 and not text[end : f.start].strip(" ,")), None)
        if report is not None:
            report.text, report.start, report.name = text[start : report.end], start, " ".join(_name_tokens(name))
            taken.append((start, end))
        elif free(start, end):
            taken.append((start, end))
            found.append(_Found("case_name", " ".join(_name_tokens(name)), name, start, end))
    for index, pattern in enumerate(_STATUTE_PATTERNS):
        for m in pattern.finditer(text):
            if not free(m.start(), m.end()):
                continue
            groups = m.groupdict()
            act, generic = None, groups.get("generic")
            if groups.get("act"):
                act = _BY_ALIAS.get(re.sub(r"\s+", "", groups["act"]).lower())
            elif index == len(_STATUTE_PATTERNS) - 1:  # bare "Article 21"
                act = _BY_ALIAS["constitution"]
            if act is None and not generic:
                continue
            word = (groups.get("word") or "").lower()
            if act is not None and act.unit == "Article" and word and not word.startswith("art"):
                continue  # "Section 21 of the Constitution" is not how Articles are cited; skip
            taken.append((m.start(), m.end()))
            for section in _sections(groups["secs"]):
                if act is not None:
                    found.append(_Found("statute", f"{act.key}:{section}", m.group(0), m.start(), m.end(), act=act, section=section))
                else:
                    name = re.sub(r"\s+", " ", generic).strip()
                    found.append(_Found("statute", f"?{name.lower()}:{section}", m.group(0), m.start(), m.end(),
                                        section=section, act_name=name))
    return sorted(found, key=lambda f: f.start)


@dataclass
class Sources:
    """What the agent was given; a citation that appears here is grounded."""

    keys: set[str]
    names: list[tuple[str, ...]]
    # Real cases from the citation index (legal_authorities) that weren't among the sources.
    known_keys: set[str] = field(default_factory=set)
    known_names: list[tuple[str, ...]] = field(default_factory=list)

    @classmethod
    def from_texts(cls, *texts: str | None) -> "Sources":
        keys, names = set(), []
        for text in texts:
            if not text:
                continue
            for f in _extract(text):
                (names.append(tuple(f.key.split())) if f.kind == "case_name" else keys.add(f.key))
                if f.name:
                    names.append(tuple(f.name.split()))
        return cls(keys, names)

    def has_name(self, tokens: tuple[str, ...]) -> bool:
        return _name_match(tokens, self.names)

    def is_known(self, key: str | None, tokens: tuple[str, ...] | None) -> bool:
        return bool((key and key in self.known_keys) or (tokens and len(tokens) >= 2 and _name_match(tokens, self.known_names)))

    def with_known(self, keys: set[str], names: list[tuple[str, ...]]) -> "Sources":
        return Sources(self.keys, self.names, self.known_keys | keys, [*self.known_names, *names])


def _name_match(tokens: tuple[str, ...], names: list[tuple[str, ...]]) -> bool:
    return any(set(tokens) <= set(known) or set(known) <= set(tokens) for known in names if known)


KNOWN_CASE_NOTE = "A real judgment (citation index or Indian Kanoon), but not among this matter's sources: check it applies"


def case_lookups(*texts: str | None) -> tuple[list[str], list[tuple[str, ...]]]:
    """The case citations in `texts` to look up in the citation index: report keys and party names."""
    keys, names = [], []
    for text in texts:
        for f in _extract(text or ""):
            if f.kind == "case":
                keys.append(f.key)
                if f.name and len(f.name.split()) >= 2:
                    names.append(tuple(f.name.split()))
            elif f.kind == "case_name" and len(f.key.split()) >= 2:
                names.append(tuple(f.key.split()))
    return keys, names


def lookup_authorities(db, keys: list[str], names: list[tuple[str, ...]]) -> tuple[set[str], list[tuple[str, ...]]]:
    """Which of these citations are real: the Supreme Court index first, then Indian Kanoon for
    party names the index doesn't know (High Court and tribunal cases). Blocking."""
    found_keys: set[str] = set()
    found_names: list[tuple[str, ...]] = []
    if keys:
        rows = db.table("legal_authorities").select("citation_keys").overlaps("citation_keys", list(set(keys))).limit(50).execute().data
        found_keys = {k for row in rows for k in row["citation_keys"]} & set(keys)
    for tokens in dict.fromkeys(names):
        rows = db.table("legal_authorities").select("name_tokens").contains("name_tokens", list(tokens)).limit(1).execute().data
        if rows:
            found_names.append(tokens)
    from app.services import indiankanoon_service

    if indiankanoon_service.is_configured():
        found_names += indiankanoon_service.find_cases([n for n in dict.fromkeys(names) if n not in found_names])
    return found_keys, found_names


def _date_note(f: _Found) -> str | None:
    """For a 2023 criminal-code section: which old section applied before 1 July 2024."""
    if f.act is None or f.act.key not in ("BNS", "BNSS", "BSA"):
        return None
    old = jurisdiction_service.old_code_section(f.act.key, f.section or "")
    earlier = f"{old} ({jurisdiction_service.CORRESPONDENCE_CAVEAT})" if old else f"the {_OLD_CODES[f.act.key]} equivalent"
    return f"Applies to offences and proceedings from 1 July 2024; before that, {earlier}"


_OLD_CODES = {"BNS": "IPC", "BNSS": "CrPC", "BSA": "Evidence Act"}


def _check_statute(f: _Found, sources: Sources) -> tuple[str, str | None]:
    status, note = _check_statute_status(f, sources)
    if status in ("grounded", "statute"):
        dated = _date_note(f)
        note = "; ".join(n for n in (note, dated) if n) or None
    return status, note


def _check_statute_status(f: _Found, sources: Sources) -> tuple[str, str | None]:
    if f.key in sources.keys:
        return "grounded", None
    act = f.act
    if act is None:
        return "unverified", f"{f.act_name} is not in the statute registry or the sources"
    base = re.match(r"\d+", f.section)
    number, letters = int(base.group(0)), f.section[len(base.group(0)):]
    label = f"{act.unit} {f.section}"
    if act.max_section is not None:
        if number < 1 or number > act.max_section:
            return "invalid", f"{act.name} has no {label} (it has {act.max_section} {act.unit.lower()}s)"
        if letters and not act.lettered:
            return "invalid", f"{act.name} has no lettered {act.unit.lower()}s such as {label}"
    if act.replaced_by:
        old = {"IPC": "IPC", "CRPC": "CrPC", "IEA": "Evidence Act"}[act.key]
        mapped = jurisdiction_service.new_code_section({"IPC": "IPC", "CRPC": "CRPC", "IEA": "IEA"}[act.key], f.section)
        hint = (f"; for matters from 1 July 2024 see {mapped.split(' (formerly')[0]} ({jurisdiction_service.CORRESPONDENCE_CAVEAT})"
                if mapped else f"; check the {act.replaced_by} equivalent")
        return "repealed", f"{label} {old} applies to offences and proceedings before 1 July 2024{hint}"
    if act.max_section is None:
        return "statute", f"{act.name} is a known act; {label} was not checked"
    return "statute", None


def check(text: str | None, sources: Sources) -> list[CitationCheck]:
    """Every citation in `text`, with its status."""
    if not text:
        return []
    checks: list[CitationCheck] = []
    for f in _extract(text):
        if f.kind == "statute":
            status, note = _check_statute(f, sources)
        elif f.kind == "case":
            tokens = tuple(f.name.split()) if f.name else None
            if f.key in sources.keys or (tokens and sources.has_name(tokens)):
                status, note = "grounded", None
            elif sources.is_known(f.key, tokens):
                status, note = "known_case", KNOWN_CASE_NOTE
            else:
                status, note = "unverified", "This case citation is not in the knowledge base, web results or documents for this matter"
        else:
            tokens = tuple(f.key.split())
            if sources.has_name(tokens):
                status, note = "grounded", None
            elif sources.is_known(None, tokens):
                status, note = "known_case", KNOWN_CASE_NOTE
            else:
                status, note = "unverified", "This case is not in the knowledge base, web results or documents for this matter"
        checks.append(CitationCheck(f.text, "statute" if f.kind == "statute" else "case", status, note, f.start, f.end))
    # One span can hold several sections ("ss. 480 and 483 BNSS"): the span takes the worst status.
    merged: dict[tuple[int, int], CitationCheck] = {}
    order = ["grounded", "known_case", "statute", "repealed", "unverified", "invalid"]
    for c in checks:
        current = merged.get((c.start, c.end))
        if current is None or order.index(c.status) > order.index(current.status):
            merged[(c.start, c.end)] = c
    return sorted(merged.values(), key=lambda c: c.start)


def annotate(text: str, checks: list[CitationCheck]) -> str:
    """Mark invalid and unverified citations in place."""
    for c in sorted((c for c in checks if c.flagged), key=lambda c: c.start, reverse=True):
        if not text[c.end :].startswith(FLAG):
            text = text[: c.end] + FLAG + text[c.end :]
    return text


_SENTENCE_END = re.compile(
    r"(?<!\bv\.)(?<!\bvs\.)(?<!\bNo\.)(?<!\bs\.)(?<!\bss\.)(?<!\bSec\.)(?<!\bArt\.)(?<!\bLtd\.)(?<!\bCo\.)"
    r"(?<=[.!?।])\s+(?=\S)"
)
CLIENT_CITATION_NOTE = "A lawyer will confirm the law that applies."


def for_client(text: str | None, checks: list[CitationCheck]) -> str | None:
    """Client-facing text: sentences citing something unverified or invalid are left out."""
    if not text:
        return text
    flagged = [c for c in checks if c.flagged]
    if not flagged:
        return text
    kept, position, dropped = [], 0, False
    for sentence in _SENTENCE_END.split(text):
        start = text.find(sentence, position)
        end = start + len(sentence)
        position = end
        if any(c.start < end and c.end > start for c in flagged):
            dropped = True
            continue
        kept.append(sentence)
    result = " ".join(kept).strip()
    return f"{result} {CLIENT_CITATION_NOTE}".strip() if dropped else result


def spoken(text: str | None) -> str | None:
    """Text to read aloud: citations are named, not recited ("the relevant provision")."""
    if not text:
        return text
    text = text.replace(FLAG, "")
    for f in sorted(_extract(text), key=lambda f: f.start, reverse=True):
        phrase = "the relevant provision" if f.kind == "statute" else "a court decision"
        text = text[: f.start] + phrase + text[f.end :]
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"(^|[.!?।]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def verify_text(text: str | None, sources: Sources) -> tuple[str | None, list[CitationCheck]]:
    checks = check(text, sources)
    return (annotate(text, checks) if text else text), checks


def verify_issue(issue: dict, sources: Sources) -> dict:
    """A legal issue with its authority checked: flagged citations are removed from it."""
    authority = issue.get("authority")
    checks = check(authority, sources)
    if not checks:
        return {**issue, "authority_status": None, "authority_note": None}
    flagged = [c for c in checks if c.flagged]
    if flagged:
        kept = [c.text for c in checks if not c.flagged]
        return {
            **issue,
            "authority": "; ".join(kept) or None,
            "authority_status": "flagged",
            "authority_note": "Removed: " + "; ".join(f"{c.text} ({c.note})" for c in flagged),
        }
    if all(c.status == "grounded" for c in checks):
        status = "verified"
    elif any(c.status == "known_case" for c in checks):
        status = "known"  # a real judgment, though not one of this matter's sources
    else:
        status = "statute"
    notes = [c.note for c in checks if c.note]
    return {**issue, "authority_status": status, "authority_note": "; ".join(notes) or None}


def summarize(checks: list[CitationCheck]) -> dict:
    counts: dict[str, int] = {}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    return counts
