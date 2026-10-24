"""Phase 6: live web search agent, talking mode (TTS), conversation mode and WebRTC."""

import asyncio
import base64
import fractions
import io
import json
import math
import os
import socket
import threading
import time
import wave
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.dependencies.auth import CurrentUser
from app.main import app
from app.models.analysis import ConsultationSummary, WebSearchPlan
from app.routers import audio_stream, webrtc
from app.services import (
    agent_workflow,
    anthropic_service,
    n8n_service,
    transcript_service,
    transcription_service,
    tts_service,
    web_search,
)
from app.services.agent_workflow import AgentContext
from app.services.rag_service import Precedent
from app.services.web_search import WebResult

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="lawyer@acme.law", access_token="good-token")
SSN = "536-22-8172"


def precedent(similarity: float) -> Precedent:
    return Precedent(id="chunk-1", source_id="src-1", title="Tenancy Act s.12", content="Deposit within 21 days.", similarity=similarity)


WEB = [
    WebResult(title="Deposit return rules updated", url="https://gov.example/deposits", snippet="From 2026 landlords must...", score=0.9, query="q"),
    WebResult(title="Tribunal ruling on deposits", url="https://law.example/case", snippet="The tribunal held...", score=0.7, query="q"),
]


# ============================================================================ web search routing


@pytest.fixture
def web_agents(monkeypatch, fake_agents):
    calls = {"plan": [], "search": []}
    plan = SimpleNamespace(value=WebSearchPlan(needed=True, queries=["security deposit return deadline landlord law 2026"]))

    async def plan_web_search(facts, risks, transcript_history, **context):
        calls["plan"].append({"facts": facts, "transcript_history": transcript_history})
        return plan.value

    async def search(queries):
        calls["search"].append(queries)
        return WEB

    monkeypatch.setattr(anthropic_service, "plan_web_search", plan_web_search)
    return SimpleNamespace(calls=calls, plan=plan, search=search, agents=fake_agents)


class Statuses:
    def __init__(self):
        self.stages = []

    async def emit(self, stage, message):
        self.stages.append(stage)


def run(state, **context):
    return asyncio.run(agent_workflow.process_audio_chunk_via_agent(state, AgentContext(**context)))


def research_returning(result):
    async def research(query):
        return result

    return research


def test_routes_to_web_search_when_the_knowledge_base_is_empty(web_agents):
    statuses = Statuses()
    result = run({"current_chunk": "My landlord kept my deposit."}, research=research_returning([]),
                 web_search=web_agents.search, emit_status=statuses.emit)

    assert statuses.stages == ["intake_analyzer", "legal_researcher", "external_researcher", "risk_evaluator", "drafter"]
    assert [r["url"] for r in result["web_results"]] == ["https://gov.example/deposits", "https://law.example/case"]
    assert result["web_search_queries"] == ["security deposit return deadline landlord law 2026"]
    # The drafter (and the risk evaluator) synthesized the web results.
    assert [r.url for r in web_agents.agents.calls["draft"][0]["web_results"]] == [r.url for r in WEB]
    assert [r.url for r in web_agents.agents.calls["risk"][0]["web_results"]] == [r.url for r in WEB]
    assert result["final_response"]["web_sources"][0]["title"] == "Deposit return rules updated"


def test_weak_knowledge_base_matches_also_go_to_the_web(web_agents):
    statuses = Statuses()
    run({"current_chunk": "x"}, research=research_returning([precedent(0.41)]), web_search=web_agents.search, emit_status=statuses.emit)
    assert "external_researcher" in statuses.stages


def test_confident_knowledge_base_matches_stay_offline(web_agents):
    statuses = Statuses()
    run({"current_chunk": "x"}, research=research_returning([precedent(0.92)]), web_search=web_agents.search, emit_status=statuses.emit)
    assert "external_researcher" not in statuses.stages and web_agents.calls["search"] == []


def test_skipped_knowledge_base_search_does_not_trigger_the_web(web_agents):
    statuses = Statuses()
    run({"current_chunk": "x"}, research=research_returning(None), web_search=web_agents.search, emit_status=statuses.emit)
    assert "external_researcher" not in statuses.stages


