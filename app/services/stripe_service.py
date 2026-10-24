"""Stripe subscriptions and usage-based billing of audio minutes.

Billing is per organization:

* `create_checkout_session` starts a Stripe Checkout subscription for the Starter, Pro or
  Enterprise tier (plus the metered audio-minutes Price, when configured).
* `handle_event` applies verified webhook events to `billing_accounts` and
  `organizations.plan_tier`, idempotently (each event id is processed once).
* `record_audio_usage` meters a finished audio session (WebSocket, WebRTC or phone call):
  it stores the duration in `audio_usage` and reports the minutes to the Stripe meter.
* `get_usage` returns the subscription status and remaining included minutes.

Webhooks and metering write with the service role: they are server-side jobs with no user
behind them, and billing tables are read-only for users (migration 007). Reads made for a
user (`get_usage`, the checkout lookup) use the user's own client, so RLS applies.
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

import stripe
from fastapi.concurrency import run_in_threadpool
from supabase import Client

from app.core.config import get_settings
from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

TIERS = ("starter", "pro", "enterprise")
# Subscription statuses that keep the paid tier (past_due: Stripe is still retrying payment).
ENTITLED_STATUSES = {"active", "trialing", "past_due"}
HANDLED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_succeeded",
    "payment_intent.succeeded",
}


class BillingError(RuntimeError):
    pass


class BillingNotConfigured(BillingError):
    pass


def is_configured() -> bool:
    return bool(get_settings().stripe_secret_key)


def _client() -> stripe.StripeClient:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise BillingNotConfigured("STRIPE_SECRET_KEY is not set")
    return stripe.StripeClient(settings.stripe_secret_key, http_client=stripe.HTTPXClient())


def price_for(tier: str) -> str:
    settings = get_settings()
    price = {"starter": settings.stripe_price_starter, "pro": settings.stripe_price_pro,
             "enterprise": settings.stripe_price_enterprise}.get(tier, "")
    if not price:
        raise BillingNotConfigured(f"No Stripe price configured for the {tier} tier (STRIPE_PRICE_{tier.upper()})")
    return price


def included_minutes(tier: str | None) -> int:
    settings = get_settings()
    return {"starter": settings.billing_starter_minutes, "pro": settings.billing_pro_minutes,
            "enterprise": settings.billing_enterprise_minutes}.get(tier or "", 0)


def tier_for_price(price_id: str | None) -> str | None:
    settings = get_settings()
    for tier, price in (("starter", settings.stripe_price_starter), ("pro", settings.stripe_price_pro),
                        ("enterprise", settings.stripe_price_enterprise)):
        if price and price == price_id:
            return tier
    return None


def billed_minutes(duration_seconds: float) -> int:
    """Minutes billed for a session: every started minute counts."""
    return math.ceil(duration_seconds / 60) if duration_seconds > 0 else 0


# ----------------------------------------------------------------------------- checkout


def get_account(db: Client) -> dict | None:
    """The active org's billing account, as the user (RLS: owners and partners). Blocking."""
    rows = db.table("billing_accounts").select("*").limit(1).execute().data
    return rows[0] if rows else None


async def create_checkout_session(org_id: str, tier: str, *, customer_id: str | None, email: str | None) -> dict:
    if tier not in TIERS:
        raise BillingError(f"Unknown tier {tier!r}")
    settings = get_settings()
    line_items = [{"price": price_for(tier), "quantity": 1}]
    if settings.stripe_metered_price:
        line_items.append({"price": settings.stripe_metered_price})  # metered: no quantity
    params = {
        "mode": "subscription",
        "line_items": line_items,
        "success_url": settings.billing_success_url,
        "cancel_url": settings.billing_cancel_url,
        "client_reference_id": org_id,
        "metadata": {"org_id": org_id, "tier": tier},
        "subscription_data": {"metadata": {"org_id": org_id, "tier": tier}},
        "allow_promotion_codes": True,
    }
    if customer_id:
        params["customer"] = customer_id
    elif email:
        params["customer_email"] = email
    try:
        session = await _client().v1.checkout.sessions.create_async(params=params)
    except stripe.StripeError as exc:
        raise BillingError(f"Stripe error: {exc.user_message or type(exc).__name__}") from exc
    return {"id": session.id, "url": session.url}


# ----------------------------------------------------------------------------- webhooks


def verify_webhook(payload: bytes, signature: str | None) -> dict:
    """Check the Stripe-Signature header; return the event as plain JSON."""
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise BillingNotConfigured("STRIPE_WEBHOOK_SECRET is not set")
    try:
        stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BillingError("Invalid Stripe webhook signature") from exc
    return json.loads(payload)


