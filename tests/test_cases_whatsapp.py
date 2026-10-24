"""Court case tracker (eCourts data, hearing reminders) and WhatsApp intake."""

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.services import ecourts_service, intake_guard, whatsapp_intake, whatsapp_service
from tests.conftest import ORG_ID

OWNER = "22222222-2222-2222-2222-222222222222"
NUMBER_ID = "109876543210"
CLIENT = "919812345678"
TODAY = date(2026, 10, 23)

PROVIDER_CASE = {
    "data": {
        "courtCaseData": {
            "caseNumber": "CC/1234/2026", "courtName": "JMFC Court No. 3, Pune", "caseStatus": "Pending",
            "petitioners": ["Ravi Sharma"], "respondents": ["Amit Joshi"], "nextHearingDate": "2026-10-25",
            "lastHearingDate": "12-09-2026", "judges": ["A. B. Patil"],
            "interimOrders": [{"orderDate": "2026-09-12", "orderUrl": "https://x/o1.pdf"}],
            "historyOfCaseHearings": [{"date": "2026-09-12", "purpose": "Appearance"}],
        },
        "entityInfo": {"nextDateOfHearing": "2026-10-25"},
    }
}


# ============================================================================ an in-memory Supabase


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload, self.opts = db, table, [], "select", None, {}
        self._order, self._limit = None, None

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: (r.get(col) or "") >= val)
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: (r.get(col) or "") <= val)
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

    def upsert(self, row, on_conflict="id", ignore_duplicates=False):
        self.op, self.payload, self.opts = "upsert", row, {"keys": on_conflict.split(","), "ignore": ignore_duplicates}
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        now = datetime.now(timezone.utc).isoformat()
        if self.op == "select":
            if self._order:
                hits = sorted(hits, key=lambda r: r.get(self._order[0]) or "", reverse=self._order[1])
            return SimpleNamespace(data=[dict(r) for r in hits[: self._limit]])
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), "created_at": now, **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.op == "upsert":
            keys = self.opts["keys"]
            found = next((r for r in rows if all(r.get(k) == self.payload.get(k) for k in keys)), None)
            if found:
                if self.opts["ignore"]:
                    return SimpleNamespace(data=[])
                found.update(self.payload)
                return SimpleNamespace(data=[dict(found)])
            defaults = {"status": "awaiting_consent", "agent_state": {}} if self.table == "whatsapp_conversations" else {}
            row = {"id": str(uuid.uuid4()), "created_at": now, **defaults, **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        for r in hits:
            r.update(self.payload)
        return SimpleNamespace(data=[dict(r) for r in hits])


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return Query(self.tables, name)


# ============================================================================ eCourts data


def test_provider_records_become_case_fields():
    fields = ecourts_service.from_provider(PROVIDER_CASE)
    assert fields["title"] == "Ravi Sharma v. Amit Joshi"
    assert (fields["next_hearing_date"], fields["last_hearing_date"]) == ("2026-10-25", "2026-09-12")
    assert fields["court_name"] == "JMFC Court No. 3, Pune" and fields["case_status"] == "Pending"
    assert fields["provider_data"]["orders"] == [{"date": "2026-09-12", "url": "https://x/o1.pdf"}]
    assert ecourts_service.normalize_cnr("mhpu-0100-1234-2026") == "MHPU010012342026"
    with pytest.raises(ValueError):
        ecourts_service.normalize_cnr("123")


def test_fetch_and_sync_use_the_provider_api(monkeypatch):
    monkeypatch.setattr(get_settings(), "ecourts_api_key", "eci_live_test")
    seen = []

    def provider(request: httpx.Request):
        seen.append((str(request.url), request.headers["authorization"]))
        if request.url.path.endswith("MHPU010012342026"):
            return httpx.Response(200, json=PROVIDER_CASE)
        return httpx.Response(404, json={})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            db = FakeDB(court_cases=[{"id": "c1", "cnr": "MHPU010012342026", "title": "Sharma cheque case"},
                                     {"id": "c2", "cnr": "MHPU019999992026", "title": "Other"}])
            ok = await ecourts_service.sync(db, db.tables["court_cases"][0], http_client=client)
            missing = await ecourts_service.sync(db, db.tables["court_cases"][1], http_client=client)
            return ok, missing

    ok, missing = asyncio.run(scenario())
    assert seen[0] == ("https://webapi.ecourtsindia.com/api/partner/case/MHPU010012342026", "Bearer eci_live_test")
    assert ok["title"] == "Sharma cheque case" and ok["next_hearing_date"] == "2026-10-25" and ok["sync_error"] is None
    assert missing["sync_error"] == "No case with this CNR"  # recorded on the case, not raised


def test_agenda_and_reminder_rules():
    cases = [
        {"id": "a", "next_hearing_date": "2026-10-23", "client_phone": "+919812345678", "reminded_for_date": None},
        {"id": "b", "next_hearing_date": "2026-10-25", "client_phone": "+919812345678", "reminded_for_date": "2026-10-25"},
        {"id": "c", "next_hearing_date": "2026-11-30", "client_phone": "+919812345678"},
        {"id": "d", "next_hearing_date": "2026-10-24", "client_phone": None},
        {"id": "e", "next_hearing_date": None},
    ]
    assert [c["id"] for c in ecourts_service.agenda(cases, TODAY, 7)] == ["a", "d", "b"]
    assert [c["id"] for c in cases if ecourts_service.needs_reminder(c, TODAY, 2)] == ["a"]


def test_daily_job_reminds_clients_once_on_whatsapp(monkeypatch):
    from app import worker

    sent, agendas = [], []

    async def send_template(number, to, template, params, http_client=None):
        sent.append((number, to, template, params))
        return "wamid.1"

    async def trigger(path, payload):
        agendas.append((path, payload["org_id"], [h["id"] for h in payload["hearings"]]))

    monkeypatch.setattr(whatsapp_service, "is_configured", lambda: True)
    monkeypatch.setattr(whatsapp_service, "send_template", send_template)
    monkeypatch.setattr(worker.n8n_service, "is_configured", lambda: True)
    monkeypatch.setattr(worker.n8n_service, "trigger_workflow", trigger)
    db = FakeDB(
        court_cases=[
            {"id": "c1", "org_id": ORG_ID, "title": "Sharma v. Joshi", "court_name": "JMFC Pune", "next_hearing_date": "2026-10-24",
             "client_phone": "+919812345678", "reminded_for_date": None},
            {"id": "c2", "org_id": ORG_ID, "title": "Later", "next_hearing_date": "2026-12-01", "client_phone": "+919812345678"},
        ],
        whatsapp_numbers=[{"phone_number_id": NUMBER_ID, "org_id": ORG_ID, "enabled": True}],
    )
    first = asyncio.run(worker.send_hearing_reminders(db, TODAY))
    second = asyncio.run(worker.send_hearing_reminders(db, TODAY))
    assert first == {"hearings": 1, "synced": 0, "reminded": 1} and second["reminded"] == 0
    assert sent == [(NUMBER_ID, "919812345678", "hearing_reminder", ["Sharma v. Joshi", "24 October 2026", "JMFC Pune"])]
    assert agendas[0] == ("hearings-agenda", ORG_ID, ["c1"])


def test_cases_api(monkeypatch, audit_log):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=OWNER, email="a@b.in", access_token="t")
    db = FakeDB(court_cases=[])
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    try:
        client = TestClient(app)
        created = client.post("/api/v1/cases", json={"title": "Bail - State v. Kumar", "next_hearing_date": "2026-10-24",
                                                     "client_phone": "98123 45678", "cnr": "mhpu010012342026"})
        assert created.status_code == 201, created.text
        assert created.json()["client_phone"] == "+919812345678" and created.json()["cnr"] == "MHPU010012342026"
        assert audit_log[-1]["action"] == "ADD_COURT_CASE"
        assert client.post("/api/v1/cases", json={"cnr": "bad"}).status_code == 422
        assert client.post("/api/v1/cases", json={}).status_code == 422  # no title, no provider
        assert client.post(f"/api/v1/cases/{created.json()['id']}/sync").status_code == 503  # no ECOURTS_API_KEY
    finally:
        app.dependency_overrides.clear()


