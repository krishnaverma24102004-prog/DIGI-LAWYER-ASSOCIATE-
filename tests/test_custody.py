"""Custody watch (P14): default-bail and s. 479 BNSS dates, computed in code from the punishment table."""

import json
import math
import sys
import types
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.routers import custody as custody_router
from app.services import citation_service
from app.services import custody_service as cs
from app.services.criminal_codes import criminal_codes
from tests.conftest import ORG_ID

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "custody_cases.json").read_text(encoding="utf-8"))
ALL_RULES = set(cs.load_table())
OWNER = "11111111-1111-4111-8111-111111111111"


def run(file: dict, today: str, orders=None, active=ALL_RULES) -> dict:
    return cs.compute(file, date.fromisoformat(today), active_rules=active, orders=orders or [])


def file_(**kw) -> dict:
    base = {"accused_name": "Ravi", "custody_type": "judicial"}
    return {**base, **kw}


# ----------------------------------------------------------------------------- golden cases


def test_golden_cases_are_marked_unsigned():
    assert "must be checked and signed by two criminal advocates before use" in GOLDEN["header"]
    assert len(GOLDEN["cases"]) >= 30 and len({c["id"] for c in GOLDEN["cases"]}) == len(GOLDEN["cases"])


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["id"] for c in GOLDEN["cases"]])
def test_golden_case(case):
    result = run(case["file"], case["today"], case.get("orders"))
    expect = case["expect"]
    codes = result["codes"]
    flag_codes = {f["code"] for f in result["flags"]}
    if "procedural" in expect:
        assert codes["procedural"] == expect["procedural"]
    if "substantive" in expect:
        assert codes["substantive"] == expect["substantive"]
    assert set(expect.get("flags", [])) <= flag_codes, flag_codes
    assert not set(expect.get("no_flags", [])) & flag_codes, flag_codes
    if "apply_today" in expect:
        assert result["apply_today"] is expect["apply_today"]
    if "days_in_custody" in expect:
        assert result["days_in_custody"] == expect["days_in_custody"]
    db = result["default_bail"]
    for key, value in expect.get("default_bail", {}).items():
        if key == "note_contains":
            assert any(value in n for n in db["notes"]), db["notes"]
        else:
            assert db[key] == value, (key, db)
    ut = result["undertrial"]
    for key, value in expect.get("undertrial", {}).items():
        if key == "alternative_date":
            assert (ut["alternative"] or {}).get("date") == value, ut
        elif key == "alternative_more_favourable":
            assert ut["alternative"]["more_favourable"] is value, ut
        elif key == "explanation_contains":
            assert value in (ut["explanation"] or ""), ut
        elif key == "basis_contains":
            assert value in ut["basis"]
        elif key == "badge_contains":
            assert any(value in b for b in result["badges"]), result["badges"]
        else:
            assert ut[key] == value, (key, ut)


# ----------------------------------------------------------------------------- acceptance tests


def test_up_to_ten_years_is_60_days():
    assert cs.default_bail_period(death=False, life=False, min_years=None, max_years=10, procedural="CrPC")[0] == 60
    assert cs.default_bail_period(death=False, life=False, min_years=10, max_years=20, procedural="CrPC")[0] == 90
    assert cs.default_bail_period(death=False, life=True, min_years=None, max_years=None, procedural="CrPC")[0] == 90
    assert cs.default_bail_period(death=True, life=True, min_years=None, max_years=None, procedural="BNSS")[0] == 90
    days, _, notes = cs.default_bail_period(death=False, life=False, min_years=None, max_years=10, procedural="BNSS")
    assert days == 60 and "BNSS wording differs" in notes[0]
    # Through the table: s. 306 IPC (up to ten years) is 60, s. 376(1) IPC (not less than ten years) is 90.
    common = {"offence_date": "2023-03-10", "fir_date": "2023-03-10", "arrest_date": "2023-03-11", "first_remand_date": "2023-03-11"}
    assert run(file_(**common, sections=["306 IPC"]), "2023-04-01")["default_bail"]["days"] == 60
    assert run(file_(**common, sections=["376 IPC"]), "2023-04-01")["default_bail"]["days"] == 90
    assert run(file_(**common, sections=["IPC-302"]), "2023-04-01")["default_bail"]["days"] == 90


