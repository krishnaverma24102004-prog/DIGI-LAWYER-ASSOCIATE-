"""Bulk document review grids: answers with verified source quotes, PII masked on the way to the model."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentUser, get_current_user
from app.main import app
from app.models.analysis import DocumentReview, GridAnswer
from app.services import anthropic_service, document_service, review_service
from tests.conftest import ORG_ID

USER = CurrentUser(id="11111111-1111-1111-1111-111111111111", email="partner@acme.law", access_token="good-token")
DOC_A = "aaaaaaaa-0000-0000-0000-000000000001"
DOC_B = "aaaaaaaa-0000-0000-0000-000000000002"

LEASE = (
    "LEAVE AND LICENCE AGREEMENT. This agreement is made at Pune between Mr. Arjun Mehta (Licensor) and "
    "Ms. Priya Nair (Licensee), whose PAN is ABCDE1234F. 4. The monthly licence fee shall be Rs. 32,000. "
    "5. The Licensee shall pay a refundable security deposit of Rs. 1,50,000, refunded within 30 days of "
    "vacating. 9. Either party may terminate this agreement by giving one month's written notice."
)


class Table:
    def __init__(self, store, name):
        self.store, self.name, self.filters = store, name, []

    def upsert(self, rows, on_conflict=None):
        rows = rows if isinstance(rows, list) else [rows]
        keys = on_conflict.split(",")
        table = self.store.setdefault(self.name, [])
        for row in rows:
            existing = next((r for r in table if all(r.get(k) == row[k] for k in keys)), None)
            existing.update(row) if existing else table.append(dict(row))
        return self

    def execute(self):
        return SimpleNamespace(data=self.store.get(self.name, []))


class DB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return Table(self.store, name)


@pytest.fixture
def reviewer(monkeypatch):
    seen = {}

    def get_document(token, document_id, include_text=False, org_id=None):
        return {"id": document_id, "filename": "lease.pdf", "extracted_text": LEASE} if document_id == DOC_A else None

    async def review_document(text, questions, *, jurisdiction=None):
        seen["text"], seen["questions"] = text, questions
        return DocumentReview(answers=[
            GridAnswer(question_id="q1", answer="Rs. 32,000 per month", quote="The monthly licence fee shall be Rs. 32,000", confidence="high"),
            GridAnswer(question_id="q2", answer="Rs. 1,50,000", quote="a security deposit of two lakh rupees", confidence="medium"),  # not in the text
            GridAnswer(question_id="q3", answer="Licensee PAN [TAX_ID]", quote="Ms. Priya Nair (Licensee), whose PAN is [TAX_ID]"),
            GridAnswer(question_id="q4", answer="Not stated in the document", quote=None, confidence="high"),
        ])

    monkeypatch.setattr(document_service, "get_document", get_document)
    monkeypatch.setattr(anthropic_service, "review_document", review_document)
    return seen


QUESTIONS = review_service.normalize_questions([
    {"question": "Monthly licence fee?", "kind": "amount"},
    {"question": "Security deposit?", "kind": "amount"},
    "Licensee's PAN?",
    {"question": "Is the agreement registered?", "kind": "yes_no"},
])


def test_each_answer_carries_a_checked_source_quote(reviewer):
    db = DB()
    grid = {"id": "g1", "jurisdiction": "IN", "document_ids": [DOC_A], "questions": QUESTIONS}
    cells = {c["question_id"]: c for c in asyncio.run(review_service.review_one(db, "tok", ORG_ID, grid, DOC_A, QUESTIONS))}

    assert cells["q1"]["verified"] is True and cells["q1"]["confidence"] == "high"
    assert cells["q2"]["verified"] is False  # a quote that isn't in the document is flagged, not trusted
    assert cells["q4"] == {**cells["q4"], "answer": review_service.NOT_STATED, "quote": None, "verified": None}
    # The model saw the PAN masked; the firm's grid shows it restored.
    assert "ABCDE1234F" not in reviewer["text"] and "[TAX_ID]" in reviewer["text"]
    assert cells["q3"]["answer"] == "Licensee PAN ABCDE1234F" and cells["q3"]["verified"] is True
    assert len(db.store["review_cells"]) == 4


def test_failures_become_error_cells(reviewer):
    db = DB()
    grid = {"id": "g1", "jurisdiction": None, "document_ids": [DOC_B], "questions": QUESTIONS}
    cells = asyncio.run(review_service.review_one(db, "tok", ORG_ID, grid, DOC_B, QUESTIONS))
    assert {c["status"] for c in cells} == {"error"} and cells[0]["error"] == "Document not found"


def test_questions_are_normalized_and_capped():
    questions = review_service.normalize_questions(["  What is   the term? ", {"question": "Deposit?", "kind": "amount"}, {"question": ""},
                                                    {"question": "Odd", "kind": "weird"}])
    assert questions == [
        {"id": "q1", "question": "What is the term?", "kind": "text"},
        {"id": "q2", "question": "Deposit?", "kind": "amount"},
        {"id": "q4", "question": "Odd", "kind": "text"},
    ]
    grid = {"id": "g", "questions": [{"id": f"q{i}", "question": "x", "kind": "text"} for i in range(1, 15)], "document_ids": []}
    with pytest.raises(review_service.ReviewError):
        review_service.add_questions(DB(), grid, ["one", "two"])


def test_csv_export_shows_sources_and_unverified_answers():
    grid = {
        "title": "Pune leases Q3", "questions": QUESTIONS[:2],
        "documents": [{"id": DOC_A, "filename": "lease.pdf"}],
        "cells": [
            {"document_id": DOC_A, "question_id": "q1", "answer": "Rs. 32,000", "quote": "fee shall be Rs. 32,000", "verified": True},
            {"document_id": DOC_A, "question_id": "q2", "answer": "Rs. 1,50,000", "quote": "two lakh", "verified": False},
        ],
    }
    lines = review_service.to_csv(grid).splitlines()
    assert lines[0].startswith("Document,Monthly licence fee?,Monthly licence fee? (source),Monthly licence fee? (verified)")
    assert lines[1] == "lease.pdf,"+ "\"Rs. 32,000\",\"fee shall be Rs. 32,000\",yes,\"Rs. 1,50,000\",two lakh,NO - check"
    assert review_service.filename(grid) == "pune-leases-q3.csv"


# ----------------------------------------------------------------------------- API


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_presets_cover_indian_document_types(client):
    names = [p["name"] for p in client.get("/api/v1/reviews/presets").json()]
    assert "Lease / leave and licence" in names and "Commercial contract (India)" in names


def test_creating_a_review_checks_documents_and_starts_it(client, audit_log, monkeypatch):
    started, created = [], []

    class Docs:
        def table(self, name):
            return self

        def select(self, *a):
            return self

        def in_(self, column, values):
            self.values = values
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": DOC_A}])

    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: Docs())

    def create_grid(db, title, document_ids, questions, jurisdiction):
        created.append((title, document_ids, [q["id"] for q in questions], jurisdiction))
        return {"id": "grid-1", "document_ids": document_ids, "questions": questions, "jurisdiction": jurisdiction}

    async def run_review(db, token, org, grid, **kwargs):
        started.append(grid["id"])

    monkeypatch.setattr(review_service, "create_grid", create_grid)
    monkeypatch.setattr(review_service, "run_review", run_review)

    body = {"title": "Leases", "document_ids": [DOC_A], "questions": [{"question": "Monthly rent?", "kind": "amount"}], "jurisdiction": "india"}
    response = client.post("/api/v1/reviews", json=body)
    assert response.status_code == 202, response.text
    assert created == [("Leases", [DOC_A], ["q1"], "IN")]
    assert audit_log[-1]["action"] == "CREATE_REVIEW"

    response = client.post("/api/v1/reviews", json={**body, "document_ids": [DOC_A, DOC_B]})
    assert response.status_code == 404 and DOC_B in response.json()["detail"]
    assert client.post("/api/v1/reviews", json={**body, "questions": []}).status_code == 422


# ----------------------------------------------------------------------------- governing law


def test_a_contracts_own_law_qualifies_enforceability_answers():
    from app.services import governing_law, jurisdiction_service

    english = governing_law.detect("21. This Agreement is governed by and construed in accordance with the laws of England and Wales.")
    assert (english["code"], english["law"], english["basis"]) == ("UK", "England and Wales", "clause")
    assert governing_law.detect("Disputes: the courts at Pune shall have exclusive jurisdiction.")["code"] == "IN"
    assert governing_law.detect("No clause about law here.") is None
    india = jurisdiction_service.get_profile("IN")
    assert governing_law.assess(governing_law.detect("Governing Law: India."), india)["mismatch"] is False

    tables = {
        "review_grids": [{"id": "g1", "title": "NDAs", "document_ids": [DOC_A, DOC_B], "questions": [], "jurisdiction": "IN"}],
        "review_cells": [
            {"grid_id": "g1", "document_id": DOC_A, "question_id": "q1", "status": "done", "answer": "The non-compete is unenforceable."},
            {"grid_id": "g1", "document_id": DOC_A, "question_id": "q2", "status": "done", "answer": "Rs. 5,00,000"},
            {"grid_id": "g1", "document_id": DOC_B, "question_id": "q1", "status": "done", "answer": "Valid and binding."},
        ],
        "documents": [
            {"id": DOC_A, "filename": "uk-nda.pdf", "governing_law": english},
            {"id": DOC_B, "filename": "old.pdf", "governing_law": None, "extracted_text": "Governed by the laws of India."},
        ],
    }

    class Query:
        def __init__(self, name):
            self.rows, self.filters = tables[name], []

        def select(self, *a):
            return self

        def eq(self, column, value):
            self.filters.append(lambda r: r.get(column) == value)
            return self

        def in_(self, column, values):
            self.filters.append(lambda r: r.get(column) in values)
            return self

        def limit(self, n):
            return self

        def execute(self):
            return SimpleNamespace(data=[dict(r) for r in self.rows if all(f(r) for f in self.filters)])

    grid = review_service.get_grid(SimpleNamespace(table=Query), "g1")
    uk, old = grid["documents"]
    assert uk["governing_law"]["mismatch"] is True and "England and Wales" in uk["governing_law"]["caveat"]
    assert old["governing_law"]["detected"]["code"] == "IN" and old["governing_law"]["mismatch"] is False
    caveats = {(c["document_id"], c["question_id"]): c.get("jurisdiction_caveat") for c in grid["cells"]}
    assert caveats[(DOC_A, "q1")] and caveats[(DOC_A, "q2")] is None and caveats[(DOC_B, "q1")] is None
