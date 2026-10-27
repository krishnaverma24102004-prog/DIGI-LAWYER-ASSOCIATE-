"""P05 cause-list reconciliation: real-list parser fixtures, matching, revisions, escalation, warnings.

Parser fixtures are real public cause lists (tests/fixtures/causelists/labels.json says where each
came from) with hand-labelled items. They cover the Supreme Court and the Delhi High Court only, a
few pages each; recall/precision here say nothing about lists outside these fixtures.
"""

import ast
import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.routers import causelists as causelists_router
from app.services import causelist_service, causelists
from app.services.causelists import Fragment, Line, ParsedItem, ParsedList, dhc, sci
from tests.conftest import ORG_ID

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "causelists"
LABELS = json.loads((FIXTURES / "labels.json").read_text(encoding="utf-8"))["fixtures"]
# Delhi High Court lists aren't in the repository (the court's terms forbid storing its pages without
# permission); a developer who has them locally in dhc/ runs those tests too.
DHC_LABELS_FILE = FIXTURES / "dhc" / "labels.json"
if DHC_LABELS_FILE.exists():
    LABELS += json.loads(DHC_LABELS_FILE.read_text(encoding="utf-8"))["fixtures"]
needs_dhc_fixtures = pytest.mark.skipif(not DHC_LABELS_FILE.exists(), reason="Delhi High Court fixtures are kept out of the repository")
IST = causelist_service.IST

OWNER = "11111111-1111-1111-1111-111111111111"
PARTNER = "22222222-2222-2222-2222-222222222222"
ASSOCIATE = "33333333-3333-3333-3333-333333333333"
JUNIOR = "44444444-4444-4444-4444-444444444444"


def at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=IST)


# ============================================================================ an in-memory Supabase


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload, self.opts = db, table, [], "select", None, {}
        self._limit = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: _norm(r.get(col)) == _norm(val))
        return self

    def in_(self, col, vals):
        vals = [_norm(v) for v in vals]
        self.filters.append(lambda r: _norm(r.get(col)) in vals)
        return self

    def is_(self, col, val):
        self.filters.append(lambda r: r.get(col) is None if val == "null" else r.get(col) == val)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, rows):
        self.op, self.payload = "insert", rows
        return self

    def upsert(self, row, on_conflict="id", ignore_duplicates=False):
        self.op, self.payload, self.opts = "upsert", row, {"keys": on_conflict.split(","), "ignore": ignore_duplicates}
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            return Result([dict(r) for r in match[: self._limit or None]])
        if self.op == "insert":
            many = isinstance(self.payload, list)
            out = []
            for row in (self.payload if many else [self.payload]):
                stored = {"id": str(uuid.uuid4()), **row}
                rows.append(stored)
                out.append(dict(stored))
            return Result(out)
        if self.op == "upsert":
            keys = self.opts["keys"]
            existing = [r for r in rows if all(r.get(k) == self.payload.get(k) for k in keys)]
            if existing:
                if not self.opts["ignore"]:
                    existing[0].update(self.payload)
                return Result([])
            rows.append(dict(self.payload))
            return Result([dict(self.payload)])
        if self.op == "update":
            for r in match:
                r.update(self.payload)
            self.db.updates.append((self.table, dict(self.payload), len(match)))
            return Result([dict(r) for r in match])
        if self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if r not in match]
            return Result([dict(r) for r in match])
        raise AssertionError(self.op)


def _norm(value):
    return value.isoformat() if isinstance(value, date) else value


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.updates: list = []

    def table(self, name):
        return Query(self, name)


def firm_db(cases=(), aliases=()) -> FakeDB:
    db = FakeDB()
    db.tables["organization_members"] = [
        {"org_id": ORG_ID, "user_id": OWNER, "role": "owner"},
        {"org_id": ORG_ID, "user_id": PARTNER, "role": "partner"},
        {"org_id": ORG_ID, "user_id": ASSOCIATE, "role": "associate"},
        {"org_id": ORG_ID, "user_id": JUNIOR, "role": "associate"},
    ]
    db.tables["users"] = [
        {"id": OWNER, "full_name": "Meera Iyer", "email": "o@x.in"},
        {"id": PARTNER, "full_name": "Karan Malhotra", "email": "p@x.in"},
        {"id": ASSOCIATE, "full_name": "Rishi Matoliya", "email": "a@x.in"},
        {"id": JUNIOR, "full_name": "Aditi Rao", "email": "j@x.in"},
    ]
    db.tables["court_cases"] = [{"org_id": ORG_ID, "user_id": ASSOCIATE, "fallback_advocate_id": None, "petitioners": [],
                                 "respondents": [], "next_hearing_date": None, **c} for c in cases]
    db.tables["advocate_aliases"] = [{"org_id": ORG_ID, **a} for a in aliases]
    return db


# ============================================================================ parser fixtures (real lists)


