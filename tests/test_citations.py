"""Citation verification: fabricated or unsupported authority never reaches the lawyer unmarked."""

import asyncio

import pytest

from app.models.analysis import DraftedResponse, LegalIssue, RiskEvaluation
from app.services import agent_workflow, anthropic_service, citation_service, jurisdiction_service
from app.services.agent_workflow import AgentContext
from app.services.citation_service import Sources

KB = Sources.from_texts(
    "Section 138 of the Negotiable Instruments Act, 1881: dishonour of cheque for insufficiency of funds. "
    "Dashrath Rupsingh Rathod v. State of Maharashtra, (2014) 9 SCC 129: territorial jurisdiction."
)


def statuses(text, sources=KB):
    return [(c.text, c.status) for c in citation_service.check(text, sources)]


@pytest.mark.parametrize("text, expected", [
    ("A complaint lies under Section 138 of the Negotiable Instruments Act, 1881.",
     [("Section 138 of the Negotiable Instruments Act, 1881", "grounded")]),
    ("A certificate under Section 63 of the Bharatiya Sakshya Adhiniyam is needed.",
     [("Section 63 of the Bharatiya Sakshya Adhiniyam", "statute")]),
    ("Punishable under Section 600 of the BNS.", [("Section 600 of the BNS", "invalid")]),
    ("Section 103A BNS applies.", [("Section 103A BNS", "invalid")]),
    ("Article 21 protects liberty, unlike Article 999.", [("Article 21", "statute"), ("Article 999", "invalid")]),
    ("This is cheating under Section 420 IPC.", [("Section 420 IPC", "repealed")]),
    ("Order 37 CPC summary suit; he paid 2 IPC officers on 3 March 2024.", []),
    ("Under Section 7 of the Karnataka Rent Act, 1999 the tenant...", [("Section 7 of the Karnataka Rent Act, 1999", "unverified")]),
])
def test_statutes_are_checked_against_the_sources_and_the_registry(text, expected):
    assert statuses(text) == expected


def test_old_code_sections_point_to_the_new_code():
    (check,) = citation_service.check("Bail under Section 438 CrPC.", KB)
    assert check.status == "repealed"
    assert "before 1 July 2024" in check.note and "Section 482 BNSS" in check.note


def test_cases_must_come_from_the_sources():
    grounded = "As held in Dashrath Rupsingh Rathod v. State of Maharashtra, (2014) 9 SCC 129, jurisdiction lies there."
    assert statuses(grounded) == [("Dashrath Rupsingh Rathod v. State of Maharashtra, (2014) 9 SCC 129", "grounded")]
    # The name alone, or the report alone, is enough to recognise a case the sources contain.
    assert statuses("In Dashrath Rupsingh Rathod v. State of Maharashtra the court held...")[0][1] == "grounded"
    invented = "As held in Ravi Kumar v. State of Punjab, (2019) 5 SCC 123, the landlord must refund."
    assert statuses(invented) == [("Ravi Kumar v. State of Punjab, (2019) 5 SCC 123", "unverified")]
    for text in ("Kesavananda Bharati, AIR 1973 SC 1461", "2023 INSC 456", "2021 SCC OnLine SC 123"):
        assert statuses(text)[0][1] == "unverified"


def test_plain_names_are_not_mistaken_for_cases():
    assert statuses("Mr Sharma met the Collector of Pune and the Bank of India about Rahul vs his landlord.") == []


def test_flagged_citations_are_marked_in_place_once():
    text, checks = citation_service.verify_text("See Ravi Kumar v. State of Punjab, (2019) 5 SCC 123 and Section 600 BNS.", KB)
    assert text == "See Ravi Kumar v. State of Punjab, (2019) 5 SCC 123 [unverified] and Section 600 BNS [unverified]."
    assert citation_service.annotate(text, citation_service.check(text, KB)).count("[unverified]") == 2
    assert citation_service.summarize(checks) == {"unverified": 1, "invalid": 1}


def test_issue_authority_keeps_only_supported_citations():
    issue = {"issue": "Cheque dishonour", "authority": "Section 138 of the Negotiable Instruments Act, 1881; Section 600 BNS"}
    checked = citation_service.verify_issue(issue, KB)
    assert checked["authority"] == "Section 138 of the Negotiable Instruments Act, 1881"
    assert checked["authority_status"] == "flagged" and "Section 600 BNS" in checked["authority_note"]

    assert citation_service.verify_issue({"issue": "x", "authority": "Section 138 NI Act"}, KB)["authority_status"] == "verified"
    assert citation_service.verify_issue({"issue": "x", "authority": "Section 73 of the Indian Contract Act"}, KB)["authority_status"] == "statute"
    assert citation_service.verify_issue({"issue": "x", "authority": "Firm intake checklist"}, KB)["authority_status"] is None


def test_verification_fields_are_hidden_from_the_model():
    properties = RiskEvaluation.model_json_schema()["$defs"]["LegalIssue"]["properties"]
    assert "authority" in properties
    assert "authority_status" not in properties and "authority_note" not in properties