def test_procedure_by_fir_date():
    transition = criminal_codes(date(2024, 6, 20), fir_date=date(2024, 7, 5))
    assert transition.procedural == "BNSS" and transition.substantive == "IPC"
    assert transition.provision("default_bail") == "s. 187(3) BNSS"
    assert "transition_s531" in transition.flag_codes()
    assert transition.flags[0]["message"] == "Offence before 1 Jul 2024, FIR after: check s. 531 BNSS"

    old = criminal_codes(date(2024, 6, 20), fir_date=date(2024, 6, 25))
    assert old.procedural == "CrPC" and old.provision("default_bail") == "s. 167(2) CrPC" and not old.flags

    new = criminal_codes(date(2024, 8, 1), fir_date=date(2024, 8, 2))
    assert new.procedural == "BNSS" and new.substantive == "BNS" and not new.flags

    # investigation_started_on (P22's "proceeding instituted on") wins over the FIR date.
    assert criminal_codes(date(2024, 6, 1), fir_date=date(2024, 7, 2), investigation_started_on=date(2024, 6, 28)).procedural == "CrPC"
    # The same rule in the custody watch.
    result = run(file_(offence_date="2024-06-20", fir_date="2024-07-05", arrest_date="2024-07-06", sections=["IPC-420"]), "2024-07-10")
    assert result["default_bail"]["provision"] == "s. 187(3) BNSS"
    assert "Offence before 1 Jul 2024, FIR after: check s. 531 BNSS" in result["badges"]


def test_missing_fir_date_flag():
    codes = criminal_codes(date(2025, 1, 1), arrest_date=date(2025, 1, 3))
    assert codes.procedure_from == "arrest_date" and codes.procedure_date == date(2025, 1, 3)
    assert codes.flags[0]["message"] == "FIR date not entered: provision assumed from arrest date"
    pre = criminal_codes(date(2024, 5, 1), arrest_date=date(2024, 6, 3))
    assert pre.procedural == "CrPC" and "fir_date_missing" in pre.flag_codes()
    result = run(file_(offence_date="2025-01-01", arrest_date="2025-01-03", sections=["BNS-305"]), "2025-01-10")
    assert any(f["message"] == "FIR date not entered: provision assumed from arrest date" for f in result["flags"])
    assert "FIR date not entered" in result["badges"]


def _pre_july(first_time):
    return file_(offence_date="2023-01-10", fir_date="2023-01-12", arrest_date="2023-03-01", first_remand_date="2023-03-02",
                 sections=["IPC-420"], first_time_offender=first_time, other_pending_cases=False)


def test_s479_pre_july_first_time_offender():
    result = run(_pre_july(True), "2024-01-01")
    ut = result["undertrial"]
    expected = date(2023, 3, 1) + timedelta(days=math.ceil(7 * 365.25 / 3))
    assert ut["date"] == expected.isoformat() == "2025-07-01"
    assert ut["provision"] == "s. 479 BNSS" and ut["share"] == "one-third: first-time offender"
    assert "s. 479 BNSS" in ut["basis"] and "23.08.2024" in ut["basis"] and "1382 Prisons" in ut["basis"]
    # s. 436A CrPC only as an alternative citation, never the deadline.
    assert ut["alternative"]["provision"] == "s. 436A CrPC" and ut["alternative"]["more_favourable"] is False
    assert ut["alternative"]["date"] > ut["date"] and "s. 436A" not in ut["basis"]


def test_s479_pre_july_not_first_time():
    ut = run(_pre_july(False), "2024-01-01")["undertrial"]
    assert ut["share"] == "one-half"
    assert ut["date"] == (date(2023, 3, 1) + timedelta(days=math.ceil(7 * 365.25 / 2))).isoformat()
    assert ut["alternative"]["provision"] == "s. 436A CrPC" and ut["alternative"]["date"] == ut["date"]
    assert "alternative citation" in ut["alternative"]["basis"]


def test_s479_excluded_life_death():
    life = run(file_(offence_date="2025-02-01", fir_date="2025-02-01", arrest_date="2025-02-02", sections=["BNS-80(2)"]), "2025-03-01")
    assert life["undertrial"]["date"] is None and life["undertrial"]["excluded"]
    assert "punishable with imprisonment for life" in life["undertrial"]["explanation"]
    death = run(file_(offence_date="2025-02-01", fir_date="2025-02-01", arrest_date="2025-02-02", sections=["BNS-103(1)"]), "2025-03-01")
    assert death["undertrial"]["date"] is None and "punishable with death" in death["undertrial"]["explanation"]
    # CrPC era, life but not death: s. 436A may be argued.
    old = run(file_(offence_date="2023-02-01", fir_date="2023-02-01", arrest_date="2023-02-02", sections=["IPC-304B"]), "2023-03-01")
    assert "s. 436A CrPC excludes only offences punishable with death" in old["undertrial"]["explanation"]


