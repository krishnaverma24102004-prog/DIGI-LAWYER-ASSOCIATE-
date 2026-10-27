"""Custody board: clients in custody, their default-bail and s. 479 BNSS dates, and the docket.

Dates are computed in code (custody_service) from the firm's signed punishment table. A file that
uses an entry the firm hasn't signed (two members, /rules/offence_punishments) is computed only
as a labelled preview, for owners and partners; others get 422 until the entry is signed.
"""

import logging
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, custody_service

router = APIRouter(prefix="/custody", tags=["custody"])
logger = logging.getLogger(__name__)
custody_service.register_engines()  # P13's blind check recomputes custody deadlines from re-entered inputs

TABLE = custody_service.TABLE
ORDERS = custody_service.ORDERS_TABLE
SENIOR = ("owner", "partner")
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class Period(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self):
        if self.end < self.start:
            raise ValueError("A custody period must end on or after its start")
        return self


class CustodyFields(BaseModel):
    accused_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    matter: Short | None = None
    court_case_id: UUID | None = None
    thread_id: UUID | None = None
    counsel_id: UUID | None = None
    backup_id: UUID | None = None
    offence_date: date | None = None
    fir_date: date | None = None
    fir_number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    police_station: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    investigation_started_on: date | None = Field(default=None, description="Defaults to the FIR date; for a complaint case, the complaint's date")
    complaint_case: bool | None = None
    arrest_date: date | None = None
    first_remand_date: date | None = None
    sections: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]] | None = Field(
        default=None, max_length=20, description="Punishment table rule ids (GET /custody/offences) or e.g. '302 IPC'")
    custody_type: Literal["police", "judicial", "released"] | None = None
    custody_periods: list[Period] | None = Field(default=None, max_length=50, description="Earlier, interrupted detention")
    chargesheet_filed_on: date | None = None
    default_bail_applied_on: date | None = None
    first_time_offender: bool | None = None
    other_pending_cases: bool | None = None
    accused_delay_days: int | None = Field(default=None, ge=0, le=10000)
    special_statute: Literal["NDPS_COMMERCIAL", "UAPA"] | None = None
    notes: Annotated[str, StringConstraints(max_length=5000)] | None = None


class CustodyCreate(CustodyFields):
    accused_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    offence_date: date
    arrest_date: date


class ExtensionOrder(BaseModel):
    order_date: date
    extended_to_days: int = Field(ge=1, le=400)
    court: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


def _row(fields: CustodyFields) -> dict:
    data = fields.model_dump(mode="json", exclude_unset=True)
    if "sections" in data and data["sections"] is not None:
        data["sections"] = [_canonical(s) for s in data["sections"]]
    return data


def _canonical(ref: str) -> str:
    """Store the table's rule id when the reference resolves; otherwise keep what was typed (flagged)."""
    rule = custody_service.resolve_section(ref)
    return rule["rule_id"] if rule else ref


async def _get_or_404(ctx: OrgContext, file_id: UUID) -> dict:
    rows = await run_in_threadpool(lambda: ctx.db().table(TABLE).select("*").eq("id", str(file_id)).limit(1).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custody file not found")
    return rows[0]


async def _orders(ctx: OrgContext, file_ids: list[str] | None = None) -> dict[str, list[dict]]:
    rows = await run_in_threadpool(lambda: ctx.db().table(ORDERS).select("*").execute().data or [])
    out: dict[str, list[dict]] = {}
    for row in rows:
        if file_ids is None or row["custody_file_id"] in file_ids:
            out.setdefault(row["custody_file_id"], []).append(row)
    return out


async def _active(ctx: OrgContext) -> set[str]:
    return await run_in_threadpool(custody_service.active_rule_ids, ctx.db(), ctx.org_id)


def _compute(file: dict, today: date, active: set[str], orders: list[dict]) -> dict:
    try:
        return custody_service.compute(file, today, active_rules=active, orders=orders)
    except custody_service.CustodyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _blocked(result: dict) -> dict:
    return {"code": "rules_unverified",
            "message": ("This computation uses punishment table entries the firm hasn't signed yet ("
                        + ", ".join(result["unverified_rules"]) + "). Two members must check and sign them under Rules; "
                        "until then owners and partners can see a labelled preview.")}


def _gate(ctx: OrgContext, result: dict, preview: bool) -> dict:
    if not result["unverified_rules"]:
        return result
    if preview and ctx.role in SENIOR:
        return result
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _blocked(result))


