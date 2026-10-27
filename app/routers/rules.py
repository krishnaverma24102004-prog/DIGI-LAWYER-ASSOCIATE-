"""Firm sign-off of statutory rule tables (limitation periods, punishments for default bail).

The rule tables in app/data/ ship as drafts written from the statutes. A rule version applies in a
firm only once two of its members (associates or above) have signed it (`rule_active()`, migration
014), so the tables are the firm's own checked rules, not the vendor's word.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, StringConstraints

from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service

router = APIRouter(prefix="/rules", tags=["rules"])

DATA = Path(__file__).resolve().parents[1] / "data"
REGISTRIES = {"limitation": "limitation_rules.json", "offence_punishments": "offence_punishments.json"}
Registry = Literal["limitation", "offence_punishments"]


class Signature(BaseModel):
    version: int
    confirm: bool  # "I have checked this rule against the statute"
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


@lru_cache(maxsize=None)
def load_registry(registry: str) -> dict[str, dict]:
    """rule_id -> rule, from the registry file (empty when the file isn't there yet)."""
    path = DATA / REGISTRIES[registry]
    if not path.exists():
        return {}
    return {r["rule_id"]: r for r in json.loads(path.read_text(encoding="utf-8")).get("rules", [])}


def _signatures(ctx: OrgContext, registry: str) -> list[dict]:
    return (ctx.db().table("rule_verifications").select("rule_id, version, verified_by, verified_at, note")
            .eq("registry", registry).execute().data)


@router.get("/{registry}")
async def list_rules(registry: Registry, ctx: OrgContext = Depends(get_org_context)):
    """Every rule with this firm's sign-offs for its current version, and whether it applies yet."""
    rules = load_registry(registry)
    signed = await run_in_threadpool(_signatures, ctx, registry)
    out = []
    for rule in rules.values():
        sigs = [s for s in signed if s["rule_id"] == rule["rule_id"] and s["version"] == rule["version"]]
        signers = sorted({s["verified_by"] for s in sigs})
        out.append({
            "rule_id": rule["rule_id"], "version": rule["version"], "title": rule.get("title"), "basis": rule.get("basis"),
            "signatures": sigs, "active": len(signers) >= 2, "signed_by_me": ctx.user.id in signers,
        })
    return out


@router.post("/{registry}/{rule_id}/sign", status_code=status.HTTP_201_CREATED)
async def sign_rule(registry: Registry, rule_id: str, payload: Signature, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Sign the current version of a rule after checking it against the statute (associates and above)."""
    rule = load_registry(registry).get(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such rule")
    if payload.version != rule["version"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The current version of this rule is {rule['version']}; review that one")
    if not payload.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirm that you checked the rule against the statute")
    try:
        row = await run_in_threadpool(lambda: ctx.db().table("rule_verifications").insert({
            "registry": registry, "rule_id": rule_id, "version": rule["version"], "note": payload.note,
        }).execute().data[0])
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message:
            raise HTTPException(status.HTTP_409_CONFLICT, "You have already signed this version") from exc
        if "row-level security" in message or "42501" in message:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Associates, partners and owners sign rules") from exc
        raise
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, "SIGN_RULE", f"{registry}_rule", rule_id,
                                        ip_address=audit_service.client_ip(request), metadata={"version": rule["version"]})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return row