def test_no_knowledge_base_means_the_web_is_the_source(web_agents):
    statuses = Statuses()
    run({"current_chunk": "x"}, research=None, web_search=web_agents.search, emit_status=statuses.emit)
    assert "external_researcher" in statuses.stages


def test_planner_can_decide_no_search_is_needed(web_agents):
    web_agents.plan.value = WebSearchPlan(needed=False, queries=[], reason="Small talk")
    result = run({"current_chunk": "Thanks, that's helpful."}, research=research_returning([]), web_search=web_agents.search)
    assert web_agents.calls["search"] == [] and result["final_response"]["message"]


def test_without_web_search_configured_the_graph_never_goes_online(web_agents):
    statuses = Statuses()
    run({"current_chunk": "x"}, research=research_returning([]), emit_status=statuses.emit)
    assert "external_researcher" not in statuses.stages and web_agents.calls["plan"] == []


def tavily_transport(seen):
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        results = [
            {"title": "Deposit rules", "url": "https://gov.example/deposits", "content": "Landlords must return...", "score": 0.8},
            {"title": "Same page, other query", "url": "https://gov.example/deposits", "content": "...", "score": 0.95},
            {"title": "Not a web page", "url": "ftp://x", "content": "", "score": 1.0},
        ] if "deposit" in body["query"] else [{"title": "Case", "url": "https://law.example/c", "content": "Held...", "score": 0.6}]
        return httpx.Response(200, json={"query": body["query"], "results": results})

    return httpx.MockTransport(handler)


def test_search_web_dedupes_ranks_and_prefers_configured_domains(monkeypatch):
    monkeypatch.setattr(get_settings(), "tavily_api_key", "tvly-test")
    monkeypatch.setattr(get_settings(), "web_search_preferred_domains", "indiankanoon.org, legislation.gov.uk")
    seen = []
    results = asyncio.run(web_search.search_web(
        ["deposit return deadline", "tribunal ruling"], http_client=httpx.AsyncClient(transport=tavily_transport(seen))
    ))
    assert [(r.url, r.score) for r in results] == [("https://gov.example/deposits", 0.95), ("https://law.example/c", 0.6)]
    assert seen[0]["include_domains"] == ["indiankanoon.org", "legislation.gov.uk"]
    assert seen[0]["include_domains_mode"] == "prefer"
    assert {b["query"] for b in seen} == {"deposit return deadline", "tribunal ruling"}


def test_only_the_planned_queries_leave_the_server(ws_session):
    """Web search sends the generic planned query, never the conversation."""
    seen = []
    ws_session.enable_web(http_client=httpx.AsyncClient(transport=tavily_transport(seen)))
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token&mode=conversation") as ws:
        ws.receive_json()
        ws.send_json({"type": "transcript_chunk", "text": f"Mr Sharma at 12 Hill Road kept my deposit; my SSN is {SSN}."})
        sources = receive_until(ws, "web_sources")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")
    assert sources["items"][0]["url"] == "https://gov.example/deposits"
    sent = json.dumps(seen)
    assert "Sharma" not in sent and "Hill Road" not in sent and SSN not in sent
    assert seen[0]["query"] == "security deposit return deadline landlord law 2026"
    # The planner itself only ever saw masked text.
    assert SSN not in ws_session.web.calls["plan"][0]["transcript_history"]


# ============================================================================ text-to-speech


def deepgram_transport(seen, body: bytes):
    def handler(request):
        seen.append({"url": str(request.url), "json": json.loads(request.content), "auth": request.headers.get("authorization")})
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)


def sine_pcm(seconds=0.5, rate=48000, freq=440.0) -> bytes:
    samples = (np.sin(2 * np.pi * freq * np.arange(int(seconds * rate)) / rate) * 12000).astype(np.int16)
    return samples.tobytes()


MP3_FRAME = bytes.fromhex("fffb9064") + b"\x00" * 413  # an MPEG-1 Layer III frame header + padding


@pytest.fixture
def deepgram_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg-test")


