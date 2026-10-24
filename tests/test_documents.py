import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.models.analysis import LiveAnalysis
from app.routers import audio_stream
from app.services import anthropic_service, document_service, pdf_service, prompt_engine, transcript_service
from app.services.document_service import DocumentContext, DocumentError

USER = CurrentUser(id="user-1", email="lawyer@example.com", access_token="good-token")
DOC_ID = str(uuid4())


def make_pdf(pages: list[str]) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    for text in pages:
        y = 800
        for line in text.splitlines():
            c.drawString(72, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buffer.getvalue()


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


# ----------------------------------------------------------------------------- extraction


def test_extracts_pdf_text_with_page_markers():
    data = make_pdf(["1. Rent is 1,000 per month.", "7.2 The deposit is returned within 21 days."])
    result = document_service.extract_text("lease.pdf", "application/pdf", data)
    assert result.page_count == 2
    assert result.content_type == "application/pdf"
    assert "[Page 2]" in result.text and "within 21 days" in result.text


def test_rejects_pdf_without_text():
    with pytest.raises(DocumentError, match="No readable text"):
        document_service.extract_text("scan.pdf", "application/pdf", make_pdf([""]))


def test_rejects_fake_pdf_and_unknown_types():
    with pytest.raises(DocumentError, match="not a valid PDF"):
        document_service.extract_text("lease.pdf", "application/pdf", b"hello there, not a pdf")
    with pytest.raises(DocumentError, match="Unsupported"):
        document_service.extract_text("lease.docx", "application/octet-stream", b"PK\x03\x04....")


def test_plain_text_is_decoded_and_normalized():
    result = document_service.extract_text("nda.txt", "text/plain", "Clause 1\r\n\r\n\r\n\r\nConfidential info ‘defined’.".encode())
    assert result.text == "Clause 1\n\nConfidential info ‘defined’."


def test_clean_filename_strips_paths():
    assert document_service.clean_filename("C:\\Users\\x\\..\\lease.pdf") == "lease.pdf"
    assert document_service.clean_filename(None) == "document"


# ----------------------------------------------------------------------------- prompt context


def test_short_documents_go_into_prompts_whole():
    doc = DocumentContext(DOC_ID, "lease.pdf", "1. Rent is due monthly.\n2. Deposit returned in 21 days.")
    assert doc.is_complete
    assert doc.prompt_text("anything") == doc.text


def test_long_documents_are_cut_to_relevant_clauses():
    filler = [f"{n}. The tenant shall maintain the garden and lawns in tidy condition." for n in range(1, 60)]
    deposit = "60. The security deposit shall be returned within twenty-one days with an itemized statement."
    doc = DocumentContext(DOC_ID, "lease.pdf", "\n".join(filler + [deposit]))
    excerpt = doc.prompt_text("Client: my landlord kept my security deposit and sent no itemized statement", max_chars=400)
    assert excerpt.startswith("[Excerpt:")
    assert "security deposit shall be returned" in excerpt
    assert len(excerpt) < 700


def test_contract_goes_in_a_cached_system_block():
    doc = DocumentContext(DOC_ID, 'lease "final".pdf', "7.2 Deposit returned within 21 days.")
    system = prompt_engine.build_system("BASE", contract_instructions=" CONTRACT RULES", document=doc, conversation="c")
    assert system[0]["text"].startswith("BASE CONTRACT RULES")
    assert system[1]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["text"].startswith("<contract filename=\"lease 'final'.pdf\">")
    assert prompt_engine.build_system("BASE", contract_instructions=" CONTRACT RULES") == "BASE"


# ----------------------------------------------------------------------------- upload endpoint


def test_upload_extracts_and_saves_as_user(client, monkeypatch):
    saved = {}

    def save(access_token, row, org_id=None):
        saved.update(row, token=access_token)
        return {**row, "id": DOC_ID, "created_at": "2026-10-19T10:00:00+00:00"}

    monkeypatch.setattr(document_service, "save_document", save)
    pdf = make_pdf(["7.2 The deposit is returned within 21 days."])
    response = client.post("/api/v1/documents/upload", files={"file": ("../../lease.pdf", pdf, "application/pdf")})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == DOC_ID and body["filename"] == "lease.pdf" and body["page_count"] == 1
    assert "extracted_text" not in body and "21 days" in body["preview"]
    assert saved["token"] == "good-token" and saved["user_id"] == "user-1"
    assert "21 days" in saved["extracted_text"]


def test_upload_rejects_unreadable_and_oversized_files(client, monkeypatch):
    response = client.post("/api/v1/documents/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert response.status_code == 422 and "valid PDF" in response.json()["detail"]

    monkeypatch.setattr(document_service, "MAX_UPLOAD_BYTES", 10)
    response = client.post("/api/v1/documents/upload", files={"file": ("x.txt", b"a" * 11, "text/plain")})
    assert response.status_code == 413


def test_upload_requires_auth():
    response = TestClient(app).post("/api/v1/documents/upload", files={"file": ("x.txt", b"hello world " * 5, "text/plain")})
    assert response.status_code == 401


# ----------------------------------------------------------------------------- PDF report


TRANSCRIPT = {
    "id": str(uuid4()),
    "user_id": "user-1",
    "document_id": DOC_ID,
    "title": "Deposit dispute <script>",
    "content": "Speaker 1: What happened?\nSpeaker 2: My landlord kept the deposit & sent nothing.",
    "summary": "Overview:\nDeposit withheld.\n\nSuggested Next Steps:\nSend a demand letter.",
    "source": "live_stream",
    "created_at": "2026-10-19T11:42:00+00:00",
    "metadata": {
        "started_at": "2026-10-19T11:05:00+00:00",
        "ended_at": "2026-10-19T11:41:00+00:00",
        "analysis": {
            "key_facts": [{"fact": "Deposit of $2,400 withheld", "category": "money"}],
            "legal_issues": [{"issue": "Return deadline missed", "severity": "high", "area_of_law": "Landlord-tenant"}],
            "follow_up_questions": ["Do you have the move-in checklist?"],
            "contract_observations": [{"clause": "7.2", "observation": "21-day return not met", "alignment": "conflict"}],
        },
    },
}


def test_pdf_report_contains_every_section():
    pdf = pdf_service.build_transcript_report(TRANSCRIPT, {"filename": "lease.pdf", "page_count": 3})
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    for expected in [
        "Deposit dispute <script>", "Duration", "36 min", "lease.pdf, 3 pages",
        "Legal Risks", "HIGH", "Return deadline missed", "Contract Cross-Reference", "Conflict",
        "Key Facts", "Deposit of $2,400 withheld", "Follow-up Recommendations", "move-in checklist",
        "Speaker 2:", "deposit & sent nothing",
    ]:
        assert expected in text, expected


def test_pdf_report_handles_a_bare_transcript():
    pdf = pdf_service.build_transcript_report({"id": "x", "title": None, "content": "", "metadata": None})
    assert pdf.startswith(b"%PDF")


def test_pdf_endpoint_streams_report(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: seen.setdefault("id", tid) and TRANSCRIPT)
    monkeypatch.setattr(document_service, "get_document", lambda token, did, **kw: {"filename": "lease.pdf", "page_count": 3})

    response = client.get(f"/api/v1/transcripts/{TRANSCRIPT['id']}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="deposit-dispute-script-2026-10-19.pdf"'
    assert response.content.startswith(b"%PDF")
    assert seen["id"] == TRANSCRIPT["id"]


def test_pdf_endpoint_404s_for_other_users_transcripts(client, monkeypatch):
    # RLS returns no row for someone else's transcript.
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: None)
    assert client.get(f"/api/v1/transcripts/{uuid4()}/pdf").status_code == 404
    assert client.get("/api/v1/transcripts/not-a-uuid/pdf").status_code == 422


def test_pdf_endpoint_requires_auth():
    assert TestClient(app).get(f"/api/v1/transcripts/{uuid4()}/pdf").status_code == 401


# ----------------------------------------------------------------------------- live session


def test_attached_contract_reaches_analysis_summary_and_saved_row(monkeypatch, fake_agents):
    seen = {"summary": [], "saved": None}
    document_row = {"id": DOC_ID, "filename": "lease.pdf", "extracted_text": "7.2 Deposit returned in 21 days."}

    async def summarize(transcript, analysis, document_context=None, **context):
        seen["summary"].append(document_context)
        from app.models.analysis import ConsultationSummary

        return ConsultationSummary(title="t", summary="s")

    def get_document(token, document_id, include_text=False, org_id=None):
        assert (token, include_text) == ("good-token", True)
        return document_row if document_id == DOC_ID else None

    def save(token, user_id, row):
        seen["saved"] = row
        return {"id": "transcript-1", **row}

    monkeypatch.setattr(audio_stream, "verify_access_token", lambda token: USER)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(document_service, "get_document", get_document)
    monkeypatch.setattr(transcript_service, "save_live_session", save)
    monkeypatch.setattr("app.services.n8n_service.is_configured", lambda: False)

    def receive_until(ws, message_type):
        while (message := ws.receive_json())["type"] != message_type:
            pass
        return message

    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "document_id": str(uuid4())})
        assert receive_until(ws, "error")["code"] == "document_not_found"
        ws.send_json({"type": "start", "document_id": DOC_ID})
        attached = receive_until(ws, "document_attached")
        assert attached["filename"] == "lease.pdf" and attached["complete_in_context"] is True
        ws.send_json({"type": "transcript_chunk", "text": "He kept my deposit."})
        receive_until(ws, "analysis")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")

    # The risk evaluator is the agent that cross-references the contract.
    assert fake_agents.calls["risk"][0]["document_context"].document_id == DOC_ID
    assert seen["summary"][0].filename == "lease.pdf"
    assert seen["saved"]["document_id"] == DOC_ID
