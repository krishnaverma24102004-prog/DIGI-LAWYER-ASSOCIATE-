"""Limitation engine (P06): golden worked examples, properties of the arithmetic, the rule registry,
and the API (rule sign-off gate, calendars, docket hand-off, Copy tracker)."""

import json
import random
import re
import sys
import types
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.routers import limitation as limitation_router
from app.services import citation_service
from app.services import limitation_service as ls
from app.services.limitation_service import Calendar, Closure, Inputs
from tests.conftest import ORG_ID

FIXTURE = Path(__file__).parent / "fixtures" / "limitation_cases.json"
GOLDEN = json.loads(FIXTURE.read_text(encoding="utf-8"))
TODAY = date.fromisoformat(GOLDEN["today"])
USER = "11111111-1111-1111-1111-111111111111"
OTHER = "33333333-3333-3333-3333-333333333333"


def fixture_calendar(code: str) -> Calendar:
    spec = GOLDEN["calendars"][code]
    closures = {}
    for c in spec["closures"]:
        day = date.fromisoformat(c["day"])
        closures[day] = Closure(day, c["reason"], "https://example.org/test-calendar", c.get("firm", False), c.get("verified", True))
    return Calendar(code, closures, set(spec["loaded_years"]))


def run_case(case: dict) -> dict:
    rule = ls.get_rule(case["rule_id"])
    code = case.get("court_code")
    calendar = fixture_calendar(code) if code else None
    if calendar is not None and not calendar.loaded_years:
        calendar = None
    return ls.compute(rule, Inputs.from_dict(case["inputs"]), calendar=calendar, today=TODAY, court_code=code)


def excluded_days(result: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in result["lines"]:
        if line["kind"] == "exclusion" and "section" in line:
            out[line["section"]] = out.get(line["section"], 0) + line.get("days", 0)
    return out


# ============================================================================ golden table


def test_golden_file_is_honest_and_big_enough():
    assert "must be checked and signed by two advocates before the rules go live" in GOLDEN["_header"]
    assert GOLDEN["signoff"] == {"status": "unsigned", "advocates": []}
    assert len(GOLDEN["cases"]) >= 30
    assert len({c["id"] for c in GOLDEN["cases"]}) == len(GOLDEN["cases"])
    covered = {c["rule_id"] for c in GOLDEN["cases"]}
    assert covered == set(ls.rules()), "every rule has at least one worked example"


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=[c["id"] for c in GOLDEN["cases"]])
def test_golden_case(case):
    result = run_case(case)
    expect = case["expect"]
    if "base_date" in expect:
        assert result["base_date"] == expect["base_date"]
    if "prescribed_end" in expect:
        assert result["prescribed_end"] == expect["prescribed_end"]
    if "safe_date" in expect:
        assert result["safe_date"] == expect["safe_date"]
        assert result["docket_date"] == expect["safe_date"]
    if "s4_shifted_to" in expect:
        shifted = result["s4"]["shifted_to"] if result["s4"] else None
        assert shifted == expect["s4_shifted_to"]
    if "s4_informational" in expect:
        assert result["s4"]["informational"] is expect["s4_informational"]
    if "outer_limit" in expect:
        assert result["outer_limit"]["date"] == expect["outer_limit"]
    if "outer_hard" in expect:
        assert result["outer_limit"]["hard"] is expect["outer_hard"]
    if "provisional" in expect:
        assert result["provisional"] is expect["provisional"]
    if "alternatives" in expect:
        assert [a["date"] for a in result["alternatives"]] == expect["alternatives"]
    if "excluded" in expect:
        got = excluded_days(result)
        for section, days in expect["excluded"].items():
            assert got.get(section) == days, (section, got)
    if "filing_status" in expect:
        assert result["filing"]["status"] == expect["filing_status"]
    for text in expect.get("warnings_contain", []):
        assert any(text in w for w in result["warnings"]), (text, result["warnings"])
    if expect.get("no_covid_line"):
        assert not [line for line in result["lines"] if line["kind"] == "covid"]
    # Every result: the label, and nothing docketed later than the safe date.
    assert result["label"] == ls.DISCLAIMER
    assert all(a["date"] >= result["safe_date"] for a in result["alternatives"])


