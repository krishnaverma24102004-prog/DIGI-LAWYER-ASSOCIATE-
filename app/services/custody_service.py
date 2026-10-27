"""Custody watch: default-bail and undertrial-release dates for every client in custody (P14).

Everything here is deterministic arithmetic over the custody file and the punishment table
(app/data/offence_punishments.json); no model is involved and nothing is sent to Claude.

  Codes          app.services.criminal_codes: IPC/BNS by offence date (punishment lookup only);
                 CrPC/BNSS by when the investigation began (s. 531 BNSS), with transition flags.
  Punishment     from the table, never typed. With several sections the gravest decides: 90 days
                 if any section carries death, life or a minimum of ten years or more; the s. 479
                 threshold uses the highest maximum; any death/life section excludes s. 479.
  Default bail   s. 167(2) CrPC / s. 187(3) BNSS: 90 days where the offence is punishable with
                 death, life or a term of not less than ten years (keyed on the MINIMUM term, per
                 Rakesh Kumar Paul v. State of Assam, 2017); 60 days otherwise. The date of the
                 first remand counts as day 1, so day N ends on remand + N - 1 and the right
                 accrues on remand + N if no chargesheet is filed by then. Special statutes
                 (NDPS s. 36A(4), UAPA s. 43D(2)) change the period; their extensions are applied
                 only when an extension order's date is entered.
  Undertrial     s. 479 BNSS for every undertrial whatever the offence, FIR or arrest date (the
                 Supreme Court's order of 23.08.2024 in In re Inhuman Conditions in 1382 Prisons):
                 one-third of the maximum for a first-time offender, one-half otherwise; death/life
                 offences excluded; s. 479(2) (other cases pending) and delay caused by the accused
                 are a checklist the lawyer confirms. Where the case began under the CrPC,
                 s. 436A CrPC (one-half) is shown as an alternative citation.

Rules ship as drafts: a computation that uses a table entry this firm hasn't signed (two members,
rule_verifications) is labelled UNVERIFIED and is only shown to owners and partners in preview.

Every date is a computation for the advocate to check; the counting conventions themselves are
golden-case items awaiting the criminal team's sign-off (tests/fixtures/custody_cases.json).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from app.services.criminal_codes import CriminalCodes, check_sections, criminal_codes

logger = logging.getLogger(__name__)

TABLE = "custody_files"
ORDERS_TABLE = "custody_extension_orders"
REGISTRY = "offence_punishments"
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "offence_punishments.json"

YEAR_DAYS = 365.25
DISCLAIMER = ("Dates are computations for the advocate to check against the statute and the record. "
              "Custody data is personal data of the accused, kept under the firm's access rules and never sent to an AI model.")
UNVERIFIED_LABEL = "UNVERIFIED punishment table entry: not for reliance"
SC_ORDER = "the Supreme Court's order of 23.08.2024 in In re Inhuman Conditions in 1382 Prisons"
COUNTING_NOTE = "the date of the first remand counted as day 1 (counting convention pending the criminal team's sign-off)"
PENDING_BADGE = "Not eligible if other cases are pending (s. 479(2) BNSS): confirm"
RIGHT_LOST = "Right lost: chargesheet filed"


class CustodyError(ValueError):
    pass


# ----------------------------------------------------------------------------- punishment table


@lru_cache(maxsize=1)
def load_table() -> dict[str, dict]:
    """rule_id -> rule, from app/data/offence_punishments.json."""
    return {r["rule_id"]: r for r in json.loads(DATA_FILE.read_text(encoding="utf-8"))["rules"]}


def offences() -> list[dict]:
    return [r for r in load_table().values() if r.get("kind") == "offence"]


def special_period(statute: str | None) -> dict | None:
    return next((r for r in load_table().values() if r.get("kind") == "special_period" and r.get("special_statute") == statute), None)


_REF = re.compile(r"^\s*(?:(?:s|ss|sec|section)\.?\s*)?(?P<a>[0-9][0-9A-Za-z()]*)\s+(?:of\s+(?:the\s+)?)?(?P<code>IPC|BNS|NDPS)(?:\s+Act)?\s*$"
                  r"|^\s*(?P<code2>IPC|BNS|NDPS)(?:\s+Act)?\s*,?\s*(?:(?:s|ss|sec|section)\.?\s*)?(?P<b>[0-9][0-9A-Za-z()]*)\s*$", re.I)


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def resolve_section(ref: str) -> dict | None:
    """A table rule for a section reference: a rule id ("BNS-103(1)") or "302 IPC" / "BNS 318(4)" / "s. 21(c) NDPS"."""
    table = load_table()
    if not ref:
        return None
    by_id = {_norm(k): v for k, v in table.items()}
    if _norm(ref) in by_id:
        return by_id[_norm(ref)]
    m = _REF.match(ref)
    if not m:
        return None
    code = (m.group("code") or m.group("code2")).upper()
    section = _norm(m.group("a") or m.group("b"))
    return next((r for r in table.values() if r.get("kind") == "offence" and r.get("code") == code
                 and section in {_norm(a) for a in r.get("aliases", [])}), None)


@dataclass
class Punishment:
    rules: list[dict] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    death: bool = False
    life: bool = False
    min_years: float | None = None
    max_years: float | None = None
    special_statute: str | None = None
    deciding: str | None = None  # rule id of the gravest section

    @property
    def known(self) -> bool:
        return bool(self.rules)

    def as_dict(self) -> dict:
        return {"sections": [{k: r.get(k) for k in ("rule_id", "version", "title", "basis", "max_years", "min_years", "life", "death")}
                             for r in self.rules],
                "unknown_sections": self.unknown, "death": self.death, "life": self.life, "min_years": self.min_years,
                "max_years": self.max_years, "special_statute": self.special_statute, "deciding_section": self.deciding}


def gravity(rule: dict) -> tuple:
    """Order of gravity: death, then life, then the highest minimum, then the highest maximum."""
    return (bool(rule.get("death")), bool(rule.get("life")), rule.get("min_years") or 0, rule.get("max_years") or 0)


def punishment(section_refs: list[str]) -> Punishment:
    """Aggregate the punishments of the sections charged (the gravest decides)."""
    p = Punishment()
    for ref in section_refs or []:
        rule = resolve_section(ref)
        if rule is None:
            p.unknown.append(ref)
        elif rule not in p.rules:
            p.rules.append(rule)
    if not p.rules:
        return p
    p.death = any(r.get("death") for r in p.rules)
    p.life = any(r.get("life") for r in p.rules)
    mins = [r["min_years"] for r in p.rules if r.get("min_years") is not None]
    maxes = [r["max_years"] for r in p.rules if r.get("max_years") is not None]
    p.min_years = max(mins) if mins else None
    p.max_years = max(maxes) if maxes else None
    p.special_statute = next((r["special_statute"] for r in p.rules if r.get("special_statute")), None)
    p.deciding = max(p.rules, key=gravity)["rule_id"]
    return p


# ----------------------------------------------------------------------------- pure computations


def default_bail_period(*, death: bool, life: bool, min_years: float | None, max_years: float | None,
                        procedural: str) -> tuple[int, str, list[str]]:
    """(days, reason, notes) under s. 167(2) CrPC / s. 187(3) BNSS, keyed on the minimum term."""
    notes: list[str] = []
    if death or life or (min_years is not None and min_years >= 10):
        what = "death" if death else "imprisonment for life" if life else f"a minimum term of {min_years:g} years"
        return 90, f"the offence is punishable with {what}", notes
    if max_years is not None and max_years >= 10:
        if procedural == "BNSS":
            notes.append("BNSS wording differs: s. 187(3) BNSS reads 'ten years or more', so 90 days is arguable for a maximum of "
                         f"{max_years:g} years with no minimum; the alert is kept at day 60 (the safe direction).")
        elif max_years > 10:
            notes.append(f"Maximum of {max_years:g} years with no minimum: 60 days on the minimum-term reading of s. 167(2) CrPC; "
                         "the advocate should confirm (golden case pending sign-off).")
    reason = ("the offence carries no minimum term of ten years (an offence punishable with imprisonment 'up to' ten years "
              "is a 60-day offence: Rakesh Kumar Paul v. State of Assam, 2017)")
    return 60, reason, notes


def custody_period(days: int, custody_from: date) -> tuple[date, date]:
    """(last day of the period, day the right accrues), counting the first remand date as day 1."""
    return custody_from + timedelta(days=days - 1), custody_from + timedelta(days=days)


def detention_days(periods: list[tuple[date, date | None]], today: date) -> int:
    """Total days in detention, both ends counted; an open period runs to today."""
    return sum(((end or today) - start).days + 1 for start, end in periods if start <= (end or today))


def threshold_date(required_days: float, periods: list[tuple[date, date | None]]) -> date | None:
    """The first day after `required_days` of detention are completed across the periods
    (earlier closed periods first, the current one open). None if no open period remains."""
    needed = math.ceil(required_days)
    for start, end in sorted(periods, key=lambda p: p[0]):
        length = (end - start).days + 1 if end else None
        if length is None or length >= needed:
            return start + timedelta(days=needed)
        needed -= length
    return None


def undertrial_share(first_time: bool | None) -> tuple[float, str]:
    return (1 / 3, "one-third: first-time offender") if first_time else (1 / 2, "one-half")


def undertrial(
    *,
    max_years: float | None,
    death: bool,
    life: bool,
    first_time: bool | None,
    periods: list[tuple[date, date | None]],
    codes: CriminalCodes,
    other_pending: bool | None = None,
    accused_delay_days: int | None = None,
) -> dict:
    """s. 479 BNSS for every undertrial, with s. 436A CrPC as an alternative citation where the case
    began under the CrPC. Returns date, basis, checklist, badge and the alternative."""
    out: dict = {"provision": "s. 479 BNSS", "date": None, "share": None, "excluded": False, "explanation": None,
                 "basis": None, "badges": [], "checklist": [], "alternative": None, "notes": []}
    crpc = codes.procedural == "CrPC"
    if death or life:
        out["excluded"] = True
        what = "death" if death else "imprisonment for life"
        text = f"s. 479 BNSS does not apply: the offence is punishable with {what}."
        if crpc and not death:
            text += (" s. 436A CrPC excludes only offences punishable with death, so it may be argued (one-half of an "
                     "indeterminate maximum): no date is computed.")
        elif crpc:
            text += " s. 436A CrPC also excludes offences punishable with death."
        out["explanation"] = text
        return out
    if max_years is None:
        out["explanation"] = "No maximum term from the punishment table: the s. 479 BNSS date can't be computed."
        return out

    delay = accused_delay_days or 0
    share, label = undertrial_share(first_time)
    required = max_years * YEAR_DAYS * share + delay
    on = threshold_date(required, periods)
    out.update(share=label, date=on.isoformat() if on else None)
    out["basis"] = (f"s. 479 BNSS: detention up to {label.split(':')[0]} of the maximum of {max_years:g} years "
                    f"({max_years:g} x 365.25 x {'1/3' if share < 0.5 else '1/2'} = {max_years * YEAR_DAYS * share:.2f} days"
                    + (f", plus {delay} days of delay caused by the accused" if delay else "")
                    + "); applies to undertrials in cases registered before 1 July 2024 too, per " + SC_ORDER
                    + ". Release cannot be refused beyond the maximum term (third proviso).")
    if on is None:
        out["explanation"] = "Not in custody: no current detention period to count."
    if first_time is None:
        alt_third = threshold_date(max_years * YEAR_DAYS / 3 + delay, periods)
        out["badges"].append("First-time offender status not confirmed: one-half used"
                             + (f"; one-third would give {alt_third:%d %b %Y}" if alt_third else ""))
    out["checklist"] = [
        {"item": "No other investigation, inquiry or trial pending against the accused (s. 479(2) BNSS)",
         "confirmed": other_pending is False, "excludes": other_pending is True},
        {"item": "Delay in the proceedings caused by the accused excluded from the period (Explanation to s. 479(1) BNSS)",
         "confirmed": accused_delay_days is not None},
    ]
    if other_pending is True:
        out["excluded"] = True
        out["explanation"] = "Not eligible under s. 479(2) BNSS: other cases are pending against the accused (confirmed by the lawyer)."
        out["badges"].append("Not eligible: other cases pending (s. 479(2) BNSS)")
    elif other_pending is None:
        out["badges"].append(PENDING_BADGE)
    if crpc and on is not None:
        alt = threshold_date(max_years * YEAR_DAYS / 2 + delay, periods)
        more = alt is not None and (out["excluded"] or alt < on)
        out["alternative"] = {
            "provision": "s. 436A CrPC", "date": alt.isoformat() if alt else None, "more_favourable": more,
            "basis": "s. 436A CrPC (alternative citation; the case began under the CrPC): detention up to one-half of the "
                     "maximum, for offences not punishable with death; s. 479 BNSS governs the deadline"
                     + ("" if not more else "; s. 436A has no other-cases-pending exclusion"),
        }
    return out


# ----------------------------------------------------------------------------- one custody file


def _d(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise CustodyError(f"Not a date: {value!r}") from None


def _periods(file: dict, today: date) -> list[tuple[date, date | None]]:
    """Detention periods: earlier interrupted periods (closed) plus the current one from arrest."""
    periods = []
    for p in file.get("custody_periods") or []:
        start, end = _d(p.get("start")), _d(p.get("end"))
        if start and end and start <= end:
            periods.append((start, end))
    arrest = _d(file.get("arrest_date"))
    if arrest and file.get("custody_type") != "released":
        periods.append((arrest, None))
    return periods


def _extension(statute: str | None, base_days: int, custody_from: date, orders: list[dict]) -> tuple[int, dict | None, list[dict]]:
    """Apply the latest valid extension order of a special statute: (days, order used, flags)."""
    flags: list[dict] = []
    rule = special_period(statute)
    if rule is None or not orders:
        return base_days, None, flags
    base_end, _ = custody_period(base_days, custody_from)
    valid = []
    for order in orders:
        on = _d(order.get("order_date"))
        if on is None:
            continue
        if on > base_end:
            flags.append({"code": "late_extension", "severity": "high",
                          "message": f"Extension order dated {on:%d %b %Y} was made after the {base_days}-day period ended on "
                                     f"{base_end:%d %b %Y}: the default-bail right may already have accrued; not applied."})
            continue
        valid.append((on, order))
    if not valid:
        return base_days, None, flags
    on, order = max(valid, key=lambda v: v[0])
    days = min(int(order.get("extended_to_days") or rule["extended_days"]), int(rule["extended_days"]))
    return max(days, base_days), {**order, "order_date": on.isoformat(), "extended_to_days": days}, flags


def compute(file: dict, today: date, *, active_rules: set[str] | None = None, orders: list[dict] | None = None) -> dict:
    """Worked dates for one custody file. `active_rules`: the table rule ids this firm has signed;
    any other rule used makes the result a labelled preview (`unverified_rules`)."""
    offence_on = _d(file.get("offence_date"))
    fir_on = _d(file.get("fir_date"))
    started = _d(file.get("investigation_started_on"))
    arrest = _d(file.get("arrest_date"))
    remand = _d(file.get("first_remand_date"))
    chargesheet = _d(file.get("chargesheet_filed_on"))
    applied = _d(file.get("default_bail_applied_on"))
    if offence_on is None:
        raise CustodyError("The date of the alleged offence is needed (it decides IPC or BNS for the punishment)")
    if arrest is None:
        raise CustodyError("The arrest date is needed")

    codes = criminal_codes(offence_on, fir_date=fir_on, investigation_started_on=started, arrest_date=arrest, today=today)
    flags = list(codes.flags)
    p = punishment(file.get("sections") or [])
    flags += check_sections(codes, [r["code"] for r in p.rules])
    for ref in p.unknown:
        flags.append({"code": "section_unknown", "severity": "medium",
                      "message": f"{ref} is not in the punishment table: its punishment is not counted. Check the sections."})
    statute = file.get("special_statute") or p.special_statute
    used = [r["rule_id"] for r in p.rules]
    special = special_period(statute) if statute else None
    if special:
        used.append(special["rule_id"])
    unverified = sorted(set(used) - (active_rules or set()))

    custody_from = remand or arrest
    if remand is None:
        flags.append({"code": "remand_date_missing", "severity": "medium",
                      "message": "First remand date not entered: the default-bail period is counted from the arrest date."})
    elif remand < arrest:
        flags.append({"code": "remand_before_arrest", "severity": "high", "message": "The first remand date is before the arrest date: check."})

    released = file.get("custody_type") == "released"
    periods = _periods(file, today)
    result: dict = {
        "id": file.get("id"), "accused_name": file.get("accused_name"), "today": today.isoformat(),
        "codes": codes.as_dict(), "punishment": p.as_dict(), "in_custody": not released,
        "days_in_custody": detention_days(periods, today) if not released else None,
        "unverified_rules": unverified, "preview": bool(unverified), "label": UNVERIFIED_LABEL if unverified else None,
        "disclaimer": DISCLAIMER,
    }

    # Default bail
    db: dict = {"provision": codes.provision("default_bail"), "days": None, "period_ends": None, "accrues_on": None,
                "status": None, "basis": None, "notes": [], "extension": None, "days_left": None}
    if not p.known and not special:
        db["status"] = "unknown"
        db["basis"] = "No charged section is in the punishment table: the 60/90-day period can't be decided."
    else:
        if special:
            days, reason = int(special["base_days"]), f"{special['basis']} ({special['title']})"
            days, used_order, ext_flags = _extension(statute, days, custody_from, orders or [])
            flags += ext_flags
            if used_order:
                db["extension"] = used_order
                reason += f"; extended to {days} days by the order of {_d(used_order['order_date']):%d %b %Y}"
            else:
                db["notes"].append(f"Extension up to {special['extended_days']} days is possible on the Public Prosecutor's report; "
                                   "it is applied only when the extension order's date is entered.")
        else:
            days, reason, notes = default_bail_period(death=p.death, life=p.life, min_years=p.min_years, max_years=p.max_years,
                                                      procedural=codes.procedural)
            db["notes"] += notes
        ends, accrues = custody_period(days, custody_from)
        db.update(days=days, period_ends=ends.isoformat(), accrues_on=accrues.isoformat(), days_left=(accrues - today).days)
        db["basis"] = (f"{db['provision']}: investigation to be completed within {days} days ({reason}); counted from "
                       f"{custody_from:%d %b %Y} with {COUNTING_NOTE}, day {days} is {ends:%d %b %Y}. If no chargesheet is "
                       f"filed by then, the right to default bail accrues on {accrues:%d %b %Y}; it is lost once a chargesheet "
                       f"is filed before the application is made.")
        if applied and applied < accrues:
            flags.append({"code": "premature_application", "severity": "medium",
                          "message": f"The default-bail application dated {applied:%d %b %Y} is before the right accrued ({accrues:%d %b %Y})."})
            applied = None
        if chargesheet and chargesheet <= ends:
            db["status"] = "chargesheet_filed"
            db["evidence"] = f"Chargesheet filed on {chargesheet:%d %b %Y}, within the {days} days"
        elif applied and (chargesheet is None or applied < chargesheet):
            db["status"] = "availed"
            db["evidence"] = f"Default-bail application made on {applied:%d %b %Y}"
        elif applied and chargesheet and applied == chargesheet:
            db["status"] = "availed"
            db["evidence"] = f"Application and chargesheet both dated {applied:%d %b %Y}"
            flags.append({"code": "same_day", "severity": "high",
                          "message": "The default-bail application and the chargesheet are dated the same day: check which came first."})
        elif chargesheet:
            db["status"] = "right_lost"
            db["evidence"] = f"Chargesheet filed on {chargesheet:%d %b %Y}, after the right accrued, with no application made"
        elif released:
            db["status"] = "not_in_custody"
        elif today >= accrues:
            db["status"] = "accrued"
        else:
            db["status"] = "running"
    result["default_bail"] = db

    # Undertrial release (s. 479 BNSS)
    ut = undertrial(max_years=p.max_years, death=p.death, life=p.life, first_time=file.get("first_time_offender"),
                    periods=periods, codes=codes, other_pending=file.get("other_pending_cases"),
                    accused_delay_days=file.get("accused_delay_days"))
    if not p.known:
        ut["explanation"] = "No charged section is in the punishment table: the s. 479 BNSS date can't be computed."
    result["undertrial"] = ut

    s479_due = bool(ut["date"]) and not ut["excluded"] and not released and _d(ut["date"]) <= today
    result["apply_today"] = db["status"] == "accrued" or s479_due
    result["flags"] = flags
    result["badges"] = _badges(codes, db, ut)
    return result


def _badges(codes: CriminalCodes, db: dict, ut: dict) -> list[str]:
    badges = []
    if "transition_s531" in codes.flag_codes():
        badges.append("Offence before 1 Jul 2024, FIR after: check s. 531 BNSS")
    if "fir_date_missing" in codes.flag_codes():
        badges.append("FIR date not entered")
    if db["status"] == "accrued":
        badges.append("Apply today: default bail")
    if db["status"] == "right_lost":
        badges.append(RIGHT_LOST)
    if ut.get("share"):
        badges.append(ut["share"])
    return badges + ut.get("badges", [])


def sort_key(result: dict) -> tuple:
    """Red 'apply today' rows first, then by the nearest date."""
    dates = [d for d in (result.get("default_bail", {}).get("accrues_on") if result.get("default_bail", {}).get("status") == "running" else None,
                         result.get("undertrial", {}).get("date")) if d]
    return (not result.get("apply_today"), min(dates) if dates else "9999-12-31")


# ----------------------------------------------------------------------------- firm sign-off


def active_rule_ids(db, org_id: str | None = None) -> set[str]:
    """Table rules whose current version two members of the org have signed (as rule_active())."""
    query = db.table("rule_verifications").select("rule_id, version, verified_by").eq("registry", REGISTRY)
    if org_id:
        query = query.eq("org_id", org_id)
    table = load_table()
    signers: dict[str, set] = defaultdict(set)
    for row in query.execute().data or []:
        rule = table.get(row["rule_id"])
        if rule and row["version"] == rule["version"]:
            signers[row["rule_id"]].add(row["verified_by"])
    return {rule_id for rule_id, who in signers.items() if len(who) >= 2}


# ----------------------------------------------------------------------------- docket and daily sweep
#
# Deadlines are created and closed through P13's deadline_service as the signed-in user (its RPCs
# check auth.uid() and the active org), so docketing happens on the user's request: when a file is
# saved, an extension order entered, or "Save to docket" pressed. The service-role sweep never
# dockets; it recomputes, records accrual / right-lost events and reports files whose dates aren't
# on the docket. The P13 ladder alerts the owner and backup daily from T-5 on hard deadlines and
# escalates to a partner.

ENGINE_VERSION = 1
DEFAULT_BAIL_RULE = "custody.default_bail"
S479_RULE = "custody.s479"


def _deadline_service():
    from app.services import deadline_service  # P13; imported lazily

    return deadline_service


def _engine_default_bail(inputs: dict) -> date | None:
    """Blind re-entry for the default-bail deadline: the day after the period, counting day 1."""
    try:
        return date.fromisoformat(inputs["custody_from"]) + timedelta(days=int(inputs["period_days"]))
    except (KeyError, TypeError, ValueError):
        return None


def _engine_s479(inputs: dict) -> date | None:
    """Blind re-entry for the s. 479 deadline (current detention from `detention_from`)."""
    try:
        share = {"1/3": 1 / 3, "1/2": 1 / 2}[inputs["share"]]
        required = float(inputs["max_years"]) * YEAR_DAYS * share + int(inputs.get("delay_days") or 0)
        earlier = int(inputs.get("earlier_detention_days") or 0)
        return date.fromisoformat(inputs["detention_from"]) + timedelta(days=math.ceil(required) - earlier)
    except (KeyError, TypeError, ValueError):
        return None


def register_engines() -> bool:
    """Let P13's blind second check recompute custody deadlines from re-entered inputs."""
    try:
        service = _deadline_service()
    except ImportError:
        return False
    service.register_engine(DEFAULT_BAIL_RULE, _engine_default_bail)
    service.register_engine(S479_RULE, _engine_s479)
    return True


