"""Supreme Court of India cause lists (daily, supplementary, advance, chamber and registrar lists).

Layout (2026): a table "SNo. | Case No. | Petitioner / Respondent | Petitioner/Respondent Advocate"
under a court header ("COURT NO. : 16" or "CHIEF JUSTICE'S COURT", "Registrar Court No. 1") and
the bench ("HON'BLE MR. JUSTICE ..."). Connected matters are numbered "1710.1 Connected". A
"DROP NOTE" table lists items deleted from (or shifted out of) that court's list. Advocates are
printed as "NAME- <AOR code> [P-1]".
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
    clean,
    status_from,
)

CODE = "SCI"
# How a firm writes this court on its matters (court_cases.court_name).
COURT_NAMES = re.compile(r"supreme\s+court|^\s*s\.?\s?c\.?\s*i?\.?\s*$", re.IGNORECASE)
API = "https://api.sci.gov.in/jonew/cl"

FETCHER = FetcherConfig(
    court_code=CODE,
    name="Supreme Court of India",
    complex="Supreme Court, Tilak Marg, New Delhi",
    state="Delhi",
    home_url="https://www.sci.gov.in/",
    url_templates=(
        # Main (daily) lists: miscellaneous (M) / regular (F) days, judges' courts (J), chamber (C),
        # single-judge (S), registrars (R).
        (API + "/{date}/M_J_1.pdf", "daily"),
        (API + "/{date}/F_J_1.pdf", "daily"),
        (API + "/{date}/M_C_1.pdf", "daily"),
        (API + "/{date}/M_S_1.pdf", "daily"),
        (API + "/{date}/M_CC_1.pdf", "daily"),
        (API + "/{date}/M_R_1.pdf", "daily"),
        # Supplementary lists ("SUPPLEMENTARY LIST" in the header).
        (API + "/{date}/M_J_2.pdf", "supplementary"),
        (API + "/{date}/F_J_2.pdf", "supplementary"),
        (API + "/{date}/M_C_2.pdf", "supplementary"),
        # Advance list: matters likely to be listed (tentative; never a listing for tomorrow).
        (API + "/advance/{date}/M_J.pdf", "advance"),
    ),
    terms_url="https://www.sci.gov.in/website-policies/",
    terms_note=(
        "Website policies (checked 2026-10-27): contents may be reproduced with due and prominent "
        "acknowledgement of the source; no clause on automated access. We fetch only the published PDF "
        "paths on api.sci.gov.in; the cause-list search page has a captcha and is never requested."
    ),
    robots_note="www.sci.gov.in/robots.txt (2026-10-27) disallows only /wp-admin/; api.sci.gov.in serves no robots.txt.",
    automated_access_allowed=True,
)

DATED = re.compile(r"CAUSE LIST FOR DATED\s*:?\s*(\d{2})-(\d{2})-(\d{4})")
ADVANCE_DATED = re.compile(r"TO BE LISTED ON\s*(\d{2})-(\d{2})-(\d{4})")
COURT = re.compile(r"^(?:COURT NO\.?\s*:?\s*(?P<no>\d+)|(?P<cj>CHIEF JUSTICE'S COURT)|REGISTRAR COURT NO\.?\s*:?\s*(?P<reg>\d+))$")
REGISTRAR = re.compile(r"^(?:SH\.|SHRI|SMT\.|MS\.|MR\.|DR\.)?\s*(?P<name>[A-Z][A-Z .]+?)\s*,\s*(?P<role>(?:ADDITIONAL |DEPUTY |ASSISTANT )?REGISTRAR)\b")
HEADING = re.compile(
    r"^(?:MISCELLANEOUS HEARING|REGULAR HEARING(?: MATTERS)?|CHAMBER MATTERS|PART-[A-Z]|FRESH MATTERS|AFTER NOTICE MATTERS"
    r"|\[(?:FRESH|AFTER NOTICE|REGULAR|SERVICE)[^\]]*\](?:-.*)?)$"
)
FURNITURE = re.compile(
    r"^(?:SUPREME COURT OF INDIA|NEW DELHI|ADDITIONAL REGISTRAR.*|\[ ?IT WILL BE APPRECIATED.*|ON RECORD DO NOT SEEK.*"
    r"|LISTED BEFORE ALL THE COURTS.*|\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}|\(TIME\s*:.*\))$"
)
CASE = re.compile(
    r"(?P<type>[A-Za-z][A-Za-z0-9().&/\s-]*?[A-Za-z.)])\s*(?:\bNos?\.?)?\s*/?\s*(?P<num>\d+[A-Z]?(?:\s*-\s*\d+[A-Z]?)?)\s*[/-]\s*(?P<year>(?:19|20)\d{2})\b"
)
ADVOCATE = re.compile(r"(?P<name>[A-Z][A-Z0-9 .&'@/()]*?)\s*-\s*(?P<code>\d{1,5})\b")
ITEM_NO = re.compile(r"^(?P<no>\d{1,5}(?:\.\d{1,3})?)(?:\s+CONNECTED)?$", re.IGNORECASE)
DEFAULT_BOUNDS = [66.0, 181.0, 421.0]


def _date(match) -> date:
    return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def _header_bounds(line: Line) -> list[float] | None:
    xs = {"case": None, "party": None, "adv": None}
    for fragment in line.fragments:
        upper = fragment.text.upper()
        if upper.startswith("CASE NO") and xs["case"] is None:
            xs["case"] = fragment.x0
        elif upper.startswith("PETITIONER") and xs["party"] is None:
            xs["party"] = fragment.x0
        elif upper.startswith("PETITIONER") and xs["party"] is not None and fragment.x0 > xs["party"] + 40:
            xs["adv"] = fragment.x0
    if None in xs.values():
        return None
    return [xs["case"] - 3, xs["party"] - 3, xs["adv"] - 3]


def _advocates(text: str) -> tuple[list[str], list[str]]:
    text = re.sub(r"\[[^\]]*\]", " ", text)
    names, codes = [], []
    for match in ADVOCATE.finditer(clean(text).upper()):
        name = clean(match.group("name").strip(" ,"))
        if len(name) >= 3 and name not in names:
            names.append(name)
            codes.append(match.group("code"))
    return names, codes


class _Item:
    def __init__(self, item_no: str, page: int):
        self.item_no = item_no
        self.page = page
        self.case: list[str] = []
        self.party: list[str] = []
        self.adv: list[str] = []


def parse(lines: list[Line]) -> ParsedList:
    out = ParsedList(CODE)
    bounds = list(DEFAULT_BOUNDS)
    courtroom = None
    judges: list[str] = []
    judges_open = False
    segment = "other"
    mode = "table"   # table | notes | drop
    current: _Item | None = None
    drop: dict | None = None
    drop_bounds: list[float] | None = None

    def finish():
        nonlocal current
        if current is not None:
            _finish_item(out, current, courtroom, judges, segment)
        current = None

    def finish_drop():
        nonlocal drop
        if drop is not None:
            _finish_drops(out, drop["rows"], courtroom)
        drop = None

    for line in lines:
        text = line.text
        upper = text.upper()
        if not text or FURNITURE.match(upper):
            continue
        if match := DATED.search(upper):
            out.list_date = out.list_date or _date(match)
            out.list_type = out.list_type or "daily"
            continue
        if match := ADVANCE_DATED.search(upper):
            out.list_date = out.list_date or _date(match)
            out.list_type = "advance"
            continue
        if upper.startswith("ADVANCE LIST") or upper.startswith("TENTATIVE LIST"):
            out.list_type = "advance"
            continue
        if upper == "SUPPLEMENTARY LIST":
            finish_drop()
            mode = "table" if mode == "drop" else mode
            if out.list_type != "advance":
                out.list_type = "supplementary"
            segment = "supplementary"
            continue
        if match := COURT.match(upper):
            room = match.group("no") or ("1" if match.group("cj") else f"R{match.group('reg')}")
            if room != courtroom:
                finish()
                finish_drop()
                courtroom, judges, segment, mode = room, [], "other", "table"
            judges_open = False
            continue
        if upper.startswith("HON'BLE") or (courtroom and courtroom.startswith("R") and REGISTRAR.match(upper)):
            if not judges_open:
                if current is not None or drop is not None:
                    finish()
                    finish_drop()
                judges = []
                judges_open = True
            if upper.startswith("HON'BLE"):
                judges += ["HON'BLE " + part.strip(" ,") for part in upper.split("HON'BLE") if part.strip(" ,")]
            else:
                registrar = REGISTRAR.match(upper)
                judges.append(f"{registrar.group('role')} {clean(registrar.group('name'))}")
            continue
        judges_open = False
        if upper.startswith("DROP NOTE"):
            finish()
            finish_drop()
            mode = "drop"
            continue
        if upper.startswith("NOTE") and mode != "drop":
            finish()
            mode = "notes"
            continue
        if "SNO." in upper and "CASE NO" in upper:
            finish()
            finish_drop()
            bounds = _header_bounds(line) or bounds
            mode = "table"
            continue
        if mode == "drop" and not HEADING.match(upper):
            # Drop-note cells are vertically centred, so rows are collected first and assigned to
            # the nearest item number when the note ends.
            if "CASE NO" in upper and not drop:
                drop_bounds = [f.x0 - 3 for f in line.fragments if f.x0 > 60] or None
                continue
            if upper in ("ITEM", "NO.", "TO") or upper.startswith("ITEM ") or upper.startswith("NO. TO"):
                continue
            cols = line.columns(drop_bounds or bounds)
            if line.ocr and (m := re.match(r"^(\d{1,5})\s+(.*)$", text)):
                cols = [m.group(1), m.group(2), m.group(2)]
            drop = drop or {"rows": []}
            drop["rows"].append((line.page, line.y, cols))
            continue
        if HEADING.match(upper):
            finish()
            finish_drop()
            mode = "table"
            if "FRESH" in upper:
                segment = "fresh"
            elif "AFTER NOTICE" in upper:
                segment = "after_notice"
            elif "REGULAR" in upper:
                segment = "regular"
            elif segment not in ("supplementary",):
                segment = "other"
            continue
        if mode == "notes":
            continue
        cols = line.columns(bounds)
        if line.ocr:
            m = re.match(r"^(\d{1,5}(?:\.\d{1,3})?)\s+(?:Connected\s+)?(.*)$", text, re.IGNORECASE)
            if m and CASE.search(m.group(2)):
                finish()
                current = _Item(m.group(1), line.page)
                current.case.append(m.group(2))
                current.party.append(m.group(2))
            elif current is not None:
                current.case.append(text)
                current.party.append(text)
            continue
        first = cols[0]
        if (re.fullmatch(r"\d{1,3}", first) and current is not None and "." in current.item_no
                and len(current.case) == 1 and (current.item_no.endswith(".") or not CASE.search(current.case[0]))):
            current.item_no += first  # '35.1' + '0', '101.' + '1': the number wrapped in its narrow column
        elif m := re.fullmatch(r"(\d{1,5}\.)(?:\s+CONNECTED)?", first, re.IGNORECASE):
            finish()
            current = _Item(m.group(1), line.page)
        elif ITEM_NO.match(first):
            finish()
            current = _Item(ITEM_NO.match(first).group("no"), line.page)
        elif re.fullmatch(r"\.\d{1,3}", first) and current is not None and "." not in current.item_no:
            current.item_no += first
        elif re.fullmatch(r"\d{1,5}\.\d{1,3}\s+CONNECTED", first.upper()):
            finish()
            current = _Item(first.split()[0], line.page)
        if current is None:
            continue
        current.case.append(cols[1])
        current.party.append(cols[2])
        current.adv.append(cols[3])
    finish()
    finish_drop()
    return out


def _finish_item(out: ParsedList, item: _Item, courtroom, judges, segment) -> None:
    item.item_no = item.item_no.rstrip(".")
    case_text = clean(" ".join(item.case)).replace("Connected", " ").replace("CONNECTED", " ")
    match = CASE.search(case_text)
    if not match:
        out.warnings.append(f"item {item.item_no} (page {item.page}): case number not recognised")
    party_text = clean(" ".join(p for p in item.party if p))
    # Parties end where the interlocutory applications and listing notes begin.
    head = re.split(r"\bIA No\.|\{Mention Memo\}|\bFOR ADMISSION\b|\bIN D No\.|\bIN [A-Za-z.()]+ No\.|\bONLY\s+(?:SLP|IA|I\.A|C\.A|CRL|DIARY|W\.P|T\.P)"
                    r"|\bOffice Report\b|\bCUSTODY CERTIFICATE\b|\sFOR\s*$", party_text, maxsplit=1, flags=re.IGNORECASE)[0]
    head = re.split(r"\[", head, maxsplit=1)[0]
    parties = clean(re.sub(r"\bVersus\b", " v. ", head, flags=re.IGNORECASE))
    notes = " ".join(re.findall(r"\[[^\]]*\]", party_text))
    names, codes = _advocates(" ".join(item.adv))
    item_segment = segment
    if re.search(r"\bFOR ADMISSION\b", party_text):
        item_segment = "fresh"
    elif re.search(r"\bAFTER NOTICE\b", party_text) and "AFTER FRESH" not in party_text.upper():
        item_segment = "after_notice"
    if out.list_type == "advance":
        item_segment = "advance"
    connected_to = item.item_no.split(".")[0] if "." in item.item_no else None
    out.items.append(ParsedItem(
        item_no=item.item_no,
        case_type=clean(match.group("type")) if match else None,
        case_number=re.sub(r"\s", "", match.group("num")) if match else None,
        case_year=int(match.group("year")) if match else None,
        courtroom=courtroom,
        bench_key=bench_key(CODE, judges),
        bench_label=bench_label(judges),
        segment=item_segment,
        connected_to=connected_to,
        status=status_from(head + " " + notes) or "listed",
        parties=parties[:1000],
        advocates=names[:30],
        advocate_codes=codes[:30],
        page=item.page,
    ))


DROP_NUMBER = re.compile(r"\bNos?\.?\s*/?\s*(?P<num>\d+(?:-\d+)?)\s*[/-]\s*(?P<year>(?:19|20)\d{2})\b")
DROP_TYPE = re.compile(r"^(?P<type>Diary|[A-Za-z][A-Za-z.]*(?:\([A-Za-z.]+\))?)\s*(?:Vs\.?)?$")


def _finish_drops(out: ParsedList, rows: list, courtroom) -> None:
    anchors = [(page, y, ITEM_NO.match(cols[0]).group("no")) for page, y, cols in rows if cols and ITEM_NO.match(cols[0])]
    for page, y, item_no in anchors:
        mine = [cols for p, yy, cols in rows
                if p == page and min(anchors, key=lambda a: (a[0] != p, abs(a[1] - yy)))[2] == item_no]
        case_lines = [cols[1] for cols in mine if len(cols) > 1 and cols[1]]
        joined = clean(" ".join(" ".join(cols[1:]) for cols in mine))
        number = DROP_NUMBER.search(clean(" ".join(case_lines))) or DROP_NUMBER.search(joined)
        case_type = None
        for text in case_lines:
            if (m := DROP_TYPE.match(text.split(" No.")[0].strip())) and m.group("type").upper() not in ("AND", "LIMITED", "VS."):
                case_type = m.group("type")
                break
        upper = joined.upper()
        shifted = re.search(r"\b(?:SHIFTED|TRANSFERRED)\b.*", upper)
        out.deletions.append(Deletion(
            case_type=case_type if number else None,
            case_number=number.group("num") if number and case_type else None,
            case_year=int(number.group("year")) if number and case_type else None,
            item_no=item_no,
            courtroom=courtroom,
            reason=clean(shifted.group(0))[:200] if shifted else "deleted",
        ))
