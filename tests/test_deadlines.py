"""Firm docket (P13): ladder, routing, escalation, safety cancel, sweep, audit HMAC and payloads.

The blind check itself is enforced in Postgres and tested in tests/db/test_deadlines_blind.py;
these tests mock the Supabase client.
"""

import asyncio
import hashlib
import hmac
import json
import random
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.core.config import get_settings
from app.dependencies.auth import CurrentUser, get_current_user
from app.routers import deadlines as deadlines_router
from app.services import deadline_service as ds
from tests.conftest import ORG_ID

A, B, C, D = (str(uuid.UUID(int=i)) for i in (1, 2, 3, 4))  # associate (owner), firm owner, partner, partner
ROLES = {A: "associate", B: "owner", C: "partner", D: "partner"}
NOW = datetime(2026, 11, 4, 4, 30, tzinfo=timezone.utc)  # Wednesday 10:00 IST
TODAY = date(2026, 11, 4)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}")


# ============================================================================ an in-memory Supabase


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload, self.conflict = db, table, [], "select", None, None

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) <= val)
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) >= val)
        return self

    def order(self, *a, **k):
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def upsert(self, row, on_conflict=None):
        self.op, self.payload, self.conflict = "upsert", row, on_conflict
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        self.db.log.append((self.op, self.table, self.payload))
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.op == "upsert":
            keys = self.conflict.split(",")
            found = next((r for r in rows if all(r.get(k) == self.payload.get(k) for k in keys)), None)
            found.update(self.payload) if found else rows.append(dict(self.payload))
            return SimpleNamespace(data=[self.payload])
        matched = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in matched:
                r.update(self.payload)
        return SimpleNamespace(data=[dict(r) for r in matched])


class FakeDB:
    def __init__(self, rpc=None, **tables):
        self.tables, self.log, self.rpcs, self._rpc = tables, [], [], rpc

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params=None):
        self.rpcs.append((name, params))
        self.log.append(("rpc", name, params))
        result = self._rpc(name, params) if self._rpc else None
        if isinstance(result, Exception):
            def fail():
                raise result
            return SimpleNamespace(execute=fail)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=result))


def deadline(**kw):
    row = {
        "id": str(uuid.uuid4()), "org_id": ORG_ID, "kind": "appeal", "title": "Ravi Sharma v. Amit Joshi",
        "court_case_id": str(uuid.uuid4()), "thread_id": None, "basis": "90 days from 19.08.2026",
        "owner_id": A, "backup_id": B, "checker_id": C, "created_by": A, "check_mode": "second",
        "check_state": "pending", "verification": "unverified", "status": "open", "source": "engine", "hard": False,
        "effective_due_date": "2026-11-18", "candidates": ["2026-11-18"], "safety_lead_days": 3,
        "created_at": "2026-10-01T05:00:00+00:00", "check_note": None, "check_cancel_reason": None,
    }
    row.update(kw)
    return row


def admin(deadlines, reminders=(), absent=(), members=ROLES, rpc=None):
    return FakeDB(
        rpc=rpc,
        deadlines=list(deadlines),
        deadline_reminders=list(reminders),
        deadline_value_views=[],
        organization_members=[{"org_id": ORG_ID, "user_id": u, "role": r, "created_at": f"2026-01-0{i + 1}"}
                              for i, (u, r) in enumerate(members.items())],
        member_absences=[{"org_id": ORG_ID, "user_id": u, "starts_on": "2026-11-01", "ends_on": "2026-11-10"} for u in absent],
        court_cases=[],
    )


def sweep(db, now=NOW):
    return asyncio.run(ds.run_sweep(db, now))


def reminders_of(db):
    return db.tables["deadline_reminders"]


# ============================================================================ the ladder