def _ts(value) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if isinstance(value, (int, float)) else None


def _id(value) -> str | None:
    """Stripe fields hold an id, or the expanded object."""
    if isinstance(value, dict):
        return value.get("id")
    return value if isinstance(value, str) else None


def _subscription_period(sub: dict) -> tuple[str | None, str | None]:
    # Newer API versions keep the period on the subscription items.
    items = (sub.get("items") or {}).get("data") or []
    start = sub.get("current_period_start") or (items[0].get("current_period_start") if items else None)
    end = sub.get("current_period_end") or (items[0].get("current_period_end") if items else None)
    return _ts(start), _ts(end)


def _subscription_tier(sub: dict) -> str | None:
    tier = (sub.get("metadata") or {}).get("tier")
    if tier in TIERS:
        return tier
    for item in (sub.get("items") or {}).get("data") or []:
        found = tier_for_price(_id(item.get("price")))
        if found:
            return found
    return None


def _invoice_subscription(invoice: dict) -> str | None:
    if invoice.get("subscription"):
        return _id(invoice["subscription"])
    details = ((invoice.get("parent") or {}).get("subscription_details")) or {}
    return _id(details.get("subscription"))


class _Accounts:
    """billing_accounts writes (service role) for one webhook event."""

    def __init__(self, db: Client):
        self.db = db

    def find_org(self, *, org_id=None, subscription_id=None, customer_id=None) -> str | None:
        if org_id:
            return org_id
        for column, value in (("stripe_subscription_id", subscription_id), ("stripe_customer_id", customer_id)):
            if value:
                rows = self.db.table("billing_accounts").select("org_id").eq(column, value).limit(1).execute().data
                if rows:
                    return rows[0]["org_id"]
        return None

    def upsert(self, org_id: str, fields: dict) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}  # unknown values keep what's stored
        self.db.table("billing_accounts").upsert({"org_id": org_id, **fields}, on_conflict="org_id").execute()
        if "status" in fields or "tier" in fields:
            row = self.db.table("billing_accounts").select("tier, status").eq("org_id", org_id).limit(1).execute().data
            account = row[0] if row else {}
            plan = account.get("tier") if account.get("status") in ENTITLED_STATUSES and account.get("tier") else "free"
            self.db.table("organizations").update({"plan_tier": plan}).eq("id", org_id).execute()


def _apply_subscription(accounts: _Accounts, sub: dict, *, deleted: bool = False) -> str:
    org_id = accounts.find_org(org_id=(sub.get("metadata") or {}).get("org_id"), subscription_id=sub.get("id"),
                               customer_id=_id(sub.get("customer")))
    if org_id is None:
        return "ignored: unknown organization"
    start, end = _subscription_period(sub)
    tier = _subscription_tier(sub)
    status = "canceled" if deleted else sub.get("status", "inactive")
    accounts.upsert(org_id, {
        "stripe_customer_id": _id(sub.get("customer")),
        "stripe_subscription_id": sub.get("id"),
        "tier": tier,
        "status": status,
        "included_minutes": included_minutes(tier) if status in ENTITLED_STATUSES else 0,
        "current_period_start": start,
        "current_period_end": end,
    })
    return f"subscription {status}"


def handle_event(event: dict, db: Client | None = None) -> str:
    """Apply one verified Stripe event. Idempotent per event id. Blocking."""
    db = db or get_supabase_admin()
    event_type = event.get("type", "")
    if event_type not in HANDLED_EVENTS:
        return "ignored"
    inserted = db.table("stripe_events").upsert(
        {"id": event["id"], "type": event_type}, on_conflict="id", ignore_duplicates=True
    ).execute().data
    if not inserted:
        return "duplicate"
    obj = (event.get("data") or {}).get("object") or {}
    accounts = _Accounts(db)
    try:
        match event_type:
            case "checkout.session.completed":
                org_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("org_id")
                if not org_id:
                    return "ignored: no organization"
                tier = (obj.get("metadata") or {}).get("tier")
                accounts.upsert(org_id, {
                    "stripe_customer_id": _id(obj.get("customer")),
                    "stripe_subscription_id": _id(obj.get("subscription")),
                    "tier": tier if tier in TIERS else None,
                })
                return "checkout linked"
            case "customer.subscription.created" | "customer.subscription.updated":
                return _apply_subscription(accounts, obj)
            case "customer.subscription.deleted":
                return _apply_subscription(accounts, obj, deleted=True)
            case "invoice.payment_succeeded":
                subscription_id = _invoice_subscription(obj)
                org_id = accounts.find_org(subscription_id=subscription_id, customer_id=_id(obj.get("customer")))
                if org_id is None:
                    return "ignored: unknown organization"
                lines = (obj.get("lines") or {}).get("data") or []
                period = (lines[0].get("period") or {}) if lines else {}
                accounts.upsert(org_id, {
                    "status": "active" if subscription_id else None,
                    "last_payment_at": _ts(obj.get("status_transitions", {}).get("paid_at")) or _ts(obj.get("created")),
                    "current_period_start": _ts(period.get("start")) if subscription_id else None,
                    "current_period_end": _ts(period.get("end")) if subscription_id else None,
                })
                return "payment recorded"
            case "payment_intent.succeeded":
                org_id = accounts.find_org(org_id=(obj.get("metadata") or {}).get("org_id"),
                                           customer_id=_id(obj.get("customer")))
                if org_id is None:
                    return "ignored: unknown organization"
                accounts.upsert(org_id, {"last_payment_at": _ts(obj.get("created"))})
                return "payment recorded"
    except Exception:
        # Let Stripe's retry process this event again.
        db.table("stripe_events").delete().eq("id", event["id"]).execute()
        raise
    return "ignored"