def _lines(path: Path) -> list[Line]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Line(row["page"], row["y"], [Fragment(f[0], f[1], f[2]) for f in row["fragments"]], row.get("ocr", False))
            for row in data["lines"]]


def _parse_fixture(fixture: dict) -> ParsedList:
    path = FIXTURES / fixture["file"]
    if path.suffix == ".pdf":
        return causelists.parse_pdf(fixture["court"], path.read_bytes())
    parsed = causelists.get_parser(fixture["court"]).parse(_lines(path))
    causelists.assign_positions(parsed.items)
    return parsed


def _key(case: str):
    match = re.match(r"^(?P<type>.+?) (?P<num>[\dA-Z-]+)/(?P<year>\d{4})$", case)
    return causelists.case_key(match.group("type"), match.group("num"), int(match.group("year")))


@pytest.mark.parametrize("fixture", LABELS, ids=[f["file"] for f in LABELS])
def test_parser_on_real_lists(fixture):
    parsed = _parse_fixture(fixture)
    assert parsed.list_date == date.fromisoformat(fixture["list_date"])
    assert parsed.list_type == fixture["list_type"]

    expected = [(i["item_no"], i["courtroom"], _key(i["case"]), i.get("connected_to")) for i in fixture["items"]]
    got = [(i.item_no, i.courtroom, causelists.case_key(i.case_type, i.case_number, i.case_year), i.connected_to)
           for i in parsed.items]
    missing = [e for e in expected if e not in got]
    extra = [g for g in got if g not in expected]
    assert not missing, f"not found (recall): {missing}"      # case-number recall 100% on these fixtures
    assert not extra, f"not in the list (precision): {extra}"  # and no invented items
    assert all(i.status == "listed" for i in parsed.items)

    by_no = {(i.item_no, i.case_number): i for i in parsed.items}
    for label in fixture["items"]:
        number = label["case"].rsplit(" ", 1)[1].split("/")[0]
        item = by_no[(label["item_no"], number)]
        if "advocates" in label:
            assert item.advocates[: len(label["advocates"])] == label["advocates"]
        if "advocate_codes" in label:
            assert item.advocate_codes[: len(label["advocate_codes"])] == label["advocate_codes"]
        if "segment" in label:
            assert item.segment == label["segment"]
        if fixture["list_type"] == "advance" and fixture["court"] == "SCI":
            assert item.segment == "advance"

    deletions = [(d.item_no, d.courtroom, causelists.case_key(d.case_type, d.case_number, d.case_year)) for d in parsed.deletions]
    assert deletions == [(d["item_no"], d["courtroom"], _key(d["case"])) for d in fixture.get("deletions", [])]


def test_positions_bench_and_parties_on_the_sc_chamber_list():
    fixture = next(f for f in LABELS if f["file"].endswith("M_C_1_p1-3.pdf"))
    parsed = _parse_fixture(fixture)
    by_no = {i.item_no: i for i in parsed.items}
    # Connected matters share their main item's printed position.
    assert by_no["1710"].position == by_no["1710.1"].position == 10
    assert by_no["1711"].position == 11
    assert by_no["1701"].bench_key == "SCI:PRASANNABVARALE"
    assert by_no["1701"].bench_label == "PRASANNA B VARALE"
    assert by_no["1701"].parties == "SYED IBRAHIM AND ANR. v. YERUKALI KONDAREDDY PADMA AND ORS."


@needs_dhc_fixtures
def test_dhc_bench_keys_survive_odd_text_layers():
    """'HON'BLE M MR.JUSTICE DINESH BHATT' and 'HON' BLE MS.JUSTICE ...' are real text layers."""
    fixture = next(f for f in LABELS if "combined_sup_1" in f["file"])
    parsed = _parse_fixture(fixture)
    court_33 = {i.bench_key for i in parsed.items if i.courtroom == "33"}
    assert court_33 == {"DLHC:DINESHBHATT|PRATHIBAMSINGH"}
    court_38 = {i.bench_key for i in parsed.items if i.courtroom == "38"}
    assert court_38 == {"DLHC:NISHASAHAYSAXENA|VIVEKCHAUDHARY"}


