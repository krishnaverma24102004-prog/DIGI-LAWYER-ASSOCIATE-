"""Phase 4: legal RAG, practice-area prompt injection, RBAC and audit logging.

Database-level behaviour (RLS, tenant isolation, pgvector search) is tested against a real
Postgres in tests/db/test_rls_policies.py; these tests cover the application layer.
"""

import json
import os
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.rbac import Permission, Role, can_manage, has_permission
from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.models.analysis import ConsultationSummary, LiveAnalysis
from app.models.practice_area import RiskEvaluationRules
from app.routers import audio_stream
from app.services import (
    anthropic_service,
    audit_service,
    n8n_service,
    org_service,
    prompt_engine,
    rag_service,
    safety_service,
    transcript_service,
)
from app.services.document_service import DocumentContext
from app.services.prompt_engine import PracticeAreaProfile
from app.services.rag_service import Embedder, Precedent, RagError
from tests.conftest import ORG_ID

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="partner@acme.law", access_token="good-token")
OTHER_USER = "22222222-2222-2222-2222-222222222222"


def precedent(n: int, similarity: float, source: str | None = None, **metadata) -> Precedent:
    return Precedent(
        id=f"chunk-{n}",
        source_id=source or f"source-{n}",
        title=f"Authority {n}",
        content=f"Text of authority {n}.",
        similarity=similarity,
        metadata=metadata,
    )


# ============================================================================ RAG: chunking


def test_chunking_respects_size_and_overlaps():
    paragraph = "The landlord shall return the deposit within 21 days of the end of the tenancy. " * 6
    text = "\n\n".join(f"Section {n}. {paragraph}" for n in range(1, 9))
    chunks = rag_service.chunk_text(text, max_chars=1200, overlap=150)

    assert len(chunks) > 3
    assert all(len(c) <= 1200 for c in chunks)
    # Each chunk after the first repeats the end of the previous one.
    for previous, current in zip(chunks, chunks[1:]):
        assert previous[-60:].split()[-1] in current[:200]


def test_chunking_keeps_short_texts_whole_and_ignores_blank_input():
    assert rag_service.chunk_text("Short statute text.") == ["Short statute text."]
    assert rag_service.chunk_text("   \n\n ") == []


# ============================================================================ RAG: ingestion and retrieval


class FakeEmbedder:
    def __init__(self, dims=4):
        self.dims = dims
        self.passages: list[str] = []
        self.queries: list[str] = []

    def embed_passages(self, texts):
        self.passages.extend(texts)
        return [[float(len(t) % 7), 1.0, 0.0, 0.5][: self.dims] for t in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return [0.1, 0.2, 0.3, 0.4][: self.dims]


class FakeKnowledgeDB:
    """Records what rag_service sends to Supabase."""

    def __init__(self, rpc_rows=None, fail_on_insert_batch=None):
        self.inserted, self.deleted, self.rpc_calls = [], [], []
        self.rpc_rows = rpc_rows or []
        self.fail_on_insert_batch = fail_on_insert_batch
        self.insert_batches = 0

    def table(self, name):
        assert name == "legal_knowledge_base"
        return FakeQuery(self)

    def rpc(self, function, params):
        self.rpc_calls.append((function, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.rpc_rows))


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def insert(self, rows):
        self.db.insert_batches += 1
        if self.db.insert_batches == self.db.fail_on_insert_batch:
            raise RuntimeError("connection reset")
        self.db.inserted.extend(rows)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))

    def delete(self):
        return self

    def eq(self, column, value):
        self.db.deleted.append((column, value))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


def test_ingest_chunks_embeds_and_stores_rows_for_the_org(monkeypatch):
    monkeypatch.setattr(rag_service, "INSERT_BATCH_SIZE", 2)
    db, embedder = FakeKnowledgeDB(), FakeEmbedder()
    text = "\n\n".join(f"Paragraph {n}. " + "Notice must be given in writing. " * 30 for n in range(5))

    result = rag_service.ingest_legal_statutes_and_precedents(
        ORG_ID, "Housing Act 1988", text, db=db, created_by=USER.id,
        metadata={"citation": "1988 c. 50", "jurisdiction": "England & Wales", "source_url": None},
        embedder=embedder,
    )

    assert result.chunk_count == len(db.inserted) > 2
    assert db.insert_batches == (result.chunk_count + 1) // 2
    assert {row["source_id"] for row in db.inserted} == {result.source_id}
    assert [row["chunk_index"] for row in db.inserted] == list(range(result.chunk_count))
    first = db.inserted[0]
    assert first["org_id"] == ORG_ID and first["created_by"] == USER.id and first["title"] == "Housing Act 1988"
    assert first["metadata"] == {"citation": "1988 c. 50", "jurisdiction": "England & Wales", "chunk_count": result.chunk_count}
    assert len(first["vector_embedding"]) == 4
    # The title is embedded with every chunk, but only the chunk text is stored.
    assert all(p.startswith("Housing Act 1988\n\n") for p in embedder.passages)
    assert not first["content"].startswith("Housing Act 1988")