def test_worked_computation_shows_each_line():
    case = next(c for c in GOLDEN["cases"] if c["id"] == "s4_after_copy_exclusion")
    result = run_case(case)
    kinds = [line["kind"] for line in result["lines"]]
    assert kinds[:3] == ["start", "period", "exclusion"]
    assert "s4" in kinds and kinds[-1] == "final"
    s4 = next(line for line in result["lines"] if line["kind"] == "s4")
    assert s4["section"] == "s. 4 Limitation Act" and s4["days"] == 3 and "Diwali" in s4["label"]
    period = next(line for line in result["lines"] if line["kind"] == "period")
    assert period["days"] == 90 and "Article 116" in period["section"]


def test_covid_line_names_the_supreme_court_order():
    case = next(c for c in GOLDEN["cases"] if c["id"] == "covid_expired_inside_window_90_days")
    covid = next(line for line in run_case(case)["lines"] if line["kind"] == "covid")
    assert "10.01.2022" in covid["label"] and "Suo Motu W.P. (C) No. 3 of 2020" in covid["label"]


def test_s34_grace_window_is_a_red_line_without_s4():
    case = next(c for c in GOLDEN["cases"] if c["id"] == "s34_s4_on_three_months_not_on_grace")
    result = run_case(case)
    outer = next(line for line in result["lines"] if line["kind"] == "outer")
    assert outer["hard"] is True and outer["date"] == "2025-11-01"
    assert any(line["kind"] == "s4" and line.get("informational") and "not applied to this limit" in line["label"]
               for line in result["lines"])


def test_no_s5_rule_has_a_red_line():
    result = ls.compute(ls.get_rule("execution_decree"), Inputs.from_dict({"start_date": "2024-02-29"}), today=TODAY)
    assert any(line["kind"] == "outer" and line.get("hard") and "s. 5" in line["section"] for line in result["lines"])


@pytest.mark.parametrize("inputs, message", [
    ({"start_date": "2025-03-03", "copy_applied_on": "2025-03-01"}, "before the start date"),
    ({"start_date": "2025-03-03", "copy_applied_on": "2025-03-05", "copy_ready_on": "2025-03-04"}, "ready before"),
    ({"start_date": "2025-03-03", "copy_ready_on": "2025-03-04"}, "applied for"),
    ({"start_date": "2025-03-03", "s14_periods": [{"from": "2025-03-10", "to": "2025-03-09"}]}, "s. 14"),
    ({"start_date": "not a date"}, "not a date"),
])
def test_bad_inputs_are_refused(inputs, message):
    with pytest.raises(ls.LimitationError, match=message):
        ls.compute(ls.get_rule("appeal_hc_decree"), Inputs.from_dict(inputs), today=TODAY)


# ============================================================================ properties (randomized)

RNG_SEED = 20261027
DAYS_RULES = ["appeal_hc_decree", "appeal_other_court_decree", "review", "revision_civil", "slp_civil", "arbitration_s34", "execution_decree"]


def _random_day(rng, lo=date(2018, 1, 1), hi=date(2027, 12, 31)) -> date:
    return lo + timedelta(days=rng.randrange((hi - lo).days))


def _random_case(rng):
    rule = ls.get_rule(rng.choice(DAYS_RULES[:-1]))  # the 12-year rule is slow to walk: covered by the golden table
    start = _random_day(rng)
    n = ls.period_days(start, rule.period)
    applied = start + timedelta(days=rng.randrange(0, n + 1))  # within the period, so s. 12(2) applies
    return rule, start, applied


def test_property_exclusions_never_move_the_date_earlier():
    rng = random.Random(RNG_SEED)
    for _ in range(300):
        rule, start, applied = _random_case(rng)
        ready = applied + timedelta(days=rng.randrange(0, 60))
        result = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=ready), today=TODAY)
        assert result["prescribed_end"] >= result["base_date"]
        assert result["safe_date"] >= result["prescribed_end"]


