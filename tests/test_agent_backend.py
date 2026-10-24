"""Phase 5: LangGraph agents, PII guardrails, output safety, OCR and case memory."""

import asyncio
import base64
import io
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.core import guardrails
from app.core.config import get_settings
from app.core.guardrails import LEGAL_DISCLAIMER, PiiMasker, mask_pii, verify_output_safety
from app.dependencies.auth import CurrentUser
from app.main import app
from app.models.analysis import ConsultationSummary, VisionExtraction
from app.routers import audio_stream
from app.services import (
    agent_workflow,
    anthropic_service,
    document_service,
    memory_service,
    n8n_service,
    ocr_service,
    rag_service,
    transcript_service,
)
from app.services.agent_workflow import AgentContext
from app.services.memory_service import CaseMemory
from app.services.rag_service import Precedent

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="lawyer@acme.law", access_token="good-token")
THREAD_ID = "77777777-7777-7777-7777-777777777777"
SSN = "536-22-8172"  # valid-format test SSN (Presidio rejects well-known fake ones)
AADHAAR = "2345 6789 0124"  # passes the Verhoeff checksum


def precedent(n: int, similarity: float = 0.8) -> Precedent:
    return Precedent(id=f"chunk-{n}", source_id=f"src-{n}", title=f"Authority {n}", content=f"Text {n}", similarity=similarity)


# ============================================================================ LangGraph orchestration


class Recorder:
    def __init__(self, research_results=()):
        self.statuses: list[str] = []
        self.queries: list[str] = []
        self.research_results = list(research_results)

    async def emit(self, stage, message):
        self.statuses.append(stage)

    async def research(self, query):
        self.queries.append(query)
        return self.research_results.pop(0) if self.research_results else None


def run_agents(state, **context):
    return asyncio.run(agent_workflow.process_audio_chunk_via_agent(state, AgentContext(**context)))


def test_first_pass_runs_every_agent_in_order(fake_agents):
    recorder = Recorder(research_results=[[precedent(1, 0.9), precedent(2, 0.7)]])
    result = run_agents(
        {"transcript_history": "Client: I was fired on 3 March.", "current_chunk": "Client: I was fired on 3 March."},
        research=recorder.research, emit_status=recorder.emit,
    )

    assert recorder.statuses == ["intake_analyzer", "legal_researcher", "risk_evaluator", "drafter"]
    assert result["extracted_facts"] == [{"fact": "Fired on 3 March", "category": "date"}]
    assert [c["id"] for c in result["rag_citations"]] == ["chunk-1", "chunk-2"]
    assert result["legal_risks"][0]["severity"] == "high"
    final = result["final_response"]
    assert final["message"] == "Ask whether there is a written employment contract."
    assert final["analysis"]["follow_up_questions"] == ["Do you have a written contract?"]
    # The researcher searched with the new speech and the extracted facts.
    assert "Case facts: Fired on 3 March" in recorder.queries[0]
    # The risk evaluator saw the citations the researcher found.
    assert [p.id for p in fake_agents.calls["risk"][0]["precedents"]] == ["chunk-1", "chunk-2"]


def test_risk_evaluation_is_skipped_when_nothing_changed(fake_agents):
    first = run_agents({"transcript_history": "x", "current_chunk": "x"})
    recorder = Recorder()  # research is rate-limited: returns None
    state = {k: first[k] for k in ("extracted_facts", "legal_risks", "rag_citations", "follow_up_questions") if k in first}
    second = run_agents({**state, "transcript_history": "x y", "current_chunk": "y"}, research=recorder.research, emit_status=recorder.emit)

    assert recorder.statuses == ["intake_analyzer", "legal_researcher", "drafter"]
    assert second["legal_risks"] == first["legal_risks"]  # carried over unchanged
    assert len(fake_agents.calls["risk"]) == 1


def test_new_facts_trigger_risk_evaluation_again(fake_agents):
    from app.models.analysis import KeyFact

    first = run_agents({"transcript_history": "x", "current_chunk": "x"})
    fake_agents.outputs.facts = [KeyFact(fact="Fired on 3 March"), KeyFact(fact="No written warning given")]
    run_agents({"extracted_facts": first["extracted_facts"], "legal_risks": first["legal_risks"], "current_chunk": "y"})
    assert len(fake_agents.calls["risk"]) == 2


