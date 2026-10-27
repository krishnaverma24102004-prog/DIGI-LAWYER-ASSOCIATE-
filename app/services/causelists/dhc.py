"""High Court of Delhi cause lists (daily, supplementary, advance; deletion notes).

Layout (2026): each court section opens with "COURT NO. 15" (or "J.R. COURT NO. 5", "ROOM NO. 101"),
an optional "DIVISION BENCH- IV", the bench ("HON'BLE MS. JUSTICE ...", "BEFORE SH. ..., REGISTRAR"),
notes, then a table "ITEM NUMBER | CASE NUMBER | PARTY NAME | ADVOCATE NAME | OTHER INFORMATION" with
segment headings ("FRESH MATTERS & APPLICATIONS", "AFTER NOTICE MISC. MATTERS", ...). Each item:
"135 CONT.CAS(C)-1086/2026", applications ("CM APPL. ..."), "WITH <case>" for matters taken up
together, parties "X V/s Y", advocates, then "OTHER DETAILS OF ADVOCATES:" (names with e-mail and
phone; we keep only the names). Deletion notes: "<case> LISTED AT ITEM NO.28 IS DELETED ...".

Some of the court's PDFs place characters individually ("W.P .( C ) 8430/202 1"), so case numbers,
dates and notes are matched on text with the spaces removed.

Automated fetching is disabled: the High Court's terms forbid systematic downloading (see FETCHER).
Lists reach us when a member forwards them.
"""

import re
from datetime import date

from app.services.causelists import (
    Deletion,
    FetcherConfig,
    Line,
    ParsedItem,
    ParsedList,
    bench_key,
    bench_label,
    case_key,
    clean,
    status_from,
)

CODE = "DLHC"
# How a firm writes this court on its matters (court_cases.court_name).
COURT_NAMES = re.compile(r"delhi\s+high\s+court|high\s+court\s+of\s+delhi|\bdl?hc\b|\bdelhi\s+hc\b|\bhc\s+delhi\b", re.IGNORECASE)
BASE = "https://delhihighcourt.nic.in/files/{yyyy_mm}/cause-list"

FETCHER = FetcherConfig(
    court_code=CODE,
    name="High Court of Delhi",
    complex="Delhi High Court, Sher Shah Road, New Delhi",
    state="Delhi",
    home_url="https://delhihighcourt.nic.in/web/cause-lists/cause-list",
    url_templates=(
        (BASE + "/combined_sup_1_{dd_mm_yyyy}.pdf", "supplementary"),
        (BASE + "/combined_advance_{ddmmyyyy}.pdf", "advance"),
    ),
    terms_url="https://delhihighcourt.nic.in/web/term-conditions",
    terms_note=(
        "Terms and conditions (checked 2026-10-27) permit downloading extracts for personal, non-commercial "
        "use and forbid creating a database by regularly or systematically downloading pages, or storing "
        "them in a retrieval system, without prior written permission. Automated fetching stays off until "
        "the High Court grants written permission; members forward the lists they download."
    ),
    robots_note="delhihighcourt.nic.in/robots.txt returned 'File not found' (2026-10-27).",
    automated_access_allowed=False,
)

# Matched on compact text (upper case, no whitespace).
PAGE_HEADER = re.compile(r"^(\d{2})\.?(\d{2})\.(\d{4})(?P<kind>[A-Z].*)$")
COURT = re.compile(r"^(?P<jr>J\.R\.)?COURTNO\.?:?(?P<no>\d+)|^ROOMNO\.?(?P<room>\d+)")
DIVISION = re.compile(r"^DIVISIONBENCH-?(?P<db>[IVXL]+)")
FURNITURE = re.compile(r"^(?:HIGHCOURTOFDELHI.*REGISTRAR\(LISTING\)|HIGHCOURTOFDELHI|REGISTRAR\(LISTING\)|\d{1,2}\.?\d{1,2}\.\d{2,4}"
                       r"|ITEM|NUMBER|ITEMNUMBER|HYBRIDMODE|\(PHYSICALHEARINGCOURT\)|[^A-Z0-9]+)$")