async def _audit(ctx: OrgContext, request: Request, action: str, file_id: str, metadata: dict | None = None) -> None:
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, action, "custody_file", file_id,
                                        ip_address=audit_service.client_ip(request), metadata=metadata)
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/offences")
async def list_offences(ctx: OrgContext = Depends(get_org_context)):
    """The punishment table for the section picker, with whether each entry is signed in this firm."""
    active = await _active(ctx)
    return [{k: r.get(k) for k in ("rule_id", "version", "kind", "code", "section", "title", "basis", "max_years", "min_years",
                                   "life", "death", "special_statute", "counterpart", "note", "base_days", "extended_days")}
            | {"active": r["rule_id"] in active}
            for r in custody_service.load_table().values()]


@router.get("")
async def list_files(preview: bool = Query(default=False, description="Owners and partners: include unsigned-table previews"),
                     include_released: bool = False, ctx: OrgContext = Depends(get_org_context)):
    """Every client in custody with today's dates; 'apply today' rows first."""
    rows = await run_in_threadpool(lambda: ctx.db().table(TABLE).select("*").limit(1000).execute().data or [])
    if not include_released:
        rows = [r for r in rows if r.get("custody_type") != "released"]
    active, orders, today = await _active(ctx), await _orders(ctx), date.today()
    out = []
    for row in rows:
        try:
            result = custody_service.compute(row, today, active_rules=active, orders=orders.get(row["id"], []))
        except custody_service.CustodyError as exc:
            out.append({"file": row, "result": None, "blocked": {"code": "invalid", "message": str(exc)}})
            continue
        if result["unverified_rules"] and not (preview and ctx.role in SENIOR):
            out.append({"file": row, "result": None, "blocked": _blocked(result)})
        else:
            out.append({"file": row, "result": result, "blocked": None})
    return sorted(out, key=lambda e: custody_service.sort_key(e["result"]) if e["result"] else (True, "9999-12-31"))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_file(payload: CustodyCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    row = _row(payload)
    _compute(row, date.today(), set(), [])  # validates the dates before saving
    saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).insert(row).execute().data[0])
    await _audit(ctx, request, "ADD_CUSTODY_FILE", saved["id"])
    return {**saved, "docket_sync": await _try_sync(ctx, request, saved["id"])}


async def _try_sync(ctx: OrgContext, request: Request, file_id: str) -> dict:
    """After a save: docket the dates when the rules are signed. A docket problem is reported, not raised."""
    try:
        return await _after_save(ctx, request, file_id)
    except HTTPException as exc:
        return {"problems": [str(exc.detail)]}
    except Exception as exc:  # the docket is another module; the custody file is saved either way
        logger.warning("custody docket sync failed for %s: %s", file_id, exc)
        return {"problems": ["The dates couldn't be saved to the docket; use Save to docket"]}


@router.get("/{file_id}")
async def get_file(file_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    file = await _get_or_404(ctx, file_id)
    orders = await _orders(ctx, [file["id"]])
    return {**file, "extension_orders": orders.get(file["id"], [])}


@router.patch("/{file_id}")
async def update_file(file_id: UUID, payload: CustodyFields, request: Request, ctx: OrgContext = Depends(get_org_context)):
    current = await _get_or_404(ctx, file_id)
    fields = _row(payload)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    for required in ("accused_name", "offence_date", "arrest_date"):
        if required in fields and fields[required] in (None, ""):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{required} can't be cleared")
    _compute({**current, **fields}, date.today(), set(), [])
    saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).update(fields).eq("id", str(file_id)).execute().data[0])
    await _audit(ctx, request, "UPDATE_CUSTODY_FILE", str(file_id), {"fields": sorted(fields)})
    return {**saved, "docket_sync": await _try_sync(ctx, request, str(file_id))}


