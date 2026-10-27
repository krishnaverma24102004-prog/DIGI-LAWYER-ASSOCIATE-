"""Cause-list grammars: one module per court, behind a common interface.

Each court module (``sci.py``, ``dhc.py``) provides

* ``CODE``: the court's code in ``public.courts`` (e.g. ``SCI``),
* ``FETCHER``: a :class:`FetcherConfig` (where the lists are published, when to poll, the court
  website's terms of use and robots policy, and whether automated access is allowed at all),
* ``parse(lines) -> ParsedList``: a deterministic grammar over the PDF's text laid out in rows and
  columns (pypdfium2 text with positions; Tesseract OCR lines for scanned pages). No AI.

Shared here: the PDF layout extraction, case-number and case-type normalisation, advocate-name
normalisation, and the captcha guard (lists behind a captcha are never fetched: a member downloads
and forwards them).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, time
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

LIST_TYPES = ("daily", "supplementary", "advance")
SEGMENTS = ("fresh", "after_notice", "regular", "supplementary", "advance", "other")
STATUSES = ("listed", "deleted", "not_to_be_taken_up")

# ----------------------------------------------------------------------------- captcha guard

# Hosts and URL fragments of services that sit behind a captcha. No fetcher may request them; the
# lists they serve (district courts on eCourts, HC services) are forward-only. tests/test_causelists.py
# checks statically that no other string in the fetcher code names one of these.
CAPTCHA_HOSTS = (
    "ecourts.gov.in",          # services., hcservices., njdg., districts. ... (case status, cause lists)
    "main.sci.gov.in",         # the old Supreme Court case-status site
    "sci.gov.in/cause-list",   # the SC search form (we use the published PDF paths instead)
    "siwp_captcha",
    "captcha",
)


def is_captcha_url(url: str) -> bool:
    lowered = url.lower()
    host = urlsplit(lowered).hostname or ""
    return any(
        host == marker or host.endswith("." + marker) or marker in lowered
        for marker in CAPTCHA_HOSTS
    )


# ----------------------------------------------------------------------------- fetcher config


@dataclass(frozen=True)
class FetcherConfig:
    court_code: str
    name: str
    complex: str | None
    state: str | None
    home_url: str
    # Format with {date} (YYYY-MM-DD) / {ddmmyyyy}; one entry per list file: (template, list_type).
    url_templates: tuple[tuple[str, str], ...]
    terms_url: str
    terms_note: str
    robots_note: str
    automated_access_allowed: bool
    poll_start: time = time(17, 0)   # IST
    poll_end: time = time(10, 0)     # IST, next morning
    poll_every_minutes: int = 30
    request_delay_seconds: float = 1.0
    user_agent: str = "DigiLawyer-CauseListBot/1.0 (+cause-list reconciliation for law firms)"

    def urls_for(self, day: date) -> list[tuple[str, str]]:
        values = {"date": day.isoformat(), "ddmmyyyy": day.strftime("%d%m%Y"), "dd_mm_yyyy": day.strftime("%d.%m.%Y"),
                  "yyyy_mm": day.strftime("%Y-%m")}
        urls = [(template.format(**values), list_type) for template, list_type in self.url_templates]
        for url, _ in urls:
            if is_captcha_url(url):  # defence in depth; the static test keeps these out of configs
                raise ValueError(f"Refusing a captcha-protected URL: {url}")
        return urls


# ----------------------------------------------------------------------------- parsed output


@dataclass
class ParsedItem:
    item_no: str
    case_type: str | None
    case_number: str | None
    case_year: int | None
    courtroom: str | None = None
    bench_key: str | None = None
    bench_label: str | None = None
    segment: str = "other"
    connected_to: str | None = None
    status: str = "listed"
    parties: str = ""
    advocates: list[str] = field(default_factory=list)
    advocate_codes: list[str] = field(default_factory=list)
    page: int | None = None
    position: int | None = None

    @property
    def case_label(self) -> str:
        if not self.case_number:
            return self.case_type or ""
        return f"{self.case_type} {self.case_number}/{self.case_year}"


@dataclass
class Deletion:
    """A drop / deletion note: the item at `item_no` (in `courtroom`, when given) is not taken up."""

    case_type: str | None
    case_number: str | None
    case_year: int | None
    item_no: str | None
    courtroom: str | None
    reason: str
    status: str = "deleted"


@dataclass
class ParsedList:
    court_code: str
    list_date: date | None = None
    list_type: str | None = None
    items: list[ParsedItem] = field(default_factory=list)
    deletions: list[Deletion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0


# ----------------------------------------------------------------------------- PDF layout

SOFT_HYPHENS = str.maketrans({"\x02": "-", "￾": "-", "­": "-", "‐": "-", "‑": "-", "–": "-",
                              "‘": "'", "’": "'", "‛": "'", "‟": "'", "′": "'",
                              "“": '"', "”": '"', " ": " ", "\t": " ", "\r": " ", "\n": " "})
MIN_PAGE_CHARS = 25


def clean(text: str) -> str:
    return re.sub(r" {2,}", " ", (text or "").translate(SOFT_HYPHENS)).strip()


@dataclass
class Fragment:
    x0: float
    x1: float
    text: str


@dataclass
class Line:
    page: int
    y: float                     # distance from the top of the page
    fragments: list[Fragment]
    ocr: bool = False

    @property
    def text(self) -> str:
        return clean(" ".join(f.text for f in self.fragments))

    def columns(self, bounds: list[float]) -> list[str]:
        """Text per column; `bounds` are the left edges of columns 1..n (column 0 is left of them)."""
        cols = [[] for _ in range(len(bounds) + 1)]
        if self.ocr:  # no positions: everything in the first column, the grammar falls back to regexes
            cols[0].append(self.text)
        else:
            for fragment in self.fragments:
                index = sum(1 for b in bounds if fragment.x0 >= b)
                cols[index].append(fragment.text)
        return [clean(" ".join(c)) for c in cols]


def _page_fragments(page) -> list[tuple[float, float, float, float, str]]:
    textpage = page.get_textpage()
    try:
        out = []
        height = page.get_height()
        for i in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(i)
            text = textpage.get_text_bounded(left, bottom, right, top)
            if text and text.strip():
                out.append((left, right, height - (bottom + top) / 2, top - bottom, text))
        return out
    finally:
        textpage.close()


def _group_lines(fragments, page_number: int) -> list[Line]:
    lines: list[Line] = []
    centre = None
    for x0, x1, y, h, text in sorted(fragments, key=lambda f: (round(f[2], 1), f[0])):
        tolerance = max(2.5, min(h, 12) * 0.4)
        if centre is not None and abs(y - centre) <= tolerance:
            lines[-1].fragments.append(Fragment(x0, x1, text))
        else:
            lines.append(Line(page_number, y, [Fragment(x0, x1, text)]))
            centre = y
    for line in lines:
        line.fragments.sort(key=lambda f: f.x0)
        merged: list[Fragment] = []
        for fragment in line.fragments:
            # Pieces of one word ("HO" + "N'BLE") touch; pieces of different cells don't.
            if merged and fragment.x0 - merged[-1].x1 < 1.2 and fragment.x0 >= merged[-1].x0:
                merged[-1] = Fragment(merged[-1].x0, max(merged[-1].x1, fragment.x1), merged[-1].text + fragment.text)
            else:
                merged.append(Fragment(fragment.x0, fragment.x1, fragment.text))
        line.fragments = [Fragment(f.x0, f.x1, clean(f.text)) for f in merged if clean(f.text)]
    return [line for line in lines if line.fragments]


def _ocr_lines(data: bytes, page_index: int) -> list[Line]:
    """Tesseract only: a cause list never goes to the vision fallback (it is not needed, and the list
    would leave the server)."""
    from app.services import ocr_service

    if not ocr_service.tesseract_available():
        raise ocr_service.OcrUnavailable("Tesseract is not installed; scanned cause-list pages can't be read")
    text, _confidence = ocr_service.ocr_image(ocr_service.render_pdf_page(data, page_index))
    return [Line(page_index + 1, float(n), [Fragment(0.0, 0.0, clean(t))], ocr=True)
            for n, t in enumerate(text.splitlines()) if clean(t)]


def pdf_lines(data: bytes, *, max_pages: int = 600) -> tuple[list[Line], int, list[str]]:
    """The PDF's text as rows of positioned fragments, page by page; scanned pages are OCR'd."""
    import pypdfium2 as pdfium

    warnings: list[str] = []
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:  # pdfium raises PdfiumError for anything unreadable
        raise ValueError("The file is not a readable PDF") from exc
    try:
        count = len(pdf)
        if count > max_pages:
            raise ValueError(f"The PDF has {count} pages; the limit is {max_pages}")
        lines: list[Line] = []
        scanned = 0
        for index in range(count):
            page = pdf[index]
            try:
                fragments = _page_fragments(page)
            finally:
                page.close()
            if sum(len(f[4].strip()) for f in fragments) >= MIN_PAGE_CHARS:
                lines += _group_lines(fragments, index + 1)
                continue
            scanned += 1
            try:
                lines += _ocr_lines(data, index)
            except Exception as exc:
                warnings.append(f"page {index + 1}: no text layer and OCR failed ({exc})")
        if scanned:
            warnings.append(f"{scanned} page(s) without a text layer")
        return lines, count, warnings
    finally:
        pdf.close()


# ----------------------------------------------------------------------------- case numbers

DEFAULT_CASE_TYPE_ALIASES: dict[str, str] = {
    "WRITPETITION(CIVIL)": "WP(C)",
    "WRITPETITION(C)": "WP(C)",
    "WRITPETITION(CRIMINAL)": "WP(CRL)",
    "WP(CRIMINAL)": "WP(CRL)",
    "SPECIALLEAVEPETITION(CIVIL)": "SLP(C)",
    "SPECIALLEAVEPETITION(C)": "SLP(C)",
    "SPECIALLEAVEPETITION(CRIMINAL)": "SLP(CRL)",
    "SLP(CRIMINAL)": "SLP(CRL)",
    "CIVILAPPEAL": "CA",
    "CRIMINALAPPEAL": "CRLA",
    "CRLAPPEAL": "CRLA",
    "LETTERSPATENTAPPEAL": "LPA",
    "BAILAPPLICATION": "BAILAPPLN",
    "BAILAPPL": "BAILAPPLN",
    "CONTEMPTCASE(CIVIL)": "CONTCAS(C)",
    "CONTEMPTCASE(C)": "CONTCAS(C)",
    "CONTEMPTPETITION(CIVIL)": "CONMT(C)",
    "TRANSFERPETITION(CIVIL)": "TP(C)",
    "TRANSFERPETITION(CRIMINAL)": "TP(CRL)",
    "CRIMINALMISCCASE": "CRLMC",
    "CRLMISC(MAIN)": "CRLMC",
    "CIVILSUIT(COMM)": "CS(COMM)",
    "COMMERCIALSUIT": "CS(COMM)",
    "REGULARFIRSTAPPEAL": "RFA",
    "REGULARSECONDAPPEAL": "RSA",
    "DIARYNO": "DIARY",
}


def type_key(case_type: str | None, aliases: dict[str, str] | None = None) -> str | None:
    """'W.P.(C.)', 'WP (C)', 'Writ Petition (Civil)' -> 'WP(C)'. Aliases map normalised -> canonical."""
    if not case_type:
        return None
    key = re.sub(r"[\s.\-_,]", "", case_type.upper()).replace("[", "(").replace("]", ")")
    table = DEFAULT_CASE_TYPE_ALIASES if aliases is None else aliases
    seen = set()
    while key in table and key not in seen:  # an alias may point at another alias
        seen.add(key)
        key = table[key]
    return key or None


FIRM_CASE = re.compile(
    r"^\s*(?P<type>.*?[A-Za-z)\].])\s*(?:No\.?|Number)?\s*[-:]?\s*(?P<num>\d+(?:\s*-\s*\d+)?)\s*(?:/|\bof\b|-)\s*(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaseKey:
    type_key: str
    first: int
    last: int
    year: int

    def covers(self, other: "CaseKey") -> bool:
        return self.type_key == other.type_key and self.year == other.year and self.first <= other.first <= self.last


def number_range(number: str | None) -> tuple[int, int] | None:
    if not number:
        return None
    parts = [re.sub(r"[A-Za-z]+$", "", p) for p in re.split(r"\s*-\s*", number.strip()) if p]  # '33837A' -> '33837'
    if not parts or not all(p.isdigit() for p in parts):
        return None
    first = int(parts[0])
    last = int(parts[-1]) if len(parts) > 1 else first
    if last < first and len(parts[-1]) < len(parts[0]):  # '73731-32' means 73731 to 73732
        last = int(parts[0][: len(parts[0]) - len(parts[-1])] + parts[-1])
    return (first, max(first, last))


def case_key(case_type: str | None, number: str | None, year: int | None, aliases: dict[str, str] | None = None) -> CaseKey | None:
    key = type_key(case_type, aliases)
    rng = number_range(number)
    if not key or not rng or not year:
        return None
    return CaseKey(key, rng[0], rng[1], int(year))


def parse_case_text(text: str | None, aliases: dict[str, str] | None = None) -> CaseKey | None:
    """A firm's case number as typed: 'W.P.(C) 1234/2025', 'WP(C) 1234 of 2025', 'Diary No. 4278-2025'."""
    if not text:
        return None
    match = FIRM_CASE.match(text.strip())
    if not match:
        return None
    return case_key(match.group("type"), re.sub(r"\s", "", match.group("num")), int(match.group("year")), aliases)