def test_property_copy_days_move_the_pre_s4_date_by_at_most_those_days():
    """Stated on the pre-s.4 date (s. 4 can add a closure run) and outside the COVID order's reach:
    one more excluded day can carry an expiry from before 15.03.2020 into the window, which the
    order then moves to 2022. Across COVID the move is only checked to be never negative."""
    rng = random.Random(RNG_SEED + 1)
    for i in range(400):
        rule, start, applied = _random_case(rng)
        if i % 2 == 0:  # half the runs after the window, where the bound must hold exactly
            start = _random_day(rng, lo=date(2022, 3, 1))
            applied = start + timedelta(days=rng.randrange(0, ls.period_days(start, rule.period) + 1))
        ready = applied + timedelta(days=rng.randrange(0, 40))
        extra = rng.randrange(1, 30)
        a = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=ready), today=TODAY)
        b = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=ready + timedelta(days=extra)), today=TODAY)
        moved = (date.fromisoformat(b["prescribed_end"]) - date.fromisoformat(a["prescribed_end"])).days
        assert moved >= 0, (rule.rule_id, start, applied, ready, extra, moved)
        covid_free = all(not any(line["kind"] == "covid" for line in r["lines"]) for r in (a, b))
        if covid_free:
            assert moved <= extra, (rule.rule_id, start, applied, ready, extra, moved)


def test_property_with_s4_the_move_is_at_most_those_days_plus_the_closure_run():
    rng = random.Random(RNG_SEED + 2)
    for _ in range(200):
        rule, start, applied = _random_case(rng)
        ready = applied + timedelta(days=rng.randrange(0, 40))
        result = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=ready), today=TODAY)
        pre = date.fromisoformat(result["prescribed_end"])
        # Close a random run of days starting on the last day: s. 4 moves the date by exactly that run.
        run = rng.randrange(1, 6)
        closures = {pre + timedelta(days=i): Closure(pre + timedelta(days=i), "Test closure") for i in range(run)}
        calendar = Calendar("RND", closures, {pre.year, pre.year + 1})
        shifted = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=ready), calendar=calendar,
                             today=TODAY, court_code="RND")
        assert shifted["prescribed_end"] == result["prescribed_end"]
        assert (date.fromisoformat(shifted["safe_date"]) - pre).days == run
        if not any(line["kind"] == "covid" for line in result["lines"]):
            base = date.fromisoformat(result["base_date"])
            assert (date.fromisoformat(shifted["safe_date"]) - base).days <= (ready - applied).days + run


def test_property_missing_copy_ready_gives_the_safe_earlier_date():
    rng = random.Random(RNG_SEED + 3)
    for _ in range(300):
        rule, start, applied = _random_case(rng)
        missing = ls.compute(rule, Inputs(start, copy_applied_on=applied), today=TODAY)
        none_excluded = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=applied), today=TODAY)
        any_ready = ls.compute(rule, Inputs(start, copy_applied_on=applied, copy_ready_on=applied + timedelta(days=rng.randrange(0, 90))),
                               today=TODAY)
        # Without COVID, the safe date is simply the date with no copy time; with the COVID order's
        # 90-day floor it can be earlier still (a later ready date can escape the floor).
        assert missing["safe_date"] <= none_excluded["safe_date"]
        assert missing["safe_date"] <= any_ready["safe_date"]
        if not any(line["kind"] == "covid" for line in none_excluded["lines"]):
            assert missing["safe_date"] == none_excluded["safe_date"]
        assert missing["docket_date"] == missing["safe_date"]
        if "s12_2" in rule.exclusions:
            assert missing["provisional"] is True
            assert all(alt["date"] >= missing["safe_date"] for alt in missing["alternatives"])