CASE = re.compile(r"^(?P<type>[A-Z][A-Z0-9.()&/]*?[A-Z.)])-?(?P<num>\d+(?:-\d+)?)/(?P<year>(?:19|20)\d{2})")
WITH = re.compile(r"^WITH(?P<type>[A-Z][A-Z0-9.()&/]*?[A-Z.)])-?(?P<num>\d+)/(?P<year>(?:19|20)\d{2})")
DELETED = re.compile(
    r"(?:^|(?<=[\d.]))(?P<case>[A-Z][A-Z0-9.()&/]{0,30}?[A-Z.)])-?(?P<num>\d+)/(?P<year>(?:19|20)\d{2})LISTED"
    r"(?:BEFORE(?P<before>.*?))?ATITEMNO\.?(?P<item>\d+)\.?IS\.?DELETED\.?(?P<reason>[^.\d]*)"
)
# Matched on normal text.
BEFORE = re.compile(r"^BEFORE\s+(?:SH\.|SHRI|SMT\.|MS\.|MR\.|DR\.)?\s*(?P<name>[A-Z][A-Z .]+?)\s*,.*?(?P<role>(?:JOINT |ADDITIONAL |DEPUTY )?REGISTRAR)")
DETAIL = re.compile(r"^(?P<name>[A-Z][A-Z .&'-]{2,}?)\s*\([^)]*\)\s*\([^)]*\)\s*\((?:PETITIONER|RESPONDENT|APPELLANT|APPLICANT|.*?)\)")
NON_PARTY = re.compile(r"^(?:CMAPPL|CRL\.M\.A|CRL\.M\.\(BAIL\)|I\.A\.|IA\d|CAV\.|EX\.APPL|OA\d|IN[A-Z])")
DEFAULT_BOUNDS = [95.0, 244.0, 448.0, 698.0]


def compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").upper())


def _segment(heading: str) -> str:
    if "FRESH" in heading:
        return "fresh"
    if "AFTERNOTICE" in heading:
        return "after_notice"
    if "REGULAR" in heading or "FINALHEARING" in heading or "PART-HEARD" in heading or "PARTHEARD" in heading:
        return "regular"
    return "other"


def _header_bounds(lines: list[Line]) -> list[float] | None:
    """Column edges from the table header, which may wrap over two or three rows."""
    xs: dict[str, float] = {}
    for line in lines:
        for fragment in line.fragments:
            upper = compact(fragment.text)
            for key, label in (("case", "CASENUMBER"), ("party", "PARTYNAME"), ("adv", "ADVOCATE"), ("other", "OTHERINF")):
                if upper.startswith(label) and key not in xs:
                    xs[key] = fragment.x0
    if "case" not in xs or "party" not in xs:
        return None
    adv = xs.get("adv", xs["party"] + 200)
    other = xs.get("other", adv + 250)
    return [xs["case"] - 3, xs["party"] - 3, adv - 3, other - 3]


class _Item:
    def __init__(self, item_no: str, case_text: str, page: int):
        self.item_no = item_no
        self.case_text = case_text  # compact
        self.page = page
        self.withs: list[re.Match] = []
        self.case_notes: list[str] = []
        self.party: list[str] = []
        self.details: list[str] = []
        self.in_details = False
        self.adv: list[str] = []
        self.other: list[str] = []