async def ahandle_event(event: dict) -> str:
    return await run_in_threadpool(handle_event, event)


# ----------------------------------------------------------------------------- usage metering


@dataclass
class UsageRecord:
    session_id: str
    billed_minutes: int
    reported_to_stripe: bool


def record_audio_usage(
    org_id: str,
    user_id: str | None,
    session_id: str,
    transport: str,
    started_at: datetime,
    ended_at: datetime,
    *,
    duration_seconds: float | None = None,
    db: Client | None = None,
) -> UsageRecord:
    """Meter one finished audio session and report it to Stripe. Blocking; idempotent per session.

    `duration_seconds` is the audio actually streamed; without it, the session's wall-clock length.
    """
    db = db or get_supabase_admin()
    wall = (ended_at - started_at).total_seconds()
    seconds = max(0.0, wall if duration_seconds is None else min(duration_seconds, wall))
    minutes = billed_minutes(seconds)
    db.table("audio_usage").upsert(
        {
            "org_id": org_id,
            "user_id": user_id,
            "session_id": session_id,
            "transport": transport,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": int(round(seconds)),
            "billed_minutes": minutes,
        },
        on_conflict="session_id",
        ignore_duplicates=True,
    ).execute()

    settings = get_settings()
    if not minutes or not is_configured() or not settings.stripe_meter_event_name:
        return UsageRecord(session_id, minutes, False)
    rows = db.table("billing_accounts").select("stripe_customer_id").eq("org_id", org_id).limit(1).execute().data
    customer_id = rows[0]["stripe_customer_id"] if rows else None
    if not customer_id:
        return UsageRecord(session_id, minutes, False)
    try:
        _client().v1.billing.meter_events.create(params={
            "event_name": settings.stripe_meter_event_name,
            "payload": {"stripe_customer_id": customer_id, "value": str(minutes)},
            # Stripe de-duplicates on the identifier, so a retried report isn't billed twice.
            "identifier": session_id,
            "timestamp": int(ended_at.timestamp()),
        })
    except stripe.StripeError:
        logger.exception("Reporting %s audio minutes to Stripe failed for session %s", minutes, session_id)
        return UsageRecord(session_id, minutes, False)
    db.table("audio_usage").update({"stripe_reported_at": datetime.now(timezone.utc).isoformat()}).eq(
        "session_id", session_id
    ).execute()
    return UsageRecord(session_id, minutes, True)


async def arecord_audio_usage(*args, **kwargs) -> UsageRecord:
    return await run_in_threadpool(record_audio_usage, *args, **kwargs)


def get_usage(db: Client) -> dict:
    """Subscription status and audio minutes for the active org, as the user (RLS). Blocking."""
    account = get_account(db) or {}
    now = datetime.now(timezone.utc)
    period_start = account.get("current_period_start") or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = db.table("audio_usage").select("billed_minutes").gte("started_at", period_start).execute().data
    used = sum(r["billed_minutes"] for r in rows)
    included = account.get("included_minutes") or 0
    return {
        "tier": account.get("tier"),
        "status": account.get("status", "inactive"),
        "active": account.get("status") in ENTITLED_STATUSES,
        "included_minutes": included,
        "used_minutes": used,
        "remaining_minutes": max(0, included - used),
        "overage_minutes": max(0, used - included),
        "current_period_start": period_start,
        "current_period_end": account.get("current_period_end"),
        "last_payment_at": account.get("last_payment_at"),
    }
