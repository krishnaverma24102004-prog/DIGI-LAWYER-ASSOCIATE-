"""Indian practice workflow packs: statutory deadlines computed in code, checklists, and a draft to start."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.org import OrgContext, get_org_context
from app.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


class Evaluate(BaseModel):
    inputs: dict[str, str | float | bool | None] = Field(default_factory=dict)


@router.get("")
def list_workflows(ctx: OrgContext = Depends(get_org_context)):
    return [pack.describe() for pack in workflow_service.PACKS.values()]


@router.post("/{workflow_id}/evaluate")
def evaluate(workflow_id: str, payload: Evaluate, ctx: OrgContext = Depends(get_org_context)):
    """Deadlines, flags, checklist and the suggested draft for this matter. No AI involved."""
    if workflow_id not in workflow_service.PACKS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    try:
        return workflow_service.evaluate(workflow_id, payload.inputs)
    except workflow_service.WorkflowError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