def parse(lines: list[Line]) -> ParsedList:
    out = ParsedList(CODE)
    bounds = list(DEFAULT_BOUNDS)
    courtroom = None
    division = None
    judges: list[str] = []
    judges_open = False
    segment = "other"
    mode = "header"   # header | table | deletion
    deletion_text: list[str] = []
    current: _Item | None = None
    previous: Line | None = None

    def finish():
        nonlocal current
        if current is not None:
            _finish_item(out, current, courtroom, division, judges, segment)
        current = None

    def finish_deletions():
        nonlocal deletion_text
        if deletion_text:
            _deletions(out, "".join(deletion_text), courtroom)
        deletion_text = []

    for index, line in enumerate(lines):
        prev, previous = previous, line
        text = line.text
        upper = text.upper()
        tight = compact(text)
        if not tight:
            continue
        if re.fullmatch(r"\d{1,4}", tight) and line.fragments[0].x0 > 200:
            continue  # page number
        if match := PAGE_HEADER.match(tight):
            kind = match.group("kind")
            if "CAUSELIST" in kind or "DELETIONNOTE" in kind or "PRONOUNCEMENT" in kind:
                try:
                    day = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                except ValueError:
                    day = None
                out.list_date = out.list_date or day
                if "ADVANCE" in kind:
                    out.list_type = "advance"
                elif "SUPPLEMENTARY" in kind or "DELETION" in kind:
                    out.list_type = out.list_type or "supplementary"
                else:
                    out.list_type = out.list_type or "daily"
                if "DELETIONNOTE" in kind:
                    finish()
                    mode = "deletion"
                continue
        if FURNITURE.match(tight):
            continue
        if match := COURT.match(tight):
            finish()
            finish_deletions()
            if match.group("room"):
                courtroom = f"Room {match.group('room')}"
            elif match.group("jr"):
                courtroom = f"JR {int(match.group('no'))}"
            else:
                courtroom = str(int(match.group("no")))
            division, judges, judges_open, segment, mode = None, [], False, "other", "header"
            continue
        if match := DIVISION.match(tight):
            division = f"DB-{match.group('db')}"
            continue
        if tight.startswith("HON'BLE") or tight.startswith("HONBLE") or BEFORE.match(upper):
            if not judges_open:
                judges = []
                judges_open = True
            if (before := BEFORE.match(upper)):
                judges.append(f"{before.group('role')} {clean(before.group('name'))}")
            else:
                judges.append(upper)
            continue
        judges_open = False
        if tight.startswith("DELETEIONNOTE") or tight.startswith("DELETIONNOTE"):
            finish()
            mode = "deletion"
            continue
        if "CASENUMBER" in tight and "PARTYNAME" in tight:
            finish()
            finish_deletions()
            following = lines[index + 1: index + 2]
            bounds = _header_bounds([x for x in [prev, line, *following] if x is not None]) or bounds
            mode = "table"
            continue
        if mode == "deletion":
            deletion_text.append(tight)
            continue
        if mode != "table":
            continue
        cols = line.columns(bounds)
        if line.ocr:
            m = re.match(r"^(\d{1,4})\s+(.*)$", text)
            if m and CASE.match(compact(m.group(2))):
                finish()
                current = _Item(m.group(1), compact(m.group(2)), line.page)
            elif current is not None:
                current.party.append(text)
            continue
        first, case_col = cols[0], cols[1]
        joined = re.match(r"^(\d{1,4})\s+(.+)$", case_col) if not first else None
        if re.fullmatch(r"\d{1,4}", first) and CASE.match(compact(case_col)):
            finish()
            current = _Item(first, compact(case_col), line.page)
        elif joined and CASE.match(compact(joined.group(2))):
            finish()
            current = _Item(joined.group(1), compact(joined.group(2)), line.page)
        elif first:
            # A heading or a note at the left margin closes the item above it.
            finish()
            if tight.startswith("NOTE"):
                continue
            if re.fullmatch(r"[A-Z0-9 &/().,'-]+", upper) and not re.search(r"\d{3,}", upper):
                segment = _segment(tight)
            continue
        elif current is None:
            continue
        elif case_col:
            case_tight = compact(case_col)
            if (w := WITH.match(case_tight)):
                current.withs.append(w)
            elif not NON_PARTY.match(case_tight):
                current.case_notes.append(case_col)
        party, adv, other = (cols[2:] + ["", "", ""])[:3]
        if party:
            if compact(party).startswith("OTHERDETAILSOFADVOCATES"):
                current.in_details = True
            elif current.in_details:
                current.details.append(party)
            else:
                current.party.append(party)
        if adv and not current.in_details:
            current.adv.append(adv)
        elif adv:
            current.details.append(adv)
        if other:
            current.other.append(other)
    finish()
    finish_deletions()
    _drop_duplicate_withs(out)
    return out