def test_a_failing_agent_keeps_the_previous_analysis(fake_agents, monkeypatch):
    previous_risk = {"issue": "Earlier issue", "severity": "low", "area_of_law": None, "rationale": None, "authority": None}

    async def broken(*args, **kwargs):
        raise anthropic_service.AIServiceError("Claude API error 529: overloaded")

    monkeypatch.setattr(anthropic_service, "evaluate_legal_risks", broken)
    result = run_agents({"legal_risks": [previous_risk], "current_chunk": "new speech"})

    assert result["legal_risks"] == [previous_risk]
    assert result["errors"] == ["risk_evaluator: Claude API error 529: overloaded"]
    assert result["final_response"]["message"]  # the drafter still ran


def test_drafted_directives_get_the_disclaimer(fake_agents):
    fake_agents.outputs.message = "You should sue the employer immediately. You will win this case."
    final = run_agents({"current_chunk": "x"})["final_response"]
    assert final["disclaimer_appended"] is True
    assert final["message"].endswith(LEGAL_DISCLAIMER)
    assert set(final["safety_flags"]) == {"directive", "guarantee"}


def test_case_memory_reaches_every_agent(fake_agents):
    run_agents({"current_chunk": "x", "case_memory": "Session of 12 Oct 2026:\nClient reported the theft."})
    for node in ("intake", "risk", "draft"):
        assert fake_agents.calls[node][0]["case_memory"].endswith("Client reported the theft.")


# ============================================================================ PII masking


def test_mask_pii_replaces_identifiers_with_labels_and_keeps_names():
    text = (
        f"Ravi Kumar says his SSN is {SSN}, card 4111 1111 1111 1111, account number 123456789012, "
        f"Aadhaar {AADHAAR}, PAN ABCPE1234F, email ravi.k@example.com, phone 212-555-0187."
    )
    result = mask_pii(text, PiiMasker())
    assert result.text == (
        "Ravi Kumar says his SSN is [CLIENT_SSN], card [CARD_NUMBER], account number [BANK_ACCT], "
        "Aadhaar [NATIONAL_ID], PAN [TAX_ID], email [EMAIL], phone [PHONE]."
    )
    assert {e["type"] for e in result.entities} >= {"US_SSN", "CREDIT_CARD", "IN_AADHAAR", "IN_PAN", "EMAIL_ADDRESS"}


def test_indian_identifiers_are_masked_even_without_a_valid_checksum():
    masker = PiiMasker()
    # An Aadhaar-shaped number with a wrong checksum (a typo, a speech-to-text slip) still identifies someone.
    text = mask_pii("Mera Aadhaar 2345 6789 0123 hai aur maine usse 9876543210 se WhatsApp kiya tha", masker).text
    assert text == "Mera Aadhaar [NATIONAL_ID] hai aur maine usse [PHONE] se WhatsApp kiya tha"
    # The same mobile number in other formats keeps its placeholder; amounts and dates are left alone.
    again = mask_pii("call +91 98765 43210 or 098765-43210 about the 50,000 rupees from 3 March 2026", masker).text
    assert again == "call [PHONE] or [PHONE] about the 50,000 rupees from 3 March 2026"


def test_placeholders_stay_consistent_within_a_session():
    masker = PiiMasker()
    first = mask_pii("My account number is 123456789012.", masker).text
    second = mask_pii("The other account number is 987654321098, not 1234 5678 9012.", masker).text
    assert first == "My account number is [BANK_ACCT]."
    assert second == "The other account number is [BANK_ACCT_2], not [BANK_ACCT]."


def test_masking_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "pii_masking_enabled", False)
    assert mask_pii(f"SSN {SSN}").text == f"SSN {SSN}"


@pytest.fixture
def ws_fakes(monkeypatch, fake_agents):
    seen = {"summary": None, "saved": None, "recorded": None}

    async def summarize(transcript, analysis, document_context=None, practice_area=None, precedents=None, case_memory=None, **context):
        seen["summary"] = {"transcript": transcript, "case_memory": case_memory}
        return ConsultationSummary(title="Identity theft", summary=f"Client reported misuse of {transcript[-40:]}")

    def save(token, user_id, row):
        seen["saved"] = row
        return {"id": "transcript-9", **row}

    monkeypatch.setattr(audio_stream, "verify_access_token", lambda token: USER)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(transcript_service, "save_live_session", save)
    monkeypatch.setattr(n8n_service, "is_configured", lambda: False)
    return SimpleNamespace(seen=seen, agents=fake_agents)