def test_failed_ingest_removes_the_partial_source(monkeypatch):
    monkeypatch.setattr(rag_service, "INSERT_BATCH_SIZE", 1)
    db = FakeKnowledgeDB(fail_on_insert_batch=2)
    text = "\n\n".join("Clause text that is fairly long. " * 40 for _ in range(3))
    with pytest.raises(RuntimeError):
        rag_service.ingest_legal_statutes_and_precedents(ORG_ID, "Lease precedent", text, db=db, embedder=FakeEmbedder())
    assert db.deleted and db.deleted[0][0] == "source_id"


def test_ingest_rejects_empty_text_and_missing_title():
    with pytest.raises(RagError):
        rag_service.ingest_legal_statutes_and_precedents(ORG_ID, "Title", "   ", db=FakeKnowledgeDB(), embedder=FakeEmbedder())
    with pytest.raises(RagError):
        rag_service.ingest_legal_statutes_and_precedents(ORG_ID, " ", "text", db=FakeKnowledgeDB(), embedder=FakeEmbedder())


def test_retrieval_queries_the_rpc_and_keeps_the_best_passage_per_source(monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_match_threshold", 0.6)
    rows = [
        {"id": "a1", "source_id": "act", "title": "Housing Act", "content": "s.21 notice", "similarity": 0.91, "chunk_index": 3, "metadata": {"citation": "s.21"}},
        {"id": "a2", "source_id": "act", "title": "Housing Act", "content": "s.8 grounds", "similarity": 0.80, "chunk_index": 1, "metadata": {}},
        {"id": "b1", "source_id": "case", "title": "Smith v Jones", "content": "deposit held", "similarity": 0.85, "chunk_index": 0, "metadata": {}},
        {"id": "c1", "source_id": "memo", "title": "Firm memo", "content": "checklist", "similarity": 0.70, "chunk_index": 0, "metadata": {}},
    ]
    db, embedder = FakeKnowledgeDB(rpc_rows=rows), FakeEmbedder()
    transcript = "Client: my landlord served a section 21 notice and kept my deposit."

    found = rag_service.retrieve_relevant_precedents(ORG_ID, transcript, top_k=2, db=db, embedder=embedder)

    assert [p.id for p in found] == ["a1", "b1"]  # best per source, highest first, capped at top_k
    function, params = db.rpc_calls[0]
    assert function == "match_legal_precedents"
    assert params == {"query_embedding": [0.1, 0.2, 0.3, 0.4], "match_threshold": 0.6, "match_count": 6,
                      "target_org_id": ORG_ID, "filter_jurisdictions": None}
    assert embedder.queries == [transcript]
    assert found[0].citation()["citation"] == "s.21"


def test_retrieval_skips_trivially_short_text():
    db = FakeKnowledgeDB()
    assert rag_service.retrieve_relevant_precedents(ORG_ID, "uh, okay", db=db, embedder=FakeEmbedder()) == []
    assert db.rpc_calls == []


def test_embedder_rejects_a_model_with_the_wrong_dimension():
    embedder = Embedder("some/model", dimensions=768)
    embedder._model = SimpleNamespace(query_embed=lambda text: [SimpleNamespace(tolist=lambda: [0.0] * 384)])
    with pytest.raises(RagError, match="384 dimensions"):
        embedder.embed_query("hello")


@pytest.mark.skipif(not os.getenv("RUN_EMBEDDING_TESTS"), reason="downloads the embedding model; set RUN_EMBEDDING_TESTS=1")
def test_real_embeddings_rank_the_relevant_statute_first():
    """End-to-end check of the actual fastembed model and its dimension."""
    import math

    embedder = rag_service.get_embedder()
    passages = [
        "A landlord must return a tenancy deposit within 21 days of the end of the tenancy, with an itemised list of deductions.",
        "A company must file its annual accounts with the registrar within nine months of its financial year end.",
        "A person arrested must be informed of the reason for the arrest and of the right to legal advice.",
    ]
    vectors = embedder.embed_passages(passages)
    query = embedder.embed_query("My landlord has not given back my deposit and it has been a month since I moved out")

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    scores = [cosine(query, v) for v in vectors]
    assert len(query) == get_settings().embedding_dimensions
    assert scores.index(max(scores)) == 0


# ============================================================================ prompt engine


PI_PROFILE = PracticeAreaProfile(
    id="pa-1",
    name="Personal Injury",
    custom_system_prompt="Focus on liability and damages.",
    risk_evaluation_rules=RiskEvaluationRules(
        high=["Limitation period expires within 6 months"], red_flags=["Recorded statement given to insurer"]
    ),
)


def test_plain_prompt_when_there_is_no_extra_context():
    assert prompt_engine.build_system("BASE") == "BASE"


def test_practice_area_rules_are_injected_before_the_cache_breakpoint():
    system = prompt_engine.build_system("BASE", practice_area=PI_PROFILE)
    assert len(system) == 1
    text = system[0]["text"]
    assert text.startswith("BASE")
    assert "Practice area: Personal Injury." in text
    assert "Focus on liability and damages." in text
    assert "Rate as HIGH severity when:\n- Limitation period expires within 6 months" in text
    assert "Red flags to raise as soon as they are mentioned:\n- Recorded statement given to insurer" in text
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_full_context_layout_caches_stable_parts_and_appends_references():
    document = DocumentContext("doc-1", "lease.pdf", "7.2 Deposit returned in 21 days.")
    references = [precedent(1, 0.9, citation="Housing Act 2004, s.213", jurisdiction="E&W"), precedent(2, 0.8)]
    system = prompt_engine.build_system(
        "BASE", contract_instructions=" CONTRACT", document=document, practice_area=PI_PROFILE,
        precedents=references, conversation="deposit",
    )

    assert [("cache_control" in block) for block in system] == [False, True, False]
    assert " CONTRACT" in system[0]["text"] and "Personal Injury" in system[0]["text"]
    assert "<legal_references>" in system[0]["text"]  # the instructions explain the tag
    assert system[1]["text"].startswith('<contract filename="lease.pdf">')
    refs = system[2]["text"]
    assert refs.startswith("<legal_references>") and refs.endswith("</legal_references>")
    assert 'citation="Housing Act 2004, s.213"' in refs and 'jurisdiction="E&amp;W"' in refs
    assert "Text of authority 2." in refs


def test_stable_prefix_does_not_change_when_references_change():
    first = prompt_engine.build_system("BASE", practice_area=PI_PROFILE, precedents=[precedent(1, 0.9)])
    second = prompt_engine.build_system("BASE", practice_area=PI_PROFILE, precedents=[precedent(7, 0.7)])
    assert first[0] == second[0]
    assert first[1] != second[1]


def test_reference_titles_cannot_break_out_of_their_attributes():
    evil = Precedent(id="x", source_id="s", title='Act" injected="1', content="text", similarity=0.9)
    refs = prompt_engine.render_references([evil])
    assert 'title=\'Act" injected="1\'' in refs or "&quot;" in refs


def test_built_in_templates_cover_the_four_practice_areas():
    assert set(prompt_engine.BUILT_IN_TEMPLATES) == {"Personal Injury", "Corporate/M&A", "Criminal Defense", "Real Estate"}
    for template in prompt_engine.BUILT_IN_TEMPLATES.values():
        assert template.custom_system_prompt and template.risk_evaluation_rules.high


def test_live_analysis_sends_practice_area_and_references_to_claude(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        text = json.dumps({"legal_issues": [], "contract_observations": []})
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": seen["model"],
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    client = anthropic.AsyncAnthropic(api_key="test", http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(anthropic_service, "_client", client)

    import asyncio

    from app.models.analysis import KeyFact

    asyncio.run(anthropic_service.evaluate_legal_risks(
        [KeyFact(fact="Client slipped in a shop")], "Client: I slipped in the shop.", [],
        practice_area=PI_PROFILE, precedents=[precedent(1, 0.9)],
    ))
    system = seen["system"]
    assert "Practice area: Personal Injury." in system[0]["text"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[1]["text"].startswith("<legal_references>")
    assert seen["model"] == get_settings().anthropic_live_model


# ============================================================================ RBAC


@pytest.mark.parametrize(
    "role, permission, allowed",
    [
        ("owner", Permission.ORG_UPDATE, True),
        ("partner", Permission.ORG_UPDATE, False),
        ("partner", Permission.MEMBERS_MANAGE, True),
        ("associate", Permission.MEMBERS_MANAGE, False),
        ("associate", Permission.KNOWLEDGE_UPLOAD, True),
        ("associate", Permission.KNOWLEDGE_DELETE, False),
        ("paralegal", Permission.KNOWLEDGE_UPLOAD, False),
        ("paralegal", Permission.KNOWLEDGE_VIEW, True),
        ("paralegal", Permission.CONSULTATION_START, True),
        ("paralegal", Permission.AUDIT_VIEW, False),
        ("partner", Permission.AUDIT_VIEW, True),
        ("associate", Permission.PRACTICE_AREAS_MANAGE, False),
        ("intern", Permission.KNOWLEDGE_VIEW, False),
        (None, Permission.KNOWLEDGE_VIEW, False),
    ],
)
def test_permission_matrix(role, permission, allowed):
    assert has_permission(role, permission) is allowed


def test_who_can_manage_whom():
    assert can_manage(Role.OWNER, Role.OWNER)
    assert can_manage(Role.PARTNER, Role.ASSOCIATE) and can_manage(Role.PARTNER, Role.PARALEGAL)
    assert not can_manage(Role.PARTNER, Role.PARTNER) and not can_manage(Role.PARTNER, Role.OWNER)
    assert not can_manage(Role.ASSOCIATE, Role.PARALEGAL)


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_paralegal_cannot_add_knowledge(client, org_role):
    org_role("paralegal")
    response = client.post("/api/v1/knowledge/upload", data={"title": "Act", "content": "Some statute text here."})
    assert response.status_code == 403
    assert "paralegal" in response.json()["detail"]


def test_associate_can_add_knowledge(client, org_role, audit_log, monkeypatch):
    org_role("associate")

    async def ingest(org_id, title, text, *, db, created_by, metadata):
        assert (org_id, created_by, metadata["citation"]) == (ORG_ID, USER.id, "s.21")
        return rag_service.IngestResult(source_id="src-1", title=title, chunk_count=3, char_count=len(text))

    monkeypatch.setattr(rag_service, "aingest_legal_statutes_and_precedents", ingest)
    response = client.post("/api/v1/knowledge/upload", data={"title": "Housing Act", "content": "Text " * 50, "citation": "s.21"})
    assert response.status_code == 201, response.text
    assert response.json()["chunk_count"] == 3
    assert audit_log[-1]["action"] == "UPLOAD_KNOWLEDGE" and audit_log[-1]["resource_id"] == "src-1"


def test_associate_cannot_manage_practice_areas(client, org_role):
    org_role("associate")
    response = client.post("/api/v1/practice-areas", json={"name": "Family Law"})
    assert response.status_code == 403


def test_requests_for_an_org_you_are_not_in_are_refused(client):
    response = client.get("/api/v1/transcripts", headers={"X-Org-Id": "99999999-9999-9999-9999-999999999999"})
    assert response.status_code == 403
    assert client.get("/api/v1/transcripts", headers={"X-Org-Id": "not-a-uuid"}).status_code == 400


def test_partner_cannot_grant_partner(client, org_role):
    org_role("partner")
    response = client.post(f"/api/v1/organizations/{ORG_ID}/members", json={"email": "new@acme.law", "role": "partner"})
    assert response.status_code == 403


def test_partner_adds_an_associate_and_it_is_audited(client, org_role, audit_log, monkeypatch):
    org_role("partner")
    added = {}
    monkeypatch.setattr(org_service, "find_user_id_by_email", lambda email: OTHER_USER if email == "new@acme.law" else None)
    monkeypatch.setattr(org_service, "get_member", lambda token, org, user: None)
    monkeypatch.setattr(org_service, "add_member", lambda token, org, user, role: added.update(org=org, user=user, role=role) or added)

    response = client.post(f"/api/v1/organizations/{ORG_ID}/members", json={"email": "new@acme.law", "role": "associate"})
    assert response.status_code == 201, response.text
    assert added == {"org": ORG_ID, "user": OTHER_USER, "role": "associate"}
    assert audit_log[-1]["action"] == "ADD_MEMBER"

    # No account yet: invited, and they join with this role when they sign up.
    invited = {}
    monkeypatch.setattr(org_service, "create_invitation",
                        lambda token, org, email, role: invited.update(org=org, email=email, role=role) or {"id": "inv-1", "email": email, "role": role})
    response = client.post(f"/api/v1/organizations/{ORG_ID}/members", json={"email": "ghost@acme.law", "role": "associate"})
    assert response.status_code == 201 and response.json()["invited"] is True
    assert invited == {"org": ORG_ID, "email": "ghost@acme.law", "role": "associate"}
    assert audit_log[-1]["action"] == "INVITE_MEMBER"


def test_invitations_are_listed_and_revoked_by_managers(client, org_role, audit_log, monkeypatch):
    monkeypatch.setattr(org_service, "list_invitations", lambda token, org: [{"id": "inv-1", "email": "ghost@acme.law", "role": "associate"}])
    monkeypatch.setattr(org_service, "revoke_invitation", lambda token, org, invitation_id: invitation_id == "5f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01")
    assert client.get(f"/api/v1/organizations/{ORG_ID}/invitations").json()[0]["email"] == "ghost@acme.law"
    assert client.delete(f"/api/v1/organizations/{ORG_ID}/invitations/5f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01").status_code == 204
    assert audit_log[-1]["action"] == "REVOKE_INVITATION"
    assert client.delete(f"/api/v1/organizations/{ORG_ID}/invitations/6f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01").status_code == 404
    org_role("associate")
    assert client.get(f"/api/v1/organizations/{ORG_ID}/invitations").status_code == 403


def test_last_owner_cannot_be_demoted_or_leave(client, org_role, monkeypatch):
    org_role("owner")
    monkeypatch.setattr(org_service, "get_member", lambda token, org, user: {"user_id": user, "role": "owner"})
    monkeypatch.setattr(org_service, "count_owners", lambda token, org: 1)
    assert client.patch(f"/api/v1/organizations/{ORG_ID}/members/{USER.id}", json={"role": "partner"}).status_code == 409
    assert client.delete(f"/api/v1/organizations/{ORG_ID}/members/{USER.id}").status_code == 409


def test_audit_log_is_only_for_owners_and_partners(client, org_role, monkeypatch):
    monkeypatch.setattr(audit_service, "list_audit_logs", lambda token, org, limit, action: [{"action": "VIEW_TRANSCRIPT"}])
    org_role("associate")
    assert client.get(f"/api/v1/organizations/{ORG_ID}/audit-logs").status_code == 403
    org_role("partner")
    assert client.get(f"/api/v1/organizations/{ORG_ID}/audit-logs").json() == [{"action": "VIEW_TRANSCRIPT"}]


# ============================================================================ audit logging


class FakeAuditTable:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def table(self, name):
        assert name == "audit_logs"
        return self

    def insert(self, row):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.rows.append(row)
        return SimpleNamespace(execute=lambda: None)


def test_log_action_writes_an_append_only_entry(monkeypatch):
    # Bypass the conftest stub: this tests the real writer.
    monkeypatch.undo()
    table = FakeAuditTable()
    monkeypatch.setattr(audit_service, "get_supabase_admin", lambda: table)

    assert audit_service.log_action(USER.id, ORG_ID, audit_service.AuditAction.EXPORT_PDF_REPORT, "transcript", "t-1", ip_address="203.0.113.9")
    assert table.rows == [{
        "user_id": USER.id, "org_id": ORG_ID, "action": "EXPORT_PDF_REPORT", "resource_type": "transcript",
        "resource_id": "t-1", "ip_address": "203.0.113.9", "metadata": {},
    }]
    audit_service.log_action(USER.id, ORG_ID, "VIEW_TRANSCRIPT", "transcript", "t-1", ip_address="not-an-ip")
    assert table.rows[-1]["ip_address"] is None


def test_log_action_fails_open_by_default_and_closed_when_configured(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(audit_service, "get_supabase_admin", lambda: FakeAuditTable(fail=True))
    assert audit_service.log_action(USER.id, ORG_ID, "VIEW_TRANSCRIPT", "transcript", "t-1") is False
    monkeypatch.setattr(get_settings(), "audit_fail_closed", True)
    with pytest.raises(audit_service.AuditError):
        audit_service.log_action(USER.id, ORG_ID, "VIEW_TRANSCRIPT", "transcript", "t-1")


def test_forwarded_for_is_only_trusted_when_configured(monkeypatch):
    connection = SimpleNamespace(headers={"x-forwarded-for": "198.51.100.7, 10.0.0.1"}, client=SimpleNamespace(host="10.0.0.1"))
    assert audit_service.client_ip(connection) == "10.0.0.1"
    monkeypatch.setattr(get_settings(), "trust_forwarded_for", True)
    assert audit_service.client_ip(connection) == "198.51.100.7"


TRANSCRIPT_ID = "33333333-3333-3333-3333-333333333333"
TRANSCRIPT_ROW = {"id": TRANSCRIPT_ID, "user_id": USER.id, "org_id": ORG_ID, "title": "Slip and fall", "content": "Client: I fell.",
                  "created_at": "2026-10-19T10:00:00+00:00", "updated_at": "2026-10-19T10:00:00+00:00", "metadata": {}}


def test_viewing_exporting_and_deleting_transcripts_are_audited(client, audit_log, monkeypatch):
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: TRANSCRIPT_ROW)
    monkeypatch.setattr(safety_service, "trash", lambda db, kind, item_id, **kw: "trash-1")

    assert client.get(f"/api/v1/transcripts/{TRANSCRIPT_ID}").status_code == 200
    assert client.get(f"/api/v1/transcripts/{TRANSCRIPT_ID}/pdf").status_code == 200
    deleted = client.delete(f"/api/v1/transcripts/{TRANSCRIPT_ID}")
    assert deleted.status_code == 200 and deleted.json()["status"] == "trashed"

    assert [(e["action"], e["resource_id"], e["org_id"], e["user_id"]) for e in audit_log] == [
        ("VIEW_TRANSCRIPT", TRANSCRIPT_ID, ORG_ID, USER.id),
        ("EXPORT_PDF_REPORT", TRANSCRIPT_ID, ORG_ID, USER.id),
        ("TRASH_ITEM", TRANSCRIPT_ID, ORG_ID, USER.id),
    ]


def test_failed_lookups_are_not_audited(client, audit_log, monkeypatch):
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: None)
    assert client.get(f"/api/v1/transcripts/{TRANSCRIPT_ID}").status_code == 404
    assert audit_log == []


def test_fail_closed_audit_blocks_the_view(client, monkeypatch):
    monkeypatch.setattr(transcript_service, "get_transcript", lambda db, tid: TRANSCRIPT_ROW)

    def broken(*args, **kwargs):
        raise audit_service.AuditError("Could not record the audit entry for this action")

    monkeypatch.setattr(audit_service, "log_action", broken)
    response = client.get(f"/api/v1/transcripts/{TRANSCRIPT_ID}")
    assert response.status_code == 503


def test_contract_upload_is_audited(client, audit_log, monkeypatch):
    from app.services import document_service

    monkeypatch.setattr(document_service, "save_document",
                        lambda token, row, org_id=None: {**row, "id": "doc-9", "created_at": "2026-10-19T10:00:00+00:00"})
    response = client.post("/api/v1/documents/upload", files={"file": ("nda.txt", b"Confidential information means ... " * 3, "text/plain")})
    assert response.status_code == 201, response.text
    assert audit_log[-1]["action"] == "UPLOAD_CONTRACT" and audit_log[-1]["resource_id"] == "doc-9"
    assert audit_log[-1]["org_id"] == ORG_ID


# ============================================================================ live session integration


@pytest.fixture
def live(monkeypatch, fake_agents):
    calls = {"retrieve": [], "summary": [], "saved": [], "agents": fake_agents.calls}

    async def retrieve(org_id, text, top_k, *, db, **filters):
        calls["retrieve"].append((org_id, text, top_k))
        return [precedent(1, 0.91, citation="Occupiers' Liability Act 1957, s.2"), precedent(2, 0.74)]

    async def summarize(transcript, analysis, document_context=None, practice_area=None, precedents=None, case_memory=None, **context):
        calls["summary"].append({"practice_area": practice_area, "precedents": precedents})
        return ConsultationSummary(title="Slip and fall", summary="Overview: ...")

    def save(token, user_id, row):
        calls["saved"].append(row)
        return {"id": "transcript-1", **row}

    monkeypatch.setattr(audio_stream, "verify_access_token", lambda token: USER)
    monkeypatch.setattr(anthropic_service, "summarize_consultation", summarize)
    monkeypatch.setattr(rag_service, "aretrieve_relevant_precedents", retrieve)
    monkeypatch.setattr(prompt_engine, "load_practice_area",
                        lambda token, org, pa_id: PI_PROFILE if pa_id == "44444444-4444-4444-4444-444444444444" else None)
    monkeypatch.setattr(transcript_service, "save_live_session", save)
    monkeypatch.setattr(n8n_service, "is_configured", lambda: False)
    return calls


def receive_until(ws, message_type, seen=None):
    while True:
        message = ws.receive_json()
        if seen is not None:
            seen.append(message)
        if message["type"] == message_type:
            return message


def test_live_session_uses_practice_area_and_streams_citations(live, audit_log, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_refresh_seconds", 3600)  # one retrieval for the whole test
    url = f"/api/v1/ws/audio?token=good-token&org_id={ORG_ID}&practice_area_id=44444444-4444-4444-4444-444444444444"

    with TestClient(app).websocket_connect(url) as ws:
        started = ws.receive_json()
        assert (started["org_id"], started["role"]) == (ORG_ID, "owner")
        assert receive_until(ws, "practice_area_selected")["name"] == "Personal Injury"

        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": "I slipped on a wet floor in the supermarket last week."})
        citations = receive_until(ws, "citations")
        assert [c["title"] for c in citations["items"]] == ["Authority 1", "Authority 2"]
        assert citations["items"][0]["citation"] == "Occupiers' Liability Act 1957, s.2"
        receive_until(ws, "analysis")

        ws.send_json({"type": "transcript_chunk", "speaker": "Client", "text": "There was no warning sign and I broke my wrist."})
        seen = []
        receive_until(ws, "analysis", seen)
        assert "citations" not in [m["type"] for m in seen]  # nothing new to report

        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")

    assert len(live["retrieve"]) == 1 and live["retrieve"][0][0] == ORG_ID
    agents = live["agents"]
    assert all(c["practice_area"] is PI_PROFILE for c in agents["intake"] + agents["risk"] + agents["draft"])
    assert [p.id for p in agents["risk"][-1]["precedents"]] == ["chunk-1", "chunk-2"]
    # Second pass: same facts, no new citations, so the risk evaluator was skipped.
    assert (len(agents["intake"]), len(agents["risk"]), len(agents["draft"])) == (2, 1, 2)
    assert [p.id for p in live["summary"][0]["precedents"]] == ["chunk-1", "chunk-2"]

    saved = live["saved"][0]
    assert saved["org_id"] == ORG_ID and saved["practice_area_id"] == "pa-1"
    assert saved["metadata"]["practice_area"] == "Personal Injury"
    assert [c["id"] for c in saved["metadata"]["citations"]] == ["chunk-1", "chunk-2"]
    assert [e["action"] for e in audit_log] == ["START_CONSULTATION", "END_CONSULTATION"]


def test_retrieval_refreshes_once_enough_new_speech_arrives(live, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_refresh_seconds", 0)
    monkeypatch.setattr(get_settings(), "rag_min_new_chars", 40)

    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        ws.receive_json()
        for text in ["I slipped on a wet floor in the supermarket.", "Yes.", "The manager said they had mopped five minutes earlier."]:
            ws.send_json({"type": "transcript_chunk", "text": text})
            receive_until(ws, "analysis")
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")

    # First chunk: retrieve. "Yes." adds too little. The third adds enough.
    assert len(live["retrieve"]) == 2


def test_unknown_practice_area_falls_back_to_general_analysis(live):
    url = "/api/v1/ws/audio?token=good-token&practice_area_id=55555555-5555-5555-5555-555555555555"
    with TestClient(app).websocket_connect(url) as ws:
        ws.receive_json()
        assert receive_until(ws, "error")["code"] == "practice_area_not_found"
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")


def test_non_members_cannot_open_a_session(live, org_role):
    org_role(None)
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(f"/api/v1/ws/audio?token=good-token&org_id={ORG_ID}") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_malformed_org_id_is_refused(live):
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token&org_id=acme") as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_paralegals_can_run_consultations(live, org_role):
    org_role("paralegal")
    with TestClient(app).websocket_connect("/api/v1/ws/audio?token=good-token") as ws:
        assert ws.receive_json()["role"] == "paralegal"
        ws.send_json({"type": "end"})
        receive_until(ws, "session_ended")