def test_item_statuses_deleted_not_to_be_listed_and_after_notice():
    assert causelists.status_from("[ DELETED ]") == "deleted"
    assert causelists.status_from("Listing Remarks: NOT TO BE LISTED") == "not_to_be_taken_up"
    assert causelists.status_from("NOT TO BE TAKEN UP TODAY") == "not_to_be_taken_up"
    assert causelists.status_from("TO BE LISTED AFTER NOTICE") == "not_to_be_taken_up"
    # Words that merely contain the markers don't count.
    assert causelists.status_from("IA No. 1/2026 - DELETING THE NAME OF PETITIONER") is None
    assert causelists.status_from("AFTER NOTICE MISC. MATTERS") is None
    # 'After notice' as a heading is a segment, not a status.
    assert dhc._segment("AFTERNOTICEMISC.MATTERS") == "after_notice"

    def row(y, *cells, x=(44, 69, 186, 426)):
        return Line(1, y, [Fragment(x0, x0 + 50, text) for x0, text in zip(x, cells) if text])

    lines = [
        row(1, "DAILY CAUSE LIST FOR DATED : 28-10-2026"), row(2, "COURT NO. : 5"),
        row(3, "HON'BLE MR. JUSTICE A. B. KUMAR"), row(4, "SNo.", "Case No.", "Petitioner / Respondent", "Petitioner/Respondent"),
        row(5, "1", "SLP(C) No. 100/2026", "RAM KUMAR", "X Y- 10"), row(6, "", "", "Versus"), row(7, "", "", "SHYAM LAL"),
        row(8, "2", "SLP(C) No. 200/2026", "GITA DEVI", "P Q- 11"), row(9, "", "", "Versus"),
        row(10, "", "", "MOHAN [ DELETED ]"),
        row(11, "3", "SLP(C) No. 300/2026", "A B C", "R S- 12"), row(12, "", "", "[ NOT TO BE TAKEN UP ]"),
    ]
    parsed = sci.parse(lines)
    causelists.assign_positions(parsed.items)
    states = {i.item_no: (i.status, i.position) for i in parsed.items}
    assert states == {"1": ("listed", 1), "2": ("deleted", None), "3": ("not_to_be_taken_up", None)}


def test_ocr_lines_fall_back_to_regexes():
    """Scanned pages come back from Tesseract as plain lines (no positions)."""
    lines = [Line(1, n, [Fragment(0, 0, t)], ocr=True) for n, t in enumerate([
        "DAILY CAUSE LIST FOR DATED : 28-10-2026", "COURT NO. : 7", "SNo. Case No. Petitioner / Respondent",
        "12 W.P.(C) No. 455/2026 ANIL KUMAR", "Versus", "STATE OF U.P.", "13 Diary No. 9001-2026 X LTD",
    ])]
    parsed = sci.parse(lines)
    assert [(i.item_no, i.case_type, i.case_number, i.case_year) for i in parsed.items] == [
        ("12", "W.P.(C)", "455", 2026), ("13", "Diary", "9001", 2026)]


def test_scanned_pages_never_use_the_vision_fallback(monkeypatch):
    from app.services import ocr_service

    monkeypatch.setattr(ocr_service, "read_page_image", lambda *a, **k: pytest.fail("vision path used"))
    monkeypatch.setattr(ocr_service, "tesseract_available", lambda: False)
    with pytest.raises(ocr_service.OcrUnavailable):
        causelists._ocr_lines(b"%PDF", 0)


# ============================================================================ matching


def _item(case: str, **extra) -> dict:
    key = causelists.parse_case_text(case)
    match = causelists.FIRM_CASE.match(case)
    return {"id": str(uuid.uuid4()), "case_type": match.group("type"), "case_number": match.group("num").replace(" ", ""),
            "case_year": int(match.group("year")), "case_type_key": key.type_key if key else None, "parties": "",
            "advocates": [], "advocate_codes": [], "status": "listed", "list_type": "daily", "item_no": "1", **extra}


def _roster(db: FakeDB) -> causelist_service.Roster:
    users = {u["id"]: u["full_name"] for u in db.tables["users"]}
    return causelist_service.Roster(ORG_ID, db.tables["court_cases"], db.tables["advocate_aliases"],
                                    db.tables["organization_members"], users)


def test_alias_matching():
    db = firm_db(cases=[{"id": "case-1", "title": "Gulshan Katyal v. Municipal Corporation of Delhi", "court_name": "Delhi High Court",
                         "case_number": "W.P.(C) 1234/2025", "petitioners": ["Gulshan Katyal"],
                         "respondents": ["Municipal Corporation of Delhi"]}])
    roster = _roster(db)
    written_one = _item("WP(C) 1234 of 2025")
    written_two = _item("W.P.(C.) 1234/2025")
    misprint = _item("W.P.(C) 1243/2025", parties="GULSHAN KATYAL v. MUNICIPAL CORPORATION OF DELHI")
    other = _item("W.P.(C) 1243/2025", parties="RAM PRASAD v. DDA")
    matches = causelist_service.match_items([written_one, written_two, misprint, other], roster, "DLHC")
    kinds = {m["item"]["id"]: m["match_type"] for m in matches}
    assert kinds[written_one["id"]] == "exact"
    assert kinds[written_two["id"]] == "exact"
    assert misprint["id"] not in kinds  # the case already matched exactly in this list
    # Without the exact listings, the misprinted number is 'probable', never exact.
    matches = causelist_service.match_items([misprint, other], roster, "DLHC")
    assert [(m["item"]["id"], m["match_type"]) for m in matches] == [(misprint["id"], "probable")]
    assert "number differs" in matches[0]["reason"]
    # Writ Petition (Civil) is an alias of W.P.(C); a matter in another court never matches.
    assert causelist_service.match_items([_item("Writ Petition (Civil) 1234/2025")], roster, "DLHC")[0]["match_type"] == "exact"
    assert causelist_service.match_items([written_one], roster, "SCI") == []