def test_s479_pending_cases_checklist():
    base = file_(offence_date="2025-02-01", fir_date="2025-02-01", arrest_date="2025-02-02", sections=["BNS-305"], first_time_offender=True)
    unconfirmed = run(base, "2025-03-01")
    ut = unconfirmed["undertrial"]
    assert ut["date"] and not ut["excluded"]
    assert "Not eligible if other cases are pending (s. 479(2) BNSS): confirm" in unconfirmed["badges"]
    assert ut["checklist"][0]["confirmed"] is False and ut["checklist"][1]["confirmed"] is False
    confirmed = run({**base, "other_pending_cases": False, "accused_delay_days": 0}, "2025-03-01")
    assert all(item["confirmed"] for item in confirmed["undertrial"]["checklist"])
    assert not any("other cases" in b for b in confirmed["badges"])
    pending = run({**base, "other_pending_cases": True}, "2025-03-01")["undertrial"]
    assert pending["excluded"] and "s. 479(2)" in pending["explanation"] and pending["alternative"] is None  # BNSS case


def test_offence_table_complete():
    table = cs.load_table()
    sources = citation_service.Sources(set(), [])
    for rule in table.values():
        assert isinstance(rule["version"], int) and rule["version"] >= 1 and rule["title"] and rule["basis"]
        if rule["kind"] == "offence":
            assert rule["max_years"] is not None or rule["life"] or rule["death"], rule["rule_id"]
            assert rule["code"] in ("IPC", "BNS", "NDPS")
            if rule.get("counterpart"):
                assert table[rule["counterpart"]]["counterpart"] == rule["rule_id"]
        else:
            assert rule["base_days"] < rule["extended_days"]
        checks = citation_service.check(rule["basis"], sources)
        assert len(checks) == 1, rule["basis"]
        status = checks[0].status
        assert status == ("repealed" if rule["code"] == "IPC" else "statute"), (rule["rule_id"], status)
    for section in ["IPC-302", "IPC-304-I", "IPC-304B", "IPC-306", "IPC-307", "IPC-323", "IPC-324", "IPC-354", "IPC-376(1)", "IPC-379",
                    "IPC-380", "IPC-392", "IPC-406", "IPC-420", "IPC-498A", "IPC-506", "BNS-103(1)", "BNS-105-I", "BNS-80(2)", "BNS-108",
                    "BNS-109(1)", "BNS-115(2)", "BNS-118(1)", "BNS-74", "BNS-64(1)", "BNS-303(2)", "BNS-305", "BNS-309(4)",
                    "BNS-316(2)", "BNS-318(4)", "BNS-85", "BNS-351(2)", "NDPS-36A(4)"]:
        assert section in table, section


def test_sections_resolve_from_common_spellings():
    assert cs.resolve_section("302 IPC")["rule_id"] == "IPC-302"
    assert cs.resolve_section("IPC 498A")["rule_id"] == "IPC-498A"
    assert cs.resolve_section("s. 318(4) BNS")["rule_id"] == "BNS-318(4)"
    assert cs.resolve_section("Section 103 BNS")["rule_id"] == "BNS-103(1)"
    assert cs.resolve_section("bns-103(1)")["rule_id"] == "BNS-103(1)"
    assert cs.resolve_section("21(c) NDPS Act")["rule_id"] == "NDPS-21(c)"
    assert cs.resolve_section("999 IPC") is None and cs.resolve_section("16 UAPA") is None


def test_unsigned_rules_are_a_labelled_preview():
    result = run(_pre_july(True), "2024-01-01", active=set())
    assert result["preview"] and result["unverified_rules"] == ["IPC-420"]
    assert result["label"] == "UNVERIFIED punishment table entry: not for reliance"
    assert not run(_pre_july(True), "2024-01-01", active={"IPC-420"})["preview"]


