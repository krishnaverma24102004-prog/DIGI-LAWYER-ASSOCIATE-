"""Trash, approvals, legal hold and the public intake switch, through the API.

The rules themselves run in the database (tests/db/test_trash_and_approvals.py); here the database
functions are scripted to check how the API turns their answers into responses and audit entries.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.services import memory_service, org_service, safety_service, transcript_service
from tests.conftest import ORG_ID

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="a@firm.in", access_token="jwt")
ITEM = "33333333-3333-3333-3333-333333333333"
APPROVAL = "44444444-4444-4444-4444-444444444444"
TRASH = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def rpc(monkeypatch):
    """Scripted database functions: `rpc.answers[name]` is a value, an APIError, or a callable."""

    class Rpc:
        def __init__(self):
            self.calls, self.answers = [], {}

        def __call__(self, db, name, params):
            self.calls.append((name, params))
            answer = self.answers.get(name)
            if callable(answer):
                answer = answer(params)
            if isinstance(answer, APIError):
                raise safety_service._translate(answer)
            return answer

        def names(self):
            return [name for name, _ in self.calls]

    fake = Rpc()
    monkeypatch.setattr(safety_service, "_rpc", fake)
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: {"id": tid, "title": "Rent dispute", "content": "x"})
    return fake


def error(message, code="42501", hint=None):
    return APIError({"message": message, "code": code, "hint": hint})


def approval_row(action="delete", kind="transcript", target=ITEM, status="pending"):
    return {"id": APPROVAL, "action": action, "target_kind": kind, "target_id": target, "status": status,
            "requested_by": "someone-else", "reason": None}


def test_delete_moves_to_trash(client, rpc, audit_log):
    rpc.answers["trash_item"] = TRASH
    response = client.delete(f"/api/v1/transcripts/{ITEM}", params={"reason": "duplicate"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "trashed" and body["trash_id"] == TRASH and "restorable_until" in body
    assert rpc.calls == [("trash_item", {"p_kind": "transcript", "p_id": ITEM, "p_reason": "duplicate", "p_approval": None})]
    assert audit_log[-1]["action"] == "TRASH_ITEM" and audit_log[-1]["metadata"]["reason"] == "duplicate"


def test_delete_without_the_role_asks_a_senior(client, rpc, audit_log, org_role):
    org_role("associate")
    rpc.answers["trash_item"] = error("approval_required", hint="A partner or owner must approve deleting this record")
    rpc.answers["request_approval"] = approval_row()
    response = client.delete(f"/api/v1/transcripts/{ITEM}")
    assert response.status_code == 202
    assert response.json()["status"] == "approval_requested"
    assert "partner or owner" in response.json()["message"]
    name, params = rpc.calls[-1]
    assert name == "request_approval" and params["p_target_label"] == "Rent dispute" and params["p_action"] == "delete"
    assert audit_log[-1]["action"] == "REQUEST_APPROVAL"


def test_legal_hold_blocks_delete_with_a_clear_message(client, rpc, monkeypatch):
    monkeypatch.setattr(memory_service, "get_thread", lambda db, tid: {"id": tid, "title": "State v. Rao"})
    rpc.answers["trash_item"] = error("legal_hold", "55006", "This record is under legal hold. A partner or owner must lift the hold")
    response = client.delete(f"/api/v1/case-threads/{ITEM}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "legal_hold"
    assert "legal hold" in response.json()["detail"]["message"]


def test_approving_carries_out_the_request(client, rpc, audit_log, monkeypatch):
    monkeypatch.setattr(safety_service, "get_approval", lambda db, aid: approval_row(status="executed"))
    rpc.answers["decide_approval"] = approval_row(status="approved")
    rpc.answers["trash_item"] = TRASH
    response = client.post(f"/api/v1/approvals/{APPROVAL}/approve", json={"note": "ok"},
                           headers={"X-Org-Id": ORG_ID})
    assert response.status_code == 200, response.text
    assert response.json()["result"] == {"trash_id": TRASH} and response.json()["status"] == "executed"
    assert ("trash_item", {"p_kind": "transcript", "p_id": ITEM, "p_reason": None, "p_approval": APPROVAL}) in rpc.calls
    assert audit_log[-1]["action"] == "APPROVE_REQUEST" and audit_log[-1]["metadata"]["executed"] is True


def test_a_failed_execution_marks_the_request_failed(client, rpc, audit_log):
    rpc.answers["decide_approval"] = approval_row(status="approved")
    rpc.answers["trash_item"] = error("legal_hold", "55006", "Under legal hold")
    rpc.answers["complete_approval"] = True
    response = client.post(f"/api/v1/approvals/{APPROVAL}/approve", json={})
    assert response.status_code == 409
    assert rpc.calls[-1] == ("complete_approval", {"p_id": APPROVAL, "p_ok": False, "p_error": "Under legal hold"})
    assert audit_log[-1]["metadata"]["executed"] is False


def test_nobody_approves_their_own_request(client, rpc):
    rpc.answers["decide_approval"] = error("Someone other than the requester must decide")
    response = client.post(f"/api/v1/approvals/{APPROVAL}/approve", json={})
    assert response.status_code == 403
    assert "other than the requester" in response.json()["detail"]["message"]


def test_erasing_early_needs_typed_confirmation_and_a_second_senior(client, rpc, monkeypatch, audit_log):
    monkeypatch.setattr(safety_service, "get_trash_item", lambda db, tid: {"id": tid, "title": "Old lease", "kind": "document"})
    assert client.post(f"/api/v1/trash/{TRASH}/erase", json={"confirm": "yes"}).status_code == 400
    assert rpc.calls == []
    rpc.answers["purge_trash_item"] = error("approval_required", hint="An owner asks and another owner or partner approves")
    rpc.answers["request_approval"] = approval_row("purge", "trash_item", TRASH)
    response = client.post(f"/api/v1/trash/{TRASH}/erase", json={"confirm": "erase", "reason": "client asked"})
    assert response.status_code == 202
    assert rpc.calls[-1][1]["p_action"] == "purge" and rpc.calls[-1][1]["p_reason"] == "client asked"


def test_restore_returns_the_item(client, rpc, audit_log):
    rpc.answers["restore_trash_item"] = {"id": TRASH, "kind": "draft", "item_id": ITEM, "title": "Notice", "snapshot": None}
    response = client.post(f"/api/v1/trash/{TRASH}/restore")
    assert response.status_code == 200 and "snapshot" not in response.json()
    assert audit_log[-1]["action"] == "RESTORE_ITEM"


def test_erasure_certificate_only_after_erasure(client, monkeypatch):
    item = {"id": TRASH, "kind": "transcript", "item_id": ITEM, "title": "Rent dispute", "deleted_by": USER.id,
            "requested_by": USER.id, "deleted_at": "2026-09-01T10:00:00+00:00", "purged_at": None,
            "purged_by": None, "snapshot_sha256": "ab" * 32, "reason": None}
    monkeypatch.setattr(safety_service, "get_trash_item", lambda db, tid: item)
    assert client.get(f"/api/v1/trash/{TRASH}/certificate").status_code == 409
    item["purged_at"] = "2026-10-01T21:00:00+00:00"
    monkeypatch.setattr(org_service, "list_members", lambda token, org: [{"user_id": USER.id, "full_name": "Adv. Rao", "email": None}])
    monkeypatch.setattr(org_service, "list_my_organizations", lambda token, uid: [{"id": ORG_ID, "name": "Rao & Co"}])
    response = client.get(f"/api/v1/trash/{TRASH}/certificate")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert "erasure-certificate-" in response.headers["content-disposition"]


def test_turning_on_intake_needs_confirmation_then_approval(client, rpc, audit_log):
    assert client.put("/api/v1/intake", json={"enabled": True}).status_code == 400
    rpc.answers["set_public_intake"] = error("approval_required", hint="Another owner or partner must approve turning on public intake")
    rpc.answers["request_approval"] = approval_row("enable_intake", "organization", ORG_ID)
    response = client.put("/api/v1/intake", json={"enabled": True, "confirm": True})
    assert response.status_code == 202
    assert rpc.calls[-1][1]["p_target_id"] == ORG_ID
    rpc.answers["set_public_intake"] = False
    response = client.put("/api/v1/intake", json={"enabled": False})
    assert response.json() == {"status": "updated", "enabled": False}
    assert audit_log[-1]["action"] == "CHANGE_PUBLIC_INTAKE"


def test_making_an_owner_needs_a_second_owner(client, rpc, monkeypatch, audit_log):
    member = "66666666-6666-6666-6666-666666666666"
    monkeypatch.setattr(org_service, "get_member", lambda token, org, uid: {"user_id": uid, "role": "partner"})
    monkeypatch.setattr(org_service, "count_owners", lambda token, org: 2)
    monkeypatch.setattr(org_service, "list_members", lambda token, org: [{"user_id": member, "full_name": "Meera", "email": None}])
    monkeypatch.setattr("app.routers.organizations.get_supabase_for_user", lambda *a: None)
    monkeypatch.setattr(org_service, "update_member_role", lambda *a: pytest.fail("changed without approval"))
    rpc.answers["request_approval"] = approval_row("make_owner", "organization_member", member)
    response = client.patch(f"/api/v1/organizations/{ORG_ID}/members/{member}", json={"role": "owner"})
    assert response.status_code == 202
    assert rpc.calls[-1][1]["p_target_label"] == "Make Meera an owner"
    # Adding someone straight in as owner isn't possible either.
    assert client.post(f"/api/v1/organizations/{ORG_ID}/members", json={"email": "x@y.in", "role": "owner"}).status_code == 409


def test_retention_job_audits_each_erasure(monkeypatch, audit_log):
    from app import worker

    rows = [{"id": TRASH, "org_id": ORG_ID, "kind": "draft", "item_id": ITEM, "title": "Notice", "snapshot_sha256": "cd" * 32}]
    monkeypatch.setattr(safety_service, "purge_expired", lambda db: rows)
    assert worker.purge_expired_trash(db=object()) == {"purged": 1}
    assert audit_log[-1]["action"] == "PURGE_EXPIRED_TRASH" and audit_log[-1]["metadata"]["sha256"] == "cd" * 32


# ============================================================================ consent before a consultation


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
def consent_required(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "consultation_consent_required", True)
    monkeypatch.setattr("app.services.anthropic_service.is_configured", lambda: True)


def test_without_consent_the_consultation_keeps_notes_only(consent_required, monkeypatch):
    from app.services import live_session, transcription_service

    async def no_transcriber(*a, **k):
        pytest.fail("audio reached speech-to-text without consent")

    monkeypatch.setattr(transcription_service, "create_transcriber", no_transcriber)
    socket = Socket()
    session = live_session.LiveConsultationSession(socket, USER, ORG_ID, "associate")

    async def scenario():
        await session._resolve_consent()
        await session._handle_audio(bytes(3200))
        await session._handle_audio(bytes(3200))

    asyncio.run(scenario())
    assert session.analysis_enabled is False and session.consent is None
    assert socket.sent[0]["type"] == "consent_required"
    assert [m.get("code") for m in socket.sent].count("consent_required") == 1  # warned once


def test_consent_turns_ai_on_and_is_remembered_on_the_case_thread(consent_required, monkeypatch, audit_log):
    from datetime import datetime, timedelta, timezone

    from app.services import live_session

    updates = []

    class Threads:
        def update(self, fields):
            updates.append(fields)
            return self

        def eq(self, *a):
            return self

        def execute(self):
            return SimpleNamespace(data=[{}])

    monkeypatch.setattr(live_session.LiveConsultationSession, "_db", lambda self: SimpleNamespace(table=lambda name: Threads()))
    socket = Socket()
    session = live_session.LiveConsultationSession(socket, USER, ORG_ID, "associate", thread_id="t-1")
    monkeypatch.setattr(memory_service, "get_thread", lambda db, tid: {"ai_consent_at": None})
    asyncio.run(session._resolve_consent())
    assert session.analysis_enabled is False
    asyncio.run(session._dispatch({"type": "consent", "method": "verbal"}))
    assert session.analysis_enabled is True and session.consent["method"] == "verbal"
    assert updates[0]["ai_consent_method"] == "verbal" and audit_log[-1]["action"] == "RECORD_CONSENT"

    # A later consultation on the same matter within 12 months doesn't ask again; after that it does.
    recent = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    monkeypatch.setattr(memory_service, "get_thread", lambda db, tid: {"ai_consent_at": recent, "ai_consent_method": "written"})
    later = live_session.LiveConsultationSession(Socket(), USER, ORG_ID, "associate", thread_id="t-1")
    asyncio.run(later._resolve_consent())
    assert later.analysis_enabled is True and later.consent["source"] == "case_thread"
    stale = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    monkeypatch.setattr(memory_service, "get_thread", lambda db, tid: {"ai_consent_at": stale})
    expired = live_session.LiveConsultationSession(Socket(), USER, ORG_ID, "associate", thread_id="t-1")
    asyncio.run(expired._resolve_consent())
    assert expired.consent is None and expired.analysis_enabled is False


def test_production_refuses_test_models(monkeypatch):
    from app.core.config import get_settings
    from app.services import anthropic_service

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_live_model", "gemma4:31b-cloud")
    monkeypatch.setattr(settings, "anthropic_base_url", "http://localhost:11434")
    assert anthropic_service.production_model_problems() == []  # development: fine
    monkeypatch.setattr(settings, "environment", "production")
    problems = anthropic_service.production_model_problems()
    assert any("ANTHROPIC_LIVE_MODEL" in p for p in problems) and any("local test gateway" in p for p in problems)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        with TestClient(app):
            pass
