"""Workflow packs: statutory deadlines are computed exactly, in code."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.services import workflow_service as wf

TODAY = date(2026, 10, 23)


def dates(result):
    return {d["label"]: (d["date"], d["status"]) for d in result["deadlines"]}


def test_cheque_bounce_timeline_before_the_notice():
    result = wf.evaluate("cheque_bounce", {"amount": "150000", "cheque_date": "2026-08-01", "presented_on": "2026-10-01",
                                           "return_memo_received_on": "2026-10-10"}, TODAY)
    assert dates(result) == {"Send the demand notice": ("2026-11-09", "upcoming")}
    assert result["flags"] == []
    assert result["draft"]["doc_type"] == "legal_notice" and "Rs. 1,50,000" in result["draft"]["facts"]
    assert "Section 138" in result["draft"]["instructions"]


def test_cheque_bounce_complaint_window_after_notice():
    result = wf.evaluate("cheque_bounce", {"amount": "50000", "return_memo_received_on": "2026-08-01",
                                           "notice_sent_on": "2026-08-20", "notice_received_on": "2026-08-25"}, TODAY)
    assert dates(result) == {
        "Send the demand notice": ("2026-08-31", "done"),
        "Drawer's time to pay ends": ("2026-09-09", "missed"),
        "File the complaint": ("2026-10-09", "missed"),  # one month from the cause of action, 10 Sep
    }
    assert any("condone" in f["message"] for f in result["flags"])
    assert result["draft"] is None  # the notice has gone


def test_cheque_bounce_flags_late_notice_and_stale_cheque():
    result = wf.evaluate("cheque_bounce", {"amount": "1", "cheque_date": "2026-01-01", "presented_on": "2026-05-01",
                                           "return_memo_received_on": "2026-05-05", "notice_sent_on": "2026-06-20"}, TODAY)
    messages = " ".join(f["message"] for f in result["flags"])
    assert "3-month validity" in messages and "after the 30-day limit" in messages


def test_consumer_forum_follows_the_amount_paid():
    def forum(paid):
        result = wf.evaluate("consumer_complaint", {"amount_paid": paid, "cause_of_action_on": "2026-01-15"}, TODAY)
        return next(s for s in result["next_steps"] if s.startswith("Forum"))

    assert "District" in forum("65000") and "State" in forum("7500000") and "National" in forum("30000000")
    result = wf.evaluate("consumer_complaint", {"amount_paid": "65000", "cause_of_action_on": "2026-01-15"}, TODAY)
    assert dates(result) == {"File the consumer complaint": ("2028-01-14", "upcoming")}
    late = wf.evaluate("consumer_complaint", {"amount_paid": "65000", "cause_of_action_on": "2023-01-15"}, TODAY)
    assert late["flags"][0]["severity"] == "high"


def test_bail_picks_the_code_by_offence_date_and_computes_default_bail():
    new = wf.evaluate("bail", {"offence_date": "2025-03-01", "custody_since": "2026-08-01", "max_punishment_years": "7",
                               "first_time_offender": "yes"}, TODAY)
    assert dates(new)["Default bail if no chargesheet"] == ("2026-09-30", "missed")  # 60 days: under 10 years
    assert "s. 187(3) BNSS" in new["deadlines"][0]["basis"]
    assert any("default bail" in f["message"] for f in new["flags"])
    assert "one-third" in next(d["basis"] for d in new["deadlines"] if d["label"] == "Release as an undertrial")
    assert "s. 480 BNSS" in new["draft"]["instructions"]

    old = wf.evaluate("bail", {"offence_date": "2023-06-01", "custody_since": "2026-09-01", "punishable_with_death_or_life": "true",
                               "chargesheet_filed": "false"}, TODAY)
    assert dates(old)["Default bail if no chargesheet"] == ("2026-11-30", "upcoming")  # 90 days for serious offences
    assert "s. 167(2) CrPC" in old["deadlines"][0]["basis"] and "CrPC" in old["summary"]

    anticipatory = wf.evaluate("bail", {"offence_date": "2026-09-01"}, TODAY)
    assert anticipatory["deadlines"] == [] and "s. 482 BNSS" in anticipatory["draft"]["instructions"]


def test_missing_and_bad_inputs_are_explained():
    with pytest.raises(wf.WorkflowError, match="Required"):
        wf.evaluate("consumer_complaint", {"amount_paid": "100"}, TODAY)
    with pytest.raises(wf.WorkflowError, match="must be a date"):
        wf.evaluate("consumer_complaint", {"amount_paid": "100", "cause_of_action_on": "yesterday"}, TODAY)
    assert wf.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_workflow_api():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", email="a@b.in", access_token="t")
    try:
        client = TestClient(app)
        packs = client.get("/api/v1/workflows").json()
        assert [p["id"] for p in packs] == ["cheque_bounce", "consumer_complaint", "bail"]
        assert any(f["key"] == "return_memo_received_on" and f["required"] for f in packs[0]["fields"])
        ok = client.post("/api/v1/workflows/consumer_complaint/evaluate", json={"inputs": {"amount_paid": 1000, "cause_of_action_on": "2026-01-01"}})
        assert ok.status_code == 200 and ok.json()["deadlines"]
        assert client.post("/api/v1/workflows/consumer_complaint/evaluate", json={"inputs": {}}).status_code == 422
        assert client.post("/api/v1/workflows/nope/evaluate", json={"inputs": {}}).status_code == 404
    finally:
        app.dependency_overrides.clear()