def test_chargesheet_stops_clock():
    base = file_(offence_date="2025-02-25", fir_date="2025-02-26", arrest_date="2025-03-01", first_remand_date="2025-03-02",
                 sections=["BNS-303(2)"])
    in_time = run({**base, "chargesheet_filed_on": "2025-04-30"}, "2025-05-02")["default_bail"]
    assert in_time["status"] == "chargesheet_filed" and "2025" in in_time["evidence"]
    late = run({**base, "chargesheet_filed_on": "2025-05-02"}, "2025-05-03")
    assert late["default_bail"]["status"] == "right_lost" and "Right lost: chargesheet filed" in late["badges"]
    accrued = run(base, "2025-05-01")
    assert accrued["default_bail"]["status"] == "accrued" and accrued["apply_today"]


# ----------------------------------------------------------------------------- in-memory Supabase


class Query:
    def __init__(self, tables, name):
        self.tables, self.name, self.filters, self.op, self.payload, self._limit = tables, name, [], "select", None, None

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) == str(val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        rows = self.tables.setdefault(self.name, [])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            return SimpleNamespace(data=[dict(r) for r in hits[: self._limit]])
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), "org_id": ORG_ID, "user_id": OWNER, "docket": {}, "history": [], **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.op == "delete":
            for r in hits:
                rows.remove(r)
            return SimpleNamespace(data=[dict(r) for r in hits])
        for r in hits:
            r.update(json.loads(json.dumps(self.payload)))
        return SimpleNamespace(data=[dict(r) for r in hits])


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return Query(self.tables, name)


def signatures(*rule_ids):
    return [{"org_id": ORG_ID, "registry": "offence_punishments", "rule_id": r, "version": 1, "verified_by": who}
            for r in rule_ids for who in ("u-a", "u-b")]


@pytest.fixture
def deadlines(monkeypatch):
    """A stand-in for P13's deadline_service (create_deadline / complete / register_engine)."""
    state = SimpleNamespace(created=[], completed=[], engines={})

    class DeadlineError(Exception):
        def __init__(self, message, status=400, code="invalid"):
            super().__init__(message)
            self.message, self.status, self.code = message, status, code

    def create_deadline(db, *, kind, title, due_date, owner_id, court_case_id=None, thread_id=None, rule_id=None,
                        rule_version=None, basis="", inputs=None, hard=False, source="engine", candidates=None, safety_lead_days=3):
        assert not getattr(db, "service_role", False), "P13 deadlines are created as the user"
        row = {"id": f"d{len(state.created) + 1}", "kind": kind, "title": title, "due_date": due_date, "owner_id": owner_id,
               "rule_id": rule_id, "rule_version": rule_version, "basis": basis, "inputs": inputs, "hard": hard,
               "source": source, "safety_lead_days": safety_lead_days}
        state.created.append(row)
        return row

    def complete(db, deadline_id, evidence):
        state.completed.append((deadline_id, evidence))
        return {"id": deadline_id, "status": "done"}

    module = types.ModuleType("app.services.deadline_service")
    module.create_deadline, module.complete, module.DeadlineError = create_deadline, complete, DeadlineError
    module.register_engine = lambda rule_id, fn: state.engines.__setitem__(rule_id, fn)
    import app.services

    monkeypatch.setitem(sys.modules, "app.services.deadline_service", module)
    monkeypatch.setattr(app.services, "deadline_service", module, raising=False)
    return state


def _watched(**kw):
    return file_(id="f1", org_id=ORG_ID, user_id=OWNER, counsel_id="counsel-1", offence_date="2025-02-25", fir_date="2025-02-26",
                 arrest_date="2025-03-01", first_remand_date="2025-03-02", sections=["BNS-303(2)"], first_time_offender=True,
                 docket={}, history=[], **kw)


