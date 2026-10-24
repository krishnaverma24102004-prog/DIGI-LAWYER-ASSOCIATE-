import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.dependencies.auth import CurrentUser
from app.main import app
from app.models.analysis import ConsultationSummary, LiveAnalysis
from app.routers import audio_stream
from app.services import anthropic_service, live_session, n8n_service, transcript_service, transcription_service

USER = CurrentUser(id="user-1", email="lawyer@example.com", access_token="good-token")


@pytest.fixture
def fakes(monkeypatch, fake_agents):
    calls = {"summary_docs": [], "saved": [], "n8n": [], "agents": fake_agents.calls}

    def verify(token):
        if token != "good-token":
            raise ValueError("bad token")
        return USER

    async def summarize(transcript, analysis, document_context=None, **context):
        calls["summary_docs"].append(document_context)
        return ConsultationSummary(title="Wrongful termination", summary="Overview: ...")

    def save(access_token, user_id, row):
        calls["saved"].append((access_token, user_id, row))
        return {"id": "transcript-1", **row, "user_id": user_id}

    async def trigger(payload):
        calls["n8n"].append(payload)
        return {}

    monkeypatch.setattr(audio_stream, "verify_access_token", verify)
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(transcript_service, "save_live_session", save)
    monkeypatch.setattr(n8n_service, "is_configured", lambda: True)
    monkeypatch.setattr(n8n_service, "trigger_post_consultation", trigger)
    return calls


def receive_until(ws, message_type):
    while True:
        message = ws.receive_json()
        if message["type"] == message_type:
            return message


def test_rejects_missing_token(fakes):
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/api/v1/ws/audio") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_rejects_invalid_token(fakes):
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/api/v1/ws/audio?token=bad") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_full_session_streams_analysis_then_saves_and_triggers_n8n(fakes):
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        started = ws.receive_json()
        assert started["type"] == "session_started"
        assert started["user_id"] == "user-1"

        ws.send_json({"type": "start", "title": "Intake call"})
        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": "I was fired on 3 March."})
        assert receive_until(ws, "chunk_received")["index"] == 0

        analysis = receive_until(ws, "analysis")
        assert analysis["data"]["legal_issues"][0]["severity"] == "high"
        assert analysis["data"]["key_facts"][0]["fact"] == "Fired on 3 March"

        ws.send_json({"type": "end"})
        ended = receive_until(ws, "session_ended")

    assert ended["transcript_id"] == "transcript-1"
    assert ended["summary"] == "Overview: ..."
    assert ended["workflow_triggered"] is True
    assert ended["end_reason"] == "client_end"

    access_token, user_id, row = fakes["saved"][0]
    assert (access_token, user_id) == ("good-token", "user-1")
    assert row["title"] == "Intake call"  # client title wins over the generated one
    assert row["content"] == "Client: I was fired on 3 March."
    assert row["source"] == "live_stream"
    assert row["metadata"]["analysis"]["legal_issues"][0]["issue"] == "Wrongful termination"

    payload = fakes["n8n"][0]
    assert payload["event"] == "consultation.completed"
    assert payload["transcript_id"] == "transcript-1"


def test_bearer_subprotocol_auth(fakes):
    with TestClient(app).websocket_connect("/api/v1/ws/audio", subprotocols=["bearer", "good-token"]) as ws:
        assert ws.receive_json()["type"] == "session_started"
        assert ws.accepted_subprotocol == "bearer"
        ws.send_json({"type": "end"})
        ended = receive_until(ws, "session_ended")
    assert ended["transcript_id"] is None  # nothing said, nothing saved
    assert fakes["saved"] == [] and fakes["n8n"] == []


def test_binary_audio_without_stt_reports_once(fakes, monkeypatch):
    monkeypatch.setattr(transcription_service, "is_configured", lambda: False)
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x01")
        ws.send_bytes(b"\x00\x01")
        error = ws.receive_json()
        assert error == {
            "type": "error",
            "code": "audio_transcription_unavailable",
            "message": error["message"],
        }
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"  # second frame produced no extra error
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")


class ScriptedWebSocket:
    """Plays client messages, then drops the connection without an "end" message.

    Drives the session directly: Starlette's TestClient cancels the app as soon as the
    client disconnects, which a real server doesn't do, so it can't test finalization.
    """

    def __init__(self, *events):
        self.incoming = [{"type": "websocket.receive", "text": json.dumps(e)} for e in events]
        self.sent = []

    async def receive(self):
        await asyncio.sleep(0.05)  # let the analysis task run between messages
        return self.incoming.pop(0) if self.incoming else {"type": "websocket.disconnect", "code": 1006}

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000):
        pass