def test_prompts_show_citation_formats_not_real_looking_citations():
    guidance = jurisdiction_service.render_guidance(jurisdiction_service.get_profile("IN"))
    assert "<Party> v. <Party>, (<year>) <volume> SCC <page>" in guidance
    assert not [c for c in citation_service.check(guidance, Sources(set(), [])) if c.kind == "case"]


def test_the_agents_output_is_verified(fake_agents, monkeypatch):
    fake_agents.outputs.issues = [
        LegalIssue(issue="Cheque dishonour", severity="high", authority="Section 138 NI Act; Ravi Kumar v. State of Punjab, (2019) 5 SCC 123"),
        LegalIssue(issue="Invented offence", severity="low", authority="Section 999 BNS"),
    ]
    fake_agents.outputs.message = (
        "A complaint under Section 138 of the Negotiable Instruments Act, 1881 is possible; "
        "see Ravi Kumar v. State of Punjab, (2019) 5 SCC 123."
    )

    async def research(query):
        return [agent_workflow.Precedent(id="c1", source_id="s1", title="NI Act s. 138",
                                         content="Section 138 of the Negotiable Instruments Act, 1881 ...", similarity=0.9)]

    state = {"transcript_history": "Client: my cheque of 2 lakh bounced", "current_chunk": "Client: my cheque of 2 lakh bounced"}
    context = AgentContext(research=research, jurisdiction=jurisdiction_service.get_profile("IN"))
    result = asyncio.run(agent_workflow.process_audio_chunk_via_agent(state, context))

    first, second = result["legal_risks"]
    assert first["authority"] == "Section 138 NI Act" and first["authority_status"] == "flagged"
    assert second["authority"] is None and "no Section 999" in second["authority_note"]
    final = result["final_response"]
    assert final["message"].endswith("(2019) 5 SCC 123 [unverified].")
    assert [(c["text"], c["status"]) for c in final["citations"]] == [
        ("Section 138 of the Negotiable Instruments Act, 1881", "grounded"),
        ("Ravi Kumar v. State of Punjab, (2019) 5 SCC 123", "unverified"),
    ]
    # The flags survive into the analysis the client is sent.
    from app.models.analysis import LiveAnalysis

    analysis = LiveAnalysis.model_validate(final["analysis"]).model_dump()
    assert analysis["legal_issues"][0]["authority_status"] == "flagged"


def test_real_judgments_from_the_citation_index_are_recognised():
    text = "See Maneka Gandhi v. Union of India; also Vijay Singh v. State of Bihar, [2024] 10 S.C.R. 108 and Ravi Kumar v. State of Punjab."
    keys, names = citation_service.case_lookups(text)
    assert "202410SCR108" in keys and ("maneka", "gandhi") in names
    sources = KB.with_known({"202410SCR108"}, [("maneka", "gandhi")])
    assert [(c.text, c.status) for c in citation_service.check(text, sources)] == [
        ("Maneka Gandhi v. Union of India", "known_case"),
        ("Vijay Singh v. State of Bihar, [2024] 10 S.C.R. 108", "known_case"),
        ("Ravi Kumar v. State of Punjab", "unverified"),
    ]
    assert citation_service.verify_issue({"issue": "x", "authority": "Maneka Gandhi v. Union of India"}, sources)["authority_status"] == "known"


def test_lookup_queries_the_citation_index():
    calls = []

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *a):
            return self

        def overlaps(self, column, values):
            calls.append(("overlaps", column, sorted(values)))
            return self

        def contains(self, column, values):
            calls.append(("contains", column, values))
            self.rows = [{"name_tokens": ["gandhi", "maneka"]}] if "maneka" in values else []
            return self

        def limit(self, n):
            return self

        def execute(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=self.rows)

    class DB:
        def table(self, name):
            assert name == "legal_authorities"
            return Query([{"citation_keys": ["202410SCR108", "2024INSC735"]}])

    keys, names = citation_service.lookup_authorities(DB(), ["202410SCR108", "20195SCC123"], [("maneka", "gandhi"), ("ravi", "kumar", "punjab")])
    assert keys == {"202410SCR108"} and names == [("maneka", "gandhi")]


def test_sc_import_builds_index_rows():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("ingest", Path(__file__).resolve().parent.parent / "scripts" / "ingest_sc_judgments.py")
    ingest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ingest)
    row = ingest.authority_row(2024, {
        "title": "VIJAY SINGH @ VIJAY KR. SHARMA versus THE STATE OF BIHAR", "citation": "[2024] 10 S.C.R. 108",
        "case_id": "2024 INSC 735", "decision_date": "25-09-2024", "path": "2024_10_108_125", "court": "Supreme Court of India",
    })
    assert row["citation_keys"] == ["202410SCR108", "2024INSC735"]
    assert {"vijay", "singh", "bihar"} <= set(row["name_tokens"])
    assert row["decision_date"] == "2024-09-25" and row["external_id"] == "sc:2024_10_108_125"
    assert row["source_url"].endswith("/data/pdf/year=2024/english/2024_10_108_125_EN.pdf")
    assert ingest.parse_years("1950-1952,2024") == [1950, 1951, 1952, 2024]
    # What a lawyer writes matches what the index stores.
    assert citation_service.case_lookups("Vijay Singh v. State of Bihar, [2024] 10 S.C.R. 108")[0] == ["202410SCR108"]
    assert citation_service.case_lookups("2024 INSC 735")[0] == ["2024INSC735"]