def test_ladder():
    due = date(2026, 12, 31)
    assert [r.label for r in ds.ladder(due, due - timedelta(days=60))] == ["T-60", "T-30", "T-14", "T-7", "T-3", "T-1", "T-0"]
    # Short deadlines are compressed: a rung the day they're entered, then only the rungs still ahead.
    assert [r.label for r in ds.ladder(due, due - timedelta(days=10))] == ["T-10", "T-7", "T-3", "T-1", "T-0"]
    assert [r.label for r in ds.ladder(due, due - timedelta(days=2))] == ["T-2", "T-1", "T-0"]
    # Hard deadlines remind every day from T-5.
    assert [r.label for r in ds.ladder(due, due - timedelta(days=10), hard=True)] == \
        ["T-10", "T-7", "T-5", "T-4", "T-3", "T-2", "T-1", "T-0"]
    assert ds.ladder(due, due - timedelta(days=10))[1].day == date(2026, 12, 24)
    # Past rungs collapse into the latest reached; overdue reminders run daily.
    assert ds.current_rung(due, due - timedelta(days=60), due - timedelta(days=5)).label == "T-7"
    assert ds.current_rung(due, due - timedelta(days=60), due + timedelta(days=2)).label == "T+2"


def test_unverified_fires_ladder():
    d = deadline()  # check pending, unverified: reminders run all the same
    db = admin([d])
    counts = sweep(db)
    assert counts["reminders"] == 1 and counts["orgs"] == 1
    [r] = reminders_of(db)
    assert (r["target_id"], r["rung"], r["for_date"], r["level"]) == (A, "T-14", "2026-11-18", 0)
    assert db.tables["deadline_value_views"] == [{"deadline_id": d["id"], "user_id": A, "via": "reminder",
                                                  "last_seen_at": NOW.isoformat()}]
    assert sweep(db).get("reminders", 0) == 0  # once per rung


def test_disputed_uses_earliest_and_fires_past_rungs():
    # The check disputed the date: the earlier candidate governs, and the rung now due for it fires
    # at once even though a T-14 reminder went out for the later date.
    d = deadline(verification="disputed", check_state="submitted", candidates=["2026-11-10", "2026-11-18"],
                 effective_due_date="2026-11-10")
    sent = {"deadline_id": d["id"], "org_id": ORG_ID, "target_id": A, "rung": "T-14", "for_date": "2026-11-18",
            "level": 0, "issued_at": NOW.isoformat(), "acknowledged_at": NOW.isoformat()}
    db = admin([d], [sent])
    sweep(db)
    new = [r for r in reminders_of(db) if r["for_date"] == "2026-11-10"]
    assert [(r["rung"], r["target_id"]) for r in new] == [("T-7", A)]


def test_leave_routing_and_broadcast():
    d = deadline()
    rung = ds.Rung("T-7", 7, TODAY)
    assert ds.reminder_targets(d, rung, ds.Team(ROLES)) == [A]
    assert ds.reminder_targets(d, rung, ds.Team(ROLES, {A})) == [B]  # covered by the backup
    # Both away: a partner, preferring one who isn't the pending checker.
    assert ds.reminder_targets(d, rung, ds.Team(ROLES, {A, B})) == [D]
    assert ds.reminder_targets(d, ds.Rung("T-1", 1, TODAY), ds.Team(ROLES)) == [A, B, C]


# ============================================================================ safety beats blindness


def test_safety_cancels_check_when_reminder_would_reach_checker():
    d = deadline(backup_id=C, checker_id=C)  # the backup is also the checker
    db = admin([d], absent=[A])               # owner on leave: reminders go to the backup
    counts = sweep(db)
    assert counts["checks_cancelled"] == 1
    row = db.tables["deadlines"][0]
    assert (row["check_state"], row["check_cancel_reason"], row["verification"]) == ("cancelled", "reminder_to_checker", "unverified")
    [r] = reminders_of(db)
    assert r["target_id"] == C and r["for_date"] == "2026-11-18"  # the reminder carries the date
    ops = [(op, table) for op, table, _ in db.log]
    assert ops.index(("update", "deadlines")) < ops.index(("insert", "deadline_reminders"))


