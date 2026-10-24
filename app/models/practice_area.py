from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Rule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
RuleList = Annotated[list[Rule], Field(max_length=25)]


class RiskEvaluationRules(BaseModel):
    """How a practice area grades risk. Rendered into the live-analysis prompt."""

    model_config = ConfigDict(extra="forbid")

    high: RuleList = Field(default_factory=list, description="Situations that are always high severity")
    medium: RuleList = Field(default_factory=list)
    low: RuleList = Field(default_factory=list)
    red_flags: RuleList = Field(default_factory=list, description="Things to flag the moment they are mentioned")
    key_facts_to_capture: RuleList = Field(default_factory=list, description="Facts the intake must establish")
    deadlines: RuleList = Field(default_factory=list, description="Time limits to check for")


class PracticeAreaCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    custom_system_prompt: Annotated[str, StringConstraints(max_length=8000)] = ""
    risk_evaluation_rules: RiskEvaluationRules = Field(default_factory=RiskEvaluationRules)


class PracticeAreaUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    description: Annotated[str, StringConstraints(max_length=1000)] | None = None
    custom_system_prompt: Annotated[str, StringConstraints(max_length=8000)] | None = None
    risk_evaluation_rules: RiskEvaluationRules | None = None


class PracticeArea(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    custom_system_prompt: str
    risk_evaluation_rules: dict
    created_at: datetime
    updated_at: datetime


class PracticeAreaTemplate(PracticeAreaCreate):
    pass