def receive_until(ws, message_type, collected=None):
    while True:
        message = ws.receive_json()
        if collected is not None:
            collected.append(message)
        if message["type"] == message_type:
            return message


def test_pii_never_reaches_the_models_but_is_kept_in_the_record(ws_fakes):
    spoken = f"Someone opened a loan with my SSN {SSN} and drained account number 123456789012."
    collected = []
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": spoken})
        chunk = receive_until(ws, "chunk_received", collected)
        receive_until(ws, "agent_response", collected)
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended", collected)

    # The lawyer's UI shows what was said, plus which placeholders the AI got instead.
    assert chunk["text"] == spoken and chunk["redactions"] == ["[CLIENT_SSN]", "[BANK_ACCT]"]
    # Every model input was masked.
    agent_inputs = json.dumps([c["current_chunk"] + c["transcript_history"] for c in ws_fakes.agents.calls["intake"]])
    assert SSN not in agent_inputs and "123456789012" not in agent_inputs
    assert "[CLIENT_SSN]" in agent_inputs
    assert SSN not in ws_fakes.seen["summary"]["transcript"]
    # The firm's own record keeps the original.
    assert SSN in ws_fakes.seen["saved"]["content"]
    assert ws_fakes.seen["saved"]["metadata"]["pii_redactions"] == 2
    # The thinking UI saw each agent start, then idle.
    stages = [m["stage"] for m in collected if m["type"] == "agent_status"]
    assert stages[:4] == ["intake_analyzer", "legal_researcher", "risk_evaluator", "drafter"] and stages[4] == "idle"


def test_masking_failure_stops_ai_analysis(ws_fakes, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("spaCy model missing")

    monkeypatch.setattr("app.services.live_session.mask_pii", broken)
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "transcript_chunk", "text": f"My SSN is {SSN}."})
        assert receive_until(ws, "error")["code"] == "pii_masking_failed"
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")
    assert ws_fakes.agents.calls["intake"] == []
    assert ws_fakes.seen["summary"] is None


def test_attached_contracts_are_masked_before_the_agents_see_them(ws_fakes, monkeypatch):
    doc_id = "88888888-8888-8888-8888-888888888888"
    monkeypatch.setattr(
        document_service, "get_document",
        lambda token, did, include_text=False, org_id=None: {"id": doc_id, "filename": "loan.pdf",
                                                            "extracted_text": "Repayments from IBAN GB82 WEST 1234 5698 7654 32 monthly."},
    )
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "document_id": doc_id})
        assert receive_until(ws, "document_attached")["pii_redactions"] == 1
        ws.send_json({"type": "transcript_chunk", "text": "The bank says I missed payments."})
        receive_until(ws, "analysis")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")
    contract = ws_fakes.agents.calls["risk"][0]["document_context"].text
    assert contract == "Repayments from IBAN [BANK_ACCT] monthly."


# ============================================================================ output safety


@pytest.mark.parametrize(
    "text, flagged",
    [
        ("You should sue the landlord before Friday.", True),
        ("Do not sign the settlement agreement.", True),
        ("I advise you to plead guilty.", True),
        ("You will win at trial.", True),
        ("This is definitely illegal.", True),
        ("You have an open-and-shut case.", True),
        ("The lawyer may want to confirm whether notice was served in writing.", False),
        ("One option is to request the CCTV footage; the limitation period should be checked.", False),
        ("The client said they will win the contract bid next month.", False),
    ],
)
def test_output_safety_flags_directives_not_information(text, flagged):
    result = verify_output_safety(text)
    assert result.flagged is flagged
    assert result.text.endswith(LEGAL_DISCLAIMER) is flagged


def test_disclaimer_is_not_added_twice():
    once = verify_output_safety("You must file the complaint.").text
    again = verify_output_safety(once)
    assert again.text == once and again.disclaimer_appended is False