def wanted_deadlines(file: dict, result: dict) -> dict[str, dict]:
    """kind -> the deadline these results call for (only from signed rules, only in custody)."""
    if result.get("unverified_rules") or not result.get("in_custody"):
        return {}
    accused = file.get("accused_name") or "accused"
    deciding = result["punishment"].get("deciding_section")
    out: dict[str, dict] = {}
    dbail = result["default_bail"]
    if dbail.get("status") in ("running", "accrued"):
        custody_from = date.fromisoformat(dbail["accrues_on"]) - timedelta(days=dbail["days"])
        out["default_bail"] = {
            "due_date": dbail["accrues_on"], "title": f"Default bail accrues: {accused} ({dbail['provision']})",
            "basis": dbail["basis"] + " The right is lost once a chargesheet is filed.", "hard": True, "safety_lead_days": 5,
            "rule_id": DEFAULT_BAIL_RULE,
            "inputs": {"custody_from": custody_from.isoformat(), "period_days": dbail["days"], "provision": dbail["provision"],
                       "punishment_rule": deciding, "custody_file_id": file.get("id")},
        }
    ut = result["undertrial"]
    if ut.get("date") and not ut.get("excluded"):
        periods = _periods(file, date.fromisoformat(result["today"]))
        current = next((s for s, e in periods if e is None), None)
        earlier = sum((e - s).days + 1 for s, e in periods if e is not None)
        out["undertrial_release"] = {
            "due_date": ut["date"], "title": f"s. 479 BNSS threshold: {accused} ({ut['share']})", "basis": ut["basis"],
            "hard": False, "safety_lead_days": 5, "rule_id": S479_RULE,
            "inputs": {"detention_from": current.isoformat() if current else None, "max_years": result["punishment"]["max_years"],
                       "share": "1/3" if ut["share"].startswith("one-third") else "1/2",
                       "delay_days": file.get("accused_delay_days") or 0, "earlier_detention_days": earlier,
                       "punishment_rule": deciding, "custody_file_id": file.get("id")},
        }
    return out