def test_property_uncertain_s4_never_moves_the_safe_date():
    rng = random.Random(RNG_SEED + 4)
    for _ in range(150):
        rule = ls.get_rule(rng.choice(["written_statement_commercial", "written_statement_ordinary"]))
        start = _random_day(rng)
        plain = ls.compute(rule, Inputs(start), today=TODAY)
        pre = date.fromisoformat(plain["prescribed_end"])
        outer = date.fromisoformat(plain["outer_limit"]["date"])
        closures = {d: Closure(d, "Test closure") for d in (pre, pre + timedelta(days=1), outer)}
        result = ls.compute(rule, Inputs(start), calendar=Calendar("RND", closures, {pre.year, outer.year}), today=TODAY, court_code="RND")
        assert result["safe_date"] == plain["safe_date"]
        assert result["outer_limit"]["date"] == plain["outer_limit"]["date"]
        assert result["s4"]["informational"] is True


# ============================================================================ the registry


def test_registry_shape_and_drafts():
    raw = json.loads(ls.RULES_PATH.read_text(encoding="utf-8"))
    assert raw["registry"] == "limitation"
    required = {"rule_id", "version", "title", "basis", "remedy", "forum", "period", "start_event", "exclusions",
                "condonable", "outer_limit", "s4_applies", "general_clauses_s10"}
    for rule in raw["rules"]:
        assert required <= set(rule), rule["rule_id"]
        assert "verified_by" not in rule and rule.get("status", "draft") == "draft", "activation is per firm (rule_verifications)"
        assert isinstance(rule["version"], int) and rule["version"] >= 1
    assert ls.load_rules() == ls.rules()


def test_registry_encodes_the_statutory_periods():
    r = ls.rules()
    assert r["appeal_hc_decree"].period == {"days": 90}
    assert r["appeal_other_court_decree"].period == {"days": 30}
    assert r["appeal_intra_court"].period == {"days": 30}
    assert r["review"].period == {"days": 30}
    assert r["revision_civil"].period == {"days": 90}
    assert r["slp_civil"].period == {"days": 90}
    assert r["slp_civil_certificate_refused"].period == {"days": 60}
    assert r["arbitration_s34"].period == {"months": 3}
    assert r["arbitration_s34"].outer_limit["after_period_days"] == 30 and r["arbitration_s34"].outer_limit["hard"] is True
    assert r["arbitration_s34"].outer_limit["s4_applies"] is False
    assert r["written_statement_commercial"].outer_limit["days"] == 120 and r["written_statement_commercial"].outer_limit["hard"] is True
    assert r["written_statement_ordinary"].outer_limit["days"] == 90 and r["written_statement_ordinary"].outer_limit["hard"] is False
    assert r["execution_decree"].period == {"months": 144} and r["execution_decree"].condonable is False
    # s. 4 only where the Limitation Act governs the period; elsewhere it is s. 10 GCA, and uncertain.
    for rule in r.values():
        assert rule.s4_applies != rule.general_clauses_s10, rule.rule_id


def test_bad_rules_are_rejected(tmp_path):
    bad = {"registry": "limitation", "rules": [{**ls.rules()["review"].describe(), "period": {"weeks": 2}}]}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="period"):
        ls.load_rules(path)


SCHEDULE_ARTICLE = re.compile(r"Article (\d{1,3}) of the Schedule to the Limitation Act, 1963")


def _basis_texts():
    for rule in ls.rules().values():
        yield rule.rule_id, rule.basis
        if rule.outer_limit and rule.outer_limit.get("basis"):
            yield f"{rule.rule_id} (outer limit)", rule.outer_limit["basis"]


def test_basis_citations():
    """Every statutory reference in every basis passes citation_service with status `statute`."""
    sources = citation_service.Sources(set(), [])
    for name, text in _basis_texts():
        checks = citation_service.check(text, sources)
        if name.endswith("(outer limit)") and not checks:
            continue  # an Order/Rule reference only ("Order VIII Rule 1 CPC"): nothing the checker extracts
        assert checks, f"{name}: the basis cites no section the checker can verify"
        for c in checks:
            assert c.status == "statute", (name, c.text, c.status, c.note)