def test_tts_returns_a_playable_mp3_buffer(deepgram_key):
    seen = []
    audio = asyncio.run(tts_service.synthesize(
        "Your deposit may be protected by statute.",
        http_client=httpx.AsyncClient(transport=deepgram_transport(seen, b"ID3\x04\x00\x00\x00\x00\x00\x00" + MP3_FRAME * 4)),
    ))
    assert audio.startswith(b"ID3") and len(audio) > 1000
    assert seen[0]["url"].startswith("https://api.deepgram.com/v1/speak?")
    assert "encoding=mp3" in seen[0]["url"] and f"model={get_settings().tts_model}" in seen[0]["url"]
    assert seen[0]["json"] == {"text": "Your deposit may be protected by statute."}
    assert seen[0]["auth"] == "Token dg-test"


def test_tts_streams_whole_pcm_samples_that_make_a_valid_wav(deepgram_key):
    pcm = sine_pcm()
    seen = []

    async def collect():
        return [c async for c in tts_service.stream_speech(
            "Hello.", http_client=httpx.AsyncClient(transport=deepgram_transport(seen, pcm[:-1] + b"\x00")))]

    chunks = asyncio.run(collect())
    assert all(len(c) % 2 == 0 for c in chunks)
    assert "encoding=linear16" in seen[0]["url"] and "sample_rate=48000" in seen[0]["url"] and "container=none" in seen[0]["url"]
    with wave.open(io.BytesIO(tts_service.pcm_to_wav(b"".join(chunks))), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        assert abs(wav.getnframes() / 48000 - 0.5) < 0.01


@pytest.mark.skipif(not os.getenv("DEEPGRAM_API_KEY"), reason="set DEEPGRAM_API_KEY to call the real Deepgram TTS")
def test_real_deepgram_tts_returns_mp3(monkeypatch):
    monkeypatch.setattr(get_settings(), "deepgram_api_key", os.environ["DEEPGRAM_API_KEY"])
    audio = asyncio.run(tts_service.synthesize("This is a test of talking mode."))
    assert audio[:3] == b"ID3" or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)


def test_text_is_made_speakable():
    from app.core.guardrails import LEGAL_DISCLAIMER

    spoken = tts_service.speakable(f"[BANK_ACCT] was charged. See https://x.example **now**.\n\n{LEGAL_DISCLAIMER}")
    assert spoken == (
        "The bank account you mentioned was charged. See now. "
        "This is general legal information, not legal advice, and a licensed attorney should review it."
    )


def test_tts_errors_are_reported_cleanly(deepgram_key):
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"err_msg": "Invalid credentials"}))
    with pytest.raises(tts_service.TTSError, match="401"):
        asyncio.run(tts_service.synthesize("Hi.", http_client=httpx.AsyncClient(transport=transport)))


# ============================================================================ conversation mode over WebSocket


class FakeTranscriber:
    instances = []

    def __init__(self, audio_format, on_final, on_interim, on_error):
        self.audio_format, self.on_final = audio_format, on_final
        self.bytes = 0
        self.finalized = 0
        self.failed = False
        FakeTranscriber.instances.append(self)

    async def feed(self, audio):
        self.bytes += len(audio)

    async def finalize(self):
        self.finalized += 1
        await self.on_final("My landlord kept my deposit.", "Speaker 1")

    async def close(self):
        pass