# ----------------------------------------------------------------------------- names

HONORIFICS = {"MR", "MS", "MRS", "DR", "SH", "SHRI", "SMT", "ADV", "ADVOCATE", "KUM", "HON'BLE", "HONBLE", "JUSTICE", "THE"}


def name_tokens(name: str | None) -> list[str]:
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("'", "")).split()
    return [w for w in words if w not in HONORIFICS]


HONBLE = re.compile(r"^\s*HON\W{0,2}\s?B\W?\s?LE\s*")


def judge_name(line: str) -> str:
    """"HON'BLE MR. JUSTICE PRASANNA B. VARALE" -> 'PRASANNA B VARALE'; 'HON'BLE THE CHIEF JUSTICE' -> 'CHIEF JUSTICE'."""
    upper = HONBLE.sub("", clean(line).upper())
    if re.search(r"CHIEF\s*JUSTICE", upper):
        return "ACTING CHIEF JUSTICE" if "ACTING" in upper else "CHIEF JUSTICE"
    upper = re.sub(r"^(?:THE\s+)?(?:M\s+(?=M[RS]))?(?:MRS|MR|MS|DR|SMT)\s*\.?\s*", "", upper.strip())
    upper = re.sub(r"^JUSTICE\b\.?", "", upper.strip())
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", upper).split())