def sync_docket(db, file: dict, result: dict) -> tuple[dict, list[dict], list[str]]:
    """Bring the docket in line with the results, as the signed-in user (`db` is their client).

    New dates are docketed once; a moved date gets a new deadline and the old one is closed as
    superseded; a default-bail deadline is closed with the chargesheet (or application) as evidence.
    Returns (docket, history events, problems the docket reported)."""
    service = _deadline_service()
    current = {k: dict(v) for k, v in (file.get("docket") or {}).items()}
    events: list[dict] = []
    problems: list[str] = []
    owner = file.get("counsel_id") or file.get("user_id")

    def close(kind: str, evidence: str) -> None:
        entry = current.get(kind)
        if not entry or entry.get("done") or not entry.get("id"):
            return
        try:
            service.complete(db, entry["id"], evidence)
            entry["done"] = True
            events.append({"event": "docket_closed", "kind": kind, "deadline_id": entry["id"], "evidence": evidence})
        except service.DeadlineError as exc:
            problems.append(f"{kind}: {exc.message}")

    dbail = result["default_bail"]
    if dbail.get("status") in ("chargesheet_filed", "availed", "right_lost") and dbail.get("evidence"):
        close("default_bail", dbail["evidence"])
    for kind, want in wanted_deadlines(file, result).items():
        entry = current.get(kind)
        if entry and entry.get("due_date") == want["due_date"] and not entry.get("done"):
            continue
        try:
            created = service.create_deadline(
                db, kind=kind, title=want["title"], due_date=date.fromisoformat(want["due_date"]), owner_id=owner,
                court_case_id=file.get("court_case_id"), thread_id=file.get("thread_id"), rule_id=want["rule_id"],
                rule_version=ENGINE_VERSION, basis=want["basis"], inputs=want["inputs"], hard=want["hard"], source="engine",
                safety_lead_days=want["safety_lead_days"],
            )
        except service.DeadlineError as exc:
            problems.append(f"{kind}: {exc.message}")
            continue
        if entry and not entry.get("done"):
            close(kind, f"Superseded: custody dates recomputed (new deadline {created.get('id')})")
        current[kind] = {"id": created.get("id"), "due_date": want["due_date"]}
        events.append({"event": "docketed", "kind": kind, "due_date": want["due_date"], "deadline_id": created.get("id"),
                       **({"supersedes": entry.get("id")} if entry else {})})
    return current, events, problems