# ============================================================================ WhatsApp


def signed(payload: dict, secret="app-secret"):
    body = json.dumps(payload).encode()
    return body, "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def message(text, mid, kind="text"):
    msg = {"from": CLIENT, "id": mid, "timestamp": "1", "type": kind}
    msg.update({"text": {"body": text}} if kind == "text" else {"audio": {"id": "media-1"}})
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": NUMBER_ID},
                                              "contacts": [{"wa_id": CLIENT, "profile": {"name": "Ravi"}}], "messages": [msg]}}]}]}


def test_webhook_handshake_and_signatures(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_verify_token", "verify-me")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "app-secret")
    handled = []

    async def handle(m):
        handled.append(m)

    monkeypatch.setattr(whatsapp_intake, "handle", handle)
    client = TestClient(app)
    ok = client.get("/api/v1/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert client.get("/api/v1/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403

    body, signature = signed(message("Hello", "wamid.A"))
    assert client.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": signature}).status_code == 200
    assert client.post("/api/v1/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=forged"}).status_code == 403
    assert [(m.wa_id, m.text, m.name) for m in handled] == [(CLIENT, "Hello", "Ravi")]


@pytest.fixture
def whatsapp(monkeypatch, fake_agents):
    outbox = []

    async def send_text(number_id, to, text, http_client=None):
        outbox.append(text)
        return f"wamid.out{len(outbox)}"

    async def download_media(media_id, http_client=None):
        return b"ogg-bytes"

    async def transcribe_voice_note(audio):
        return "mera account number 1234 5678 9012 hai"

    async def no_precedents(*a, **k):
        return []

    monkeypatch.setattr(whatsapp_service, "send_text", send_text)
    monkeypatch.setattr(whatsapp_service, "download_media", download_media)
    monkeypatch.setattr(whatsapp_service, "transcribe_voice_note", transcribe_voice_note)
    monkeypatch.setattr("app.services.rag_service.aretrieve_relevant_precedents", no_precedents)
    fake_agents.outputs.message = "Samajh gaya. Kya aapke paas rent agreement hai?"
    db = FakeDB(
        organizations=[{"id": ORG_ID, "public_intake_enabled": True}],
        whatsapp_numbers=[{"phone_number_id": NUMBER_ID, "org_id": ORG_ID, "owner_user_id": OWNER, "enabled": True,
                           "jurisdiction": "IN", "greeting": "Namaste from Sharma & Associates."}],
        legal_authorities=[],
    )

    def run(*incoming):
        for i in incoming:
            asyncio.run(whatsapp_intake.handle(i, db))

    return SimpleNamespace(db=db, outbox=outbox, run=run, agents=fake_agents)


def parsed(text, mid, kind="text"):
    return whatsapp_service.parse_messages(message(text, mid, kind))[0]


def test_nothing_reaches_the_ai_before_consent(whatsapp):
    whatsapp.run(parsed("Mera landlord deposit nahi de raha", "m1"))
    assert "Namaste from Sharma & Associates." in whatsapp.outbox[0] and "Reply *YES*" in whatsapp.outbox[0]
    assert whatsapp.agents.calls["intake"] == []
    conversation = whatsapp.db.tables["whatsapp_conversations"][0]
    assert conversation["status"] == "awaiting_consent" and conversation["client_name"] == "Ravi"


def test_intake_after_consent_masks_pii_and_keeps_a_case_file(whatsapp):
    whatsapp.run(parsed("Hello", "m1"), parsed("Haan", "m2"),
                 parsed("Mere landlord ne Pune mein 50,000 ka deposit rakh liya, mera PAN ABCDE1234F hai", "m3"),
                 parsed("", "m4", kind="audio"))
    conversation = whatsapp.db.tables["whatsapp_conversations"][0]
    assert conversation["status"] == "intake" and conversation["consent_at"]
    assert whatsapp.outbox[1].startswith("Thank you. Please tell me about your legal matter")
    assert whatsapp.outbox[2] == whatsapp.agents.outputs.message  # the AI's reply went to the client

    # The agents never saw the PAN or the account number from the voice note, nor the pre-consent "Hello".
    sent_to_ai = whatsapp.agents.calls["intake"][-1]["transcript_history"]
    assert "ABCDE1234F" not in sent_to_ai, sent_to_ai
    assert "1234 5678 9012" not in sent_to_ai, sent_to_ai
    assert "Hello" not in sent_to_ai, sent_to_ai
    assert "[TAX_ID]" in sent_to_ai and "[voice note]" in sent_to_ai

    transcript = whatsapp.db.tables["transcripts"][0]
    assert transcript["source"] == "whatsapp" and transcript["user_id"] == OWNER and transcript["org_id"] == ORG_ID
    assert "Client: Mere landlord ne Pune" in transcript["content"] and "ABCDE1234F" in transcript["content"]  # the firm's record
    assert transcript["metadata"]["analysis"]["key_facts"]
    assert conversation["transcript_id"] == transcript["id"]


def test_retried_webhooks_are_ignored_and_lawyer_takes_over(whatsapp):
    whatsapp.run(parsed("Hi", "m1"), parsed("yes", "m2"), parsed("Deposit dispute", "m3"), parsed("Deposit dispute", "m3"))
    assert len(whatsapp.agents.calls["intake"]) == 1  # m3 delivered twice, handled once

    whatsapp.run(parsed("Lawyer", "m4"), parsed("Any update?", "m5"))
    conversation = whatsapp.db.tables["whatsapp_conversations"][0]
    assert conversation["status"] == "lawyer" and whatsapp.outbox[-1] == whatsapp_intake.HANDED_OFF
    assert len(whatsapp.agents.calls["intake"]) == 1  # the AI stays quiet once a lawyer is involved

    asyncio.run(whatsapp_intake.reply_as_lawyer(conversation, "Main kal call karunga.", whatsapp.db))
    senders = [m["sender"] for m in whatsapp.db.tables["whatsapp_messages"]]
    assert senders[-1] == "lawyer" and whatsapp.outbox[-1] == "Main kal call karunga."


def test_without_public_intake_the_lawyer_answers(whatsapp):
    whatsapp.db.tables["organizations"][0]["public_intake_enabled"] = False
    whatsapp.run(parsed("Mera deposit nahi mila", "m1"))
    conversation = whatsapp.db.tables["whatsapp_conversations"][0]
    assert conversation["status"] == "lawyer" and whatsapp.outbox == [whatsapp_intake.HANDED_OFF]
    assert whatsapp.agents.calls["intake"] == []


def test_replies_with_legal_substance_wait_for_a_lawyer(whatsapp):
    whatsapp.agents.outputs.message = "Aap legal notice bhej sakte hain. Kya aapke paas rent agreement hai?"
    whatsapp.run(parsed("Hi", "m1"), parsed("yes", "m2"), parsed("Deposit nahi mila", "m3"), parsed("Agreement hai", "m4"))
    held = [m for m in whatsapp.db.tables["whatsapp_messages"] if m.get("status") == "pending"]
    assert len(held) == 2 and held[0]["hold_reasons"] == ["legal_substance"]
    assert all("notice bhej" not in text for text in whatsapp.outbox)  # nothing with legal substance went out
    assert whatsapp.outbox.count(intake_guard.HOLDING_MESSAGE) == 1  # told once, not after every message
    # The client never saw the held replies, so the AI doesn't think it said them.
    assert "notice bhej" not in whatsapp.agents.calls["intake"][-1]["transcript_history"]

    conversation = whatsapp.db.tables["whatsapp_conversations"][0]
    sent = asyncio.run(whatsapp_intake.settle_held_reply(conversation, held[0]["id"], OWNER, send=True,
                                                         text="Main aapko kal call karke bataunga.", db=whatsapp.db))
    assert sent["status"] == "sent" and whatsapp.outbox[-1] == "Main aapko kal call karke bataunga."
    stored = next(m for m in whatsapp.db.tables["whatsapp_messages"] if m["id"] == held[0]["id"])
    assert stored["sender"] == "lawyer" and stored["reviewed_by"] == OWNER
    with pytest.raises(LookupError):  # already handled
        asyncio.run(whatsapp_intake.settle_held_reply(conversation, held[0]["id"], OWNER, send=True, db=whatsapp.db))
    discarded = asyncio.run(whatsapp_intake.settle_held_reply(conversation, held[1]["id"], OWNER, send=False, db=whatsapp.db))
    assert discarded["status"] == "discarded" and len(whatsapp.outbox) == 4
