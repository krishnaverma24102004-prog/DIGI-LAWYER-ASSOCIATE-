"""Firm sign-off of rule tables through the API (the two-signature rule itself is tested in tests/db)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.routers import rules

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="a@firm.in", access_token="jwt")
RULE = {"rule_id": "appeal_hc_decree", "version": 2, "title": "Appeal to a High Court from a decree", "basis": "Article 116(a), Limitation Act, 1963"}


class Table:
    def __init__(self, rows, inserted):
        self.rows, self.inserted = rows, inserted

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def insert(self, row):
        self.inserted.append(row)
        self.rows.append({**row, "verified_by": USER.id})
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows if not self.inserted else [self.rows[-1]])


@pytest.fixture
def client(monkeypatch):
    signed = [{"rule_id": "appeal_hc_decree", "version": 2, "verified_by": "partner-1", "verified_at": "2026-10-27T10:00:00Z", "note": None},
              {"rule_id": "appeal_hc_decree", "version": 1, "verified_by": "partner-2", "verified_at": "2026-01-01T10:00:00Z", "note": None}]
    inserted = []
    monkeypatch.setattr(rules, "load_registry", lambda registry: {RULE["rule_id"]: RULE})
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user",
                        lambda *a, **k: SimpleNamespace(table=lambda name: Table(signed, inserted)))
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app), inserted
    app.dependency_overrides.clear()


def test_rules_show_sign_offs_for_the_current_version_only(client):
    http, _ = client
    [rule] = http.get("/api/v1/rules/limitation").json()
    assert rule["rule_id"] == "appeal_hc_decree" and rule["version"] == 2
    assert [s["verified_by"] for s in rule["signatures"]] == ["partner-1"]  # the version-1 signature doesn't count
    assert rule["active"] is False and rule["signed_by_me"] is False


def test_signing_needs_the_current_version_and_a_confirmation(client, audit_log):
    http, inserted = client
    assert http.post("/api/v1/rules/limitation/appeal_hc_decree/sign", json={"version": 1, "confirm": True}).status_code == 409
    assert http.post("/api/v1/rules/limitation/appeal_hc_decree/sign", json={"version": 2, "confirm": False}).status_code == 400
    assert http.post("/api/v1/rules/limitation/missing/sign", json={"version": 1, "confirm": True}).status_code == 404
    response = http.post("/api/v1/rules/limitation/appeal_hc_decree/sign", json={"version": 2, "confirm": True, "note": "checked with the Act"})
    assert response.status_code == 201
    assert inserted == [{"registry": "limitation", "rule_id": "appeal_hc_decree", "version": 2, "note": "checked with the Act"}]
    assert audit_log[-1]["action"] == "SIGN_RULE"
    assert http.get("/api/v1/rules/unknown").status_code == 422