def _advocates(adv_lines: list[str], details: list[str]) -> list[str]:
    names: list[str] = []

    def add(name: str) -> None:
        name = clean(name).strip(" .,")
        # One-word entries are departments ('MCD') or the tail of a wrapped name; skip them.
        if len(name.split()) >= 2 and name not in names:
            names.append(name)

    text = clean(" ".join(adv_lines)).upper().split("LISTING REMARKS", 1)[0]
    for part in re.split(r",", text):
        add(re.sub(r"\(.*?\)", " ", part))
    buffer = ""
    for line in details:
        buffer = clean(f"{buffer} {line}").upper()
        if (match := DETAIL.match(buffer)):
            add(match.group("name"))
            buffer = ""
        elif "(" in buffer and buffer.count(")") >= 3:
            buffer = ""  # an entry we can't read (FIR details, other cases); don't let it swallow the next one
    return names


def _finish_item(out: ParsedList, item: _Item, courtroom, division, judges, segment) -> None:
    match = CASE.match(item.case_text)
    remarks = " ".join(item.other + item.case_notes)
    adv_text = clean(" ".join(item.adv)).upper()
    if "LISTING REMARKS" in adv_text:
        remarks += " " + adv_text.split("LISTING REMARKS", 1)[1]
    status = status_from(remarks) or "listed"
    parties = clean(re.sub(r"\bV/S\b", " v. ", " ".join(item.party), flags=re.IGNORECASE))
    label = "; ".join(([division] if division else []) + [bench_label(judges) or ""]).strip("; ") or None
    item_segment = segment
    if segment == "other" and out.list_type in ("advance", "supplementary"):
        item_segment = out.list_type
    common = dict(courtroom=courtroom, bench_key=bench_key(CODE, judges), bench_label=label, segment=item_segment,
                  status=status, parties=parties[:1000], advocates=_advocates(item.adv, item.details)[:30], page=item.page)
    if not match:
        out.warnings.append(f"item {item.item_no} (page {item.page}): case number not recognised")
    out.items.append(ParsedItem(
        item_no=item.item_no,
        case_type=match.group("type") if match else None,
        case_number=match.group("num") if match else None,
        case_year=int(match.group("year")) if match else None,
        **common,
    ))
    for connected in item.withs:
        out.items.append(ParsedItem(
            item_no=item.item_no,
            case_type=connected.group("type"),
            case_number=connected.group("num"),
            case_year=int(connected.group("year")),
            connected_to=item.item_no,
            **common,
        ))


def _drop_duplicate_withs(out: ParsedList) -> None:
    """'WITH LPA 585/2025' under item 3 when LPA 585/2025 is also item 4 in that court: keep item 4 only."""
    main = {(i.courtroom, case_key(i.case_type, i.case_number, i.case_year)) for i in out.items if not i.connected_to}
    out.items = [i for i in out.items
                 if not i.connected_to or (i.courtroom, case_key(i.case_type, i.case_number, i.case_year)) not in main]


def _deletions(out: ParsedList, tight: str, courtroom) -> None:
    for match in DELETED.finditer(tight):
        case_type = re.sub(r"^\d+\.?", "", match.group("case"))
        reason = match.group("reason") or ""
        out.deletions.append(Deletion(
            case_type=case_type,
            case_number=match.group("num"),
            case_year=int(match.group("year")),
            item_no=match.group("item"),
            courtroom=courtroom if not match.group("before") else None,
            reason=("deleted" + (": " + reason.lower() if reason else ""))[:200],
        ))