def test_schedule_articles_are_checked():
    """Schedule articles are recognised as such (not as Constitution articles) and checked against 1-137."""
    sources = citation_service.Sources(set(), [])
    for name, text in _basis_texts():
        for number in SCHEDULE_ARTICLE.findall(text):
            [check] = [c for c in citation_service.check(f"Article {number} of the Schedule to the Limitation Act, 1963", sources)]
            assert check.status == "statute", (name, number, check.note)
    [fake] = citation_service.check("Article 140 of the Schedule to the Limitation Act, 1963", sources)
    assert fake.status == "invalid"


# ============================================================================ copy tracker (pure)


def test_copy_check_every_three_working_days():
    # Applied Monday 05.10.2026: checks on Thu 08.10, Tue 13.10, Fri 16.10 (weekends skipped)...
    row = {"applied_on": "2026-10-05", "status": "pending"}
    assert ls.copy_status(row, date(2026, 10, 6))["next_check_on"] == "2026-10-08"
    assert ls.copy_status(row, date(2026, 10, 9))["next_check_on"] == "2026-10-13"
    due = ls.copy_status(row, date(2026, 10, 13))
    assert due["check_due"] is True and due["days_since_applied"] == 8
    # A closure is not a working day.
    closed = {date(2026, 10, 7)}
    assert ls.copy_status(row, date(2026, 10, 6), closed)["next_check_on"] == "2026-10-09"
    ready = ls.copy_status({**row, "ready_on": "2026-10-12", "status": "ready"}, date(2026, 10, 13))
    assert ready["pending"] is False and ready["next_check_on"] is None


def test_copy_status_derived_from_dates():
    assert ls.derive_status({"applied_on": "2026-10-05"}) == "pending"
    assert ls.derive_status({"applied_on": "2026-10-05", "ready_on": "2026-10-09"}) == "ready"
    assert ls.derive_status({"applied_on": "2026-10-05", "ready_on": "2026-10-09", "delivered_on": "2026-10-10"}) == "delivered"
    assert ls.derive_status({"applied_on": "2026-10-05", "status": "withdrawn"}) == "withdrawn"


# ============================================================================ API

# An in-memory stand-in for the user's RLS-scoped Supabase client.


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload = db, table, [], "select", None
        self._order, self._limit = None, None

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) == str(val))
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) >= val)
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) <= val)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
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
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), "org_id": ORG_ID, "user_id": self.db.user_id, **self.payload}
            rows.append(row)
            return _Result([dict(row)])
        matched = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in matched:
                r.update(self.payload)
            return _Result([dict(r) for r in matched])
        if self.op == "delete":
            for r in matched:
                rows.remove(r)
            return _Result([dict(r) for r in matched])
        if self._order:
            matched.sort(key=lambda r: str(r.get(self._order[0])), reverse=self._order[1])
        return _Result([dict(r) for r in matched[: self._limit]])


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.active_rules: set[tuple[str, int]] = set()
        self.user_id = USER

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        assert name == "rule_active" and params["p_registry"] == "limitation"
        return types.SimpleNamespace(execute=lambda: _Result((params["p_rule_id"], params["p_version"]) in self.active_rules))


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    return db


@pytest.fixture
def client(fake_db):
    app = FastAPI()
    app.include_router(limitation_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=USER, email="a@b.in", access_token="t")
    return TestClient(app)


def _activate(db, rule_id):
    rule = ls.get_rule(rule_id)
    db.active_rules.add((rule.rule_id, rule.version))
    db.tables.setdefault("rule_verifications", []).extend([
        {"rule_id": rule.rule_id, "version": rule.version, "registry": "limitation", "verified_by": USER, "verified_at": "2026-10-01T10:00:00Z"},
        {"rule_id": rule.rule_id, "version": rule.version, "registry": "limitation", "verified_by": OTHER, "verified_at": "2026-10-02T10:00:00Z"},
    ])


