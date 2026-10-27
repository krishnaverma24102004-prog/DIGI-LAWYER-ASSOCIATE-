"""Firm docket (P13): deadlines, the reminder ladder, escalation and the blind second check.

A missed deadline is rarely a wrong rule; it is a date typed wrongly, entered once with no
early reminder, or owned by one person who went on leave. So every deadline carries its inputs,
rule and basis, an owner and a backup, and reminders from the moment it exists, escalating when
nobody acknowledges them. When it rests on typed dates a second member re-enters the inputs
without seeing the first entry; disagreement keeps both dates and the earlier one governs.

The blindness lives in the database (migration 015): the tables are closed to clients and the
read functions mask the assigned checker's view. This module calls those functions as the user
and runs the hourly sweep (service role, one org at a time) that issues reminders. Safety beats
blindness: before a reminder would reach the checker, or once the due date is within the
deadline's `safety_lead_days`, the check is cancelled and the reminder goes out with the date.

Audit rows never carry dates or inputs. They carry an HMAC of the inputs under a per-org key
derived from a server secret: a plain hash of a handful of dates could be reversed by trying
every date in a year.
"""

import hashlib
import hmac
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from postgrest.exceptions import APIError

from app.core.config import get_settings
from app.services import audit_service, n8n_service, whatsapp_service

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SOURCES = ("engine", "manual", "cause_list", "ai_proposed")
LADDER_DAYS = (30, 14, 7, 3, 1, 0)
HARD_DAILY_FROM = 5          # hard deadlines: a reminder every day from T-5
BROADCAST_FROM = 1           # T-1, T-0 and overdue reminders go to everyone on the deadline
ESCALATE_AFTER_HOURS = 4     # working hours without an acknowledgement
WORK_START, WORK_END = time(9, 0), time(19, 0)
WORK_WEEKDAYS = frozenset(range(6))  # Monday to Saturday
MAX_LEVEL = 2                # 0 ladder, 1 backup, 2 a partner
REMINDER_WEBHOOK = "deadline-reminder"
DIGEST_WEBHOOK = "deadline-digest"
MEMBER_TEMPLATE = "deadline_member_v1"
_AUDIT_FALLBACK_SECRET = "digi-lawyer-deadline-audit"

DEADLINES, REMINDERS, VIEWS = "deadlines", "deadline_reminders", "deadline_value_views"