def test_number_ranges_cover_each_matter():
    db = firm_db(cases=[{"id": "c", "title": "State of West Bengal v. Dub Associates", "court_name": "Supreme Court",
                         "case_number": "SLP(C) No. 26148/2025"}])
    item = _item("SLP(C) 26147-26149/2025")
    assert causelist_service.match_items([item], _roster(db), "SCI")[0]["match_type"] == "exact"


def test_possibly_ours():
    db = firm_db(aliases=[{"user_id": JUNIOR, "alias": "D. Abhinav Rao", "enrolment_no": None},
                          {"user_id": PARTNER, "alias": "Karanjawala & Co.", "enrolment_no": "1707"}])
    roster = _roster(db)
    by_name = _item("SLP(C) 7439/2023", advocates=["D. ABHINAV RAO", "ANAND DILIP LANDGE"], advocate_codes=["2277", "2739"])
    variant = _item("SLP(C) 1/2026", advocates=["ABHINAV RAO D"])
    by_code = _item("Diary 4278/2025", advocates=["SOMEONE ELSE"], advocate_codes=["1707"])
    by_member = _item("C.A. 7/2026", advocates=["RISHI MATOLIYA"])  # a member's own name
    stranger = _item("C.A. 8/2026", advocates=["ABHINAV KUMAR"])
    matches = causelist_service.match_items([by_name, variant, by_code, by_member, stranger], roster, "SCI")
    found = {m["item"]["id"]: (m["match_type"], m["appearing_advocate_id"]) for m in matches}
    assert found == {by_name["id"]: ("possibly_ours", JUNIOR), variant["id"]: ("possibly_ours", JUNIOR),
                     by_code["id"]: ("possibly_ours", PARTNER), by_member["id"]: ("possibly_ours", ASSOCIATE)}
    assert all(m["court_case_id"] is None for m in matches)


# ============================================================================ ingestion, revisions, escalation


CASES = [
    {"id": "case-a", "title": "Ruchi Gupta v. Shaligram Prasad Gupta", "court_name": "Delhi High Court",
     "case_number": "CONT.CAS(C) 1086/2026", "fallback_advocate_id": JUNIOR, "next_hearing_date": "2026-12-01"},
    {"id": "case-b", "title": "Madan Lal Kapoor v. State", "court_name": "Delhi High Court", "case_number": "CRL.M.C. 5784/2025",
     "fallback_advocate_id": None},
    {"id": "case-c", "title": "Ravi Kumar v. State", "court_name": "Delhi High Court", "case_number": "CRL.A. 488/2025"},
]


def _parsed(day="2026-10-28", kind="supplementary", items=(), deletions=()) -> ParsedList:
    parsed = ParsedList("DLHC", date.fromisoformat(day), kind, list(items), list(deletions), [], 1)
    causelists.assign_positions(parsed.items)
    return parsed


def _pi(no, case, room="15", status="listed", advocates=()):
    match = causelists.FIRM_CASE.match(case)
    return ParsedItem(no, match.group("type"), match.group("num"), int(match.group("year")), courtroom=room,
                      bench_key="DLHC:X", bench_label="X", status=status, advocates=list(advocates))


@pytest.fixture
def parse_with(monkeypatch):
    queue = []

    def fake_parse(court, data):
        return queue.pop(0)

    monkeypatch.setattr(causelists, "parse_pdf", fake_parse)
    return queue


async def _ingest(db, parsed_queue, parsed, data, when, url="https://example.test/list.pdf", **kw):
    parsed_queue.append(parsed)
    return await causelist_service.ingest_pdf(db, "DLHC", data, now=when, source_url=url, **kw)


async def test_exact_daily_listing_sets_the_hearing_date_and_advance_does_not(parse_with, audit_log):
    db = firm_db(cases=CASES)
    await _ingest(db, parse_with, _parsed("2026-10-30", "advance", [_pi("4", "CRL.A. 488/2025")]), b"%PDF adv", at("2026-10-27", "18:00"),
                  url="https://example.test/adv.pdf")
    assert next(c for c in db.tables["court_cases"] if c["id"] == "case-c")["next_hearing_date"] is None
    result = await _ingest(db, parse_with, _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026"), _pi("71", "CRL.A. 488/2025", "27", status="deleted")]),
                           b"%PDF v1", at("2026-10-27", "18:00"))
    assert result["exact"] == 2 and result["hearing_dates_set"] == 1
    cases = {c["id"]: c for c in db.tables["court_cases"]}
    assert cases["case-a"]["next_hearing_date"] == "2026-10-28"   # exact, supplementary, listed
    assert cases["case-c"]["next_hearing_date"] is None           # deleted from the list
    audit = [e for e in audit_log if e["action"] == "SET_HEARING_FROM_CAUSE_LIST"]
    assert [(e["resource_id"], e["metadata"]["previous"]) for e in audit] == [("case-a", "2026-12-01")]
    # The write is scoped to the case and its org.
    match = next(m for m in db.tables["listing_matches"] if m["court_case_id"] == "case-a")
    assert (match["previous_hearing_date"], match["hearing_date_set"], match["fallback_advocate_id"]) == ("2026-12-01", True, JUNIOR)
    # Payloads carry case numbers, never party names.
    for payload in result["_notifications"]:
        assert "GUPTA" not in json.dumps(payload).upper()