def judge_key(line: str) -> str:
    """A spacing-proof key for one judge: letters only, titles removed ('DINESHBHATT')."""
    letters = re.sub(r"[^A-Z]", "", HONBLE.sub("", clean(line).upper()))
    if "CHIEFJUSTICE" in letters:
        return "ACTINGCHIEFJUSTICE" if "ACTING" in letters else "CHIEFJUSTICE"
    # 'M MS.' occurs in some text layers (an overprinted glyph).
    return re.sub(r"^(?:THE)?(?:M(?=M[RS]))?(?:MRS|MR|MS|DR|SMT)?(?:JUSTICE)?", "", letters)


def bench_key(court_code: str, judges: list[str]) -> str | None:
    """`judges` are the bench lines as printed; the key doesn't change with spacing or titles."""
    names = sorted({judge_key(j) for j in judges if judge_key(j)})
    return f"{court_code}:" + "|".join(names) if names else None


def bench_label(judges: list[str]) -> str | None:
    return "; ".join(n for n in (judge_name(j) for j in judges) if n) or None


def fingerprint(item: ParsedItem, list_type: str) -> str:
    """Where and how a matter is listed: a revised list re-notifies a matter only when this changes."""
    parts = [list_type, item.courtroom or "", item.bench_key or "", item.item_no, str(item.position), item.status, item.connected_to or ""]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def assign_positions(items: list[ParsedItem]) -> None:
    """Printed rank per courtroom: connected matters share their main item's position; deleted have none."""
    counters: dict[str | None, int] = {}
    by_item: dict[tuple[str | None, str], int] = {}
    for item in items:
        if item.status != "listed":
            item.position = None
            continue
        if item.connected_to and (item.courtroom, item.connected_to) in by_item:
            item.position = by_item[(item.courtroom, item.connected_to)]
            continue
        counters[item.courtroom] = counters.get(item.courtroom, 0) + 1
        item.position = counters[item.courtroom]
        by_item[(item.courtroom, item.item_no)] = item.position


