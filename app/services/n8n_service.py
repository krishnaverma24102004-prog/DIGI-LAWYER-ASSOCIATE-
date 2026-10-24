"""n8n integration (phase 2): trigger outbound workflows and verify inbound callbacks."""

import hmac

import httpx

from app.core.config import get_settings


async def trigger_workflow(webhook_path: str, payload: dict) -> dict:
    """POST to an n8n Webhook node, e.g. webhook_path='transcript-uploaded'."""
    settings = get_settings()
    if not settings.n8n_webhook_base_url:
        raise RuntimeError("N8N_WEBHOOK_BASE_URL is not set")

    url = f"{settings.n8n_webhook_base_url.rstrip('/')}/{webhook_path.lstrip('/')}"
    headers = {"X-Webhook-Secret": settings.n8n_webhook_secret} if settings.n8n_webhook_secret else {}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json() if response.content else {}


def is_configured() -> bool:
    return bool(get_settings().n8n_webhook_base_url)


async def trigger_post_consultation(payload: dict) -> dict:
    """Start the post-consultation workflow (follow-up emails, tasks, CRM, ...)."""
    return await trigger_workflow(get_settings().n8n_post_consultation_path, payload)


def verify_webhook_secret(provided: str | None) -> bool:
    expected = get_settings().n8n_webhook_secret
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided, expected)