class DeadlineError(Exception):
    """A docket rule stopped the action. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _translate(exc: APIError) -> DeadlineError:
    code, message, hint = exc.code or "", exc.message or "Deadline error", exc.hint
    if message == "check_not_open":
        return DeadlineError(hint or "The self re-entry isn't open yet", 409, "check_not_open")
    if code == "P0002":
        return DeadlineError(message, 404, "not_found")
    if code == "42501":
        return DeadlineError(message, 403, "forbidden")
    if code in ("55000", "23505"):
        return DeadlineError(message, 409, "conflict")
    if code in ("22023", "23514", "22P02", "22007", "22008"):
        return DeadlineError(message, 400, "invalid")
    return DeadlineError(message, 500, "error")


def _rpc(db, name: str, params: dict | None = None):
    try:
        return db.rpc(name, params or {}).execute().data
    except APIError as exc:
        raise _translate(exc) from exc


# ----------------------------------------------------------------------------- inputs and audit
def normalize_inputs(inputs: dict | None) -> dict[str, str]:
    """Named inputs as strings (dates as ISO), so two entries of the same facts compare equal."""
    out: dict[str, str] = {}
    for key, value in (inputs or {}).items():
        name = " ".join(str(key).split())
        if not name or value is None or value == "":
            continue
        if isinstance(value, datetime):
            value = value.date().isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        else:
            value = " ".join(str(value).split())
        out[name[:80]] = value[:200]
    return out


def normalize_kind(kind: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", (kind or "").strip().lower()).strip("_")[:60]
    if len(slug) < 2:
        raise DeadlineError("Name the kind of deadline, e.g. appeal or written_statement")
    return slug


def _audit_key(org_id: str) -> bytes:
    secret = get_settings().supabase_service_role_key or _AUDIT_FALLBACK_SECRET
    return hmac.new(secret.encode(), f"deadline-audit:{org_id}".encode(), hashlib.sha256).digest()


def inputs_digest(org_id: str, inputs: dict | None, computed: date | str | None) -> str:
    """HMAC-SHA256 of an entry under the org's key: lets an auditor see that two entries match
    without letting anyone who reads the audit log recover the dates by enumeration."""
    computed = computed.isoformat() if isinstance(computed, date) else computed
    canonical = json.dumps({"inputs": normalize_inputs(inputs), "computed": computed}, sort_keys=True, separators=(",", ":"))
    return hmac.new(_audit_key(org_id), canonical.encode(), hashlib.sha256).hexdigest()


def audit_metadata(org_id: str, deadline: dict, *, inputs: dict | None = None, computed=None, **extra) -> dict:
    """What an audit row may say about a deadline: ids, statuses, reasons and the HMAC. No dates."""
    meta = {
        "deadline_id": deadline.get("id"),
        "kind": deadline.get("kind"),
        "source": deadline.get("source"),
        "check_mode": deadline.get("check_mode"),
        "check_state": deadline.get("check_state"),
        "verification": deadline.get("verification"),
        "status": deadline.get("status"),
    }
    if inputs is not None or computed is not None:
        meta["entry_hmac"] = inputs_digest(org_id, inputs, computed)
    meta.update({k: v for k, v in extra.items() if v is not None})
    return {k: v for k, v in meta.items() if v is not None}


def audit_event(user_id: str | None, org_id: str, action: str, deadline: dict, *, ip_address: str | None = None,
                inputs: dict | None = None, computed=None, **extra) -> bool:
    return audit_service.log_action(
        user_id, org_id, action, "deadline", deadline.get("id"), ip_address=ip_address,
        metadata=audit_metadata(org_id, deadline, inputs=inputs, computed=computed, **extra),
    )


# ----------------------------------------------------------------------------- rule engines
# Other modules (the limitation engine) register how a rule turns inputs into a date, so a
# checker's re-entry is recomputed by the same engine instead of trusting a typed date.
_ENGINES: dict[str, Callable[[dict], date | None]] = {}


def register_engine(rule_id: str, compute: Callable[[dict], date | None]) -> None:
    _ENGINES[rule_id] = compute


def recompute(rule_id: str | None, inputs: dict) -> date | None:
    engine = _ENGINES.get(rule_id or "")
    return engine(inputs) if engine else None


# ----------------------------------------------------------------------------- user calls (RPCs)
def _create(db, *, kind, title, due_date, owner_id, court_case_id, thread_id, rule_id, rule_version, basis, inputs,
            hard, source, candidates, safety_lead_days, backup_id) -> dict:
    if source not in SOURCES:
        raise DeadlineError(f"source must be one of {', '.join(SOURCES)}")
    title = " ".join((title or "").split())
    if not title:
        raise DeadlineError("Give the deadline a title")
    if not 0 <= int(safety_lead_days) <= 60:
        raise DeadlineError("safety_lead_days must be between 0 and 60")
    normalized = normalize_inputs(inputs)
    row = _rpc(db, "create_deadline", {
        "p_kind": normalize_kind(kind), "p_title": title[:300], "p_due_date": due_date.isoformat(),
        "p_owner": str(owner_id), "p_court_case": str(court_case_id) if court_case_id else None,
        "p_thread": str(thread_id) if thread_id else None, "p_rule_id": rule_id, "p_rule_version": rule_version,
        "p_basis": (basis or "")[:2000], "p_inputs": normalized, "p_hard": bool(hard), "p_source": source,
        "p_candidates": [d.isoformat() for d in candidates or []] or None,
        "p_safety_lead_days": int(safety_lead_days), "p_backup": str(backup_id) if backup_id else None,
    })
    audit_event(row.get("created_by"), row["org_id"], "CREATE_DEADLINE", row, inputs=normalized, computed=due_date,
                check_note=row.get("check_note"))
    return row


def create_deadline(db, *, kind: str, title: str, due_date: date, owner_id: str, court_case_id: str | None = None,
                    thread_id: str | None = None, rule_id: str | None = None, rule_version: int | None = None,
                    basis: str = "", inputs: dict | None = None, hard: bool = False, source: str = "engine",
                    candidates: list[date] | None = None, safety_lead_days: int = 3) -> dict:
    """Docket a deadline as the signed-in user (`db` is their client). The checker is assigned
    in the same call; the result is the deadline as its maker sees it."""
    return _create(db, kind=kind, title=title, due_date=due_date, owner_id=owner_id, court_case_id=court_case_id,
                   thread_id=thread_id, rule_id=rule_id, rule_version=rule_version, basis=basis, inputs=inputs,
                   hard=hard, source=source, candidates=candidates, safety_lead_days=safety_lead_days, backup_id=None)


def list_deadlines(db, *, court_case_id: str | None = None, thread_id: str | None = None,
                   include_done: bool = False) -> list[dict]:
    return _rpc(db, "list_deadlines", {
        "p_court_case": str(court_case_id) if court_case_id else None,
        "p_thread": str(thread_id) if thread_id else None, "p_include_done": include_done,
    }) or []


def get_deadline(db, deadline_id: str) -> dict:
    return _rpc(db, "get_deadline", {"p_id": str(deadline_id)})


def deadline_entries(db, deadline_id: str) -> list[dict]:
    return _rpc(db, "my_deadline_entries", {"p_id": str(deadline_id)}) or []


def my_reminders(db) -> list[dict]:
    return _rpc(db, "my_deadline_reminders") or []


def submit_entry(db, deadline_id: str, *, inputs: dict, due_date: date | None = None) -> tuple[dict, dict, date]:
    """The checker's blind re-entry. When an engine is registered for the rule it recomputes the
    date from the re-entered inputs. Returns (deadline after, normalized inputs, computed date)."""
    current = get_deadline(db, deadline_id)  # masked for the checker: rule and input names only
    normalized = normalize_inputs(inputs)
    computed = recompute(current.get("rule_id"), normalized) or due_date
    if computed is None:
        raise DeadlineError("Enter the date these inputs give")
    row = _rpc(db, "submit_deadline_entry", {"p_id": str(deadline_id), "p_inputs": normalized, "p_computed": computed.isoformat()})
    return row, normalized, computed


def acknowledge(db, reminder_id: str) -> dict:
    return _rpc(db, "acknowledge_deadline_reminder", {"p_reminder": str(reminder_id)})


def complete(db, deadline_id: str, evidence: str) -> dict:
    return _rpc(db, "complete_deadline", {"p_id": str(deadline_id), "p_evidence": evidence})


def reassign_check(db, deadline_id: str) -> dict:
    return _rpc(db, "reassign_deadline_check", {"p_id": str(deadline_id)})


# ----------------------------------------------------------------------------- the ladder
@dataclass(frozen=True)
class Rung:
    label: str
    offset: int  # days before the due date; negative once overdue
    day: date


def ladder(due: date, created: date, hard: bool = False) -> list[Rung]:
    """T-30/T-14/T-7/T-3/T-1/T-0, only the rungs after creation for short deadlines, a first
    rung the day the deadline is entered, and every day from T-5 for hard deadlines."""
    span = max((due - created).days, 0)
    offsets = {o for o in LADDER_DAYS if o <= span} | {span}
    if hard:
        offsets |= set(range(min(HARD_DAILY_FROM, span) + 1))
    return [Rung(f"T-{o}", o, due - timedelta(days=o)) for o in sorted(offsets, reverse=True)]


def current_rung(due: date, created: date, today: date, hard: bool = False) -> Rung | None:
    """The rung a reminder is due for today: the latest one reached (past rungs collapse into
    it, e.g. after a dispute moves the date earlier), or a daily T+n once overdue."""
    if today > due:
        n = (today - due).days
        return Rung(f"T+{n}", -n, today)
    reached = [r for r in ladder(due, created, hard) if r.day <= today]
    return reached[-1] if reached else None


def working_hours_between(start: datetime, end: datetime) -> float:
    """Office hours (09:00-19:00 IST, Monday to Saturday) between two instants."""
    start, end = start.astimezone(IST), end.astimezone(IST)
    if end <= start:
        return 0.0
    total = 0.0
    day = start.date()
    while day <= end.date():
        if day.weekday() in WORK_WEEKDAYS:
            open_at = datetime.combine(day, WORK_START, IST)
            close_at = datetime.combine(day, WORK_END, IST)
            overlap = (min(end, close_at) - max(start, open_at)).total_seconds()
            total += max(overlap, 0) / 3600
        day += timedelta(days=1)
    return total


# ----------------------------------------------------------------------------- routing
@dataclass
class Team:
    """An org's members (user id -> role, in membership order) and who is away today."""

    roles: dict[str, str]
    absent: set[str] = field(default_factory=set)

    def present(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id in self.roles and user_id not in self.absent

    def senior(self, exclude: set = frozenset(), avoid: str | None = None) -> str | None:
        """A partner (else an owner) who is in today, preferring someone other than `avoid`."""
        order = list(self.roles)
        seniors = [u for u, r in self.roles.items() if r in ("owner", "partner") and self.present(u) and u not in exclude]
        seniors.sort(key=lambda u: (u == avoid, self.roles[u] != "partner", order.index(u)))
        return seniors[0] if seniors else None


def _blind_pending(d: dict) -> bool:
    return d.get("check_mode") == "second" and d.get("check_state") == "pending"


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _instant(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def reminder_targets(d: dict, rung: Rung, team: Team) -> list[str]:
    """The owner; while they are away, the backup ("covered by"); failing both, a partner.
    From T-1 everyone on the deadline (owner, backup, checker) is reminded."""
    owner, backup, checker = d.get("owner_id"), d.get("backup_id"), d.get("checker_id")
    primary = next((u for u in (owner, backup) if team.present(u)), None)
    if primary is None:
        primary = team.senior(exclude={owner, backup}, avoid=checker if _blind_pending(d) else None)
    targets = [primary] if primary else []
    if rung.offset <= BROADCAST_FROM:
        targets += [u for u in (owner, backup, checker) if team.present(u)]
    return list(dict.fromkeys(targets))


def escalation_target(d: dict, reminder: dict, team: Team, already: set[str]) -> str | None:
    """Unacknowledged ladder reminder -> the backup; unacknowledged after that -> a partner."""
    if reminder.get("level", 0) == 0:
        backup = d.get("backup_id")
        if team.present(backup) and backup not in already:
            return backup
    return team.senior(exclude=already, avoid=d.get("checker_id") if _blind_pending(d) else None)


def safety_cancel_reason(d: dict, targets: list[str] | set[str], today: date) -> str | None:
    """Why a pending check must be cancelled before reminders go out, if it must."""
    if d.get("check_state") != "pending" or d.get("status", "open") != "open":
        return None
    if (_day(d["effective_due_date"]) - today).days <= int(d.get("safety_lead_days", 3)):
        return "due_within_lead"
    if _blind_pending(d) and d.get("checker_id") in set(targets):
        return "reminder_to_checker"
    return None


# ----------------------------------------------------------------------------- payloads
def short_code(d: dict) -> str:
    """A matter reference that names nobody: M-<6 hex> of the court case or thread, else D-<6 hex>."""
    matter = d.get("court_case_id") or d.get("thread_id") or (d.get("matter") or {}).get("court_case_id") \
        or (d.get("matter") or {}).get("thread_id")
    ref = (matter or d.get("id") or "").replace("-", "")[:6].upper()
    return f"{'M' if matter else 'D'}-{ref}"


def member_payload(reminder: dict, deadline: dict) -> dict:
    """The WhatsApp reminder for a firm member: short code, kind and date. No party names, title,
    basis or court; the details are in the app."""
    return {
        "template": MEMBER_TEMPLATE,
        "org_id": deadline.get("org_id"),
        "target_user_id": reminder.get("target_id"),
        "reminder_id": reminder.get("id"),
        "short_code": short_code(deadline),
        "kind": deadline.get("kind"),
        "date": str(reminder.get("for_date") or deadline.get("effective_due_date")),
        "rung": reminder.get("rung"),
        "level": reminder.get("level", 0),
        "app_path": f"/deadlines#{deadline.get('id')}",
    }


async def deliver(reminder: dict, deadline: dict) -> bool:
    """Push a member reminder to WhatsApp through n8n (which looks up the member's number).
    In-app delivery needs nothing: listing a reminder marks it delivered."""
    if reminder.get("payload_class", "member") != "member":
        return False  # content-free pings to non-member clerks are not built yet
    if not (whatsapp_service.is_configured() and n8n_service.is_configured()):
        return False
    try:
        await n8n_service.trigger_workflow(REMINDER_WEBHOOK, member_payload(reminder, deadline))
        return True
    except Exception:
        logger.warning("Deadline reminder %s could not be pushed", reminder.get("id"), exc_info=True)
        return False


def partner_digest(deadlines: list[dict], reminders: list[dict], today: date, matters_without_date: int = 0) -> dict:
    """Monday digest for partners. A deadline whose blind check is pending is listed without its
    date, because a partner reading the digest may be its checker."""

    def item(d):
        entry = {"short_code": short_code(d), "kind": d.get("kind")}
        if not _blind_pending(d):
            entry["date"] = str(d.get("effective_due_date"))
        return entry

    open_ids = {d["id"] for d in deadlines}
    return {
        "overdue": [item(d) for d in deadlines if not _blind_pending(d) and _day(d["effective_due_date"]) < today],
        "unacknowledged_reminders": sum(1 for r in reminders if r.get("deadline_id") in open_ids and not r.get("acknowledged_at")),
        "unverified": [item(d) for d in deadlines if d.get("verification") in ("unverified", "disputed")
                       and d.get("check_state") in ("cancelled", "none")],
        "cancelled_checks": [{**item(d), "reason": d.get("check_cancel_reason")} for d in deadlines
                             if d.get("check_state") == "cancelled"],
        "recheck_impossible": [{**item(d), "note": "re-check impossible: all eligible members have viewed"}
                               for d in deadlines if d.get("check_note") == "all_eligible_viewed"],
        "awaiting_check": sum(1 for d in deadlines if d.get("check_state") == "pending"),
        "matters_without_forward_date": matters_without_date,
    }


# ----------------------------------------------------------------------------- the sweep
async def run_sweep(admin_db, now: datetime | None = None) -> dict:
    """Hourly job (service role): reassigns orphaned deadlines, cancels checks that safety
    requires, issues due reminders, escalates unacknowledged ones, and on Monday's 08:00 IST run
    posts the partner digest. Each org is handled on its own. Returns counts."""
    now = _instant(now or datetime.now(timezone.utc))
    today = now.astimezone(IST).date()
    counts: Counter = Counter()
    rows = admin_db.table(DEADLINES).select("org_id").eq("status", "open").execute().data
    for org_id in sorted({r["org_id"] for r in rows}):
        try:
            await _sweep_org(admin_db, org_id, now, today, counts)
            counts["orgs"] += 1
        except Exception:
            logger.exception("Deadline sweep failed for org %s", org_id)
            counts["errors"] += 1
    return dict(counts)


def _safe_audit(*args, **kwargs) -> None:
    try:
        audit_event(*args, **kwargs)
    except audit_service.AuditError:
        logger.error("Deadline audit entry not written", exc_info=True)


async def _sweep_org(admin_db, org_id: str, now: datetime, today: date, counts: Counter) -> None:
    deadlines = admin_db.table(DEADLINES).select("*").eq("org_id", org_id).eq("status", "open").execute().data
    members = (admin_db.table("organization_members").select("user_id, role, created_at")
               .eq("org_id", org_id).order("created_at").execute().data)
    away = (admin_db.table("member_absences").select("user_id").eq("org_id", org_id)
            .lte("starts_on", today.isoformat()).gte("ends_on", today.isoformat()).execute().data)
    team = Team(roles={m["user_id"]: m["role"] for m in members}, absent={a["user_id"] for a in away})
    ids = [d["id"] for d in deadlines]
    reminders = []
    for start in range(0, len(ids), 100):  # keeps the query string short
        reminders += (admin_db.table(REMINDERS).select("*").eq("org_id", org_id)
                      .in_("deadline_id", ids[start:start + 100]).execute().data)

    for d in deadlines:
        d = _fix_people(admin_db, org_id, d, team, counts)
        existing = [r for r in reminders if r["deadline_id"] == d["id"]]
        fresh = await _issue_due(admin_db, org_id, d, team, existing, now, today, counts)
        await _escalate(admin_db, org_id, d, team, existing, now, today, counts)
        reminders.extend(fresh)

    if now.astimezone(IST).weekday() == 0 and now.astimezone(IST).hour == 8 and n8n_service.is_configured():
        cases = admin_db.table("court_cases").select("id, next_hearing_date").eq("org_id", org_id).execute().data
        linked = {d.get("court_case_id") for d in deadlines}
        without = sum(1 for c in cases if c["id"] not in linked
                      and (not c.get("next_hearing_date") or _day(c["next_hearing_date"]) < today))
        try:
            await n8n_service.trigger_workflow(DIGEST_WEBHOOK, {
                "org_id": org_id, "week_of": today.isoformat(),
                "digest": partner_digest(deadlines, reminders, today, without)})
            counts["digests"] += 1
        except Exception:
            logger.warning("Deadline digest for org %s not posted", org_id, exc_info=True)


def _update(admin_db, d: dict, fields: dict) -> dict:
    admin_db.table(DEADLINES).update(fields).eq("id", d["id"]).execute()
    d.update(fields)
    return d


def _fix_people(admin_db, org_id: str, d: dict, team: Team, counts: Counter) -> dict:
    """Owner or backup left the firm: the backup (else a partner) takes over. Checker left:
    the check goes to someone else eligible (never a member who has seen the values)."""
    owner, backup = d.get("owner_id"), d.get("backup_id")
    if owner not in team.roles:
        new_owner = backup if backup in team.roles else team.senior() or next(
            (u for u, r in team.roles.items() if r in ("owner", "partner")), None)
        if new_owner:
            fields = {"owner_id": new_owner}
            if new_owner == backup:
                fields["backup_id"] = team.senior(exclude={new_owner}) or next(
                    (u for u, r in team.roles.items() if u != new_owner and r != "paralegal"), None)
            _update(admin_db, d, fields)
            _safe_audit(None, org_id, "REASSIGN_ORPHAN_DEADLINE", d, reason="owner_left")
            counts["orphans"] += 1
        else:
            counts["orphans_unresolved"] += 1
    elif backup and backup not in team.roles:
        _update(admin_db, d, {"backup_id": team.senior(exclude={owner}) or next(
            (u for u, r in team.roles.items() if u != owner and r != "paralegal"), None)})
        counts["backups_replaced"] += 1

    if d.get("check_state") == "pending" and d.get("checker_id") and d["checker_id"] not in team.roles:
        admin_db.rpc("deadline_assign_check", {"p_deadline": d["id"], "p_exclude": d["checker_id"]}).execute()
        fresh = admin_db.table(DEADLINES).select("*").eq("id", d["id"]).execute().data
        if fresh:
            d.update(fresh[0])
        _safe_audit(None, org_id, "REASSIGN_DEADLINE_CHECK", d, reason="checker_left", check_note=d.get("check_note"))
        counts["checks_reassigned"] += 1
    return d


def _cancel_check(admin_db, org_id: str, d: dict, reason: str, counts: Counter) -> None:
    admin_db.table(DEADLINES).update({"check_state": "cancelled", "check_cancel_reason": reason}) \
        .eq("id", d["id"]).eq("check_state", "pending").execute()
    d.update(check_state="cancelled", check_cancel_reason=reason)
    _safe_audit(None, org_id, "CANCEL_DEADLINE_CHECK", d, reason=reason)
    counts["checks_cancelled"] += 1


async def _send(admin_db, org_id: str, d: dict, target: str, rung: Rung, level: int, now: datetime,
                counts: Counter, parent: str | None = None) -> dict:
    row = {
        "deadline_id": d["id"], "org_id": org_id, "target_id": target, "rung": rung.label,
        "for_date": str(d["effective_due_date"]), "level": level, "parent_id": parent,
        "channel": "in_app", "payload_class": "member", "issued_at": now.isoformat(),
    }
    saved = (admin_db.table(REMINDERS).insert(row).execute().data or [row])[0]
    admin_db.table(VIEWS).upsert({"deadline_id": d["id"], "user_id": target, "via": "reminder",
                                  "last_seen_at": now.isoformat()}, on_conflict="deadline_id,user_id").execute()
    counts["escalations" if level else "reminders"] += 1
    if await deliver(saved, d):
        admin_db.table(REMINDERS).update({"channel": "whatsapp", "delivered_at": now.isoformat()}).eq("id", saved.get("id")).execute()
        saved.update(channel="whatsapp", delivered_at=now.isoformat())
        counts["delivered"] += 1
    return saved


async def _issue_due(admin_db, org_id, d, team, existing, now, today, counts) -> list[dict]:
    due = _day(d["effective_due_date"])
    rung = current_rung(due, _instant(d["created_at"]).astimezone(IST).date(), today, bool(d.get("hard")))
    targets = reminder_targets(d, rung, team) if rung else []
    reason = safety_cancel_reason(d, targets, today)
    if reason:
        _cancel_check(admin_db, org_id, d, reason, counts)  # before anything carrying the date goes out
    if rung is None:
        return []
    if not targets:
        counts["unroutable"] += 1
        return []
    issued = {(str(r["for_date"]), r["rung"], r.get("level", 0), r["target_id"]) for r in existing}
    sent = []
    for target in targets:
        if (due.isoformat(), rung.label, 0, target) not in issued:
            sent.append(await _send(admin_db, org_id, d, target, rung, 0, now, counts))
    return sent


async def _escalate(admin_db, org_id, d, team, existing, now, today, counts) -> None:
    for r in list(existing):
        if (r.get("acknowledged_at") or r.get("escalated_at") or r.get("level", 0) >= MAX_LEVEL
                or str(r["for_date"]) != str(d["effective_due_date"])
                or working_hours_between(_instant(r["issued_at"]), now) < ESCALATE_AFTER_HOURS):
            continue
        already = {x["target_id"] for x in existing if x["for_date"] == r["for_date"] and x["rung"] == r["rung"]}
        target = escalation_target(d, r, team, already)
        if target is None:
            counts["unescalatable"] += 1
            continue
        reason = safety_cancel_reason(d, [target], today)
        if reason:
            _cancel_check(admin_db, org_id, d, reason, counts)
        rung = Rung(r["rung"], 0, today)
        sent = await _send(admin_db, org_id, d, target, rung, r.get("level", 0) + 1, now, counts, parent=r.get("id"))
        admin_db.table(REMINDERS).update({"escalated_at": now.isoformat()}).eq("id", r.get("id")).execute()
        r["escalated_at"] = now.isoformat()
        existing.append(sent)
