"""P47: hearing briefs (app/services/brief_service.py)."""

import types
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import anthropic_service, brief_service
from app.services.brief_service import OrderDirection, OrderReading
from tests.conftest import ORG_ID
from tests.test_schedule import FakeDB

NOW = datetime(2026, 10, 27, 19, 0, tzinfo=brief_service.IST)
TOMORROW = "2026-10-28"
CASE_A = "11111111-1111-4111-8111-111111111111"
CASE_B = "22222222-2222-4222-8222-222222222222"
ORDER_TEXT = """IN THE HIGH COURT OF DELHI AT NEW DELHI
W.P.(C) 1234/2026
Order dated 01.10.2026
Present: Counsel for the petitioner. Counsel for the respondent (mobile 9876543210).
Notice issued. The respondent shall file reply within four weeks. Rejoinder, if any, within two weeks thereafter.
The petitioner shall deposit Rs. 50,000 with the Registry within 15 days from the date of receipt of this order.
List on 12.11.2026."""


@pytest.fixture
def docket(monkeypatch):
    """The docket (P13) as list_deadlines' contract describes it; one deadline's date is masked."""
    calls = []

    def list_deadlines(db, *, court_case_id=None, thread_id=None, include_done=False):
        calls.append(court_case_id)
        return [
            {"kind": "filing", "title": "Reply", "effective_due_date": "2026-10-29", "status": "open", "basis": "order of 1 Oct"},
            {"kind": "limitation", "title": "Appeal", "effective_due_date": None, "status": "open", "basis": "awaiting second check"},
        ]

    module = types.ModuleType("app.services.deadline_service")
    module.list_deadlines = list_deadlines
    monkeypatch.setitem(__import__("sys").modules, "app.services.deadline_service", module)
    return calls


def case_row(case_id=CASE_A, orders=None, next_hearing=None, **extra):
    return {"id": case_id, "org_id": ORG_ID, "user_id": "owner-1", "title": "Sharma v. Union of India", "court_name": "Delhi High Court",
            "case_number": "W.P.(C) 1234/2026", "cnr": None, "next_hearing_date": next_hearing,
            "provider_data": {"orders": orders or [], "judges": ["Justice A"]}, **extra}


def database(**tables):
    base = {"court_cases": [], "cause_list_items": [], "listing_matches": [], "hearing_outcomes": [], "case_counsel": [],
            "hearing_briefs": []}
    return FakeDB(**{**base, **tables})


# ============================================================================ trigger


def test_trigger(monkeypatch, docket):
    fetched = []

    async def fetch(order, **kw):
        fetched.append(order["url"])
        return brief_service.OrderText(ORDER_TEXT, date.fromisoformat(order["date"]), "provider", brief_service.order_key(order),
                                       order["url"])

    monkeypatch.setattr(brief_service, "fetch_order_text", fetch)
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: False)
    db = database(
        court_cases=[case_row(orders=[{"date": "2026-10-01", "url": "https://orders.example/o1.pdf"}]),
                     case_row(CASE_B, next_hearing=TOMORROW, title="Mehta v. Mehta")],
        cause_list_items=[{"id": "i1", "court_code": "DLHC", "courtroom": "12", "list_date": TOMORROW, "item_no": "8",
                           "position": 8, "bench_label": "Justice A", "list_type": "daily", "status": "listed"}],
        listing_matches=[{"id": "m1", "item_id": "i1", "court_case_id": CASE_A, "match_type": "exact", "state": "open",
                          "ingested_at": "2026-10-27T18:00:00+05:30", "list_date": TOMORROW}],
        hearing_outcomes=[{"court_case_id": CASE_A, "hearing_date": "2026-10-01", "outcome": "adjourned",
                           "adjourned_at_instance_of": "respondent"}],
    )
    assert asyncio_run(brief_service.generate_due_briefs(db, NOW)) == {"generated": 2, "skipped": 0, "failed": 0}
    briefs = {b["court_case_id"]: b for b in db.tables["hearing_briefs"]}
    a = briefs[CASE_A]
    assert a["trigger"] == "listing_match" and a["listing_match_id"] == "m1" and a["hearing_date"] == TOMORROW
    assert a["sections"]["listing"]["item_no"] == "8" and a["sections"]["listing"]["bench"] == "Justice A"
    assert a["sections"]["adjournments"]["respondent"] == 1
    assert a["ai_status"] == "not_configured" and a["order_date"] == "2026-10-01"
    assert briefs[CASE_B]["trigger"] == "next_hearing_date" and briefs[CASE_B]["ai_status"] == "no_order"

    # The same list ingested again: nothing is duplicated or rebuilt.
    assert asyncio_run(brief_service.generate_due_briefs(db, NOW)) == {"generated": 0, "skipped": 2, "failed": 0}
    assert len(db.tables["hearing_briefs"]) == 2 and fetched == ["https://orders.example/o1.pdf"]

    # A new order arrives: that brief (only) is regenerated in place.
    db.tables["court_cases"][0]["provider_data"]["orders"].append({"date": "2026-10-20", "url": "https://orders.example/o2.pdf"})
    assert asyncio_run(brief_service.generate_due_briefs(db, NOW)) == {"generated": 1, "skipped": 1, "failed": 0}
    assert len(db.tables["hearing_briefs"]) == 2
    assert {b["court_case_id"]: b for b in db.tables["hearing_briefs"]}[CASE_A]["order_date"] == "2026-10-20"


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ============================================================================ the AI section