async def test_revised_list_replaces(parse_with):
    db = firm_db(cases=CASES)
    first = _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026"), _pi("88", "CRL.M.C. 5784/2025", "31")])
    one = await _ingest(db, parse_with, first, b"%PDF v1", at("2026-10-27", "18:00"))
    assert {p["event"] for p in one["_notifications"]} == {"listing.new"}
    a = next(m for m in db.tables["listing_matches"] if m["court_case_id"] == "case-a")
    a["state"], a["confirmed_by"] = "confirmed", ASSOCIATE

    same = await _ingest(db, parse_with, first, b"%PDF v1", at("2026-10-27", "18:30"))
    assert same["status"] == "unchanged"
    parse_with.clear()

    # Same URL, new content: item 88 moved to court 32 as item 9; item 135 unchanged; case-c newly listed.
    second = _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026"), _pi("9", "CRL.M.C. 5784/2025", "32"), _pi("71", "CRL.A. 488/2025", "27")])
    two = await _ingest(db, parse_with, second, b"%PDF v2", at("2026-10-27", "23:10"))
    assert two["status"] == "revised"
    events = sorted((p["event"], p["case"]) for p in two["_notifications"])
    assert events == [("listing.changed", "CRL.M.C. 5784/2025"), ("listing.new", "CRL.A. 488/2025")]
    lists = db.tables["cause_lists"]
    assert len(lists) == 2 and lists[0]["superseded_by"] == lists[1]["id"] and lists[1].get("superseded_by") is None
    assert len(db.tables["cause_list_items"]) == 5  # the old list's items are kept for audit
    current = {m["court_case_id"]: m for m in db.tables["listing_matches"]}
    assert len(db.tables["listing_matches"]) == 3 and all(m["cause_list_id"] == lists[1]["id"] for m in current.values())
    assert current["case-a"]["state"] == "confirmed"                       # unchanged matter keeps its confirmation
    assert current["case-a"]["ingested_at"] == a["ingested_at"]
    assert current["case-b"]["state"] == "open"                            # moved: confirm again, clock restarts
    assert current["case-b"]["ingested_at"].startswith("2026-10-27T17:40")  # 23:10 IST


async def test_a_dropped_listing_restores_the_hearing_date(parse_with, audit_log):
    db = firm_db(cases=CASES)
    await _ingest(db, parse_with, _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026")]), b"%PDF v1", at("2026-10-27", "18:00"))
    assert db.tables["court_cases"][0]["next_hearing_date"] == "2026-10-28"
    note = causelists.Deletion("CONT.CAS(C)", "1086", 2026, "135", "15", "deleted")
    result = await _ingest(db, parse_with, _parsed(deletions=[note]), b"%PDF del", at("2026-10-27", "21:30"),
                           url="https://example.test/deletion.pdf")
    assert db.tables["court_cases"][0]["next_hearing_date"] == "2026-12-01"
    assert [p["event"] for p in result["_notifications"]] == ["listing.deleted"]
    assert db.tables["cause_list_items"][0]["status"] == "deleted"
    assert any(e["action"] == "RESTORE_HEARING_AFTER_CAUSE_LIST" for e in audit_log)


async def test_confirmation_escalation(parse_with):
    """freezegun isn't installed; the job takes `now`, which is what the cron passes."""
    db = firm_db(cases=CASES)
    await _ingest(db, parse_with, _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026"), _pi("88", "CRL.M.C. 5784/2025", "31"),
                                                 _pi("71", "CRL.A. 488/2025", "27")]), b"%PDF v1", at("2026-10-27", "18:00"))
    by_case = {m["court_case_id"]: m for m in db.tables["listing_matches"]}
    by_case["case-c"]["state"] = "confirmed"

    assert (await causelist_service.escalate(db, at("2026-10-27", "19:59")))["escalated"] == 0
    amber = await causelist_service.escalate(db, at("2026-10-27", "20:00"))
    recipients = {p["case"]: p["recipients"] for p in amber["notifications"]}
    assert recipients == {"CONT.CAS(C) 1086/2026": [JUNIOR],  # its fallback
                          "CRL.M.C. 5784/2025": [PARTNER]}    # no fallback: straight to the partner
    assert (await causelist_service.escalate(db, at("2026-10-27", "20:15")))["escalated"] == 0
    red = await causelist_service.escalate(db, at("2026-10-27", "21:00"))
    assert {p["case"]: (p["escalation_level"], p["recipients"]) for p in red["notifications"]} == {
        "CONT.CAS(C) 1086/2026": (2, [PARTNER, JUNIOR]), "CRL.M.C. 5784/2025": (2, [PARTNER])}
    by_case["case-a"]["state"] = "confirmed"
    morning = await causelist_service.escalate(db, at("2026-10-28", "07:30"))
    assert [(p["case"], p["escalation_level"]) for p in morning["notifications"]] == [("CRL.M.C. 5784/2025", 3)]
    assert {m["court_case_id"]: m["escalation_level"] for m in db.tables["listing_matches"]} == {"case-a": 2, "case-b": 3, "case-c": 0}