def test_safety_cancels_check_within_lead_days():
    db = admin([deadline(effective_due_date="2026-11-06", candidates=["2026-11-06"])])
    sweep(db)
    assert db.tables["deadlines"][0]["check_cancel_reason"] == "due_within_lead"
    # The lead is per deadline (short bail or IBC windows can ask for more or less).
    db = admin([deadline(effective_due_date="2026-11-06", candidates=["2026-11-06"], safety_lead_days=1)])
    sweep(db)
    assert db.tables["deadlines"][0]["check_state"] == "pending"
    db = admin([deadline(effective_due_date="2026-11-18", safety_lead_days=20)])
    sweep(db)
    assert db.tables["deadlines"][0]["check_cancel_reason"] == "due_within_lead"


def test_self_check_is_not_cancelled_by_reminding_its_maker():
    d = deadline(check_mode="self", checker_id=A, backup_id=None)
    db = admin([d])
    sweep(db)
    assert db.tables["deadlines"][0]["check_state"] == "pending"


# ============================================================================ escalation


def test_working_hours():
    ist = timezone(timedelta(hours=5, minutes=30))
    friday_5pm = datetime(2026, 11, 6, 17, 0, tzinfo=ist)
    assert ds.working_hours_between(friday_5pm, datetime(2026, 11, 7, 11, 0, tzinfo=ist)) == 4  # Saturday counts
    saturday_6pm = datetime(2026, 11, 7, 18, 0, tzinfo=ist)
    assert ds.working_hours_between(saturday_6pm, datetime(2026, 11, 9, 10, 0, tzinfo=ist)) == 2  # Sunday doesn't
    assert ds.working_hours_between(friday_5pm, friday_5pm - timedelta(hours=1)) == 0


def test_escalation():
    d = deadline()
    tuesday_noon = "2026-11-03T06:30:00+00:00"
    ladder_reminder = {"id": "r0", "deadline_id": d["id"], "org_id": ORG_ID, "target_id": A, "rung": "T-30",
                       "for_date": "2026-11-18", "level": 0, "issued_at": tuesday_noon}
    backup_reminder = {"id": "r1", "deadline_id": d["id"], "org_id": ORG_ID, "target_id": B, "rung": "T-40",
                       "for_date": "2026-11-18", "level": 1, "issued_at": "2026-11-02T06:30:00+00:00", "parent_id": "rx"}
    acked = {**ladder_reminder, "id": "r2", "rung": "T-48", "acknowledged_at": tuesday_noon}
    recent = {**ladder_reminder, "id": "r3", "rung": "T-35", "issued_at": "2026-11-04T03:30:00+00:00"}  # 09:00 IST today
    db = admin([d], [ladder_reminder, backup_reminder, acked, recent])
    counts = sweep(db)
    escalated = [(r["target_id"], r["level"], r["parent_id"]) for r in reminders_of(db) if r.get("parent_id") in ("r0", "r1")]
    # Ladder reminder unacknowledged for 7 working hours -> backup; the backup's -> a partner who isn't the checker.
    assert sorted(escalated) == sorted([(B, 1, "r0"), (D, 2, "r1")])
    assert counts["escalations"] == 2
    assert {r["id"]: r.get("escalated_at") for r in reminders_of(db) if r["id"] in ("r2", "r3")} == {"r2": None, "r3": None}
    assert db.tables["deadlines"][0]["check_state"] == "pending"


def test_escalation_to_the_checker_cancels_the_check():
    d = deadline()
    reminder = {"id": "r1", "deadline_id": d["id"], "org_id": ORG_ID, "target_id": B, "rung": "T-30",
                "for_date": "2026-11-18", "level": 1, "issued_at": "2026-11-02T06:30:00+00:00"}
    db = admin([d], [reminder], members={A: "associate", B: "owner", C: "partner"})  # only partner is the checker
    sweep(db)
    assert any(r["target_id"] == C and r["level"] == 2 for r in reminders_of(db))
    assert db.tables["deadlines"][0]["check_cancel_reason"] == "reminder_to_checker"


# ============================================================================ orphans and departures