@pytest.fixture
def ws_session(monkeypatch, fake_agents):
    seen = {"saved": None, "spoken": []}
    FakeTranscriber.instances.clear()

    async def summarize(transcript, analysis, **context):
        return ConsultationSummary(title="Deposit", summary="Overview: ...")

    def save(token, user_id, row):
        seen["saved"] = row
        return {"id": "transcript-1", **row}

    async def synthesize(text, encoding="mp3", http_client=None):
        seen["spoken"].append(tts_service.speakable(text))
        return b"ID3" + MP3_FRAME

    async def stream_speech(text, sample_rate=48000, http_client=None):
        seen["spoken"].append(tts_service.speakable(text))
        pcm = sine_pcm(0.4)
        for i in range(0, len(pcm), 9600):
            yield pcm[i : i + 9600]

    async def create_transcriber(audio_format, on_final, on_interim, on_error):
        return FakeTranscriber(audio_format, on_final, on_interim, on_error)

    monkeypatch.setattr(audio_stream, "verify_access_token", lambda token: USER)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(transcript_service, "save_live_session", save)
    monkeypatch.setattr(n8n_service, "is_configured", lambda: False)
    monkeypatch.setattr(tts_service, "is_configured", lambda: True)
    monkeypatch.setattr(tts_service, "synthesize", synthesize)
    monkeypatch.setattr(tts_service, "stream_speech", stream_speech)
    monkeypatch.setattr(transcription_service, "create_transcriber", create_transcriber)
    monkeypatch.setattr(get_settings(), "conversation_debounce_seconds", 0.05)

    session = SimpleNamespace(seen=seen, agents=fake_agents, web=None)

    def enable_web(http_client):
        calls = {"plan": []}

        async def plan_web_search(facts, risks, transcript_history, **context):
            calls["plan"].append({"transcript_history": transcript_history})
            return WebSearchPlan(needed=True, queries=["security deposit return deadline landlord law 2026"])

        real_search = web_search.search_web

        async def search(queries, max_results=None, http_client_=None):
            return await real_search(queries, http_client=http_client)

        monkeypatch.setattr(get_settings(), "tavily_api_key", "tvly-test")
        monkeypatch.setattr(anthropic_service, "plan_web_search", plan_web_search)
        monkeypatch.setattr(web_search, "search_web", search)
        session.web = SimpleNamespace(calls=calls)

    session.enable_web = enable_web
    return session


def receive_until(ws, message_type, collected=None):
    while True:
        message = ws.receive_json()
        if collected is not None:
            collected.append(message)
        if message["type"] == message_type:
            return message


def test_talking_mode_speaks_replies_and_keeps_them_as_chat_turns(ws_session):
    ws_session.agents.outputs.message = "I understand. Was [CLIENT_SSN] used anywhere else?"
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token&mode=conversation&voice=1") as ws:
        started = ws.receive_json()
        assert (started["mode"], started["voice"]) == ("conversation", True)
        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": f"Someone used my SSN {SSN} for a loan."})
        reply = receive_until(ws, "agent_response")
        audio = receive_until(ws, "agent_audio")

        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": "Only for the loan, as far as I know."})
        receive_until(ws, "agent_response")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")

    # Shown to the person who said it: their own details restored. Spoken: a phrase, never the number.
    assert reply["message"] == f"I understand. Was {SSN} used anywhere else?" and reply["spoken"] is True
    assert base64.b64decode(audio["audio"]).startswith(b"ID3")
    assert ws_session.seen["spoken"][0] == "I understand. Was the Social Security number you mentioned used anywhere else?"
    # The reply became a chat turn the agents see as history, not as new speech.
    second = ws_session.agents.calls["intake"][1]
    assert "AI Assistant: I understand. Was [CLIENT_SSN] used anywhere else?" in second["transcript_history"]
    assert "AI Assistant" not in second["current_chunk"]
    assert "AI Assistant: " in ws_session.seen["saved"]["content"] and ws_session.seen["saved"]["metadata"]["mode"] == "conversation"


def test_push_to_talk_release_finalizes_the_utterance(ws_session):
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token&mode=conversation") as ws:
        ws.receive_json()
        ws.send_json({"type": "ptt", "state": "start"})
        ws.send_bytes(bytes(3200))
        ws.send_json({"type": "ptt", "state": "stop"})
        chunk = receive_until(ws, "chunk_received")
        receive_until(ws, "agent_response")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")
    assert FakeTranscriber.instances[0].finalized == 1 and chunk["text"] == "My landlord kept my deposit."


# ============================================================================ WebRTC (real peer connection over localhost)


class ToneTrack:
    """A microphone stand-in: 20 ms frames of a 300 Hz tone at 48 kHz."""

    def __new__(cls):
        from aiortc import MediaStreamTrack
        from av import AudioFrame

        class _Tone(MediaStreamTrack):
            kind = "audio"

            def __init__(self):
                super().__init__()
                self._pts = 0
                self._start = None

            async def recv(self):
                if self._start is None:
                    self._start = time.time()
                else:
                    self._pts += 960
                    await asyncio.sleep(max(0, self._start + self._pts / 48000 - time.time()))
                t = (self._pts + np.arange(960)) / 48000
                samples = (np.sin(2 * math.pi * 300 * t) * 8000).astype(np.int16).reshape(1, -1)
                frame = AudioFrame.from_ndarray(samples, format="s16", layout="mono")
                frame.sample_rate, frame.pts, frame.time_base = 48000, self._pts, fractions.Fraction(1, 48000)
                return frame

        return _Tone()