async def test_escalation_clock_runs_from_ingestion(parse_with):
    db = firm_db(cases=CASES)
    await _ingest(db, parse_with, _parsed(items=[_pi("135", "CONT.CAS(C) 1086/2026")]), b"%PDF late", at("2026-10-27", "22:05"))
    assert (await causelist_service.escalate(db, at("2026-10-27", "22:30")))["escalated"] == 0  # amber is due at 23:05
    morning = await causelist_service.escalate(db, at("2026-10-28", "07:30"))
    assert [p["escalation_level"] for p in morning["notifications"]] == [3]
    assert causelist_service.due_level(at("2026-10-27", "17:00"), date(2026, 10, 28), at("2026-10-27", "20:00")) == 1
    assert causelist_service.due_level(at("2026-10-27", "23:00"), date(2026, 10, 28), at("2026-10-27", "23:59")) == 0
    assert causelist_service.due_level(at("2026-10-28", "08:00"), date(2026, 10, 28), at("2026-10-28", "09:00")) == 1


def test_order_lag_warning():
    today = date(2026, 10, 27)
    case = {"last_hearing_date": "2026-10-23", "case_status": "Pending", "provider_data": {"orders": []}}
    assert [w["message"] for w in causelist_service.case_warnings(case, today)] == ["last hearing 23 Oct, order not uploaded yet"]
    case["provider_data"]["orders"].append({"date": "2026-10-23", "url": "https://x/o.pdf"})
    assert causelist_service.case_warnings(case, today) == []
    assert causelist_service.case_warnings({"last_hearing_date": "2026-10-25"}, today) == []  # still within 3 days
    disposed = {"last_hearing_date": "2026-09-01", "case_status": "Disposed", "provider_data": {"orders": [{"date": "2026-01-10"}]}}
    kinds = [w["kind"] for w in causelist_service.case_warnings(disposed, today)]
    assert kinds == ["order_lag", "disposed_no_judgment"]
    assert causelist_service.disposed_without_judgment(disposed)
    disposed["provider_data"]["orders"].append({"date": "2026-09-01"})
    assert causelist_service.case_warnings(disposed, today) == []


# ============================================================================ fetching