def test_orphan_sweep(audit_log):
    gone = str(uuid.UUID(int=99))
    d = deadline(owner_id=gone, check_state="submitted", verification="verified")
    db = admin([d])
    counts = sweep(db)
    assert counts["orphans"] == 1
    row = db.tables["deadlines"][0]
    assert row["owner_id"] == B and row["backup_id"] not in (B, None)
    assert audit_log[0]["action"] == "REASSIGN_ORPHAN_DEADLINE" and audit_log[0]["metadata"]["reason"] == "owner_left"
    assert reminders_of(db)[0]["target_id"] == B


def test_checker_left_is_reassigned():
    gone = str(uuid.UUID(int=98))
    d = deadline(checker_id=gone)

    def rpc(name, params):
        assert (name, params["p_exclude"]) == ("deadline_assign_check", gone)
        db.tables["deadlines"][0].update(checker_id=D)
        return "second"

    db = admin([d], rpc=rpc)
    assert sweep(db)["checks_reassigned"] == 1
    assert db.tables["deadlines"][0]["checker_id"] == D


# ============================================================================ audit: HMAC, no dates


def test_audit_hmac_resists_date_enumeration(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_service_role_key", "server-held-secret")
    order = date(2026, 3, 17)
    computed = order + timedelta(days=90)
    meta = ds.audit_metadata(ORG_ID, {"id": "d1", "kind": "appeal", "check_state": "pending"},
                             inputs={"order_date": order}, computed=computed)
    assert not DATE_RE.search(json.dumps(meta))
    digest = meta["entry_hmac"]

    # Someone reading the audit log knows the format and tries every date pair in a year.
    window = [date(2026, 1, 1) + timedelta(days=i) for i in range(365)]
    guessed_keys = [b"", ORG_ID.encode(), ds._AUDIT_FALLBACK_SECRET.encode()]
    for o in window:
        for c in window:
            canonical = json.dumps({"inputs": {"order_date": o.isoformat()}, "computed": c.isoformat()},
                                   sort_keys=True, separators=(",", ":")).encode()
            assert hashlib.sha256(canonical).hexdigest() != digest
            if c == o + timedelta(days=90):
                assert all(hmac.new(k, canonical, hashlib.sha256).hexdigest() != digest for k in guessed_keys)
    # Only the server, holding the key, can match it (so the enumeration above was a real attack).
    assert [o for o in window if ds.inputs_digest(ORG_ID, {"order_date": o}, o + timedelta(days=90)) == digest] == [order]
    # Keys differ per org.
    assert ds.inputs_digest(str(uuid.uuid4()), {"order_date": order}, computed) != digest


def test_create_deadline_calls_rpc_and_audits_without_dates(audit_log):
    def rpc(name, params):
        assert name == "create_deadline"
        return {"id": "d1", "org_id": ORG_ID, "created_by": A, "kind": params["p_kind"], "source": params["p_source"],
                "check_mode": "second", "check_state": "pending", "verification": "unverified", "status": "open",
                "effective_due_date": params["p_due_date"]}

    db = FakeDB(rpc=rpc)
    row = ds.create_deadline(db, kind="Written Statement", title="  WS  in  Sharma v. Joshi ", due_date=date(2026, 12, 1),
                             owner_id=A, inputs={"summons_served_on": date(2026, 10, 2), "note": " 30 days "},
                             candidates=[date(2026, 11, 28)], court_case_id="c1", safety_lead_days=5)
    _, params = db.rpcs[0]
    assert params["p_kind"] == "written_statement" and params["p_title"] == "WS in Sharma v. Joshi"
    assert params["p_inputs"] == {"summons_served_on": "2026-10-02", "note": "30 days"}
    assert params["p_candidates"] == ["2026-11-28"] and params["p_due_date"] == "2026-12-01"
    assert (params["p_court_case"], params["p_safety_lead_days"], params["p_backup"]) == ("c1", 5, None)
    assert row["id"] == "d1"
    [entry] = audit_log
    assert entry["action"] == "CREATE_DEADLINE" and entry["resource_id"] == "d1"
    assert len(entry["metadata"]["entry_hmac"]) == 64
    assert not DATE_RE.search(json.dumps(entry["metadata"])) and "30 days" not in json.dumps(entry["metadata"])

    with pytest.raises(ds.DeadlineError):
        ds.create_deadline(db, kind="appeal", title="x", due_date=date(2026, 12, 1), owner_id=A, source="guess")
    with pytest.raises(ds.DeadlineError):
        ds.create_deadline(db, kind="?", title="x", due_date=date(2026, 12, 1), owner_id=A)


def test_rpc_errors_become_deadline_errors():
    def rpc(name, params):
        return APIError({"code": "55000", "message": "check_not_open", "hint": "Self re-entry opens at 05 Nov 09:40 IST"})

    with pytest.raises(ds.DeadlineError) as info:
        ds.reassign_check(FakeDB(rpc=rpc), "d1")
    assert (info.value.status, info.value.code, info.value.message) == (409, "check_not_open", "Self re-entry opens at 05 Nov 09:40 IST")


def test_submit_recomputes_with_registered_engine():
    calls = []

    def rpc(name, params):
        calls.append((name, params))
        if name == "get_deadline":
            return {"id": "d1", "rule_id": "test_rule_90", "effective_due_date": None, "masked": True}
        return {"id": "d1", "verification": "verified"}

    ds.register_engine("test_rule_90", lambda inputs: date.fromisoformat(inputs["order_date"]) + timedelta(days=90))
    try:
        row, inputs, computed = ds.submit_entry(FakeDB(rpc=rpc), "d1", inputs={"order_date": date(2026, 3, 17)},
                                                due_date=date(2026, 1, 1))
    finally:
        ds._ENGINES.pop("test_rule_90")
    assert computed == date(2026, 6, 15) and calls[1][1]["p_computed"] == "2026-06-15"
    with pytest.raises(ds.DeadlineError):
        ds.submit_entry(FakeDB(rpc=rpc), "d1", inputs={"order_date": "2026-03-17"})  # no engine, no date


# ============================================================================ reminder payloads


def test_member_whatsapp_has_no_party_names():
    rng = random.Random(13)
    first = ["Ravi", "Amit", "Sunita", "Farhan", "Lakshmi", "Gurpreet"]
    last = ["Sharma", "Joshi", "Iyer", "Qureshi", "Banerjee", "Gill"]
    for _ in range(200):
        parties = [f"{rng.choice(first)} {rng.choice(last)}" for _ in range(2)]
        cnr = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(16))
        d = deadline(title=f"{parties[0]} v. {parties[1]} ({cnr})", basis=f"Order of JMFC Pune, CC/{rng.randint(1, 9999)}/2026")
        reminder = {"id": "r1", "target_id": A, "for_date": d["effective_due_date"], "rung": "T-7", "level": 0}
        payload = ds.member_payload(reminder, d)
        text = json.dumps(payload)
        assert payload["date"] == "2026-11-18" and payload["kind"] == "appeal"
        assert re.fullmatch(r"M-[0-9A-F]{6}", payload["short_code"])
        for leaked in [*parties, *(p.split()[1] for p in parties), cnr, d["basis"], "JMFC", d["title"]]:
            assert leaked not in text


