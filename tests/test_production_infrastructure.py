"""Phase 7: Stripe billing and metering, Twilio phone intake, ARQ background jobs, rate
limiting and Prometheus metrics.

Supabase is replaced by a small in-memory table store; Stripe, Twilio, Deepgram and Claude
by fakes. Background jobs run through a real ARQ worker, on Redis when TEST_REDIS_URL is
set (CI) and on fakeredis otherwise.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import time
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.core import metrics, rate_limiter
from app.core.config import get_settings
from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.models.analysis import ConsultationSummary
from app.services import (
    anthropic_service,
    n8n_service,
    queue_service,
    stripe_service,
    transcription_service,
    tts_service,
    twilio_service,
)
from tests.conftest import ORG_ID

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="owner@acme.law", access_token="good-token")
OWNER_ID = "22222222-2222-2222-2222-222222222222"
WEBHOOK_SECRET = "whsec_test"
TWILIO_TOKEN = "twilio-test-auth-token"
NUMBER = "+14155550100"


# ============================================================================ in-memory Supabase


class FakeQuery:
    def __init__(self, db: "FakeDB", table: str):
        self.db, self.table = db, table
        self.filters, self.op, self.payload, self.opts, self._limit = [], "select", None, {}, None

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self.filters.append(lambda row: row.get(column) == value)
        return self

    def gte(self, column, value):
        self.filters.append(lambda row: (row.get(column) or "") >= value)
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self.op, self.payload = "insert", dict(row)
        return self

    def upsert(self, row, on_conflict="id", ignore_duplicates=False):
        self.op, self.payload, self.opts = "upsert", dict(row), {"key": on_conflict, "ignore": ignore_duplicates}
        return self

    def update(self, fields):
        self.op, self.payload = "update", dict(fields)
        return self

    def delete(self):
        self.op = "delete"
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        matching = [row for row in rows if all(check(row) for check in self.filters)]
        match self.op:
            case "select":
                data = [dict(r) for r in matching[: self._limit]]
            case "insert":
                row = {"id": str(uuid.uuid4()), **self.payload}
                rows.append(row)
                data = [dict(row)]
            case "upsert":
                key = self.opts["key"]
                existing = [r for r in rows if r.get(key) == self.payload[key]]
                if existing and self.opts["ignore"]:
                    data = []
                elif existing:
                    existing[0].update(self.payload)
                    data = [dict(existing[0])]
                else:
                    rows.append(dict(self.payload))
                    data = [dict(self.payload)]
            case "update":
                for row in matching:
                    row.update(self.payload)
                data = [dict(r) for r in matching]
            case "delete":
                for row in matching:
                    rows.remove(row)
                data = matching
        return SimpleNamespace(data=data)


class FakeBucket:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def upload(self, path, data, options=None):
        self.db.files[(self.name, path)] = data


class FakeDB:
    def __init__(self, **tables):
        self.tables = {name: [dict(r) for r in rows] for name, rows in tables.items()}
        self.files = {}
        self.storage = SimpleNamespace(from_=lambda name: FakeBucket(self, name))

    def table(self, name):
        return FakeQuery(self, name)

    def rows(self, name):
        return self.tables.get(name, [])


# ============================================================================ Stripe webhooks


def signed(event: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, str]:
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


def event(event_type: str, obj: dict) -> dict:
    return {"id": f"evt_{uuid.uuid4().hex[:12]}", "type": event_type, "data": {"object": obj}}


@pytest.fixture
def billing_db(monkeypatch):
    db = FakeDB(organizations=[{"id": ORG_ID, "plan_tier": "free"}])
    monkeypatch.setattr(stripe_service, "get_supabase_admin", lambda: db)
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_price_pro", "price_pro")
    monkeypatch.setattr(settings, "stripe_price_starter", "price_starter")
    return db


def post_webhook(client, evt, secret=WEBHOOK_SECRET):
    payload, header = signed(evt, secret)
    return client.post("/api/v1/billing/webhook", content=payload, headers={"Stripe-Signature": header})


def test_stripe_webhooks_drive_the_org_subscription_tier(billing_db):
    client = TestClient(app)
    now = int(time.time())
    checkout = event("checkout.session.completed", {
        "id": "cs_1", "client_reference_id": ORG_ID, "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"org_id": ORG_ID, "tier": "pro"},
    })
    assert post_webhook(client, checkout).json() == {"received": True, "outcome": "checkout linked"}

    # Newer API versions: the period lives on the subscription item, the tier comes from the price.
    subscription = {
        "id": "sub_1", "customer": "cus_1", "status": "active", "metadata": {},
        "items": {"data": [{"price": {"id": "price_pro"}, "current_period_start": now, "current_period_end": now + 30 * 86400}]},
    }
    assert post_webhook(client, event("customer.subscription.updated", subscription)).json()["outcome"] == "subscription active"
    account = billing_db.rows("billing_accounts")[0]
    assert (account["tier"], account["status"], account["included_minutes"], account["stripe_customer_id"]) == (
        "pro", "active", get_settings().billing_pro_minutes, "cus_1"
    )
    assert account["current_period_end"] is not None
    assert billing_db.rows("organizations")[0]["plan_tier"] == "pro"

    invoice = event("invoice.payment_succeeded", {
        "id": "in_1", "customer": "cus_1", "created": now,
        "parent": {"subscription_details": {"subscription": "sub_1"}},
        "lines": {"data": [{"period": {"start": now, "end": now + 30 * 86400}}]},
    })
    assert post_webhook(client, invoice).json()["outcome"] == "payment recorded"
    assert billing_db.rows("billing_accounts")[0]["last_payment_at"] is not None

    payment = event("payment_intent.succeeded", {"id": "pi_1", "customer": "cus_1", "created": now + 5})
    assert post_webhook(client, payment).json()["outcome"] == "payment recorded"

    # Redelivery of an event is a no-op.
    assert post_webhook(client, invoice).json()["outcome"] == "duplicate"

    deleted = event("customer.subscription.deleted", {**subscription, "status": "canceled"})
    assert post_webhook(client, deleted).json()["outcome"] == "subscription canceled"
    account = billing_db.rows("billing_accounts")[0]
    assert (account["status"], account["included_minutes"]) == ("canceled", 0)
    assert billing_db.rows("organizations")[0]["plan_tier"] == "free"


def test_stripe_webhook_rejects_bad_signatures_and_ignores_unknown_orgs(billing_db):
    client = TestClient(app)
    response = post_webhook(client, event("invoice.payment_succeeded", {"customer": "cus_x"}), secret="whsec_wrong")
    assert response.status_code == 400
    assert post_webhook(client, event("invoice.payment_succeeded", {"customer": "cus_unknown"})).json()["outcome"] == (
        "ignored: unknown organization"
    )
    assert post_webhook(client, event("charge.refunded", {})).json()["outcome"] == "ignored"
    assert billing_db.rows("billing_accounts") == []


def test_a_failed_event_can_be_retried(billing_db, monkeypatch):
    evt = event("customer.subscription.updated", {"id": "sub_1", "customer": "cus_1", "status": "active",
                                                   "metadata": {"org_id": ORG_ID, "tier": "pro"}})
    calls = {"n": 0}
    real_upsert = stripe_service._Accounts.upsert

    def flaky(self, org_id, fields):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return real_upsert(self, org_id, fields)

    monkeypatch.setattr(stripe_service._Accounts, "upsert", flaky)
    with pytest.raises(RuntimeError):
        stripe_service.handle_event(evt, billing_db)
    assert billing_db.rows("stripe_events") == []  # forgotten, so Stripe's retry is processed
    assert stripe_service.handle_event(evt, billing_db) == "subscription active"


# ============================================================================ checkout and usage


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_owners_start_checkout_others_cannot(client, org_role, audit_log, monkeypatch):
    created = []

    async def create_checkout_session(org_id, tier, *, customer_id, email):
        created.append((org_id, tier, customer_id, email))
        return {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}

    monkeypatch.setattr(stripe_service, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_service, "get_account", lambda db: {"stripe_customer_id": "cus_1"})
    monkeypatch.setattr(stripe_service, "create_checkout_session", create_checkout_session)

    response = client.post("/api/v1/billing/checkout-session", json={"tier": "pro"})
    assert response.status_code == 200
    assert response.json()["url"].startswith("https://checkout.stripe.com/")
    assert created == [(ORG_ID, "pro", "cus_1", USER.email)]
    assert audit_log[-1]["action"] == "START_CHECKOUT"

    assert client.post("/api/v1/billing/checkout-session", json={"tier": "platinum"}).status_code == 422
    org_role("partner")
    assert client.post("/api/v1/billing/checkout-session", json={"tier": "pro"}).status_code == 403


def test_checkout_without_stripe_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(stripe_service, "is_configured", lambda: False)
    assert client.post("/api/v1/billing/checkout-session", json={"tier": "starter"}).status_code == 503


def test_audio_usage_is_metered_and_reported_to_stripe_once(monkeypatch):
    from datetime import datetime, timedelta, timezone

    db = FakeDB(billing_accounts=[{"org_id": ORG_ID, "stripe_customer_id": "cus_1", "tier": "starter",
                                   "status": "active", "included_minutes": 300}])
    reported = []
    fake_stripe = SimpleNamespace(v1=SimpleNamespace(billing=SimpleNamespace(
        meter_events=SimpleNamespace(create=lambda params: reported.append(params)))))
    monkeypatch.setattr(stripe_service, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_service, "_client", lambda: fake_stripe)

    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    usage = stripe_service.record_audio_usage(ORG_ID, USER.id, "sess-1", "webrtc", start, start + timedelta(seconds=61), db=db)
    assert (usage.billed_minutes, usage.reported_to_stripe) == (2, True)  # every started minute counts
    assert reported == [{
        "event_name": "audio_minutes",
        "payload": {"stripe_customer_id": "cus_1", "value": "2"},
        "identifier": "sess-1",
        "timestamp": int((start + timedelta(seconds=61)).timestamp()),
    }]
    row = db.rows("audio_usage")[0]
    assert (row["duration_seconds"], row["billed_minutes"], row["transport"]) == (61, 2, "webrtc")
    assert row["stripe_reported_at"] is not None

    # The same session again (e.g. a retried finalize) isn't stored twice; Stripe de-duplicates on the identifier.
    stripe_service.record_audio_usage(ORG_ID, USER.id, "sess-1", "webrtc", start, start + timedelta(seconds=61), db=db)
    assert len(db.rows("audio_usage")) == 1


def test_usage_endpoint_reports_remaining_minutes(client, monkeypatch):
    real_get_usage = stripe_service.get_usage

    def get_usage(db):
        return real_get_usage(FakeDB(
            billing_accounts=[{"org_id": ORG_ID, "tier": "starter", "status": "active", "included_minutes": 300,
                               "current_period_start": "2026-10-01T00:00:00+00:00"}],
            audio_usage=[
                {"started_at": "2026-10-03T10:00:00+00:00", "billed_minutes": 120},
                {"started_at": "2026-10-09T10:00:00+00:00", "billed_minutes": 45},
                {"started_at": "2026-09-20T10:00:00+00:00", "billed_minutes": 999},  # previous period
            ],
        ))

    monkeypatch.setattr(stripe_service, "get_usage", get_usage)
    body = client.get("/api/v1/billing/usage").json()
    assert (body["tier"], body["active"], body["used_minutes"], body["remaining_minutes"], body["overage_minutes"]) == (
        "starter", True, 165, 135, 0
    )


def test_usage_is_for_owners_and_partners(client, org_role):
    org_role("associate")
    assert client.get("/api/v1/billing/usage").status_code == 403


# ============================================================================ Twilio: audio and TwiML


def test_mulaw_codec_matches_g711():
    # Reference points from ITU-T G.711: silence is 0xFF, full scale is 0x80 / 0x00.
    assert twilio_service.pcm16_to_mulaw(np.array([0, 32767, -32768], dtype="<i2").tobytes()) == bytes([0xFF, 0x80, 0x00])
    assert twilio_service.mulaw_to_pcm16(bytes([0xFF, 0x7F])) == np.array([0, 0], dtype="<i2").tobytes()
    assert np.frombuffer(twilio_service.mulaw_to_pcm16(bytes([0x80, 0x00])), "<i2").tolist() == [32124, -32124]

    # Every byte decodes and re-encodes to itself (0x7F, "negative zero", encodes as 0xFF).
    all_bytes = bytes(range(256))
    round_trip = twilio_service.pcm16_to_mulaw(twilio_service.mulaw_to_pcm16(all_bytes))
    assert [i for i in range(256) if round_trip[i] != i] == [0x7F]

    # A tone survives the round trip with telephone quality (mu-law SNR is ~38 dB).
    t = np.arange(8000) / 8000
    tone = (np.sin(2 * math.pi * 440 * t) * 12000).astype("<i2")
    decoded = np.frombuffer(twilio_service.mulaw_to_pcm16(twilio_service.pcm16_to_mulaw(tone.tobytes())), "<i2")
    snr = 10 * math.log10(np.sum(tone.astype(float) ** 2) / np.sum((tone.astype(float) - decoded) ** 2))
    assert snr > 30


def test_mulaw_codec_matches_the_reference_implementation():
    audioop = pytest.importorskip("audioop")  # removed from the standard library in Python 3.13
    pcm = np.arange(-32768, 32768, dtype="<i2").tobytes()
    assert twilio_service.pcm16_to_mulaw(pcm) == audioop.lin2ulaw(pcm, 2)
    assert twilio_service.mulaw_to_pcm16(bytes(range(256))) == audioop.ulaw2lin(bytes(range(256)), 2)


def test_media_messages_are_twilio_shaped():
    message = json.loads(twilio_service.media_message("MZ1", b"\xff" * 160))
    assert message == {"event": "media", "streamSid": "MZ1", "media": {"payload": base64.b64encode(b"\xff" * 160).decode()}}
    assert json.loads(twilio_service.clear_message("MZ1")) == {"event": "clear", "streamSid": "MZ1"}
    assert [len(f) for f in twilio_service.frames(b"x" * 400)] == [160, 160, 80]


@pytest.fixture
def twilio(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "twilio_auth_token", TWILIO_TOKEN)
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.com")
    numbers = {NUMBER: {"phone_number": NUMBER, "org_id": ORG_ID, "owner_user_id": OWNER_ID, "practice_area_id": None,
                        "jurisdiction": "US-CA", "greeting": "Hello, this is the intake assistant.", "enabled": True}}
    monkeypatch.setattr(twilio_service, "find_number", lambda number, db=None: numbers.get(number))
    intake = {"enabled": True}
    monkeypatch.setattr("app.routers.telephony.get_supabase_admin", lambda: None)
    monkeypatch.setattr("app.services.safety_service.public_intake_enabled", lambda db, org_id: intake["enabled"])
    numbers["_intake"] = intake
    return numbers


def twilio_post(client, params, *, signature=None, url="https://api.example.com/api/v1/telephony/voice/incoming"):
    signature = signature or RequestValidator(TWILIO_TOKEN).compute_signature(url, params)
    return client.post("/api/v1/telephony/voice/incoming", data=params, headers={"X-Twilio-Signature": signature})


def test_incoming_call_connects_a_media_stream(twilio):
    params = {"CallSid": "CA123", "From": "+14155559999", "To": NUMBER, "AccountSid": "AC1"}
    response = twilio_post(TestClient(app), params)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    xml = response.text
    assert '<Connect><Stream url="wss://api.example.com/api/v1/ws/telephony">' in xml
    assert '<Parameter name="caller" value="+14155559999"' in xml
    token = xml.split('<Parameter name="token" value="')[1].split('"')[0]
    assert twilio_service.verify_stream_token(token) == twilio_service.StreamClaims("CA123", NUMBER)


def test_incoming_call_requires_twilios_signature(twilio):
    params = {"CallSid": "CA123", "From": "+14155559999", "To": NUMBER}
    assert twilio_post(TestClient(app), params, signature="forged").status_code == 403


def test_calls_are_declined_while_public_intake_is_off(twilio):
    twilio["_intake"]["enabled"] = False
    response = twilio_post(TestClient(app), {"CallSid": "CA8", "From": "+14155559999", "To": NUMBER})
    assert "<Say>" in response.text and "<Hangup />" in response.text and "<Stream" not in response.text


def test_phone_replies_with_legal_substance_are_held_for_the_lawyer():
    from app.services import intake_guard
    from app.services.telephony_session import TelephonySession

    session = SimpleNamespace(held_replies=[], masker=SimpleNamespace(unmask=lambda text: text))
    ask = "Thank you. When did your landlord ask you to leave?"
    assert TelephonySession._public_reply(session, ask) == ask
    advice = "You can file a complaint within 30 days. Did you keep the receipts?"
    assert TelephonySession._public_reply(session, advice) == intake_guard.HOLDING_LINE
    assert session.held_replies[0]["draft"] == advice and "deadline_or_amount" in session.held_replies[0]["reasons"]


def test_calls_to_unconfigured_numbers_are_declined(twilio):
    response = twilio_post(TestClient(app), {"CallSid": "CA9", "From": "+14155559999", "To": "+14155550199"})
    assert "<Say>" in response.text and "<Hangup />" in response.text and "<Stream" not in response.text


def test_stream_tokens_reject_tampering_and_expiry(twilio):
    token = twilio_service.create_stream_token("CA1", NUMBER)
    body, signature = token.split(".")
    forged_body = base64.urlsafe_b64encode(json.dumps({"c": "CA1", "n": "+14155550111", "e": 9_999_999_999}).encode()).decode().rstrip("=")
    assert twilio_service.verify_stream_token(f"{forged_body}.{signature}") is None
    assert twilio_service.verify_stream_token(twilio_service.create_stream_token("CA1", NUMBER, ttl_seconds=-1)) is None
    assert twilio_service.verify_stream_token("garbage") is None


# ============================================================================ Twilio: a whole call


class PhoneTranscriber:
    instances: list["PhoneTranscriber"] = []

    def __init__(self, audio_format, on_final, on_interim, on_error):
        self.audio_format, self.on_final = audio_format, on_final
        self.audio = b""
        self.failed = False
        PhoneTranscriber.instances.append(self)

    async def feed(self, audio: bytes) -> None:
        first = not self.audio
        self.audio += audio
        if first:
            await self.on_final("My landlord kept my deposit, my card is 4111 1111 1111 1111", "Speaker 0")

    async def finalize(self):
        pass

    async def close(self):
        pass


def tone_mulaw(seconds: float) -> bytes:
    t = np.arange(int(8000 * seconds)) / 8000
    return twilio_service.pcm16_to_mulaw((np.sin(2 * math.pi * 300 * t) * 8000).astype("<i2").tobytes())


def test_a_phone_call_runs_through_speech_agents_and_voice(twilio, fake_agents, audit_log, monkeypatch):
    from app.services import telephony_session

    PhoneTranscriber.instances.clear()
    fake_agents.outputs.message = "Thank you. When were you fired, and do you have a written contract?"
    spoken, saved, metered = [], [], []
    db = FakeDB()

    async def stream_speech(text, sample_rate=48000, http_client=None, model=None):
        spoken.append((tts_service.speakable(text), sample_rate))
        t = np.arange(int(sample_rate * 0.1)) / sample_rate
        yield (np.sin(2 * math.pi * 200 * t) * 6000).astype("<i2").tobytes()

    async def create_transcriber(audio_format, on_final, on_interim, on_error):
        return PhoneTranscriber(audio_format, on_final, on_interim, on_error)

    async def summarize(transcript, analysis, **context):
        saved.append(transcript)  # what Claude would receive
        return ConsultationSummary(title="Deposit dispute", summary="Caller's landlord kept the deposit.")

    async def record_usage(org_id, user_id, session_id, transport, started_at, ended_at, duration_seconds=None):
        metered.append({"org_id": org_id, "user_id": user_id, "transport": transport, "seconds": duration_seconds})
        return stripe_service.UsageRecord(session_id, 1, False)

    monkeypatch.setattr(tts_service, "is_configured", lambda: True)
    monkeypatch.setattr(tts_service, "stream_speech", stream_speech)
    monkeypatch.setattr(transcription_service, "create_transcriber", create_transcriber)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(n8n_service, "is_configured", lambda: False)
    monkeypatch.setattr(stripe_service, "arecord_audio_usage", record_usage)
    monkeypatch.setattr(telephony_session, "get_supabase_admin", lambda: db)
    monkeypatch.setattr(get_settings(), "conversation_debounce_seconds", 0.05)
    completed = REGISTRY.get_sample_value("telephony_calls_total", {"outcome": "completed"}) or 0

    token = twilio_service.create_stream_token("CA42", NUMBER)
    outbound = []
    with TestClient(app).websocket_connect("/api/v1/ws/telephony") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call"}))
        ws.send_text(json.dumps({"event": "start", "streamSid": "MZ42", "start": {
            "streamSid": "MZ42", "callSid": "CA42", "customParameters": {"token": token, "caller": "+14155559999"},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        }}))
        audio = tone_mulaw(0.2)
        for frame in twilio_service.frames(audio):
            ws.send_text(json.dumps({"event": "media", "streamSid": "MZ42",
                                     "media": {"track": "inbound", "payload": base64.b64encode(frame).decode()}}))
        # Greeting, then the AI's reply: wait for the second reply's end mark.
        while True:
            message = json.loads(ws.receive_text())
            outbound.append(message)
            if message["event"] == "mark" and message["mark"]["name"] == "reply-2":
                break
        ws.send_text(json.dumps({"event": "stop", "streamSid": "MZ42"}))
        try:
            while True:
                outbound.append(json.loads(ws.receive_text()))
        except WebSocketDisconnect:
            pass

    # Inbound mu-law became 8 kHz linear PCM for speech-to-text.
    transcriber = PhoneTranscriber.instances[0]
    assert transcriber.audio_format == transcription_service.AudioFormat("linear16", 8000, 1)
    assert transcriber.audio == twilio_service.mulaw_to_pcm16(audio)

    # The caller heard the greeting and the agents' reply, as 8 kHz mu-law in Twilio frames.
    assert spoken[0] == (f"Hello, this is the intake assistant. {telephony_session.PHONE_NOTICE}", 8000)  # the AI and recording are announced
    assert spoken[1][0] == fake_agents.outputs.message
    media = [m for m in outbound if m["event"] == "media"]
    assert media and all(m["streamSid"] == "MZ42" for m in media)
    assert all(len(base64.b64decode(m["media"]["payload"])) <= 160 for m in media)
    assert sum(len(base64.b64decode(m["media"]["payload"])) for m in media) == 2 * 800  # 2 x 0.1 s at 8 kHz

    # The agents only ever saw the masked card number.
    assert "4111" not in fake_agents.calls["intake"][0]["current_chunk"]
    assert "[CARD_NUMBER]" in saved[0]

    # The call is saved for the number's owner in its org, and its minutes are metered.
    transcript = db.rows("transcripts")[0]
    assert (transcript["user_id"], transcript["org_id"], transcript["source"]) == (OWNER_ID, ORG_ID, "phone")
    assert "Caller: My landlord kept my deposit" in transcript["content"]
    assert transcript["metadata"]["client_metadata"] == {"channel": "phone", "call_sid": "CA42",
                                                         "caller": "+14155559999", "dialled": NUMBER, "held_replies": []}
    assert transcript["metadata"]["jurisdiction"] == "US-CA"
    assert [(m["org_id"], m["user_id"], m["transport"]) for m in metered] == [(ORG_ID, OWNER_ID, "telephony")]
    assert 0 <= metered[0]["seconds"] < 5  # the streamed audio, not the whole call
    assert REGISTRY.get_sample_value("telephony_calls_total", {"outcome": "completed"}) == completed + 1
    assert REGISTRY.get_sample_value("telephony_response_latency_seconds_count") >= 1


def test_media_streams_without_a_valid_token_are_refused(twilio):
    with TestClient(app).websocket_connect("/api/v1/ws/telephony") as ws:
        ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1",
                                                              "customParameters": {"token": "forged.token"}}}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008

    token = twilio_service.create_stream_token("CA-other", NUMBER)  # issued for another call
    with TestClient(app).websocket_connect("/api/v1/ws/telephony") as ws:
        ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1",
                                                              "customParameters": {"token": token}}}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


# ============================================================================ background jobs (ARQ)


@pytest.fixture
def arq_redis(monkeypatch):
    """An ARQ Redis pool: real Redis if TEST_REDIS_URL is set, else fakeredis."""
    from arq.connections import ArqRedis

    url = os.environ.get("TEST_REDIS_URL")
    if url:
        from redis.asyncio import ConnectionPool

        def make():
            return ArqRedis(connection_pool=ConnectionPool.from_url(url))
    else:
        fakeredis = pytest.importorskip("fakeredis")
        from fakeredis import aioredis
        from redis.asyncio import ConnectionPool

        server = fakeredis.FakeServer()

        def make():
            return ArqRedis(connection_pool=ConnectionPool(connection_class=aioredis.FakeConnection, server=server))

        async def no_info(*args, **kwargs):  # fakeredis has no INFO command
            pass

        monkeypatch.setattr("arq.worker.log_redis_info", no_info)
    monkeypatch.setattr(get_settings(), "redis_url", url or "redis://fake")
    return make


async def run_worker(pool):
    from arq.worker import Worker

    from app.worker import WorkerSettings

    worker = Worker(functions=WorkerSettings.functions, redis_pool=pool, burst=True, poll_delay=0.01,
                    queue_name=queue_service.QUEUE_NAME, handle_signals=False, keep_result=60)
    await worker.main()  # burst: returns once the queue is empty (close() uses SIGUSR1, absent on Windows)


def test_jobs_are_queued_run_and_visible_only_to_their_owner(arq_redis, monkeypatch):
    import app.worker as worker_module

    exported = []
    monkeypatch.setattr(worker_module, "generate_pdf_report",
                        lambda transcript_id, user_id: exported.append((transcript_id, user_id)) or
                        {"path": f"{ORG_ID}/{transcript_id}.pdf", "filename": "report.pdf", "size_bytes": 1234})

    async def scenario():
        pool = arq_redis()
        if os.environ.get("TEST_REDIS_URL"):
            await pool.flushdb()
        monkeypatch.setattr(queue_service, "_pool", pool)
        job_id = await queue_service.enqueue("task_generate_pdf_report", transcript_id="t-1", user_id=USER.id)
        assert (await queue_service.get_job(job_id, USER.id)).status == "queued"
        await run_worker(pool)
        done = await queue_service.get_job(job_id, USER.id)
        other = await queue_service.get_job(job_id, "someone-else")
        missing = await queue_service.get_job("no-such-job", USER.id)
        await pool.aclose()
        return done, other, missing

    done, other, missing = asyncio.run(scenario())
    assert exported == [("t-1", USER.id)]
    assert (done.status, done.function, done.result["path"]) == ("complete", "task_generate_pdf_report", f"{ORG_ID}/t-1.pdf")
    assert other is None and missing is None


def test_n8n_delivery_retries_with_exponential_backoff(arq_redis, monkeypatch):
    attempts = []

    async def flaky_n8n(payload):
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise ConnectionError("n8n is down")
        return {"ok": True}

    monkeypatch.setattr(n8n_service, "trigger_post_consultation", flaky_n8n)
    monkeypatch.setattr(get_settings(), "n8n_retry_base_seconds", 0.2)

    async def scenario():
        pool = arq_redis()
        if os.environ.get("TEST_REDIS_URL"):
            await pool.flushdb()
        job = await pool.enqueue_job("task_trigger_n8n_webhook", {"event": "consultation.completed"},
                                     _queue_name=queue_service.QUEUE_NAME)
        await run_worker(pool)
        info = await job.result_info()
        await pool.aclose()
        return info

    info = asyncio.run(scenario())
    assert info.success and info.result == {"ok": True} and info.job_try == 3
    gaps = [b - a for a, b in zip(attempts, attempts[1:])]
    # 1x, then 2x the base delay (with slack for the ~16 ms clock tick on Windows)
    assert gaps[0] >= 0.18 and gaps[1] >= 0.38


def test_n8n_delivery_gives_up_after_retry_count(arq_redis, monkeypatch):
    async def down(payload):
        raise ConnectionError("n8n is down")

    monkeypatch.setattr(n8n_service, "trigger_post_consultation", down)
    monkeypatch.setattr(get_settings(), "n8n_retry_base_seconds", 0.01)

    async def scenario():
        pool = arq_redis()
        if os.environ.get("TEST_REDIS_URL"):
            await pool.flushdb()
        job = await pool.enqueue_job("task_trigger_n8n_webhook", {"event": "x"}, retry_count=1,
                                     _queue_name=queue_service.QUEUE_NAME)
        await run_worker(pool)
        info = await job.result_info()
        await pool.aclose()
        return info

    info = asyncio.run(scenario())
    assert not info.success and info.job_try == 2 and isinstance(info.result, ConnectionError)


def test_pdf_report_endpoint_queues_a_job(client, audit_log, monkeypatch):
    from app.services import transcript_service

    queued = []

    async def enqueue(function, **kwargs):
        queued.append((function, kwargs))
        return "job-1"

    monkeypatch.setattr(queue_service, "is_configured", lambda: True)
    monkeypatch.setattr(queue_service, "enqueue", enqueue)
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: {"id": tid} if tid.startswith("5") else None)

    tid = "5f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01"
    response = client.post(f"/api/v1/transcripts/{tid}/pdf/jobs")
    assert response.status_code == 202 and response.json() == {"job_id": "job-1", "status": "queued"}
    assert queued == [("task_generate_pdf_report", {"transcript_id": tid, "user_id": USER.id})]
    assert audit_log[-1]["action"] == "QUEUE_PDF_REPORT"
    # Transcripts the caller can't see (RLS returns nothing) are not queued.
    assert client.post("/api/v1/transcripts/6f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01/pdf/jobs").status_code == 404

    monkeypatch.setattr(queue_service, "is_configured", lambda: False)
    assert client.post(f"/api/v1/transcripts/{tid}/pdf/jobs").status_code == 503


def test_worker_rechecks_access_before_exporting():
    from app.worker import TaskError, generate_pdf_report

    db = FakeDB(
        transcripts=[{"id": "t-1", "org_id": ORG_ID, "user_id": "partner-1", "title": "Deposit", "content": "Client: hello",
                      "summary": None, "metadata": {}, "created_at": "2026-10-01T10:00:00+00:00", "document_id": None}],
        organization_members=[{"org_id": ORG_ID, "user_id": "associate-1", "role": "associate"},
                              {"org_id": ORG_ID, "user_id": "owner-1", "role": "owner"}],
    )
    with pytest.raises(TaskError):
        generate_pdf_report("t-1", "associate-1", db=db)  # not theirs, not senior
    with pytest.raises(TaskError):
        generate_pdf_report("t-1", "outsider", db=db)
    result = generate_pdf_report("t-1", "owner-1", db=db)
    assert result["path"] == f"{ORG_ID}/t-1.pdf"
    assert db.files[("reports", f"{ORG_ID}/t-1.pdf")].startswith(b"%PDF")


def test_batch_embedding_indexes_a_document_for_knowledge_roles(monkeypatch):
    from app.services import rag_service
    from app.worker import TaskError, batch_embed_document

    ingested = []

    def ingest(org_id, title, text, *, db, created_by=None, metadata=None, embedder=None):
        ingested.append((org_id, title, len(text), created_by, metadata["jurisdiction_code"]))
        return rag_service.IngestResult(source_id="src-1", title=title, chunk_count=12, char_count=len(text))

    monkeypatch.setattr(rag_service, "ingest_legal_statutes_and_precedents", ingest)
    db = FakeDB(
        documents=[{"id": "d-1", "org_id": ORG_ID, "user_id": "associate-1", "filename": "bns.pdf", "extracted_text": "x" * 50_000}],
        organization_members=[{"org_id": ORG_ID, "user_id": "associate-1", "role": "associate"},
                              {"org_id": ORG_ID, "user_id": "paralegal-1", "role": "paralegal"}],
    )
    with pytest.raises(TaskError):
        batch_embed_document("d-1", "paralegal-1", db=db)
    result = batch_embed_document("d-1", "associate-1", title="Bharatiya Nyaya Sanhita", jurisdiction="India", db=db)
    assert result == {"source_id": "src-1", "title": "Bharatiya Nyaya Sanhita", "chunk_count": 12, "char_count": 50_000}
    assert ingested == [(ORG_ID, "Bharatiya Nyaya Sanhita", 50_000, "associate-1", "IN")]


# ============================================================================ rate limiting


def test_named_limits_return_429_with_retry_after(monkeypatch):
    monkeypatch.setattr(rate_limiter.limiter, "enabled", True)
    monkeypatch.setattr(get_settings(), "rate_limit_llm", "2/minute")
    mini = FastAPI()

    @mini.post("/expensive", dependencies=[Depends(rate_limiter.limit("llm"))])
    def expensive():
        return {"ok": True}

    client = TestClient(mini)
    me = {"Authorization": f"Bearer token-{uuid.uuid4()}"}
    you = {"Authorization": f"Bearer token-{uuid.uuid4()}"}
    codes = [client.post("/expensive", headers=me).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    blocked = client.post("/expensive", headers=me)
    assert 0 < int(blocked.headers["Retry-After"]) <= 60
    assert client.post("/expensive", headers=you).status_code == 200  # limits are per client


def test_default_limit_covers_the_api_but_not_webhooks(monkeypatch):
    monkeypatch.setattr(rate_limiter.limiter, "enabled", True)
    monkeypatch.setattr(get_settings(), "rate_limit_default", "3/minute")
    mini = FastAPI()
    mini.add_middleware(rate_limiter.RateLimitMiddleware)

    @mini.get("/api/v1/things")
    def things():
        return []

    @mini.post("/api/v1/billing/webhook")
    def webhook():
        return {}

    @mini.get("/health")
    def health():
        return {}

    client = TestClient(mini, headers={"Authorization": f"Bearer token-{uuid.uuid4()}"})
    assert [client.get("/api/v1/things").status_code for _ in range(4)] == [200, 200, 200, 429]
    assert all(client.post("/api/v1/billing/webhook").status_code == 200 for _ in range(5))
    assert all(client.get("/health").status_code == 200 for _ in range(5))


def test_rate_limit_keys_hash_tokens_and_fall_back_to_ip():
    from starlette.requests import Request

    def request(headers):
        return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                        "client": ("203.0.113.9", 5000)})

    key = rate_limiter.client_key(request({"Authorization": "Bearer secret-jwt"}))
    assert key.startswith("token:") and "secret-jwt" not in key
    assert rate_limiter.client_key(request({})) == "ip:203.0.113.9"


# ============================================================================ metrics


def test_metrics_expose_claude_tokens_sessions_and_http(monkeypatch):
    before = REGISTRY.get_sample_value("claude_tokens_total", {"model": "claude-haiku-5-5", "kind": "input"}) or 0
    metrics.record_claude_usage(SimpleNamespace(
        model="claude-haiku-5-5", stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300, cache_read_input_tokens=900, cache_creation_input_tokens=None),
    ))
    metrics.record_claude_usage(object())  # never raises on odd responses
    assert REGISTRY.get_sample_value("claude_tokens_total", {"model": "claude-haiku-5-5", "kind": "input"}) == before + 1200

    client = TestClient(app)
    client.get("/api/v1/public-config")
    body = client.get("/metrics").text
    for name in ("claude_tokens_total", "telephony_response_latency_seconds", "telephony_active_calls",
                 "live_sessions_active", "db_connections_open", "http_requests_total"):
        assert name in body

    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-secret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200


def test_db_connection_gauge_reads_the_rpc(monkeypatch):
    calls = []
    fake = SimpleNamespace(rpc=lambda name, params: calls.append(name) or SimpleNamespace(execute=lambda: SimpleNamespace(data=17)))
    monkeypatch.setattr("app.database.get_supabase_admin", lambda: fake)
    metrics.refresh_db_connections()
    assert calls == ["db_connection_count"]
    assert REGISTRY.get_sample_value("db_connections_open") == 17


# ============================================================================ Claude gateway


def test_claude_can_go_through_an_anthropic_compatible_gateway(monkeypatch):
    import httpx2  # the HTTP library the Anthropic SDK uses

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "anthropic_auth_token", "gateway-token")
    monkeypatch.setattr(settings, "anthropic_base_url", "http://litellm.internal:4000/")
    monkeypatch.setattr(settings, "anthropic_server_fallback", False)
    monkeypatch.setattr(anthropic_service, "_client", None)
    seen = {}

    def gateway(request: httpx2.Request) -> httpx2.Response:
        seen.update(url=str(request.url), auth=request.headers.get("authorization"), body=json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": json.dumps({"title": "Deposit", "summary": "Landlord kept it."})}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    assert anthropic_service.is_configured()
    client = anthropic_service._get_client()
    client._client = httpx2.AsyncClient(transport=httpx2.MockTransport(gateway))  # keep the SDK, fake the network

    from app.models.analysis import LiveAnalysis

    result = asyncio.run(anthropic_service.summarize_consultation("Client: my landlord kept my deposit", LiveAnalysis()))
    monkeypatch.setattr(anthropic_service, "_client", None)

    assert result.title == "Deposit"
    assert seen["url"].startswith("http://litellm.internal:4000/v1/messages")
    assert seen["auth"] == "Bearer gateway-token"
    # With the fallback off, no beta parameters are sent for the gateway to reject.
    assert "fallbacks" not in seen["body"]


def test_fallback_beta_is_on_by_default():
    assert anthropic_service._fallback_options() == {"betas": [anthropic_service.FALLBACK_BETA], "fallbacks": "default"}


def test_prompt_mode_gets_json_from_models_without_structured_outputs(monkeypatch):
    """Ollama-style endpoints ignore output formats: the schema goes in the prompt, the reply is validated."""
    import httpx2

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "ollama")
    monkeypatch.setattr(settings, "anthropic_base_url", "http://localhost:11434")
    monkeypatch.setattr(settings, "anthropic_server_fallback", True)  # ignored in prompt mode
    monkeypatch.setattr(settings, "anthropic_structured_output", "prompt")
    monkeypatch.setattr(anthropic_service, "_client", None)
    replies = iter([
        "Here is the summary:\n**Title:** Deposit",  # not JSON: triggers one corrective retry
        'Sure!\n```json\n{"title": "Deposit dispute", "summary": "Landlord kept the deposit."}\n```',
    ])
    requests = []

    def ollama(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "gemma4:31b",
            "content": [{"type": "text", "text": next(replies)}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    client = anthropic_service._get_client()
    client._client = httpx2.AsyncClient(transport=httpx2.MockTransport(ollama))

    from app.models.analysis import LiveAnalysis

    result = asyncio.run(anthropic_service.summarize_consultation("Client: my landlord kept my deposit", LiveAnalysis()))
    monkeypatch.setattr(anthropic_service, "_client", None)

    assert (result.title, result.summary) == ("Deposit dispute", "Landlord kept the deposit.")
    assert len(requests) == 2
    first = requests[0]
    assert "output_config" not in first and "fallbacks" not in first and "output_format" not in first
    system = first["system"] if isinstance(first["system"], str) else first["system"][-1]["text"]
    assert system.rstrip().endswith("}") and '"title"' in system  # the JSON schema closes the system prompt
    assert requests[1]["messages"][-1]["content"].startswith("That reply was not a valid JSON object")


# ============================================================================ push-to-talk and metering


def test_only_audio_while_the_mic_is_held_is_transcribed_and_billed(monkeypatch):
    from app.services import live_session

    monkeypatch.setattr(live_session, "PTT_TAIL_SECONDS", 0.05)
    fed = []

    class Transcriber:
        failed = False

        async def feed(self, audio):
            fed.append(audio)

        async def finalize(self):
            fed.append("finalize")

        async def close(self):
            pass

    async def create_transcriber(*args, **kwargs):
        return Transcriber()

    monkeypatch.setattr(transcription_service, "create_transcriber", create_transcriber)
    session = live_session.LiveConsultationSession(SimpleNamespace(), USER, ORG_ID, "owner", transport="webrtc")

    async def scenario():
        frame = bytes(3200)  # 100 ms at 16 kHz
        assert not session.accepts_push_to_talk_audio()  # typing only: nothing is streamed
        await session._handle_push_to_talk({"state": "start"})
        for _ in range(5):
            assert session.accepts_push_to_talk_audio()
            await session.handle_pcm_audio(frame)
            await asyncio.sleep(0.1)
        await session._handle_push_to_talk({"state": "stop"})
        assert session.accepts_push_to_talk_audio()  # the tail of the utterance still counts
        await asyncio.sleep(0.15)
        assert not session.accepts_push_to_talk_audio()

    asyncio.run(scenario())
    assert fed[-1] == "finalize" and len(fed) == 6
    assert session.audio_received and 0.3 < session.audio_seconds < 0.7


def test_typed_only_sessions_are_not_metered(monkeypatch):
    from datetime import datetime, timezone

    from app.services import live_session

    calls = []

    async def record(*args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(stripe_service, "arecord_audio_usage", record)
    session = live_session.LiveConsultationSession(SimpleNamespace(), USER, ORG_ID, "owner", transport="webrtc")
    asyncio.run(session._meter_audio(datetime.now(timezone.utc)))
    assert calls == []


def test_metering_bills_streamed_seconds_not_session_length():
    from datetime import datetime, timedelta, timezone

    db = FakeDB()
    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    usage = stripe_service.record_audio_usage(ORG_ID, USER.id, "sess-ptt", "webrtc", start, start + timedelta(minutes=30),
                                              duration_seconds=75.4, db=db)
    assert usage.billed_minutes == 2  # 75 s of speech in a 30-minute session
    assert db.rows("audio_usage")[0]["duration_seconds"] == 75