STATUS_PATTERNS = (
    (re.compile(r"\bNOT\s+TO\s+BE\s+(?:LISTED|TAKEN\s+UP)\b"), "not_to_be_taken_up"),
    (re.compile(r"\b(?:TO\s+BE\s+LISTED\s+AFTER\s+NOTICE|LIST\s+AFTER\s+NOTICE)\b"), "not_to_be_taken_up"),
    (re.compile(r"(?:^|[\s\[(-])DELETED\b"), "deleted"),
)


def status_from(text: str) -> str | None:
    upper = (text or "").upper()
    for pattern, status in STATUS_PATTERNS:
        if pattern.search(upper):
            return status
    return None


# ----------------------------------------------------------------------------- registry


def parsers() -> dict:
    from app.services.causelists import dhc, sci

    return {sci.CODE: sci, dhc.CODE: dhc}


def get_parser(court_code: str):
    return parsers().get((court_code or "").upper())


def parse_pdf(court_code: str, data: bytes) -> ParsedList:
    module = get_parser(court_code)
    if module is None:
        raise LookupError(f"No cause-list parser for {court_code} yet")
    lines, pages, warnings = pdf_lines(data)
    parsed = module.parse(lines)
    parsed.page_count = pages
    parsed.warnings = warnings + parsed.warnings
    assign_positions(parsed.items)
    return parsed
