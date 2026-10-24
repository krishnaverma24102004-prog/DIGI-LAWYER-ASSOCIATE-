"""Shared test doubles for the API tests (tests/db runs against a real Postgres instead).

Every API test runs inside an organization where the caller is an owner, with audit
writes captured in memory and knowledge-base retrieval returning nothing. Tests that
care about any of these override them.
"""

import pytest

from app.core import config

# Tests use the defaults, never a developer's .env (real keys, REDIS_URL, ...). Only once: this
# module may be imported again as `tests.conftest`, after the app has captured its settings.
if config.Settings.model_config.get("env_file") is not None:
    config.Settings.model_config["env_file"] = None
    config.get_settings.cache_clear()

from app.services.org_service import Membership  # noqa: E402

ORG_ID = "6f0e8a52-1b7d-4c1e-9a43-2a7d8c6b5e01"


class FakeSupabase:
    """Stands in for a Supabase client where tests stub the service functions anyway."""

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected Supabase call: .{name}()")


@pytest.fixture
def org_role(monkeypatch):
    """Set the caller's role (or None for a non-member) in the test organization."""
    state = {"role": "owner"}

    def resolve(access_token, user_id, requested_org_id=None):
        if state["role"] is None or requested_org_id not in (None, ORG_ID):
            return None
        return Membership(org_id=ORG_ID, role=state["role"])

    monkeypatch.setattr("app.services.org_service.resolve_membership", resolve)
    return lambda role: state.update(role=role)


@pytest.fixture
def audit_log(monkeypatch):
    entries = []

    def log_action(user_id, org_id, action, resource_type, resource_id=None, *, ip_address=None, metadata=None):
        entries.append(
            {"user_id": user_id, "org_id": org_id, "action": str(action), "resource_type": resource_type,
             "resource_id": resource_id, "metadata": metadata}
        )
        return True

    monkeypatch.setattr("app.services.audit_service.log_action", log_action)
    return entries


@pytest.fixture
def fake_agents(monkeypatch):
    """Replaces the three Claude calls behind the agent nodes; records what each received.

    Tests can change `fake_agents.outputs` to script what the agents return.
    """
    from types import SimpleNamespace

    from app.models.analysis import DraftedResponse, KeyFact, LegalIssue, RiskEvaluation
    from app.services import anthropic_service

    outputs = SimpleNamespace(
        facts=[KeyFact(fact="Fired on 3 March", category="date")],
        issues=[LegalIssue(issue="Wrongful termination", severity="HIGH")],
        observations=[],
        message="Ask whether there is a written employment contract.",
        questions=["Do you have a written contract?"],
    )
    calls = {"intake": [], "risk": [], "draft": []}

    async def extract_case_facts(transcript_history, current_chunk, known_facts, **context):
        calls["intake"].append({"transcript_history": transcript_history, "current_chunk": current_chunk, **context})
        return outputs.facts

    async def evaluate_legal_risks(facts, transcript_history, previous_risks, **context):
        calls["risk"].append({"facts": facts, "transcript_history": transcript_history, **context})
        return RiskEvaluation(legal_issues=outputs.issues, contract_observations=outputs.observations)

    async def draft_response(facts, risks, transcript_history, previous_questions, **context):
        calls["draft"].append({"facts": facts, "risks": risks, **context})
        return DraftedResponse(message=outputs.message, follow_up_questions=outputs.questions)

    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    monkeypatch.setattr(anthropic_service, "extract_case_facts", extract_case_facts)
    monkeypatch.setattr(anthropic_service, "evaluate_legal_risks", evaluate_legal_risks)
    monkeypatch.setattr(anthropic_service, "draft_response", draft_response)
    return SimpleNamespace(outputs=outputs, calls=calls)


@pytest.fixture(autouse=True)
def _api_defaults(request, monkeypatch, org_role, audit_log):
    if "tests/db" in request.node.nodeid.replace("\\", "/"):
        return

    async def no_precedents(*args, **kwargs):
        return []

    monkeypatch.setattr("app.services.rag_service.aretrieve_relevant_precedents", no_precedents)
    # Rate limits are tested on their own (test_production_infrastructure.py).
    monkeypatch.setattr("app.core.rate_limiter.limiter.enabled", False)
    # So is the consent gate on consultations (test_safety_rails.py).
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "consultation_consent_required", False)

    # Audio sessions meter their minutes; tests that check metering capture this themselves.
    from app.services.stripe_service import UsageRecord

    async def no_metering(org_id, user_id, session_id, *args, **kwargs):
        return UsageRecord(session_id, 0, False)

    monkeypatch.setattr("app.services.stripe_service.arecord_audio_usage", no_metering)
    fake_client = lambda *args, **kwargs: FakeSupabase()  # noqa: E731
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", fake_client)
    monkeypatch.setattr("app.services.live_session.get_supabase_for_user", fake_client)