def test_fetchers_have_no_captcha_path():
    """Static: no string in the fetcher code names a captcha-protected host, and every configured
    URL passes the guard. (The guard's own list, CAPTCHA_HOSTS, is the only place they appear.)"""
    sources = [ROOT / "app" / "services" / "causelist_service.py", *sorted((ROOT / "app" / "services" / "causelists").glob("*.py"))]
    markers = [m for m in causelists.CAPTCHA_HOSTS if "." in m or "/" in m]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guard = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "CAPTCHA_HOSTS" for t in node.targets):
                guard |= {id(n) for n in ast.walk(node.value)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in guard:
                lowered = node.value.lower()
                assert not any(m in lowered for m in markers), f"{path.name}: {node.value!r}"
                for url in re.findall(r"https?://\S+", lowered):  # every URL the code can request
                    assert not causelists.is_captcha_url(url), f"{path.name}: {url}"
    for module in causelists.parsers().values():
        for url, _ in module.FETCHER.urls_for(date(2026, 10, 28)):
            assert url.startswith("https://") and not causelists.is_captcha_url(url)
        assert module.FETCHER.terms_url and module.FETCHER.terms_note and module.FETCHER.robots_note
    for url in ("https://services.ecourts.gov.in/ecourtindia_v6/?p=cause_list/index", "https://hcservices.ecourts.gov.in/x",
                "https://www.sci.gov.in/cause-list/", "https://main.sci.gov.in/case-status"):
        assert causelists.is_captcha_url(url)


async def test_fetch_and_ingest_respects_terms_and_windows():
    pdf = (FIXTURES / "sci" / "2026-10-27_M_C_1_p1-3.pdf").read_bytes()
    seen = []

    def handler(request: httpx.Request):
        seen.append(str(request.url))
        assert "DigiLawyer" in request.headers["user-agent"]
        if str(request.url).endswith("/2026-10-27/M_C_1.pdf"):
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)  # polite polling: an unchanged list isn't downloaded again
            return httpx.Response(200, content=pdf, headers={"etag": '"v1"'})
        return httpx.Response(404)

    db = firm_db(cases=[{"id": "case-sc", "title": "Suresh Kumar Abusaria v. Devendra Kumar Pareek", "court_name": "Supreme Court of India",
                         "case_number": "SLP(C) 24435/2025"}],
                 aliases=[{"user_id": JUNIOR, "alias": "Rishi Matoliya", "enrolment_no": "2217"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        idle = await causelist_service.fetch_and_ingest(db, at("2026-10-26", "15:00"), http_client=client, delay=0)
        assert seen == [] and {s["court"] for s in idle["skipped"]} == {"SCI", "DLHC"}
        report = await causelist_service.fetch_and_ingest(db, at("2026-10-26", "18:00"), http_client=client, delay=0)
        again = await causelist_service.fetch_and_ingest(db, at("2026-10-26", "18:30"), http_client=client, delay=0)
    assert {"court": "DLHC", "reason": "the court's terms do not allow automated access"} in report["skipped"]
    assert not any("delhihighcourt" in url for url in seen)
    assert all(url.startswith("https://api.sci.gov.in/") for url in seen)
    assert [r["url"] for r in report["ingested"]] == ["https://api.sci.gov.in/jonew/cl/2026-10-27/M_C_1.pdf"]
    assert report["ingested"][0]["items"] == 16 and again["unchanged"] == 1 and again["ingested"] == []
    assert db.tables["courts"][0]["code"] == "SCI"
    kinds = sorted((m["match_type"], m["court_case_id"]) for m in db.tables["listing_matches"])
    # 1710 is the firm's matter; 1710.1 (same parties) is listed with it and isn't flagged; the alias
    # (Rishi Matoliya, AOR 2217) is on the connected matter, so that is 'possibly ours'.
    assert kinds == [("exact", "case-sc"), ("possibly_ours", None)]
    assert db.tables["court_cases"][0]["next_hearing_date"] == "2026-10-27"


def test_case_type_aliases_are_seeded_by_the_migration():
    sql = (ROOT / "supabase" / "migrations" / "016_cause_lists.sql").read_text(encoding="utf-8")
    seeded = dict(re.findall(r"\(null, '([^']+)', '([^']+)'\)", sql))
    assert seeded == causelists.DEFAULT_CASE_TYPE_ALIASES


# ============================================================================ the API


@pytest.fixture
def api(monkeypatch):
    db = firm_db(cases=CASES)
    app = FastAPI()
    app.include_router(causelists_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=ASSOCIATE, email="a@x.in", access_token="t")
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    monkeypatch.setattr(causelists_router, "get_supabase_admin", lambda: db)
    return TestClient(app), db


async def _seed(db, parse_with, when=at("2026-10-27", "18:00")):
    items = [_pi("135", "CONT.CAS(C) 1086/2026"), _pi("88", "CRL.M.C. 5784/2025", "31", advocates=["RISHI MATOLIYA"]),
             _pi("12", "W.P.(C) 999/2026", "31", advocates=["RISHI MATOLIYA"])]
    db.tables["court_cases"][1]["case_number"] = "CRL.M.C. 5874/2025"  # the firm's record has a typo
    db.tables["court_cases"][1]["petitioners"] = ["Madan Lal Kapoor"]
    items[1].parties = "MADAN LAL KAPOOR v. THE STATE GOVT. OF NCT OF DELHI"
    await _ingest(db, parse_with, _parsed(items=items), b"%PDF v1", when)


async def test_board_confirm_claim_dismiss(api, parse_with, audit_log, monkeypatch):
    client, db = api
    await _seed(db, parse_with)
    monkeypatch.setattr(causelists_router, "_now", lambda: at("2026-10-27", "20:30"))
    board = client.get("/api/v1/causelists/board", params={"date": "2026-10-28"}).json()
    rooms = [(c["complex"], r["courtroom"], [i["item_no"] for i in r["items"]]) for c in board["complexes"] for r in c["courtrooms"]]
    assert rooms == [("Delhi High Court, Sher Shah Road, New Delhi", "15", ["135"])]  # grouped by court complex
    assert board["complexes"][0]["courtrooms"][0]["court_name"] == "High Court of Delhi"
    row = board["complexes"][0]["courtrooms"][0]["items"][0]
    assert (row["tone"], row["appearing_advocate"], row["fallback_advocate"], row["list_type"]) == ("amber", "Rishi Matoliya", "Aditi Rao", "supplementary")
    possibly = {p["case_label"]: p["match_type"] for p in board["possibly_ours"]}
    assert possibly == {"CRL.M.C. 5784/2025": "probable", "W.P.(C) 999/2026": "possibly_ours"}

    confirmed = client.post(f"/api/v1/causelists/matches/{row['id']}/confirm")
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "confirmed"
    probable = next(p for p in board["possibly_ours"] if p["match_type"] == "probable")
    claimed = client.post(f"/api/v1/causelists/matches/{probable['id']}/claim", json={})
    assert claimed.json()["state"] == "claimed" and claimed.json()["hearing_date_set"] is True
    assert db.tables["court_cases"][1]["next_hearing_date"] == "2026-10-28"  # only after the click
    other = next(p for p in board["possibly_ours"] if p["match_type"] == "possibly_ours")
    assert client.post(f"/api/v1/causelists/matches/{other['id']}/dismiss").json()["state"] == "dismissed"

    board = client.get("/api/v1/causelists/board", params={"date": "2026-10-28"}).json()
    assert board["possibly_ours"] == [] and board["dismissed"] == 1
    tones = {i["case_label"]: i["tone"] for c in board["complexes"] for r in c["courtrooms"] for i in r["items"]}
    assert tones == {"CONT.CAS(C) 1086/2026": "confirmed", "CRL.M.C. 5784/2025": "amber"}
    assert {e["action"] for e in audit_log} >= {"CONFIRM_LISTING", "CLAIM_LISTING", "DISMISS_LISTING"}
    assert client.post(f"/api/v1/causelists/matches/{uuid.uuid4()}/confirm").status_code == 404


async def test_assign_advocates_and_remember_the_fallback(api, parse_with):
    client, db = api
    await _seed(db, parse_with)
    match = next(m for m in db.tables["listing_matches"] if m["court_case_id"] == "case-a")
    response = client.put(f"/api/v1/causelists/matches/{match['id']}/advocates",
                          json={"fallback_advocate_id": PARTNER, "remember_fallback": True})
    assert response.status_code == 200 and response.json()["fallback_advocate_id"] == PARTNER
    assert db.tables["court_cases"][0]["fallback_advocate_id"] == PARTNER
    assert client.put(f"/api/v1/causelists/matches/{match['id']}/advocates", json={}).status_code == 400


@needs_dhc_fixtures
def test_upload_a_forwarded_list(api, audit_log):
    client, db = api
    pdf = (FIXTURES / "dhc" / "sup_del_jr_for_27.10.2026.pdf").read_bytes()
    db.tables["court_cases"].append({"id": "case-jr", "org_id": ORG_ID, "user_id": ASSOCIATE, "title": "DTC v. Ram Babu",
                                     "court_name": "Delhi High Court", "case_number": "W.P.(C) 1188/2018", "next_hearing_date": None})
    response = client.post("/api/v1/causelists/upload", data={"court_code": "dlhc"},
                           files={"file": ("sup_del_jr.pdf", pdf, "application/pdf")})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["list_date"], body["list_type"], body["items"], body["exact"]) == ("new", "2026-10-27", "supplementary", 1, 1)
    stored = db.tables["cause_lists"][0]
    assert (stored["org_id"], stored["source"], stored["uploaded_by"]) == (ORG_ID, "forwarded", ASSOCIATE)
    assert any(e["action"] == "UPLOAD_CAUSE_LIST" for e in audit_log)
    again = client.post("/api/v1/causelists/upload", data={"court_code": "DLHC"}, files={"file": ("x.pdf", pdf, "application/pdf")})
    assert again.json()["status"] == "unchanged"
    db.tables["cause_lists"].clear()
    wrong_day = client.post("/api/v1/causelists/upload", data={"court_code": "DLHC", "list_date": "2026-10-29"},
                            files={"file": ("y.pdf", pdf, "application/pdf")})
    assert wrong_day.status_code == 422 and "2026-10-27" in wrong_day.json()["detail"]
    assert client.post("/api/v1/causelists/upload", data={"court_code": "MH-PUNE"},
                       files={"file": ("z.pdf", pdf, "application/pdf")}).status_code == 422
    assert client.post("/api/v1/causelists/upload", data={"court_code": "DLHC"},
                       files={"file": ("z.txt", b"hello", "text/plain")}).status_code == 422


def test_aliases_crud(api):
    client, db = api
    assert client.post("/api/v1/causelists/aliases", json={"user_id": JUNIOR, "alias": "Rao"}).status_code == 422
    created = client.post("/api/v1/causelists/aliases", json={"user_id": JUNIOR, "alias": "D.  Aditi Rao", "enrolment_no": "D/12/2020"})
    assert created.status_code == 201 and created.json()["alias"] == "D. Aditi Rao"
    assert [a["alias"] for a in client.get("/api/v1/causelists/aliases").json()] == ["D. Aditi Rao"]
    assert client.delete(f"/api/v1/causelists/aliases/{created.json()['id']}").status_code == 204
    assert db.tables["advocate_aliases"] == []
    courts = {c["code"]: c["automated_access_allowed"] for c in client.get("/api/v1/causelists/courts").json()}
    assert courts == {"SCI": True, "DLHC": False}