@router.post("/{file_id}/compute")
async def compute_file(file_id: UUID, preview: bool = False, ctx: OrgContext = Depends(get_org_context)):
    """Worked dates with their basis, flags and badges (nothing is saved)."""
    file = await _get_or_404(ctx, file_id)
    orders, active = await _orders(ctx, [file["id"]]), await _active(ctx)
    result = _compute(file, date.today(), active, orders.get(file["id"], []))
    return _gate(ctx, result, preview)


async def _sync(ctx: OrgContext, request: Request, file: dict, result: dict) -> dict:
    """Docket (or close) this file's deadlines as the user; never fails the save it follows."""
    if result["unverified_rules"]:
        return {"docket": file.get("docket") or {}, "created": [], "problems": [], "skipped": "rules_unverified"}
    current, events, problems = await run_in_threadpool(custody_service.sync_docket, ctx.db(), file, result)
    update: dict = {"computed": result}
    if events:
        update["docket"] = current
        update["history"] = [*(file.get("history") or []), *events][-200:]
    await run_in_threadpool(lambda: ctx.db().table(TABLE).update(update).eq("id", file["id"]).execute())
    if events:
        await _audit(ctx, request, "DOCKET_CUSTODY_DATES", file["id"], {"events": [f"{e['event']}:{e['kind']}" for e in events]})
    return {"docket": current, "created": [e for e in events if e["event"] == "docketed"], "events": events, "problems": problems}


async def _after_save(ctx: OrgContext, request: Request, file_id: str) -> dict:
    file = await _get_or_404(ctx, UUID(file_id))
    orders, active = await _orders(ctx, [file["id"]]), await _active(ctx)
    result = _compute(file, date.today(), active, orders.get(file["id"], []))
    return await _sync(ctx, request, file, result)


@router.post("/{file_id}/docket")
async def save_to_docket(file_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Save the default-bail (hard, lead 5 days) and s. 479 dates as docket deadlines; close the
    default-bail deadline when a chargesheet or application ends it. Signed rules only."""
    file = await _get_or_404(ctx, file_id)
    orders, active = await _orders(ctx, [file["id"]]), await _active(ctx)
    result = _compute(file, date.today(), active, orders.get(file["id"], []))
    if result["unverified_rules"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _blocked(result))
    synced = await _sync(ctx, request, file, result)
    if synced["problems"] and not synced["events"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(synced["problems"]))
    return synced


@router.post("/{file_id}/extension-orders", status_code=status.HTTP_201_CREATED)
async def add_extension_order(file_id: UUID, payload: ExtensionOrder, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Record a special-statute extension order (NDPS s. 36A(4) / UAPA s. 43D(2)); only then is the extension applied."""
    file = await _get_or_404(ctx, file_id)
    rule = custody_service.special_period(file.get("special_statute") or custody_service.punishment(file.get("sections") or []).special_statute)
    if rule is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Extension orders apply only to NDPS (commercial quantity) and UAPA files")
    if payload.extended_to_days > rule["extended_days"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"{rule['basis']} allows an extension up to {rule['extended_days']} days")
    row = {**payload.model_dump(mode="json"), "custody_file_id": file["id"]}
    saved = await run_in_threadpool(lambda: ctx.db().table(ORDERS).insert(row).execute().data[0])
    await _audit(ctx, request, "ADD_CUSTODY_EXTENSION", file["id"], {"order_date": row["order_date"]})
    return {**saved, "docket_sync": await _try_sync(ctx, request, file["id"])}


@router.delete("/{file_id}/extension-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension_order(file_id: UUID, order_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    await _get_or_404(ctx, file_id)
    await run_in_threadpool(lambda: ctx.db().table(ORDERS).delete().eq("id", str(order_id)).eq("custody_file_id", str(file_id)).execute())
    await _audit(ctx, request, "DELETE_CUSTODY_EXTENSION", str(file_id), {"order_id": str(order_id)})
    await _try_sync(ctx, request, str(file_id))