@pytest.fixture
def fake_claude(monkeypatch):
    calls = []

    async def parse(system, content, output_format, what, max_tokens=16000):
        calls.append({"system": system, "content": content, "format": output_format})
        return OrderReading(
            operative_quote="Notice issued.",
            directions=[
                OrderDirection(direction="The respondent files its reply (see s. 999 BNSS).", responsible="respondent",
                               quote="The respondent shall file reply within four weeks."),
                OrderDirection(direction="The petitioner pays costs of Rs. 1,00,000.", responsible="petitioner",
                               quote="The petitioner shall pay costs of Rs. 1,00,000 within one week."),
            ],
        )

    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    monkeypatch.setattr(anthropic_service, "_parse_detailed", parse)
    return calls


def test_quote_verification(fake_claude, docket):
    db = database(court_cases=[case_row()])
    order = brief_service.pasted_order(ORDER_TEXT, date(2026, 10, 1))
    brief = asyncio_run(brief_service.generate_brief(db, case_row(), date(2026, 10, 28), trigger="manual", order=order))

    assert brief["ai_status"] == "done" and brief["discarded_unverified"] == 1
    section = brief["ai_section"]
    assert section["label"] == "AI-assisted brief for the advocate; verify against the order"
    assert [d["quote"] for d in section["directions"]] == ["The respondent shall file reply within four weeks."]
    kept = section["directions"][0]
    assert kept["quote_match"] == "exact" and kept["due"]["due_date"] == "2026-10-29"
    assert "[unverified]" in kept["direction"] and kept["citations"][0]["status"] == "invalid"  # BNSS has no s. 999
    assert section["operative"]["quote"] == "Notice issued."

    # What reached Claude: masked text, behind a cached system prompt.
    call = fake_claude[0]
    assert "9876543210" not in call["content"] and "Notice issued." in call["content"]
    assert isinstance(call["system"], list) and call["system"][0].get("cache_control") == {"type": "ephemeral"}
    # Deterministic sections sit beside it, with the docket's masked date left masked.
    deadlines = brief["sections"]["deadlines"]["items"]
    assert deadlines[0]["due_date"] == "2026-10-29" and deadlines[1] == {
        "kind": "limitation", "title": "Appeal", "due_date": None, "masked": True, "status": "open", "basis": "awaiting second check"}


def test_direction_date():
    assert brief_service.due_date("file reply within four weeks", date(2026, 10, 1))["due_date"] == "2026-10-29"
    assert brief_service.due_date("within 4 (four) weeks", date(2026, 10, 1))["due_date"] == "2026-10-29"
    assert brief_service.due_date("deposit within 2 months", date(2026, 12, 31))["due_date"] == "2027-02-28"
    assert brief_service.due_date("within 10 days", date(2026, 10, 1))["basis"] == "10 days from the order date (1 Oct 2026)"
    stated = brief_service.due_date("file the affidavit on or before 15.11.2026", date(2026, 10, 1))
    assert stated == {"due_date": "2026-11-15", "basis": "date stated in the order (15 Nov 2026)", "runs_from": "stated"}
    receipt = brief_service.due_date("within 15 days from the date of receipt of this order", date(2026, 10, 1))
    assert receipt["due_date"] == "2026-10-16" and receipt["runs_from"] == "receipt" and "earliest" in receipt["basis"]
    assert brief_service.due_date("उत्तर 4 सप्ताह में दाखिल करें", date(2026, 10, 1))["due_date"] == "2026-10-29"
    assert brief_service.due_date("Notice issued.", date(2026, 10, 1)) is None