# ============================================================================ OCR


def text_image(lines, size=(1700, 1100), font_size=40) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except OSError:
            font = ImageFont.load_default(size=font_size)
    for i, line in enumerate(lines):
        draw.text((80, 80 + i * int(font_size * 1.8)), line, fill="black", font=font)
    return image


needs_tesseract = pytest.mark.skipif(not ocr_service.tesseract_available(), reason="Tesseract is not installed")
FIR_LINES = ["FIRST INFORMATION REPORT", "Police Station: Andheri East", "Complainant: Ravi Kumar", "Motorcycle stolen on 12 March 2026"]


@needs_tesseract
def test_ocr_reads_a_sample_image():
    text, confidence = ocr_service.ocr_image(text_image(FIR_LINES))
    assert "FIRST INFORMATION REPORT" in text
    assert "Andheri East" in text and "Ravi Kumar" in text
    assert confidence > 80


@needs_tesseract
def test_scanned_pdf_upload_is_routed_through_ocr(monkeypatch):
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: False)  # no vision: pure OCR
    buffer = io.BytesIO()
    text_image(FIR_LINES).save(buffer, format="PDF", resolution=200)
    extracted = document_service.extract_text("fir.pdf", "application/pdf", buffer.getvalue())
    assert extracted.extraction["methods"] == {"ocr": 1}
    assert "Motorcycle stolen on 12 March 2026" in extracted.text


@needs_tesseract
def test_photographed_document_upload_is_ocrd(monkeypatch):
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: False)
    buffer = io.BytesIO()
    text_image(FIR_LINES).convert("L").save(buffer, format="JPEG", quality=85)
    extracted = document_service.extract_text("fir.jpg", "image/jpeg", buffer.getvalue())
    assert extracted.content_type == "image/jpeg" and "Ravi Kumar" in extracted.text


def test_pages_ocr_cannot_read_go_to_claude_vision(monkeypatch):
    monkeypatch.setattr(ocr_service, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr_service, "ocr_image", lambda image: ("Rv Kmr st0l3n", 31.0))  # messy handwriting
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    sent = []

    def vision(image_bytes, media_type):
        sent.append(media_type)
        return VisionExtraction(text="Ravi Kumar - motorcycle stolen", contains_handwriting=True, legibility="medium")

    monkeypatch.setattr(anthropic_service, "extract_text_from_image", vision)
    page = ocr_service.read_page_image(text_image(["scribble"]), 1)
    assert (page.method, page.text) == ("vision", "Ravi Kumar - motorcycle stolen")
    assert sent == ["image/jpeg"]


def test_without_vision_low_confidence_ocr_is_kept(monkeypatch):
    monkeypatch.setattr(ocr_service, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr_service, "ocr_image", lambda image: ("Rv Kmr st0l3n bike on 12 Mar", 31.0))
    monkeypatch.setattr(get_settings(), "ocr_vision_fallback", False)
    page = ocr_service.read_page_image(text_image(["scribble"]), 1)
    assert (page.method, page.confidence) == ("ocr", 31.0)


def test_vision_budget_caps_pages_sent_to_claude(monkeypatch):
    monkeypatch.setattr(ocr_service, "tesseract_available", lambda: False)
    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    monkeypatch.setattr(get_settings(), "ocr_vision_max_pages", 2)
    monkeypatch.setattr(anthropic_service, "extract_text_from_image", lambda b, m: VisionExtraction(text="page text"))
    budget = ocr_service._VisionBudget()
    methods = [ocr_service.read_page_image(text_image(["x"]), n, budget).method for n in range(1, 5)]
    assert methods == ["vision", "vision", "none", "none"]


