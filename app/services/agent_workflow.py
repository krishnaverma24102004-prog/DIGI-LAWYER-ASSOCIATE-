"""Multi-agent orchestration for live consultations (LangGraph).

Each pass over new speech runs this graph:

    START -> intake_analyzer -> legal_researcher -+-(knowledge base weak or empty)-> external_researcher -+
                                                  |                                                      |
                                                  +------------------------------------------------------+
                                                  |
                                                  +-(something new)-> risk_evaluator -> drafter -> END
                                                  +-(nothing new)---------------------> drafter

  intake_analyzer      updates the case's key facts from the new speech (Claude, fast model)
  legal_researcher     searches the org's knowledge base (pgvector) using the facts and new speech
  external_researcher  when the knowledge base has no confident match, searches the live web for
                       recent legal news, public case law and current statutes (privacy-safe
                       queries written by Claude, then Tavily)
  risk_evaluator       cross-references facts with citations, web sources, practice-area rules
                       and the contract
  drafter              writes the note for the lawyer (copilot mode) or the spoken reply
                       (conversation mode), then passes it through the output-safety guardrail

The state carries only data. Per-session dependencies (practice area, contract, the
research function, the status callback) travel in the LangGraph runtime context.
Text in the state is already PII-masked by the caller.

A node that fails keeps the previous values and records the error, so one slow or failed
model call never wipes the analysis the lawyer is looking at.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.core.config import get_settings
from app.core.guardrails import verify_output_safety
from app.models.analysis import ContractObservation, KeyFact, LegalIssue
from app.services import anthropic_service, citation_service, jurisdiction_service
from app.services.document_service import DocumentContext
from app.services.jurisdiction_service import JurisdictionProfile
from app.services.prompt_engine import PracticeAreaProfile
from app.services.rag_service import Precedent
from app.services.web_search import WebResult

logger = logging.getLogger(__name__)


class State(TypedDict, total=False):
    # Inputs for this pass
    transcript_history: str  # recent masked transcript
    current_chunk: str  # masked speech since the previous pass
    case_memory: str | None  # summaries of earlier sessions in the case thread
    # Carried between passes and updated by the agents
    extracted_facts: list[dict]
    rag_citations: list[dict]  # Precedent fields, including the passage text
    web_results: list[dict]  # WebResult fields from the external researcher
    legal_risks: list[dict]
    contract_observations: list[dict]
    follow_up_questions: list[str]
    # Output of this pass
    final_response: dict
    facts_changed: bool
    citations_changed: bool
    web_results_changed: bool
    needs_web_search: bool
    web_search_queries: list[str]
    errors: list[str]


StatusCallback = Callable[[str, str], Awaitable[None]]
ResearchFunction = Callable[[str], Awaitable[list[Precedent] | None]]
WebSearchFunction = Callable[[list[str]], Awaitable[list[WebResult] | None]]


@dataclass
class AgentContext:
    practice_area: PracticeAreaProfile | None = None
    document: DocumentContext | None = None
    # Returns the matched passages, or None when the search was skipped (rate limit).
    research: ResearchFunction | None = None
    # Called as each agent starts, e.g. ("legal_researcher", "Researching statutes...").
    emit_status: StatusCallback | None = None
    # Live web search; None when unavailable or not allowed right now (session rate limit).
    web_search: WebSearchFunction | None = None
    # "copilot": notes for the lawyer. "conversation": spoken replies to the user.
    mode: str = "copilot"
    # Statutory framework and citation style for every agent (and the RAG filter, in `research`).
    jurisdiction: JurisdictionProfile | None = None
    # Looks case citations up in the citation index: (report keys, party names) -> the known ones.
    lookup_authorities: Callable[[list[str], list[tuple[str, ...]]], Awaitable[tuple[set[str], list[tuple[str, ...]]]]] | None = None
    # Public channels (WhatsApp, phone): the drafter only asks intake questions; the channel holds
    # anything with legal substance for a lawyer (services/intake_guard.py).
    intake_only: bool = False


NODE_STATUS = {
    "intake_analyzer": "Analyzing what was said...",
    "legal_researcher": "Researching statutes and precedents...",
    "external_researcher": "Searching the web for recent law...",
    "risk_evaluator": "Evaluating legal risks...",
    "drafter": "Drafting guidance...",
}


async def _status(runtime: Runtime[AgentContext], node: str) -> None:
    callback = runtime.context.emit_status if runtime.context else None
    if callback is not None:
        await callback(node, NODE_STATUS[node])


def _errors(state: State, node: str, exc: Exception) -> list[str]:
    logger.warning("Agent node %s failed: %s", node, exc)
    return [*state.get("errors", []), f"{node}: {exc}"]


def _precedents(state: State) -> list[Precedent]:
    return [Precedent(**c) for c in state.get("rag_citations", [])]


def _web_results(state: State) -> list[WebResult]:
    return [WebResult(**r) for r in state.get("web_results", [])]


def _sources(state: State, context: "AgentContext") -> citation_service.Sources:
    """The authority the agents were given: a citation found here is grounded.

    Not the conversation: a case the client mentions isn't authority until a source confirms it.
    """
    precedents = [f"{p.title}\n{p.metadata.get('citation') or ''}\n{p.content}" for p in _precedents(state)]
    web = [f"{r.title}\n{r.snippet}" for r in _web_results(state)]
    return citation_service.Sources.from_texts(
        state.get("case_memory"),
        context.document.text if context.document else None,
        jurisdiction_service.render_guidance(context.jurisdiction) if context.jurisdiction else None,
        *precedents,
        *web,
    )


async def _checked_sources(state: State, context: "AgentContext", *texts: str | None) -> citation_service.Sources:
    """The sources, plus any case cited in `texts` that the citation index knows to be real."""
    sources = _sources(state, context)
    keys, names = citation_service.case_lookups(*texts)
    if context.lookup_authorities is None or not (keys or names):
        return sources
    try:
        return sources.with_known(*await context.lookup_authorities(keys, names))
    except Exception as exc:
        logger.warning("Citation index lookup failed: %s", exc)
        return sources


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


# ----------------------------------------------------------------------------- nodes


async def node_intake_analyzer(state: State, runtime: Runtime[AgentContext]) -> dict:
    await _status(runtime, "intake_analyzer")
    known = [KeyFact.model_validate(f) for f in state.get("extracted_facts", [])]
    try:
        facts = await anthropic_service.extract_case_facts(
            state.get("transcript_history", ""),
            state.get("current_chunk", ""),
            known,
            case_memory=state.get("case_memory"),
            practice_area=runtime.context.practice_area,
            jurisdiction=runtime.context.jurisdiction,
        )
    except Exception as exc:
        return {"facts_changed": False, "errors": _errors(state, "intake_analyzer", exc)}
    dumped = [f.model_dump() for f in facts]
    return {"extracted_facts": dumped, "facts_changed": not _same(dumped, state.get("extracted_facts", []))}


async def node_legal_researcher(state: State, runtime: Runtime[AgentContext]) -> dict:
    research = runtime.context.research
    can_search_web = runtime.context.web_search is not None and bool(state.get("extracted_facts"))
    if research is None:  # no knowledge base this session: the web is the only source
        return {"citations_changed": False, "needs_web_search": can_search_web}
    await _status(runtime, "legal_researcher")
    facts = "; ".join(f["fact"] for f in state.get("extracted_facts", []) if f.get("fact"))
    # rag_service keeps the end of the query when trimming, so the facts go last.
    query = f"{state.get('current_chunk', '')}\n\nCase facts: {facts}" if facts else state.get("current_chunk", "")
    try:
        found = await research(query)
    except Exception as exc:
        return {"citations_changed": False, "needs_web_search": can_search_web, "errors": _errors(state, "legal_researcher", exc)}
    if found is None:  # skipped this pass (rate limit): wait for the next search before going to the web
        return {"citations_changed": False, "needs_web_search": False}
    citations = [asdict(p) for p in found]
    changed = [c["id"] for c in citations] != [c["id"] for c in state.get("rag_citations", [])]
    best = max((p.similarity for p in found), default=0.0)
    weak = best < get_settings().web_search_rag_threshold
    return {"rag_citations": citations, "citations_changed": changed, "needs_web_search": can_search_web and weak}


def route_to_assessment(state: State) -> str:
    """Re-evaluate risks only when there is something new to evaluate."""
    if state.get("facts_changed") or state.get("citations_changed") or state.get("web_results_changed"):
        return "risk_evaluator"
    if state.get("extracted_facts") and not state.get("legal_risks"):
        return "risk_evaluator"
    return "drafter"


def route_after_research(state: State) -> str:
    """Go to the web when the knowledge base was empty or weak for these facts."""
    if state.get("needs_web_search"):
        return "external_researcher"
    return route_to_assessment(state)


async def node_external_researcher(state: State, runtime: Runtime[AgentContext]) -> dict:
    web_search = runtime.context.web_search
    if web_search is None:
        return {"web_results_changed": False}
    await _status(runtime, "external_researcher")
    try:
        plan = await anthropic_service.plan_web_search(
            [KeyFact.model_validate(f) for f in state.get("extracted_facts", [])],
            [LegalIssue.model_validate(r) for r in state.get("legal_risks", [])],
            state.get("transcript_history", ""),
            practice_area=runtime.context.practice_area,
            jurisdiction=runtime.context.jurisdiction,
        )
        if not plan.needed or not plan.queries:
            return {"web_results_changed": False, "web_search_queries": []}
        results = await web_search(plan.queries)
    except Exception as exc:
        return {"web_results_changed": False, "errors": _errors(state, "external_researcher", exc)}
    if results is None:
        return {"web_results_changed": False, "web_search_queries": plan.queries}
    dumped = [r.as_dict() for r in results]
    changed = [r["url"] for r in dumped] != [r["url"] for r in state.get("web_results", [])]
    return {"web_results": dumped, "web_results_changed": changed, "web_search_queries": plan.queries}


async def node_risk_evaluator(state: State, runtime: Runtime[AgentContext]) -> dict:
    await _status(runtime, "risk_evaluator")
    try:
        evaluation = await anthropic_service.evaluate_legal_risks(
            [KeyFact.model_validate(f) for f in state.get("extracted_facts", [])],
            state.get("transcript_history", ""),
            [LegalIssue.model_validate(r) for r in state.get("legal_risks", [])],
            previous_observations=[ContractObservation.model_validate(o) for o in state.get("contract_observations", [])],
            precedents=_precedents(state),
            practice_area=runtime.context.practice_area,
            jurisdiction=runtime.context.jurisdiction,
            document_context=runtime.context.document,
            case_memory=state.get("case_memory"),
            web_results=_web_results(state),
        )
    except Exception as exc:
        return {"errors": _errors(state, "risk_evaluator", exc)}
    # Fabricated authority is removed from each issue (CLAUDE.md invariant 3).
    sources = await _checked_sources(state, runtime.context, *(i.authority for i in evaluation.legal_issues))
    return {
        "legal_risks": [citation_service.verify_issue(r.model_dump(), sources) for r in evaluation.legal_issues],
        "contract_observations": [o.model_dump() for o in evaluation.contract_observations],
    }


async def node_drafter(state: State, runtime: Runtime[AgentContext]) -> dict:
    await _status(runtime, "drafter")
    questions = state.get("follow_up_questions", [])
    message, safety, citations = None, None, []
    try:
        draft = await anthropic_service.draft_response(
            [KeyFact.model_validate(f) for f in state.get("extracted_facts", [])],
            [LegalIssue.model_validate(r) for r in state.get("legal_risks", [])],
            state.get("transcript_history", ""),
            questions,
            precedents=_precedents(state),
            practice_area=runtime.context.practice_area,
            jurisdiction=runtime.context.jurisdiction,
            case_memory=state.get("case_memory"),
            web_results=_web_results(state),
            mode="intake" if runtime.context.intake_only else runtime.context.mode,
        )
        questions = draft.follow_up_questions
        # Citations the sources don't support are marked "[unverified]" in the message itself.
        sources = await _checked_sources(state, runtime.context, draft.message)
        checked, checks = citation_service.verify_text(draft.message, sources)
        if runtime.context.mode == "conversation" or runtime.context.intake_only:
            # Said to the client: unsupported citations are left out rather than flagged.
            checked = citation_service.for_client(draft.message, checks)
        citations = [c.as_dict() for c in checks]
        safety = verify_output_safety(checked)
        message = safety.text
    except Exception as exc:
        errors = _errors(state, "drafter", exc)
    else:
        errors = state.get("errors", [])

    final_response = {
        "message": message,
        "disclaimer_appended": bool(safety and safety.disclaimer_appended),
        "safety_flags": safety.reasons if safety else [],
        "citations": citations,
        "web_sources": [r.source() for r in _web_results(state)],
        "analysis": {
            "key_facts": state.get("extracted_facts", []),
            "legal_issues": state.get("legal_risks", []),
            "follow_up_questions": questions,
            "contract_observations": state.get("contract_observations", []),
        },
    }
    return {"follow_up_questions": questions, "final_response": final_response, "errors": errors}


# ----------------------------------------------------------------------------- graph


def build_graph():
    graph = StateGraph(State, context_schema=AgentContext)
    graph.add_node("intake_analyzer", node_intake_analyzer)
    graph.add_node("legal_researcher", node_legal_researcher)
    graph.add_node("external_researcher", node_external_researcher)
    graph.add_node("risk_evaluator", node_risk_evaluator)
    graph.add_node("drafter", node_drafter)
    graph.add_edge(START, "intake_analyzer")
    graph.add_edge("intake_analyzer", "legal_researcher")
    graph.add_conditional_edges("legal_researcher", route_after_research, ["external_researcher", "risk_evaluator", "drafter"])
    graph.add_conditional_edges("external_researcher", route_to_assessment, ["risk_evaluator", "drafter"])
    graph.add_edge("risk_evaluator", "drafter")
    graph.add_edge("drafter", END)
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def process_audio_chunk_via_agent(state: State, context: AgentContext | None = None) -> State:
    """Run one pass of the agent team over new speech and return the updated state."""
    fresh = {"errors": [], "web_results_changed": False, "needs_web_search": False, "web_search_queries": []}
    return await get_graph().ainvoke({**state, **fresh}, context=context or AgentContext())