def test_docket_as_the_user_hard_default_bail_and_chargesheet_closes_it(deadlines):
    file = _watched()
    result = run(file, "2025-04-26")
    docket, events, problems = cs.sync_docket(FakeDB(), file, result)
    assert problems == [] and [e["kind"] for e in events] == ["default_bail", "undertrial_release"]
    bail = deadlines.created[0]
    assert bail["kind"] == "default_bail" and bail["hard"] is True and bail["safety_lead_days"] == 5
    assert bail["due_date"] == date(2025, 5, 1) and bail["owner_id"] == "counsel-1" and bail["source"] == "engine"
    assert "right is lost once a chargesheet is filed" in bail["basis"]
    assert bail["rule_id"] == cs.DEFAULT_BAIL_RULE and bail["inputs"]["punishment_rule"] == "BNS-303(2)"
    s479 = deadlines.created[1]
    assert s479["hard"] is False and s479["due_date"] == date(2026, 3, 2) and "s. 479 BNSS" in s479["basis"]

    # The blind second check recomputes both dates from re-entered inputs (P13 engines).
    assert cs.register_engines()
    norm = lambda d: {k: str(v) for k, v in d.items() if v is not None}  # noqa: E731
    assert deadlines.engines[cs.DEFAULT_BAIL_RULE](norm(bail["inputs"])) == date(2025, 5, 1)
    assert deadlines.engines[cs.S479_RULE](norm(s479["inputs"])) == date(2026, 3, 2)

    # Nothing twice; a chargesheet within the period closes the default-bail deadline with that evidence.
    file["docket"] = docket
    assert cs.sync_docket(FakeDB(), file, run(file, "2025-04-27"))[1] == []
    file["chargesheet_filed_on"] = "2025-04-28"
    docket, events, _ = cs.sync_docket(FakeDB(), file, run(file, "2025-04-29"))
    assert deadlines.completed == [("d1", "Chargesheet filed on 28 Apr 2025, within the 60 days")]
    assert docket["default_bail"]["done"] and events[0]["event"] == "docket_closed"

    # A moved date (interrupted custody entered) gets a new deadline; the old one is closed as superseded.
    file["custody_periods"] = [{"start": "2025-01-01", "end": "2025-01-10"}]
    file["docket"] = docket
    docket, events, _ = cs.sync_docket(FakeDB(), file, run(file, "2025-04-29"))
    assert docket["undertrial_release"]["due_date"] == "2026-02-20" and events[-1]["supersedes"] == "d2"
    assert deadlines.completed[-1][0] == "d2" and deadlines.completed[-1][1].startswith("Superseded")


def test_sweep_records_accrual_and_right_lost_without_docketing(deadlines):
    file = _watched()
    other_org = {**file, "id": "f2", "org_id": "another-org"}
    db = FakeDB(custody_files=[file, other_org], custody_extension_orders=[], rule_verifications=signatures("BNS-303(2)"))
    db.service_role = True

    stats = cs.recompute_all(db, ORG_ID, date(2025, 4, 26))
    assert stats["files"] == 1 and stats["computed"] == 1 and deadlines.created == []
    assert stats["undocketed"] == 1 and stats["undocketed_files"][0]["kinds"] == ["default_bail", "undertrial_release"]
    assert db.tables["custody_files"][1].get("computed") is None  # another org's file is untouched

    # On the accrual day: the 'accrued' event and an 'apply today' row.
    stats = cs.recompute_all(db, ORG_ID, date(2025, 5, 1))
    saved = db.tables["custody_files"][0]
    assert stats["accrued"] == 1 and stats["apply_today"] == 1
    assert saved["history"][-1]["event"] == "accrued" and saved["computed"]["apply_today"]
    assert cs.recompute_all(db, ORG_ID, date(2025, 5, 2))["accrued"] == 0  # recorded once

    # A chargesheet after accrual with no application: the history shows the right was lost.
    saved["chargesheet_filed_on"] = "2025-05-03"
    stats = cs.recompute_all(db, ORG_ID, date(2025, 5, 4))
    assert stats["right_lost"] == 1
    assert saved["history"][-1]["event"] == "right_lost" and saved["history"][-1]["message"] == "Right lost: chargesheet filed"


def test_unsigned_rules_are_never_docketed(deadlines):
    file = _watched()
    db = FakeDB(custody_files=[file], custody_extension_orders=[], rule_verifications=signatures("BNS-303(2)")[:1])
    stats = cs.recompute_all(db, ORG_ID, date(2025, 4, 1))
    assert stats["unverified"] == 1 and stats["undocketed"] == 0
    assert db.tables["custody_files"][0]["computed"]["label"] == cs.UNVERIFIED_LABEL
    assert cs.sync_docket(FakeDB(), file, run(file, "2025-04-01", active=set())) == ({}, [], [])
    assert deadlines.created == []


# ----------------------------------------------------------------------------- API


@pytest.fixture
def api(monkeypatch, org_role, audit_log):
    test_app = FastAPI()
    test_app.include_router(custody_router.router, prefix="/api/v1")
    test_app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=OWNER, email="a@b.in", access_token="t")
    db = FakeDB(custody_files=[], custody_extension_orders=[], rule_verifications=[])
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    return SimpleNamespace(client=TestClient(test_app), db=db, role=org_role, audit=audit_log)


