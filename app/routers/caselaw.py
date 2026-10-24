"""Case-law search across Indian courts (Indian Kanoon)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.services import indiankanoon_service

router = APIRouter(prefix="/caselaw", tags=["caselaw"])


@router.get("/search", dependencies=[Depends(limit("llm"))])
async def search_caselaw(
    q: Annotated[str, Query(min_length=3, max_length=500, description="Words, phrases in quotes, ANDD / ORR / NOTT")],
    page: Annotated[int, Query(ge=0, le=20)] = 0,
    courts: Annotated[str | None, Query(max_length=200, description="e.g. supremecourt, highcourts, delhi")] = None,
    ctx: OrgContext = Depends(get_org_context),
):
    """Judgments matching the query, with links to the full text on indiankanoon.org."""
    if not indiankanoon_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Case law search is not configured (INDIANKANOON_API_TOKEN)")
    try:
        results = await run_in_threadpool(indiankanoon_service.search, q, page=page, doctypes=courts)
    except indiankanoon_service.IndianKanoonError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"results": results, "page": page, "attribution": indiankanoon_service.ATTRIBUTION}