def test_disconnect_still_saves(fakes, audit_log):
    ws = ScriptedWebSocket({"type": "transcript_chunk", "text": "My landlord kept my deposit."})
    session = live_session.LiveConsultationSession(ws, USER, "org-1", "associate")
    asyncio.run(session.run())

    assert fakes["saved"][0][2]["metadata"]["end_reason"] == "disconnected"
    assert fakes["n8n"][0]["end_reason"] == "disconnected"
    assert [e["action"] for e in audit_log] == ["START_CONSULTATION", "END_CONSULTATION"]


def test_recent_transcript_keeps_latest_lines():
    session = live_session.LiveConsultationSession.__new__(live_session.LiveConsultationSession)
    session.segments = [
        live_session.TranscriptSegment(f"line {i}", None, "client_text", "", masked_text=f"line {i}") for i in range(100)
    ]
    recent = session._recent_transcript(30)
    assert recent.endswith("line 99")
    assert "line 0\n" not in recent


class FakeTranscriber:
    """Stands in for Deepgram: every audio frame 'transcribes' to the next scripted line."""

    instances = []

    def __init__(self, audio_format, on_final, on_interim, on_error):
        self.audio_format = audio_format
        self.on_final, self.on_interim = on_final, on_interim
        self.frames = []
        self.closed = False
        self.failed = False
        FakeTranscriber.instances.append(self)

    async def feed(self, audio):
        self.frames.append(audio)
        await self.on_interim("I was fi")
        await self.on_final("I was fired on 3 March.", "Speaker 1")

    async def close(self):
        # Deepgram flushes buffered audio on close; the last words must still be saved.
        await self.on_final("That is all.", "Speaker 2")
        self.closed = True


def test_audio_frames_are_transcribed_analyzed_and_flushed_on_end(fakes, monkeypatch):
    FakeTranscriber.instances.clear()

    async def create(audio_format, on_final, on_interim, on_error):
        return FakeTranscriber(audio_format, on_final, on_interim, on_error)

    monkeypatch.setattr(transcription_service, "create_transcriber", create)

    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "audio": {"encoding": "linear16", "sample_rate": 16000, "channels": 1}})
        ws.send_bytes(bytes(1600))
        assert receive_until(ws, "transcript_interim")["text"] == "I was fi"
        chunk = receive_until(ws, "chunk_received")
        assert (chunk["text"], chunk["speaker"], chunk["source"]) == ("I was fired on 3 March.", "Speaker 1", "audio")
        receive_until(ws, "analysis")
        ws.send_json({"type": "end"})
        ended = receive_until(ws, "session_ended")

    transcriber = FakeTranscriber.instances[0]
    assert transcriber.audio_format == transcription_service.AudioFormat("linear16", 16000, 1)
    assert transcriber.closed
    assert ended["transcript_id"] == "transcript-1"
    content = fakes["saved"][0][2]["content"]
    assert content.splitlines() == ["Speaker 1: I was fired on 3 March.", "Speaker 2: That is all."]


def test_invalid_audio_format_is_rejected(fakes):
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "audio": {"encoding": "mp3-ish"}})
        assert receive_until(ws, "error")["code"] == "invalid_audio_format"
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")


def test_deepgram_result_is_split_by_speaker():
    from deepgram.listen.v1 import ListenV1Results

    words = [
        {"word": w, "punctuated_word": p, "start": 0, "end": 0, "confidence": 1, "speaker": s}
        for w, p, s in [("hello", "Hello.", 0), ("hi", "Hi,", 1), ("there", "there.", 1)]
    ]
    result = ListenV1Results.model_validate(
        {
            "type": "Results", "channel_index": [0, 1], "duration": 1, "start": 0, "is_final": True,
            "channel": {"alternatives": [{"transcript": "hello hi there", "confidence": 1, "words": words}]},
            "metadata": {"request_id": "r", "model_info": {"name": "n", "version": "v", "arch": "a"}, "model_uuid": "u"},
        }
    )
    assert transcription_service.segments_from_result(result) == [("Hello.", "Speaker 1"), ("Hi, there.", "Speaker 2")]


def test_static_test_page_is_served():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Live Consultation Test" in response.text