@pytest.fixture
def live_server(ws_session, monkeypatch, org_role):
    """The real app on a localhost port (WebRTC needs a real event loop and UDP sockets)."""
    monkeypatch.setattr(get_settings(), "webrtc_stun_urls", "")  # no internet needed
    from app.dependencies.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: USER
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    app.dependency_overrides.clear()


def test_webrtc_round_trip_mic_in_events_and_ai_voice_out(live_server, ws_session):
    from aiortc import RTCPeerConnection, RTCSessionDescription

    ws_session.agents.outputs.message = "Thanks. When did you move out?"

    async def scenario():
        pc = RTCPeerConnection()
        events, inbound = [], []
        got = {name: asyncio.Event() for name in ("started", "reply", "spoken", "ended")}
        channel = pc.createDataChannel("events")

        @channel.on("message")
        def on_message(message):
            event = json.loads(message)
            events.append(event)
            if event["type"] == "session_started":
                got["started"].set()
            elif event["type"] == "agent_response":
                got["reply"].set()
            elif event["type"] == "agent_speaking" and event["state"] == "stop":
                got["spoken"].set()
            elif event["type"] == "session_ended":
                got["ended"].set()

        @pc.on("track")
        def on_track(track):
            async def drain():
                while True:
                    try:
                        frame = await track.recv()
                    except Exception:
                        return
                    inbound.append(np.abs(frame.to_ndarray()).max())

            asyncio.ensure_future(drain())

        pc.addTrack(ToneTrack())
        await pc.setLocalDescription(await pc.createOffer())
        async with httpx.AsyncClient(base_url=live_server, timeout=30) as http:
            answer = (await http.post("/api/v1/webrtc/offer", json={
                "sdp": pc.localDescription.sdp, "type": "offer", "mode": "conversation", "voice": True,
            })).json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

        await asyncio.wait_for(got["started"].wait(), 15)
        await asyncio.sleep(0.7)  # microphone frames arrive, but the mic button isn't held
        got["transcribers_before_ptt"] = len(FakeTranscriber.instances)
        channel.send(json.dumps({"type": "ptt", "state": "start"}))
        await asyncio.sleep(1.0)  # let some microphone audio flow
        channel.send(json.dumps({"type": "ptt", "state": "stop"}))  # releasing finishes the utterance
        await asyncio.wait_for(got["reply"].wait(), 15)
        await asyncio.wait_for(got["spoken"].wait(), 15)
        await asyncio.sleep(0.3)
        channel.send(json.dumps({"type": "end"}))
        await asyncio.wait_for(got["ended"].wait(), 15)
        await pc.close()
        return answer, events, inbound, got["transcribers_before_ptt"]

    answer, events, inbound, got_transcribers_before_ptt = asyncio.run(scenario())

    assert answer["voice"] is True
    types = [e["type"] for e in events]
    assert types[0] == "session_started" and "agent_status" in types
    assert next(e for e in events if e["type"] == "agent_response")["message"] == "Thanks. When did you move out?"
    # Microphone audio reached speech-to-text as 16 kHz PCM, but only while the mic button was held.
    assert got_transcribers_before_ptt == 0
    transcriber = FakeTranscriber.instances[0]
    assert transcriber.finalized == 1
    assert transcriber.audio_format.sample_rate == 16000 and transcriber.bytes > 16000
    # The AI's voice came back over the audio track (the tone, not just silence).
    assert max(inbound) > 5000
    assert ws_session.seen["spoken"] == ["Thanks. When did you move out?"]
    assert ws_session.seen["saved"]["metadata"]["mode"] == "conversation"


def test_webrtc_offer_requires_membership_and_audio(live_server, org_role):
    org_role(None)
    response = httpx.post(f"{live_server}/api/v1/webrtc/offer", json={"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"})
    assert response.status_code == 403
    org_role("associate")
    response = httpx.post(f"{live_server}/api/v1/webrtc/offer", json={"sdp": "v=0\r\n"})
    assert response.status_code == 400
