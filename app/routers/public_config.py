from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["config"])


@router.get("/public-config")
def public_config() -> dict:
    """Values a browser client needs to sign in with Supabase. Both are public by design."""
    settings = get_settings()
    return {"supabase_url": settings.supabase_url, "supabase_anon_key": settings.supabase_anon_key}
