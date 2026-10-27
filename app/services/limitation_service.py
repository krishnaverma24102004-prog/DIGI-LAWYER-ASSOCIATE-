"""Limitation engine: statutory dates computed in code from a signed rule table, shown line by line.

No model is involved. A rule (app/data/limitation_rules.json) gives the period, its start event,
the exclusions that apply, whether delay can be condoned, any hard outer limit, and whether s. 4
of the Limitation Act applies. The computation follows the statute:

  s. 12(1)   the day of the start event is excluded (the count starts the next day)
  s. 12(2)   for appeals, reviews, revisions and leave to appeal, the time from the copy
             application to the day the copy was ready is excluded, but only if the copy was
             applied for before the period ran out; time before applying is not excluded
  s. 12(3)   the same for the copy of the decree or order; days already excluded count once
  s. 14      time spent prosecuting another proceeding in good faith (both its first and its
             last day are excluded: Explanation (a)), for suits and applications only
  COVID      the Supreme Court's order of 10.01.2022 (M.A. No. 21 of 2022 in Suo Motu W.P. (C)
             No. 3 of 2020): 15.03.2020 to 28.02.2022 is excluded; where the period would have
             expired inside that window, at least 90 days from 01.03.2022 are allowed
  s. 4       a period that ends on a day the court is closed (from `court_calendars`) runs to
             the day it reopens; never applied to a condonable extension window (the 30 days
             of s. 34(3) Arbitration Act) or to a period the Limitation Act doesn't govern

Conservatism rule: where an input, a calendar or the law is uncertain, the engine takes the
reading that gives the earlier date and says so. The `safe_date` is the date to rely on and is
the date the docket gets. Nothing shown is later than it except the explicitly labelled
alternatives ("if the copy is ready today"), which are never docketed.

Every result is labelled as a computation for a lawyer to check, not advice.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from app.services.workflow_service import add_months

RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "limitation_rules.json"
REGISTRY = "limitation"

COVID_START = date(2020, 3, 15)
COVID_END = date(2022, 2, 28)
COVID_MIN_DAYS = 90
COVID_ORDER = ("Supreme Court order of 10.01.2022 in M.A. No. 21 of 2022 in Suo Motu W.P. (C) No. 3 of 2020 "
               "(In Re: Cognizance for Extension of Limitation)")

DISCLAIMER = "Computation for a lawyer to check; not legal advice. No AI is involved in this date."
UNVERIFIED_LABEL = "UNVERIFIED RULE: not for reliance"
EXCLUSION_KEYS = {"s12_1", "s12_2", "s12_3", "s14", "covid"}


class LimitationError(ValueError):
    """Bad inputs (a copy applied for before the judgment, a period that ends before it starts...)."""


# ============================================================================ rules


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: int
    title: str
    basis: str
    remedy: str
    forum: str
    period: dict
    start_event: str
    exclusions: tuple[str, ...]
    condonable: bool
    outer_limit: dict | None
    s4_applies: bool
    general_clauses_s10: bool
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        period = data["period"]
        if set(period) - {"days", "months"} or len(period) != 1 or int(next(iter(period.values()))) <= 0:
            raise ValueError(f"{data['rule_id']}: period must be one of {{'days': n}} or {{'months': n}}")
        unknown = set(data["exclusions"]) - EXCLUSION_KEYS
        if unknown:
            raise ValueError(f"{data['rule_id']}: unknown exclusions {sorted(unknown)}")
        outer = data.get("outer_limit")
        if outer is not None and not (("days" in outer) ^ ("after_period_days" in outer)):
            raise ValueError(f"{data['rule_id']}: outer_limit needs 'days' (from the start event) or 'after_period_days'")
        return cls(
            rule_id=data["rule_id"], version=int(data["version"]), title=data["title"], basis=data["basis"],
            remedy=data["remedy"], forum=data["forum"], period=dict(period), start_event=data["start_event"],
            exclusions=tuple(data["exclusions"]), condonable=bool(data["condonable"]), outer_limit=outer,
            s4_applies=bool(data["s4_applies"]), general_clauses_s10=bool(data["general_clauses_s10"]),
            notes=data.get("notes", ""),
        )

    def describe(self) -> dict:
        return {
            "rule_id": self.rule_id, "version": self.version, "title": self.title, "basis": self.basis,
            "remedy": self.remedy, "forum": self.forum, "period": self.period, "period_label": period_label(self.period),
            "start_event": self.start_event, "exclusions": list(self.exclusions), "condonable": self.condonable,
            "outer_limit": self.outer_limit, "s4_applies": self.s4_applies, "general_clauses_s10": self.general_clauses_s10,
            "notes": self.notes,
        }


def load_rules(path: Path = RULES_PATH) -> dict[str, Rule]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("registry") != REGISTRY:
        raise ValueError(f"{path} is not the limitation registry")
    rules = [Rule.from_dict(r) for r in data["rules"]]
    if len({r.rule_id for r in rules}) != len(rules):
        raise ValueError("Duplicate rule_id in the limitation registry")
    return {r.rule_id: r for r in rules}


@lru_cache(maxsize=1)
def rules() -> dict[str, Rule]:
    return load_rules()


def get_rule(rule_id: str) -> Rule | None:
    return rules().get(rule_id)


def period_label(period: dict) -> str:
    if "days" in period:
        return f"{period['days']} days"
    months = int(period["months"])
    if months % 12 == 0:
        years = months // 12
        return f"{years} year{'s' if years > 1 else ''}"
    return f"{months} month{'s' if months > 1 else ''}"


# ============================================================================ inputs and calendars


@dataclass(frozen=True)
class Closure:
    day: date
    reason: str
    source_url: str | None = None
    firm: bool = False       # entered by the firm (an ad hoc closure), not from the court's calendar
    verified: bool = True    # a firm closure counts for s. 4 only once someone verified it

    @property
    def certain(self) -> bool:
        return not self.firm or self.verified


@dataclass
class Calendar:
    court_code: str
    closures: dict[date, Closure] = field(default_factory=dict)
    loaded_years: set[int] = field(default_factory=set)  # years with any rows for this court

    @classmethod
    def from_rows(cls, court_code: str, rows: list[dict]) -> "Calendar":
        """Rows from `court_calendars`; the court's own (shared) entry wins over a firm's for the same day."""
        cal = cls(court_code)
        for row in rows:
            day = _as_date(row["day"])
            cal.loaded_years.add(day.year)
            if not row.get("closed", True):
                continue
            firm = row.get("org_id") is not None
            closure = Closure(day, row.get("reason") or "Closed", row.get("source_url"), firm, bool(row.get("verified_by")))
            current = cal.closures.get(day)
            if current is None or (current.firm and not firm):
                cal.closures[day] = closure
        return cal

    def closed(self, day: date) -> Closure | None:
        return self.closures.get(day)


@dataclass
class Inputs:
    start_date: date
    copy_applied_on: date | None = None
    copy_ready_on: date | None = None
    copy_delivered_on: date | None = None
    decree_copy_applied_on: date | None = None
    decree_copy_ready_on: date | None = None
    s14_periods: list[tuple[date, date]] = field(default_factory=list)
    filing_on: date | None = None  # optional: was a filing on this day in time?

    @classmethod
    def from_dict(cls, data: dict) -> "Inputs":
        def d(key):
            value = data.get(key)
            return _as_date(value) if value else None

        if not data.get("start_date"):
            raise LimitationError("start_date is required")
        periods = []
        for p in data.get("s14_periods") or []:
            start, end = _as_date(p["from"]), _as_date(p["to"])
            periods.append((start, end))
        return cls(
            start_date=_as_date(data["start_date"]), copy_applied_on=d("copy_applied_on"), copy_ready_on=d("copy_ready_on"),
            copy_delivered_on=d("copy_delivered_on"), decree_copy_applied_on=d("decree_copy_applied_on"),
            decree_copy_ready_on=d("decree_copy_ready_on"), s14_periods=periods, filing_on=d("filing_on"),
        )

    def to_dict(self) -> dict:
        out = {k: v.isoformat() for k, v in self.__dict__.items() if isinstance(v, date)}
        if self.s14_periods:
            out["s14_periods"] = [{"from": a.isoformat(), "to": b.isoformat()} for a, b in self.s14_periods]
        return out

    def validate(self) -> None:
        s = self.start_date
        for label, applied, ready in (("copy", self.copy_applied_on, self.copy_ready_on),
                                      ("decree copy", self.decree_copy_applied_on, self.decree_copy_ready_on)):
            if applied and applied < s:
                raise LimitationError(f"The {label} can't have been applied for before the start date ({_fmt(s)})")
            if ready and not applied:
                raise LimitationError(f"Give the date the {label} was applied for")
            if ready and ready < applied:
                raise LimitationError(f"The {label} can't be ready before it was applied for")
        if self.copy_delivered_on and (not self.copy_applied_on or self.copy_delivered_on < self.copy_applied_on):
            raise LimitationError("The copy can't be delivered before it was applied for")
        if self.copy_delivered_on and self.copy_ready_on and self.copy_delivered_on < self.copy_ready_on:
            raise LimitationError("The copy can't be delivered before it was ready")
        for a, b in self.s14_periods:
            if b < a:
                raise LimitationError("An s. 14 period ends before it starts")


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise LimitationError(f"{value!r} is not a date (YYYY-MM-DD)") from None


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


# ============================================================================ arithmetic


def _days(start: date, n: int) -> set[date]:
    return {start + timedelta(days=i) for i in range(n)}


def copy_days(start: date, applied: date, ready: date) -> set[date]:
    """The (ready - applied) days excluded for a copy: from the application day, or from the day
    after the start event when applied on that day (which s. 12(1) already excludes)."""
    first = max(applied, start + timedelta(days=1))
    return _days(first, (ready - applied).days)


def period_days(start: date, period: dict) -> int:
    if "days" in period:
        return int(period["days"])
    return (add_months(start, int(period["months"])) - start).days


def walk(start: date, n: int, excluded: set[date] | frozenset = frozenset()) -> date:
    """The day on which `n` running days are complete, counting from the day after `start`
    (s. 12(1)) and skipping excluded days."""
    day, counted = start, 0
    if not excluded:
        return start + timedelta(days=n)
    while counted < n:
        day += timedelta(days=1)
        if day not in excluded:
            counted += 1
    return day


COVID_WINDOW = frozenset(_days(COVID_START, (COVID_END - COVID_START).days + 1))


def with_covid(start: date, n: int, excluded: set[date]) -> tuple[date, str | None]:
    """The end date with the COVID exclusion, and how it applied (None: it didn't)."""
    plain = walk(start, n, excluded)
    if plain < COVID_START or start > COVID_END:
        return plain, None
    end = walk(start, n, excluded | COVID_WINDOW)
    if COVID_START <= plain <= COVID_END:
        floor = COVID_END + timedelta(days=COVID_MIN_DAYS)
        if floor > end:
            return floor, "floor"
        return end, "balance"
    return end, "window"


# ============================================================================ the computation


@dataclass
class Line:
    kind: str           # start | period | exclusion | covid | s4 | outer | final | warning | info
    label: str
    section: str = ""
    days: int | None = None
    date: str | None = None
    hard: bool = False
    informational: bool = False

    def as_dict(self) -> dict:
        out = {"kind": self.kind, "label": self.label}
        if self.section:
            out["section"] = self.section
        if self.days is not None:
            out["days"] = self.days
        if self.date:
            out["date"] = self.date
        if self.hard:
            out["hard"] = True
        if self.informational:
            out["informational"] = True
        return out


def _s4_run(day: date, calendar: Calendar) -> tuple[date, list[Closure]]:
    run = []
    while (closure := calendar.closed(day)) is not None:
        run.append(closure)
        day += timedelta(days=1)
    return day, run


def compute(rule: Rule, inputs: Inputs, *, calendar: Calendar | None = None, today: date | None = None,
            court_code: str | None = None) -> dict:
    """The worked computation for `rule` on `inputs`. `calendar` is the court's loaded calendar (None:
    no court chosen or no rows at all); `today` dates the 'if the copy is ready today' alternative."""
    inputs.validate()
    today = today or date.today()
    start = inputs.start_date
    n = period_days(start, rule.period)
    covid_on = "covid" in rule.exclusions
    lines: list[Line] = []
    warnings: list[str] = []

    def warn(text: str) -> None:
        warnings.append(text)
        lines.append(Line("warning", text))

    lines.append(Line("start", f"{rule.start_event}: {_fmt(start)} (this day is not counted)",
                      "s. 12(1) Limitation Act" if "s12_1" in rule.exclusions else "s. 9 General Clauses Act", date=start.isoformat()))
    base = walk(start, n)
    lines.append(Line("period", f"Period: {period_label(rule.period)} from the day after; without exclusions it ends on {_fmt(base)}",
                      _short_basis(rule), days=n, date=base.isoformat()))

    # s. 14: needed first, because a copy only counts if applied for within the (s. 14 extended) period.
    s14: set[date] = set()
    if inputs.s14_periods:
        if "s14" in rule.exclusions:
            for a, b in inputs.s14_periods:
                s14 |= _days(a, (b - a).days + 1)
        else:
            warn("s. 14 is not applied to this remedy (it covers suits and applications); a delay needs condonation instead")

    def end_with(excluded: set[date]) -> tuple[date, str | None]:
        return with_covid(start, n, excluded) if covid_on else (walk(start, n, excluded), None)

    without_copies, _ = end_with(s14)

    # s. 12(2) and 12(3): copy time, when the copy was applied for within the period.
    copy_rules = [("s12_2", "copy of the judgment", "s. 12(2) Limitation Act", inputs.copy_applied_on, inputs.copy_ready_on),
                  ("s12_3", "copy of the decree or order", "s. 12(3) Limitation Act", inputs.decree_copy_applied_on, inputs.decree_copy_ready_on)]
    copies: list[tuple[str, str, str, date, date | None]] = []
    for key, what, section, applied, ready in copy_rules:
        if applied is None:
            continue
        if key not in rule.exclusions:
            warn(f"Time for the {what} is not excluded for this remedy ({section} does not apply)")
            continue
        if applied > without_copies:
            lines.append(Line("exclusion", f"The {what} was applied for on {_fmt(applied)}, after the period ran out on "
                                           f"{_fmt(without_copies)}: no time is excluded", section, days=0))
            warnings.append(f"The {what} was applied for after the period expired: {section} gives no exclusion")
            continue
        copies.append((key, what, section, applied, ready))

    provisional = any(ready is None for *_, ready in copies)
    excluded: set[date] = set()
    previous = base
    for key, what, section, applied, ready in copies:
        if ready is None:
            lines.append(Line("exclusion", f"The {what} was applied for on {_fmt(applied)} but no ready date is entered: no time is "
                                           "excluded (safe date)", section, days=0, informational=True))
            continue
        excluded |= copy_days(start, applied, ready)
        current = walk(start, n, excluded)
        lines.append(Line("exclusion", f"Time to obtain the {what}: applied {_fmt(applied)}, ready {_fmt(ready)} "
                                       f"({(ready - applied).days} days; days already excluded count once)",
                          section, days=(current - previous).days, date=current.isoformat()))
        previous = current
    if s14:
        current = walk(start, n, excluded | s14)
        spans = ", ".join(f"{_fmt(a)} to {_fmt(b)}" for a, b in inputs.s14_periods)
        lines.append(Line("exclusion", f"Time in another proceeding prosecuted in good faith ({spans}; first and last day included)",
                          "s. 14 Limitation Act", days=(current - previous).days, date=current.isoformat()))
        previous = current
    excluded |= s14

    prescribed_end, covid_how = end_with(excluded)
    if covid_how:
        lines.append(_covid_line(covid_how, previous, prescribed_end))
    if covid_how == "floor":
        # The 90-day floor only applies where the period would have expired inside the window. A
        # missing copy-ready date could be late enough to carry the expiry past 28.02.2022, where
        # the floor no longer applies and the date is earlier: the safe date must allow for that.
        for *_, applied, ready in copies:
            if ready is None:
                escape = _covid_floor_escape(start, n, excluded, applied)
                if escape is not None and escape < prescribed_end:
                    text = (f"If the copy time carried the expiry past 28.02.2022, the 90-day minimum wouldn't apply and the date "
                            f"would be {_fmt(escape)}: that earlier date is used until the copy-ready date is entered")
                    lines.append(Line("warning", text, "Supreme Court order, 10.01.2022", date=escape.isoformat()))
                    warnings.append(text)
                    prescribed_end = escape
    lines.append(Line("info", f"Prescribed period ends on {_fmt(prescribed_end)}", date=prescribed_end.isoformat()))

    # s. 4: the court closed on the last day.
    safe_date = prescribed_end
    s4 = _apply_s4(rule.s4_applies, rule.general_clauses_s10, prescribed_end, calendar, court_code, lines, warnings,
                   what="the prescribed period")
    if s4 and not s4["informational"]:
        safe_date = date.fromisoformat(s4["shifted_to"])

    # Outer limits (hard or condonable windows): s. 4 never extends them.
    outer = None
    if rule.outer_limit:
        outer = _outer_limit(rule, start, n, excluded, covid_on, safe_date, calendar, lines)
    elif not rule.condonable:
        lines.append(Line("outer", "No extension: delay in this remedy cannot be condoned under s. 5", "s. 5 Limitation Act",
                          date=safe_date.isoformat(), hard=True))

    # Alternatives when the copy-ready date is missing: labelled, never docketed.
    alternatives = []
    if provisional:
        for key, what, section, applied, ready in copies:
            if ready is not None:
                continue
            if key == "s12_2" and inputs.copy_delivered_on:
                guess, label = inputs.copy_delivered_on, f"If the {what} was ready on the day it was delivered ({_fmt(inputs.copy_delivered_on)})"
            else:
                guess, label = max(today, applied), f"If the {what} is ready today ({_fmt(max(today, applied))})"
            alt_excluded = excluded | copy_days(start, applied, guess)
            alt_end, _ = end_with(alt_excluded)
            alternatives.append({"label": label, "date": alt_end.isoformat(),
                                 "note": "Not for the docket: s. 4 not applied; enter the ready date to fix the date"})
        warnings.append("Provisional: the copy-ready date is missing, so the safe date leaves out the copy time")

    lines.append(Line("final", f"Safe date: {_fmt(safe_date)}", date=safe_date.isoformat(), hard=not rule.condonable))

    result = {
        "label": DISCLAIMER,
        "rule": {"rule_id": rule.rule_id, "version": rule.version, "title": rule.title, "basis": rule.basis,
                 "remedy": rule.remedy, "forum": rule.forum},
        "inputs": {**inputs.to_dict(), **({"court_code": court_code} if court_code else {})},
        "lines": [line.as_dict() for line in lines],
        "base_date": base.isoformat(),
        "prescribed_end": prescribed_end.isoformat(),
        "s4": s4,
        "safe_date": safe_date.isoformat(),
        "docket_date": safe_date.isoformat(),
        "outer_limit": outer,
        "provisional": provisional,
        "alternatives": alternatives,
        "condonable": rule.condonable,
        "warnings": warnings,
    }
    if inputs.filing_on:
        result["filing"] = filing_status(result, inputs.filing_on)
    return result


def _short_basis(rule: Rule) -> str:
    return rule.basis.split(":")[0]


def _covid_floor_escape(start: date, n: int, excluded: set[date], applied: date) -> date | None:
    """The earliest end date over the copy-ready dates that carry the (non-COVID) expiry past
    28.02.2022, or None if no ready date does. Past that point more copy time only adds days."""

    def copy_until(k: int) -> set[date]:
        return excluded | copy_days(start, applied, applied + timedelta(days=k))

    lo, hi = 0, 2 * len(COVID_WINDOW)
    if walk(start, n, copy_until(hi)) <= COVID_END:
        return None
    while lo < hi:  # the expiry without the order grows with the copy time: binary search
        mid = (lo + hi) // 2
        if walk(start, n, copy_until(mid)) > COVID_END:
            hi = mid
        else:
            lo = mid + 1
    end, _ = with_covid(start, n, copy_until(lo))
    return end


def _covid_line(how: str, before: date, after: date) -> Line:
    if how == "floor":
        text = (f"The period would have expired inside 15.03.2020 to 28.02.2022: at least {COVID_MIN_DAYS} days from 01.03.2022 "
                f"(counted from 01.03.2022 itself, the earlier reading; 30.05.2022 is also commonly stated)")
    elif how == "balance":
        text = ("The period would have expired inside 15.03.2020 to 28.02.2022: the balance left on 15.03.2020 runs from "
                f"01.03.2022 (longer than {COVID_MIN_DAYS} days)")
    else:
        text = "15.03.2020 to 28.02.2022 is excluded"
    return Line("covid", f"{text}. {COVID_ORDER}", "Supreme Court order, 10.01.2022", days=(after - before).days, date=after.isoformat())


def _apply_s4(applies: bool, via_gca: bool, end: date, calendar: Calendar | None, court_code: str | None,
              lines: list[Line], warnings: list[str], *, what: str) -> dict | None:
    """The s. 4 line for a period ending on `end`. Returns the shift (or None when nothing shifts)."""
    if not applies and not via_gca:
        return None
    if calendar is None or not calendar.loaded_years:
        text = (f"No court chosen: s. 4 not checked for {what}" if not court_code
                else f"No calendar is loaded for {court_code}: no s. 4 shift is applied; check whether the court is open on {_fmt(end)}")
        lines.append(Line("warning", text))
        warnings.append(text)
        return None
    if end.year not in calendar.loaded_years:
        text = f"The {calendar.court_code} calendar for {end.year} is not loaded: no s. 4 shift is applied; check whether the court is open on {_fmt(end)}"
        lines.append(Line("warning", text))
        warnings.append(text)
        return None
    reopens, run = _s4_run(end, calendar)
    if not run:
        if end.weekday() >= 5:
            lines.append(Line("info", f"{_fmt(end)} is a {end.strftime('%A')}, but the {calendar.court_code} calendar doesn't list it "
                                      "as closed: no s. 4 shift is applied"))
        return None
    closures = [{"day": c.day.isoformat(), "reason": c.reason, "source_url": c.source_url, "firm": c.firm, "verified": c.verified}
                for c in run]
    reasons = "; ".join(f"{_fmt(c.day)} {c.reason}" for c in run)
    uncertain = None
    if not applies:
        uncertain = ("this period is not governed by the Limitation Act, so whether s. 4 (through s. 10 of the General Clauses Act) "
                     "extends it is uncertain")
    elif not all(c.certain for c in run):
        uncertain = "a closure in this run was entered by the firm and is not verified"
    if uncertain:
        lines.append(Line("s4", f"The court is closed ({reasons}); it reopens {_fmt(reopens)}. Shown for information only: {uncertain}, "
                                f"so the safe date stays {_fmt(end)}", "s. 4 Limitation Act", days=(reopens - end).days,
                          date=reopens.isoformat(), informational=True))
    else:
        lines.append(Line("s4", f"The court is closed ({reasons}): the period runs to the day it reopens, {_fmt(reopens)}",
                          "s. 4 Limitation Act", days=(reopens - end).days, date=reopens.isoformat()))
    return {"from": end.isoformat(), "shifted_to": reopens.isoformat(), "closures": closures, "informational": bool(uncertain),
            "reason": uncertain}


def _outer_limit(rule: Rule, start: date, n: int, excluded: set[date], covid_on: bool, safe_date: date,
                 calendar: Calendar | None, lines: list[Line]) -> dict:
    spec = rule.outer_limit
    total = n + int(spec["after_period_days"]) if "after_period_days" in spec else int(spec["days"])
    if covid_on:
        end, _ = with_covid(start, total, excluded)
    else:
        end = walk(start, total, excluded)
    # A prescribed period extended by s. 4 past the window still stands (it is the period itself).
    end = max(end, safe_date)
    hard = bool(spec.get("hard"))
    lines.append(Line("outer", spec["label"] + f": {_fmt(end)}" + (" (cannot be extended)" if hard else ""),
                      spec.get("basis", ""), days=total, date=end.isoformat(), hard=hard))
    if calendar is not None and calendar.closed(end) and end.year in calendar.loaded_years:
        lines.append(Line("s4", f"The court is closed on {_fmt(end)} ({calendar.closed(end).reason}); s. 4 is not applied to this limit, so it stays "
                                f"{_fmt(end)}", "s. 4 Limitation Act", days=0, informational=True))
    return {"date": end.isoformat(), "hard": hard, "label": spec["label"], "basis": spec.get("basis", "")}


def filing_status(result: dict, filed: date) -> dict:
    """Whether a filing on `filed` was within the safe date, needs the court's indulgence, or is barred."""
    safe = date.fromisoformat(result["safe_date"])
    outer = result.get("outer_limit")
    if filed <= safe:
        return {"status": "in_time", "message": f"Filed on or before the safe date ({_fmt(safe)})"}
    if outer:
        limit = date.fromisoformat(outer["date"])
        if filed <= limit:
            return {"status": "needs_extension", "message": f"After {_fmt(safe)} but within {_fmt(limit)}: only if the court allows it"}
        if outer["hard"]:
            return {"status": "barred", "message": f"After the outer limit {_fmt(limit)}, which cannot be extended"}
        return {"status": "needs_extension", "message": f"After {_fmt(limit)}: only with the court's leave, in exceptional circumstances"}
    if result["condonable"]:
        return {"status": "needs_extension", "message": f"After {_fmt(safe)}: needs condonation of delay (s. 5)"}
    return {"status": "barred", "message": f"After {_fmt(safe)}, and delay cannot be condoned"}


def candidate_dates(result: dict) -> list[str]:
    """The safe date first, then any labelled alternatives (for the docket's candidate dates)."""
    return [result["safe_date"], *[a["date"] for a in result["alternatives"]]]


# ============================================================================ copy tracker


def working_days_after(day: date, n: int, closed: set[date]) -> date:
    """`n` working days after `day` (Monday to Friday, not a listed closure)."""
    counted = 0
    while counted < n:
        day += timedelta(days=1)
        if day.weekday() < 5 and day not in closed:
            counted += 1
    return day


CHECK_EVERY_WORKING_DAYS = 3


def copy_status(row: dict, today: date, closed: set[date] | None = None) -> dict:
    """Days since applied and when to check the copy section next (every 3 working days while pending)."""
    applied = _as_date(row["applied_on"])
    pending = not row.get("ready_on") and not row.get("delivered_on") and row.get("status", "pending") == "pending"
    out = {"days_since_applied": (today - applied).days, "pending": pending, "next_check_on": None, "check_due": False}
    if pending:
        closed = closed or set()
        check = working_days_after(applied, CHECK_EVERY_WORKING_DAYS, closed)
        while check < today:
            check = working_days_after(check, CHECK_EVERY_WORKING_DAYS, closed)
        out["next_check_on"] = check.isoformat()
        out["check_due"] = check <= today
    return out


def derive_status(row: dict) -> str:
    if row.get("status") == "withdrawn":
        return "withdrawn"
    if row.get("delivered_on"):
        return "delivered"
    if row.get("ready_on"):
        return "ready"
    return "pending"


# ============================================================================ docket


def save_to_docket(db, result: dict, *, owner_id: str, title: str, court_case_id: str | None = None,
                   thread_id: str | None = None) -> list[dict]:
    """Write the safe date (and any outer limit) as docket deadlines. Raises deadline_service.DeadlineError."""
    from app.services import deadline_service  # the docket (P13); imported here so this module loads without it

    rule = result["rule"]
    common = {"owner_id": owner_id, "court_case_id": court_case_id, "thread_id": thread_id, "rule_id": rule["rule_id"],
              "rule_version": rule["version"], "basis": rule["basis"], "inputs": result["inputs"], "source": "engine"}
    saved = [deadline_service.create_deadline(
        db, kind="limitation", title=title, due_date=date.fromisoformat(result["docket_date"]),
        hard=not result["condonable"], candidates=candidate_dates(result), **common)]
    outer = result.get("outer_limit")
    if outer and outer["date"] != result["docket_date"]:
        saved.append(deadline_service.create_deadline(
            db, kind="limitation_outer_limit", title=f"{title}: outer limit", due_date=date.fromisoformat(outer["date"]),
            hard=outer["hard"], candidates=[outer["date"]], **common))
    return saved