def test_deliver_only_when_whatsapp_and_n8n_are_configured(monkeypatch):
    posted = []

    async def trigger(path, payload):
        posted.append((path, payload))

    monkeypatch.setattr("app.services.n8n_service.trigger_workflow", trigger)
    d, reminder = deadline(), {"id": "r1", "target_id": A, "for_date": "2026-11-18", "rung": "T-7"}
    assert asyncio.run(ds.deliver(reminder, d)) is False and posted == []
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", "t")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "s")
    monkeypatch.setattr(settings, "n8n_webhook_base_url", "https://n8n.example/webhook")
    assert asyncio.run(ds.deliver(reminder, d)) is True
    assert posted[0][0] == "deadline-reminder" and posted[0][1]["template"] == "deadline_member_v1"
    assert asyncio.run(ds.deliver({**reminder, "payload_class": "content_free"}, d)) is False

    db = admin([d])
    assert sweep(db)["delivered"] == 1 and reminders_of(db)[0]["channel"] == "whatsapp"


def test_partner_digest_hides_dates_of_pending_checks():
    pending = deadline(effective_due_date="2026-11-01")
    overdue = deadline(effective_due_date="2026-11-02", check_state="submitted", verification="verified")
    viewed = deadline(check_state="pending", check_mode="self", check_note="all_eligible_viewed", checker_id=A)
    digest = ds.partner_digest([pending, overdue, viewed], [], TODAY)
    assert digest["overdue"] == [{"short_code": ds.short_code(overdue), "kind": "appeal", "date": "2026-11-02"}]
    assert "2026-11-01" not in json.dumps(digest)
    assert digest["recheck_impossible"][0]["note"].startswith("re-check impossible")


