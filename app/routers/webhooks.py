from fastapi import APIRouter, Header, HTTPException, status

from app.services import n8n_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/n8n")
async def n8n_callback(payload: dict, x_webhook_secret: str | None = Header(default=None)) -> dict:
    """Inbound callback from n8n. Wire up real handling in the next phase."""
    if not n8n_service.verify_webhook_secret(x_webhook_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook secret")
    return {"received": True}