def test_a_case_the_client_mentions_is_not_authority(fake_agents):
    fake_agents.outputs.message = "Ravi Kumar v. State of Punjab, (2019) 5 SCC 123 says you can claim double the deposit."
    said = "Client: my friend says Ravi Kumar v. State of Punjab, (2019) 5 SCC 123 gives me double the deposit"
    result = asyncio.run(agent_workflow.process_audio_chunk_via_agent(
        {"transcript_history": said, "current_chunk": said}, AgentContext(jurisdiction=jurisdiction_service.get_profile("IN"))
    ))
    final = result["final_response"]
    assert "(2019) 5 SCC 123 [unverified]" in final["message"]
    assert final["citations"][0]["status"] == "unverified"
    assert "is a claim, not authority" in anthropic_service.SHARED_RULES


def test_indian_kanoon_confirms_cases_the_index_does_not_know(monkeypatch):
    import httpx

    from app.core.config import get_settings
    from app.services import indiankanoon_service as ik

    monkeypatch.setattr(get_settings(), "indiankanoon_api_token", "ik-token")
    ik.case_exists.cache_clear()
    calls = []
    real = httpx.Client

    def handler(request: httpx.Request):
        calls.append((request.method, dict(request.url.params), request.headers["authorization"]))
        hits = [{"tid": 1, "title": "Arjun <b>Mehta</b> vs Priya Nair on 2 May, 2024", "docsource": "Bombay High Court", "headline": "x"}]
        return httpx.Response(200, json={"docs": hits if "mehta" in request.url.params["formInput"] else []})

    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    class EmptyIndex:
        def table(self, name):
            return self

        def select(self, *a):
            return self

        def overlaps(self, *a):
            return self

        def contains(self, *a):
            return self

        def limit(self, n):
            return self

        def execute(self):
            from types import SimpleNamespace

            return SimpleNamespace(data=[])

    names = [("arjun", "mehta", "priya", "nair"), ("ravi", "kumar", "punjab"), ("single",)]
    keys, found = citation_service.lookup_authorities(EmptyIndex(), [], names)
    assert found == [("arjun", "mehta", "priya", "nair")]
    assert calls[0][0] == "POST" and calls[0][2] == "Token ik-token" and len(calls) == 2  # one-word names aren't looked up
    citation_service.lookup_authorities(EmptyIndex(), [], names[:1])
    assert len(calls) == 2  # remembered
    assert ik.search("mehta")[0]["title"] == "Arjun Mehta vs Priya Nair on 2 May, 2024"
    ik.case_exists.cache_clear()


# ============================================================================ honest labels, both codes, client text


def test_checks_say_what_was_and_wasnt_checked():
    checks = citation_service.check("Section 103 BNS and Section 420 IPC and Section 600 BNS", citation_service.Sources.from_texts(""))
    by_text = {c.text: c.as_dict() for c in checks}
    assert by_text["Section 103 BNS"]["label"] == "Section exists · its wording isn't checked"
    assert "Section 302 IPC" in by_text["Section 103 BNS"]["note"] and "official table" in by_text["Section 103 BNS"]["note"]
    assert "318(4) BNS" in by_text["Section 420 IPC"]["note"] and by_text["Section 420 IPC"]["status"] == "repealed"
    assert by_text["Section 600 BNS"]["label"] == "No such section"


def test_client_text_drops_unsupported_citations_and_speech_names_none():
    text = "Murder is covered by Section 103 BNS. Kumar v. State, (2019) 5 SCC 123 says so. What happened next?"
    checked, checks = citation_service.verify_text(text, citation_service.Sources.from_texts(""))
    client = citation_service.for_client(text, checks)
    assert "Kumar" not in client and "[unverified]" not in client
    assert client.startswith("Murder is covered by Section 103 BNS.") and client.endswith(citation_service.CLIENT_CITATION_NOTE)
    assert citation_service.for_client("No citations here?", []) == "No citations here?"
    spoken = citation_service.spoken(checked)
    assert spoken == "Murder is covered by the relevant provision. A court decision says so. What happened next?"


def test_quotes_are_matched_exactly_or_closely_with_the_differences():
    from app.services.evidence_service import quote_match

    assert quote_match("the tenant shall pay rent", "Clause 4. The Tenant shall pay rent monthly.").kind == "exact"
    close = quote_match("the tenant shall pay the rent monthly by cheque", "The tenant shall pay the rent monthly by cash.")
    assert close.kind == "close" and close.differs == ("cheque",)
    assert quote_match("nothing like the source", "The tenant shall pay rent.") is None