def test_unverified_rule_hidden(client, fake_db, org_role):
    body = {"rule_id": "appeal_hc_decree", "start_date": "2025-03-03"}
    org_role("associate")
    response = client.post("/api/v1/limitation/compute", json=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "rule_unverified"
    # Associates can't preview either.
    assert client.post("/api/v1/limitation/compute", json={**body, "preview": True}).status_code == 422
    org_role("owner")
    assert client.post("/api/v1/limitation/compute", json=body).status_code == 422
    preview = client.post("/api/v1/limitation/compute", json={**body, "preview": True})
    assert preview.status_code == 200
    assert preview.json()["unverified"] is True and preview.json()["label"].startswith("UNVERIFIED RULE: not for reliance")
    # A preview can never reach the docket.
    assert client.post("/api/v1/limitation/compute", json={**body, "preview": True, "save_to_docket": True}).status_code == 422
    # Once two members signed the version, everyone can use it.
    _activate(fake_db, "appeal_hc_decree")
    org_role("paralegal")
    ok = client.post("/api/v1/limitation/compute", json=body)
    assert ok.status_code == 200 and ok.json()["safe_date"] == "2025-06-01" and "unverified" not in ok.json()


def test_unknown_rule_404(client):
    assert client.post("/api/v1/limitation/compute", json={"rule_id": "nope", "start_date": "2025-03-03"}).status_code == 404


def test_rules_list_shows_this_firms_signoff(client, fake_db):
    fake_db.tables["rule_verifications"] = [
        {"rule_id": "review", "version": 1, "registry": "limitation", "verified_by": OTHER, "verified_at": "2026-10-02T10:00:00Z"}]
    _activate(fake_db, "slp_civil")
    rules = {r["rule_id"]: r for r in client.get("/api/v1/limitation/rules").json()["rules"]}
    assert rules["slp_civil"]["active"] is True and rules["slp_civil"]["signed_by_me"] is True
    assert rules["review"]["active"] is False and rules["review"]["signatures_needed"] == 1
    assert rules["execution_decree"]["status"] == "draft" and rules["execution_decree"]["signatures"] == []


def test_calendar_missing_warns(client, fake_db):
    _activate(fake_db, "appeal_other_court_decree")
    body = {"rule_id": "appeal_other_court_decree", "start_date": "2025-09-02", "court_code": "nocal"}
    result = client.post("/api/v1/limitation/compute", json=body).json()
    assert result["safe_date"] == "2025-10-02" and result["s4"] is None
    assert any("No calendar is loaded for NOCAL" in w for w in result["warnings"])
    # With the court's closure loaded (and a firm's own entry for the same day), s. 4 applies.
    fake_db.tables["court_calendars"] = [
        {"court_code": "NOCAL", "day": "2025-10-02", "closed": True, "reason": "Gandhi Jayanti", "source_url": "https://x", "org_id": None},
        {"court_code": "NOCAL", "day": "2025-10-02", "closed": True, "reason": "dup", "source_url": "https://y", "org_id": ORG_ID},
    ]
    result = client.post("/api/v1/limitation/compute", json=body).json()
    assert result["safe_date"] == "2025-10-03" and result["s4"]["closures"][0]["reason"] == "Gandhi Jayanti"


def test_compute_is_audited_without_dates(client, fake_db, audit_log):
    _activate(fake_db, "review")
    client.post("/api/v1/limitation/compute", json={"rule_id": "review", "start_date": "2025-08-14"})
    entry = audit_log[-1]
    assert entry["action"] == "COMPUTE_LIMITATION" and entry["resource_id"] == "review"
    assert "2025" not in json.dumps(entry["metadata"])


def test_save_to_docket_uses_the_safe_date(client, fake_db, monkeypatch):
    calls = []

    class DeadlineError(Exception):
        pass

    def create_deadline(db, **kwargs):
        calls.append(kwargs)
        if kwargs["title"] == "fail":
            raise DeadlineError("owner is not a member")
        return {"id": f"d{len(calls)}", **{k: str(v) for k, v in kwargs.items()}}

    fake = types.ModuleType("app.services.deadline_service")
    fake.create_deadline, fake.DeadlineError = create_deadline, DeadlineError
    monkeypatch.setitem(sys.modules, "app.services.deadline_service", fake)
    import app.services as services_pkg

    monkeypatch.setattr(services_pkg, "deadline_service", fake, raising=False)
    _activate(fake_db, "arbitration_s34")
    case_id = str(uuid.uuid4())
    body = {"rule_id": "arbitration_s34", "start_date": "2025-06-10", "save_to_docket": True, "court_case_id": case_id,
            "title": "Award v. Sharma: s. 34"}
    result = client.post("/api/v1/limitation/compute", json=body).json()
    assert [d["id"] for d in result["deadlines"]] == ["d1", "d2"]
    first, outer = calls
    assert first["due_date"] == date(2025, 9, 10) and first["kind"] == "limitation" and first["source"] == "engine"
    assert first["rule_id"] == "arbitration_s34" and first["rule_version"] == 1 and first["owner_id"] == USER
    assert first["court_case_id"] == case_id and first["inputs"]["start_date"] == "2025-06-10" and first["basis"].startswith("Section 34(3)")
    assert first["candidates"] == ["2025-09-10"]
    assert outer["due_date"] == date(2025, 10, 10) and outer["hard"] is True
    # A missing copy-ready date: the docket gets the safe date; the later alternative is only a candidate.
    calls.clear()
    _activate(fake_db, "appeal_hc_decree")
    client.post("/api/v1/limitation/compute", json={"rule_id": "appeal_hc_decree", "start_date": "2026-09-01",
                                                    "copy_applied_on": "2026-09-05", "save_to_docket": True})
    assert calls[0]["due_date"] == date(2026, 11, 30) and calls[0]["candidates"][0] == "2026-11-30" and len(calls) == 1
    # The docket's own refusals come back as 422.
    response = client.post("/api/v1/limitation/compute", json={**body, "title": "fail"})
    assert response.status_code == 422 and "owner" in response.json()["detail"]


def test_copy_tracker_crud(client, fake_db, org_role):
    case_id = str(uuid.uuid4())
    # A copy must be linked to a case or a thread, and dates must be in order.
    assert client.post("/api/v1/limitation/copy-applications", json={"applied_on": "2026-10-05"}).status_code == 422
    bad = {"court_case_id": case_id, "applied_on": "2026-10-05", "ready_on": "2026-10-01"}
    assert client.post("/api/v1/limitation/copy-applications", json=bad).status_code == 422
    created = client.post("/api/v1/limitation/copy-applications",
                          json={"court_case_id": case_id, "applied_on": "2026-10-05", "order_date": "2026-10-01", "court_code": "testhc"})
    assert created.status_code == 201
    row = created.json()
    assert row["status"] == "pending" and row["court_code"] == "TESTHC" and row["pending"] is True
    listed = client.get("/api/v1/limitation/copy-applications").json()
    assert listed[0]["id"] == row["id"] and listed[0]["next_check_on"] is not None
    # Marking it ready derives the status; the dates feed the calculator.
    updated = client.patch(f"/api/v1/limitation/copy-applications/{row['id']}", json={"ready_on": "2026-10-12"}).json()
    assert updated["status"] == "ready" and updated["pending"] is False
    _activate(fake_db, "appeal_hc_decree")
    result = client.post("/api/v1/limitation/compute", json={"rule_id": "appeal_hc_decree", "start_date": "2026-10-01",
                                                             "copy_application_id": row["id"]}).json()
    assert result["inputs"]["copy_ready_on"] == "2026-10-12" and result["inputs"]["court_code"] == "TESTHC"
    assert client.get("/api/v1/limitation/copy-applications", params={"status": "pending"}).json() == []
    # Only the person who logged it deletes it (even a partner can't delete another's row).
    fake_db.tables["copy_applications"][0]["user_id"] = OTHER
    org_role("partner")
    assert client.delete(f"/api/v1/limitation/copy-applications/{row['id']}").status_code == 403
    fake_db.tables["copy_applications"][0]["user_id"] = USER
    assert client.delete(f"/api/v1/limitation/copy-applications/{row['id']}").status_code == 204
    assert client.delete(f"/api/v1/limitation/copy-applications/{row['id']}").status_code == 404