# ============================================================================ the API


@pytest.fixture
def api(monkeypatch, org_role, audit_log):
    app = FastAPI()
    app.include_router(deadlines_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=A, email="a@b.in", access_token="t")
    state = {"calls": []}

    def rpc(name, params):
        state["calls"].append((name, params))
        base = {"id": "d1", "org_id": ORG_ID, "created_by": A, "kind": "appeal", "source": "manual", "status": "open",
                "check_mode": "second", "check_state": "pending", "verification": "unverified",
                "effective_due_date": "2026-12-18", "rule_id": None}
        if name == "submit_deadline_entry":
            return {**base, "check_state": "submitted", "verification": "disputed"}
        if name == "complete_deadline":
            return {**base, "status": "done"}
        if name == "acknowledge_deadline_reminder":
            return {"deadline_id": "d1", "acknowledged": 2}
        if name == "list_deadlines":
            return [base]
        return base

    db = FakeDB(rpc=rpc)
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    state["client"] = TestClient(app)
    return state


def test_api_state_changes_write_one_audit_row_without_dates(api, audit_log):
    client, d1 = api["client"], str(uuid.UUID(int=7))
    created = client.post("/api/v1/deadlines", json={
        "kind": "appeal", "title": "Appeal - Sharma v. Joshi", "due_date": "2026-12-18",
        "inputs": {"order_date": "2026-09-19"}, "hard": True})
    assert created.status_code == 201, created.text
    name, params = api["calls"][-1]
    assert (name, params["p_source"], params["p_owner"], params["p_hard"]) == ("create_deadline", "manual", A, True)
    assert client.post(f"/api/v1/deadlines/{d1}/check", json={"inputs": {"order_date": "2026-09-18"},
                                                               "due_date": "2026-12-17"}).status_code == 200
    assert client.post(f"/api/v1/deadlines/reminders/{d1}/acknowledge").json()["acknowledged"] == 2
    assert client.post(f"/api/v1/deadlines/{d1}/complete", json={"evidence": "Filed, diary no. 4411/2026"}).status_code == 200
    assert client.post(f"/api/v1/deadlines/{d1}/complete", json={"evidence": ""}).status_code == 422
    assert [e["action"] for e in audit_log] == ["CREATE_DEADLINE", "SUBMIT_DEADLINE_CHECK",
                                                "ACKNOWLEDGE_DEADLINE_REMINDER", "COMPLETE_DEADLINE"]
    for entry in audit_log:
        assert not DATE_RE.search(json.dumps(entry["metadata"])), entry
    assert client.get("/api/v1/deadlines").json()[0]["id"] == "d1"


def test_api_maps_database_refusals(api, monkeypatch):
    def refuse(name, params):
        return APIError({"code": "42501", "message": "You are not assigned to check this deadline"})

    db = FakeDB(rpc=refuse)
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    response = api["client"].post(f"/api/v1/deadlines/{uuid.UUID(int=7)}/reassign-check")
    assert response.status_code == 403 and response.json()["detail"]["code"] == "forbidden"