def undocketed(file: dict, result: dict) -> list[str]:
    """Kinds whose computed date isn't on the docket yet."""
    docket = file.get("docket") or {}
    return [k for k, want in wanted_deadlines(file, result).items()
            if (docket.get(k) or {}).get("due_date") != want["due_date"] or (docket.get(k) or {}).get("done")]


def _transitions(previous: dict | None, result: dict, today: date) -> list[dict]:
    before = ((previous or {}).get("default_bail") or {}).get("status")
    after = result["default_bail"].get("status")
    if after == before or after in (None, "running", "unknown"):
        return []
    message = {"accrued": "Default bail accrued: apply today",
               "right_lost": RIGHT_LOST, "chargesheet_filed": "Chargesheet filed within the period",
               "availed": "Default-bail application made", "not_in_custody": "Released"}.get(after, after)
    return [{"event": after, "on": today.isoformat(), "message": message, "evidence": result["default_bail"].get("evidence")}]


def recompute_all(admin_db, org_id: str, today: date) -> dict:
    """Daily 07:00 IST sweep for one organization (service role, every query scoped to `org_id`).

    Recomputes every custody file with the firm's signed rules, stores the result, and records
    status changes in the file's history (default bail accrued, right lost, chargesheet filed in
    time, application made). It does not docket (P13's RPCs act as a user): files whose dates
    aren't on the docket are counted in `undocketed` and listed in `undocketed_files`. Blocking;
    see `arecompute_all`."""
    files = admin_db.table(TABLE).select("*").eq("org_id", org_id).execute().data or []
    orders = admin_db.table(ORDERS_TABLE).select("*").eq("org_id", org_id).execute().data or []
    by_file: dict[str, list[dict]] = defaultdict(list)
    for o in orders:
        by_file[o["custody_file_id"]].append(o)
    active = active_rule_ids(admin_db, org_id)
    stats: dict = {"files": 0, "computed": 0, "unverified": 0, "accrued": 0, "right_lost": 0, "apply_today": 0,
                   "undocketed": 0, "undocketed_files": [], "errors": 0}
    for file in files:
        stats["files"] += 1
        try:
            result = compute(file, today, active_rules=active, orders=by_file.get(file["id"], []))
        except CustodyError as exc:
            stats["errors"] += 1
            logger.info("custody file %s not computed: %s", file.get("id"), exc)
            continue
        stats["computed"] += 1
        stats["unverified"] += bool(result["unverified_rules"])
        stats["apply_today"] += bool(result["apply_today"])
        events = _transitions(file.get("computed"), result, today)
        stats["accrued"] += any(e["event"] == "accrued" for e in events)
        stats["right_lost"] += any(e["event"] == "right_lost" for e in events)
        missing = undocketed(file, result)
        if missing:
            stats["undocketed"] += 1
            stats["undocketed_files"].append({"id": file["id"], "kinds": missing})
        update = {"computed": result, "computed_at": datetime.now(timezone.utc).isoformat()}
        if events:
            update["history"] = [*(file.get("history") or []), *events][-200:]
        admin_db.table(TABLE).update(update).eq("id", file["id"]).eq("org_id", org_id).execute()
    return stats


async def arecompute_all(admin_db, org_id: str, today: date) -> dict:
    return await asyncio.to_thread(recompute_all, admin_db, org_id, today)
