"""Billing: Stripe Checkout for subscriptions, Stripe webhooks, and audio-minute usage."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.rate_limiter import limit
from app.core.rbac import Permission
from app.dependencies.org import OrgContext, require_permission
from app.services import audit_service, stripe_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    tier: Literal["starter", "pro", "enterprise"]


class CheckoutSession(BaseModel):
    id: str
    url: str


@router.post("/checkout-session", response_model=CheckoutSession, dependencies=[Depends(limit("billing"))])
async def create_checkout_session(
    payload: CheckoutRequest, request: Request, ctx: OrgContext = Depends(require_permission(Permission.BILLING_MANAGE))
):
    """Start a Stripe Checkout subscription for the active organization. Owners only."""
    if not stripe_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured (STRIPE_SECRET_KEY)")
    account = await run_in_threadpool(stripe_service.get_account, ctx.db())
    try:
        session = await stripe_service.create_checkout_session(
            ctx.org_id, payload.tier,
            customer_id=(account or {}).get("stripe_customer_id"), email=ctx.user.email,
        )
    except stripe_service.BillingNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except stripe_service.BillingError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.START_CHECKOUT, "billing", session["id"],
            ip_address=audit_service.client_ip(request), metadata={"tier": payload.tier},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return session


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Stripe events. Authenticated by the Stripe-Signature header, not a user token."""
    payload = await request.body()
    try:
        event = stripe_service.verify_webhook(payload, request.headers.get("stripe-signature"))
    except stripe_service.BillingNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except stripe_service.BillingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    outcome = await stripe_service.ahandle_event(event)
    return {"received": True, "outcome": outcome}


@router.get("/usage")
async def get_usage(ctx: OrgContext = Depends(require_permission(Permission.BILLING_VIEW))):
    """Subscription status and audio minutes for the current billing period (owners and partners)."""
    return await run_in_threadpool(stripe_service.get_usage, ctx.db())