def test_custody_api(api, deadlines):
    created = api.client.post("/api/v1/custody", json={
        "accused_name": "Ravi Kumar", "offence_date": "2023-01-10", "fir_date": "2023-01-12", "arrest_date": "2023-03-01",
        "first_remand_date": "2023-03-02", "sections": ["420 IPC", "506 IPC"], "first_time_offender": True,
    })
    assert created.status_code == 201, created.text
    file_id = created.json()["id"]
    assert created.json()["sections"] == ["IPC-420", "IPC-506"]  # stored as table entries
    assert api.audit[-1]["action"] == "ADD_CUSTODY_FILE"
    assert api.client.post("/api/v1/custody", json={"accused_name": "X"}).status_code == 422

    offences = api.client.get("/api/v1/custody/offences").json()
    assert any(o["rule_id"] == "BNS-103(1)" and o["active"] is False for o in offences)

    # Unsigned table: owners and partners get a labelled preview; others get 422.
    assert api.client.post(f"/api/v1/custody/{file_id}/compute").status_code == 422
    preview = api.client.post(f"/api/v1/custody/{file_id}/compute?preview=true").json()
    assert preview["label"] == "UNVERIFIED punishment table entry: not for reliance"
    api.role("associate")
    blocked = api.client.post(f"/api/v1/custody/{file_id}/compute?preview=true")
    assert blocked.status_code == 422 and blocked.json()["detail"]["code"] == "rules_unverified"
    listed = api.client.get("/api/v1/custody?preview=true").json()
    assert listed[0]["result"] is None and listed[0]["blocked"]["code"] == "rules_unverified"
    api.role("owner")
    assert api.client.post(f"/api/v1/custody/{file_id}/docket").status_code == 422

    # Signed by two members: the real computation, and the dates go to the docket once.
    api.db.tables["rule_verifications"] = signatures("IPC-420", "IPC-506")
    worked = api.client.post(f"/api/v1/custody/{file_id}/compute").json()
    assert not worked["preview"] and worked["undertrial"]["date"] == "2025-07-01"
    assert worked["default_bail"]["provision"] == "s. 167(2) CrPC"
    listed = api.client.get("/api/v1/custody").json()
    assert listed[0]["result"]["undertrial"]["share"] == "one-third: first-time offender"

    docketed = api.client.post(f"/api/v1/custody/{file_id}/docket")
    assert docketed.status_code == 200, docketed.text
    assert [e["kind"] for e in docketed.json()["created"]] == ["default_bail", "undertrial_release"]
    assert api.audit[-1]["action"] == "DOCKET_CUSTODY_DATES"
    assert api.client.post(f"/api/v1/custody/{file_id}/docket").json()["created"] == []

    # Saving the chargesheet date closes the default-bail deadline, as the user.
    patched = api.client.patch(f"/api/v1/custody/{file_id}", json={"chargesheet_filed_on": "2023-04-20"})
    assert patched.status_code == 200
    assert patched.json()["docket_sync"]["events"][0]["event"] == "docket_closed"
    assert deadlines.completed == [("d1", "Chargesheet filed on 20 Apr 2023, within the 60 days")]
    assert api.client.patch(f"/api/v1/custody/{file_id}", json={"arrest_date": None}).status_code == 422

    # Extension orders only for NDPS commercial / UAPA files, within the statute's limit.
    assert api.client.post(f"/api/v1/custody/{file_id}/extension-orders",
                           json={"order_date": "2023-04-01", "extended_to_days": 180}).status_code == 422
    ndps = api.client.post("/api/v1/custody", json={"accused_name": "N", "offence_date": "2025-01-01", "fir_date": "2025-01-01",
                                                    "arrest_date": "2025-01-02", "sections": ["NDPS-21(c)"]}).json()
    assert api.client.post(f"/api/v1/custody/{ndps['id']}/extension-orders",
                           json={"order_date": "2025-06-20", "extended_to_days": 400}).status_code == 422
    order = api.client.post(f"/api/v1/custody/{ndps['id']}/extension-orders", json={"order_date": "2025-06-20", "extended_to_days": 365})
    assert order.status_code == 201
    assert len(api.client.get(f"/api/v1/custody/{ndps['id']}").json()["extension_orders"]) == 1
    assert api.client.get(f"/api/v1/custody/{uuid.uuid4()}").status_code == 404
