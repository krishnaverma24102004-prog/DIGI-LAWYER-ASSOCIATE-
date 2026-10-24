from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.database import get_supabase_admin

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness check: the API process is up."""
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/health/db")
def health_db() -> dict:
    """Readiness check: Supabase is reachable and the schema exists."""
    try:
        get_supabase_admin().table("users").select("id").limit(1).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return {"status": "ok", "database": "reachable"}