def test_vision_request_sends_the_image_to_the_configured_model(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        seen["beta"] = request.headers.get("anthropic-beta")
        body = json.dumps({"text": "Handwritten FIR text", "contains_handwriting": True, "legibility": "low", "notes": None})
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": seen["model"],
            "content": [{"type": "text", "text": body}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    client = anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(anthropic_service, "_sync_client", client)
    result = anthropic_service.extract_text_from_image(b"\xff\xd8\xff fake jpeg", "image/jpeg")

    assert result.legibility == "low" and result.contains_handwriting
    image_block = seen["messages"][0]["content"][0]
    assert image_block["type"] == "image" and image_block["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image_block["source"]["data"]) == b"\xff\xd8\xff fake jpeg"
    assert seen["model"] == get_settings().anthropic_vision_model
    assert seen["fallbacks"] == "default" and seen["beta"] == anthropic_service.FALLBACK_BETA


# ============================================================================ case memory


def test_case_memory_lists_sessions_oldest_first_and_drops_the_oldest_over_budget():
    sessions = [
        {"content": f"Summary {n}.", "metadata": {"started_at": f"2026-10-0{n}T10:00:00+00:00", "open_questions": [f"Q{n}?"]}}
        for n in range(1, 5)
    ]
    full = memory_service.format_case_memory("Kumar - stolen motorcycle", sessions, max_chars=10_000)
    assert full.index("Summary 1.") < full.index("Summary 4.")
    assert "Session of 04 Oct 2026:\nSummary 4.\nOpen questions then: Q4?" in full

    tight = memory_service.format_case_memory("Kumar - stolen motorcycle", sessions, max_chars=150)
    assert "Summary 4." in tight and "Summary 1." not in tight
    assert "earlier session(s) omitted]" in tight


def test_first_session_in_a_thread_says_so():
    assert "first recorded session" in memory_service.format_case_memory("New matter", [], 1000)


def test_thread_memory_is_loaded_into_the_agents_and_the_session_is_recorded(ws_fakes, monkeypatch):
    recorded = {}
    monkeypatch.setattr(
        memory_service, "load_case_memory",
        lambda db, thread_id: CaseMemory(thread_id, "Kumar - identity theft", "Session of 14 Oct 2026:\nClient first reported the loan.", 1)
        if thread_id == THREAD_ID else None,
    )
    monkeypatch.setattr(memory_service, "record_session", lambda db, thread_id, **kw: recorded.update(thread_id=thread_id, **kw))

    with TestClient(app).websocket_connect(f"/api/v1/ws/audio?token=good-token&thread_id={THREAD_ID}") as ws:
        ws.receive_json()
        loaded = receive_until(ws, "case_memory_loaded")
        assert (loaded["title"], loaded["previous_sessions"]) == ("Kumar - identity theft", 1)
        ws.send_json({"type": "transcript_chunk", "text": f"Since last week they also used my SSN {SSN}."})
        receive_until(ws, "agent_response")
        ws.send_json({"type": "end"})
        ended = receive_until(ws, "session_ended")

    assert ws_fakes.agents.calls["intake"][0]["case_memory"].endswith("Client first reported the loan.")
    assert ws_fakes.seen["summary"]["case_memory"].startswith("Session of 14 Oct 2026")
    assert ws_fakes.seen["saved"]["thread_id"] == THREAD_ID and ended["thread_id"] == THREAD_ID
    assert recorded["thread_id"] == THREAD_ID and recorded["transcript_id"] == "transcript-9"
    # What the thread remembers comes from the masked transcript.
    assert SSN not in recorded["summary"]


def test_unknown_thread_is_reported_and_not_recorded(ws_fakes, monkeypatch):
    monkeypatch.setattr(memory_service, "load_case_memory", lambda db, thread_id: None)
    recorded = []
    monkeypatch.setattr(memory_service, "record_session", lambda *a, **k: recorded.append(k))
    with TestClient(app).websocket_connect(f"/api/v1/ws/audio?token=good-token&thread_id={THREAD_ID}") as ws:
        ws.receive_json()
        assert receive_until(ws, "error")["code"] == "thread_not_found"
        ws.send_json({"type": "transcript_chunk", "text": "Hello."})
        receive_until(ws, "analysis")
        ws.send_json({"type": "end"})
        assert receive_until(ws, "session_ended")["thread_id"] is None
    assert recorded == []


def test_account_numbers_said_in_groups_are_masked():
    masker = PiiMasker()
    assert mask_pii("mera account number 1234 5678 9012 hai", masker).text == "mera account number [BANK_ACCT] hai"
    # Times, amounts and case numbers are left alone.
    for text in ("He paid 50,000 at 10 30", "case number 12 of 2024", "account mein 2 lakh the"):
        assert mask_pii(text, masker).text == text