def test_no_order_available(monkeypatch, docket):
    monkeypatch.setattr(anthropic_service, "_parse_detailed", lambda *a, **k: pytest.fail("no order: no AI call"))
    db = database(court_cases=[case_row()])
    brief = asyncio_run(brief_service.generate_brief(db, case_row(), date(2026, 10, 28), trigger="next_hearing_date"))
    assert brief["ai_status"] == "no_order" and brief["ai_section"]["last_order"] == "last order not available"
    assert brief["sections"]["listing"]["source"] == "case_record" and brief["sections"]["deadlines"]["available"]
    assert brief["sections"]["prior_bench"] == ["Justice A"] and brief["sections"]["adjournments"]["total"] == 0


def test_unreliable_scan_is_not_sent_to_the_ai(fake_claude, docket):
    order = brief_service.OrderText(ORDER_TEXT, date(2026, 10, 1), "document", "doc:1", ocr_confidence=31.0)
    brief = asyncio_run(brief_service.generate_brief(database(), case_row(), date(2026, 10, 28), trigger="manual", order=order))
    assert brief["ai_status"] == "unreliable_text" and brief["ai_section"]["last_order"] == "order text unreliable"
    assert fake_claude == []


def test_docket_unavailable_still_renders(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "app.services.deadline_service", None)
    brief = asyncio_run(brief_service.generate_brief(database(), case_row(), date(2026, 10, 28), trigger="manual"))
    assert brief["sections"]["deadlines"] == {"available": False, "items": [], "note": "docket not available"}


def test_order_urls_are_fetched_over_https_only():
    assert brief_service._safe_url("https://orders.example/o1.pdf")
    for url in ("http://orders.example/o1.pdf", "https://127.0.0.1/o.pdf", "https://10.0.0.5/o.pdf", "https://localhost/o.pdf",
                "file:///etc/passwd", None):
        assert not brief_service._safe_url(url)


# ============================================================================ API


@pytest.fixture
def briefs_client(monkeypatch, fake_claude, docket):
    from app.dependencies.auth import CurrentUser, get_current_user
    from app.routers import hearings

    db = database(court_cases=[case_row(next_hearing=TOMORROW)])
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    app = FastAPI()
    app.include_router(hearings.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="owner-1", email="a@example.com", access_token="t")
    return TestClient(app), db


def test_briefs_api(briefs_client, audit_log):
    client, db = briefs_client
    response = client.post("/api/v1/hearings/briefs/regenerate",
                           json={"court_case_id": CASE_A, "order_text": ORDER_TEXT, "order_date": "2026-10-01"})
    assert response.status_code == 200, response.text
    brief = response.json()
    assert brief["hearing_date"] == TOMORROW and brief["trigger"] == "manual" and brief["generated_by"] == "owner-1"
    assert brief["discarded_unverified"] == 1
    listed = client.get("/api/v1/hearings/briefs?date=2026-10-27").json()
    assert [b["title"] for b in listed] == ["Sharma v. Union of India"]
    assert client.get(f"/api/v1/hearings/briefs/{brief['id']}").json()["id"] == brief["id"]
    assert [e["action"] for e in audit_log] == ["GENERATE_HEARING_BRIEF", "VIEW_HEARING_BRIEF"]
    # Again: the same row is replaced, not duplicated.
    client.post("/api/v1/hearings/briefs/regenerate", json={"court_case_id": CASE_A, "order_text": ORDER_TEXT})
    assert len(db.tables["hearing_briefs"]) == 1
    missing = client.post("/api/v1/hearings/briefs/regenerate", json={"court_case_id": CASE_B})
    assert missing.status_code == 404
