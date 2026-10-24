from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

MAX_KEY_FACTS = 25
MAX_LEGAL_ISSUES = 15
MAX_FOLLOW_UP_QUESTIONS = 8
MAX_CONTRACT_OBSERVATIONS = 15


class KeyFact(BaseModel):
    fact: str
    category: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data):
        return {"fact": data} if isinstance(data, str) else data


class LegalIssue(BaseModel):
    issue: str
    area_of_law: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    rationale: str | None = None
    # Statute, case or firm precedent from the knowledge base that supports the issue.
    authority: str | None = None
    # Set by the citation check (services/citation_service.py), never by the model, so they're
    # left out of the JSON schema the model sees: verified | statute | flagged.
    authority_status: SkipJsonSchema[str | None] = None
    authority_note: SkipJsonSchema[str | None] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data):
        return {"issue": data} if isinstance(data, str) else data

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value):
        value = str(value or "").strip().lower()
        return value if value in {"low", "medium", "high"} else "medium"


class ContractObservation(BaseModel):
    """How something said in the consultation relates to the attached contract."""

    clause: str
    observation: str
    alignment: Literal["consistent", "conflict", "not_covered", "unclear"] = "unclear"

    @field_validator("alignment", mode="before")
    @classmethod
    def _normalize_alignment(cls, value):
        value = str(value or "").strip().lower().replace(" ", "_")
        return value if value in {"consistent", "conflict", "not_covered", "unclear"} else "unclear"


class LiveAnalysis(BaseModel):
    """Running analysis of a live consultation. Each update is a full snapshot."""

    key_facts: list[KeyFact] = Field(default_factory=list)
    legal_issues: list[LegalIssue] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    # Only filled when a contract is attached to the consultation.
    contract_observations: list[ContractObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap_lengths(self):
        self.key_facts = self.key_facts[:MAX_KEY_FACTS]
        self.legal_issues = self.legal_issues[:MAX_LEGAL_ISSUES]
        self.follow_up_questions = self.follow_up_questions[:MAX_FOLLOW_UP_QUESTIONS]
        self.contract_observations = self.contract_observations[:MAX_CONTRACT_OBSERVATIONS]
        return self


class ConsultationSummary(BaseModel):
    title: str
    summary: str


class VisionExtraction(BaseModel):
    """A page transcribed by Claude's vision model (OCR fallback)."""

    text: str
    contains_handwriting: bool = False
    legibility: Literal["high", "medium", "low"] = "medium"
    notes: str | None = None


# Structured outputs of the live agent nodes (services/agent_workflow.py).


class FactExtraction(BaseModel):
    key_facts: list[KeyFact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap(self):
        self.key_facts = self.key_facts[:MAX_KEY_FACTS]
        return self


class RiskEvaluation(BaseModel):
    legal_issues: list[LegalIssue] = Field(default_factory=list)
    contract_observations: list[ContractObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap(self):
        self.legal_issues = self.legal_issues[:MAX_LEGAL_ISSUES]
        self.contract_observations = self.contract_observations[:MAX_CONTRACT_OBSERVATIONS]
        return self


class DraftedResponse(BaseModel):
    message: str
    follow_up_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap(self):
        self.follow_up_questions = self.follow_up_questions[:MAX_FOLLOW_UP_QUESTIONS]
        return self


class WebSearchPlan(BaseModel):
    """Privacy-safe queries for the external-researcher agent."""

    needed: bool
    queries: list[str] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def _cap(self):
        self.queries = [q for q in self.queries if q.strip()][:2]
        return self


# ----------------------------------------------------------------------------- contract redlining

RiskImpact = Literal["increased", "decreased", "neutral"]
ChangeCategory = Literal[
    "added_risk", "removed_protection", "altered_liability", "altered_obligation", "altered_payment",
    "altered_termination", "altered_ip", "altered_confidentiality", "altered_dispute_resolution",
    "drafting_only", "other",
]


class ClauseRiskAssessment(BaseModel):
    clause_id: str
    change_summary: str
    risk_impact: RiskImpact = "neutral"
    categories: list[ChangeCategory] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "low"
    explanation: str = ""
    recommended_counter_clause: str | None = None

    @field_validator("risk_impact", mode="before")
    @classmethod
    def _impact(cls, value):
        value = str(value or "").strip().lower()
        return value if value in {"increased", "decreased", "neutral"} else "neutral"

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value):
        value = str(value or "").strip().lower()
        return value if value in {"low", "medium", "high"} else "low"


class ContractDiffAnalysis(BaseModel):
    clauses: list[ClauseRiskAssessment] = Field(default_factory=list)
    overall_summary: str = ""
    key_concerns: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- contradiction analysis

ContradictionKind = Literal["direct", "temporal", "location", "numerical", "identity", "sequence", "omission", "other"]


class ContradictionFinding(BaseModel):
    statement_line: int
    statement_quote: str
    source_id: str
    source_quote: str
    kind: ContradictionKind = "direct"
    severity: Literal["low", "medium", "high"] = "medium"
    explanation: str
    cross_examination_questions: list[str] = Field(default_factory=list)
    # Set by verification (not the model): "exact" or "close", and a close quote's words that differ.
    statement_match: Literal["exact", "close"] | None = None
    statement_differs: list[str] = Field(default_factory=list)
    source_match: Literal["exact", "close"] | None = None
    source_differs: list[str] = Field(default_factory=list)

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value):
        value = str(value or "").strip().lower()
        return value if value in {"low", "medium", "high"} else "medium"

    @model_validator(mode="after")
    def _cap(self):
        self.cross_examination_questions = self.cross_examination_questions[:5]
        return self


class ContradictionAnalysis(BaseModel):
    contradictions: list[ContradictionFinding] = Field(default_factory=list)
    consistent_points: list[str] = Field(default_factory=list)
    overall_assessment: str = ""


# ----------------------------------------------------------------------------- drafting


class NamedValue(BaseModel):
    name: str
    value: str


class DraftFill(BaseModel):
    """Claude's contribution to a template: variable values and the passages it writes."""

    title: str | None = None
    variables: list[NamedValue] = Field(default_factory=list)
    slots: list[NamedValue] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ClauseRevision(BaseModel):
    revised_text: str
    explanation: str


# ----------------------------------------------------------------------------- bulk review grid


class GridAnswer(BaseModel):
    """One question answered from one document."""

    question_id: str
    answer: str
    # The passage the answer rests on, copied exactly from the document; null when it doesn't say.
    quote: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value):
        value = str(value or "").strip().lower()
        return value if value in {"high", "medium", "low"} else "medium"


class DocumentReview(BaseModel):
    answers: list[GridAnswer] = Field(default_factory=list)
