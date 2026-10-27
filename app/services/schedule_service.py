"""Clash board and reach estimates (P04). Deterministic: there is no AI anywhere in this module.

1. Positions: an item's position is its rank in the courtroom's printed list for the day.
   Connected matters listed "with" an item count as one call; deleted and "not to be taken up"
   items are skipped.
2. Sitting clock: court timings per court (sitting start, lunch, rising). The day starts at the
   junior's "bench assembled" tap when logged, otherwise at the profile's sitting start. Elapsed
   time is counted in sitting minutes, which exclude the lunch interval.
   Source of truth for timings: the `courts` table (migration 014, `courts.timings`). The JSON
   profiles in app/data/court_timings/ are shipped defaults used only for a court whose row has no
   complete timings; a court with neither gets no estimate ("court timings not recorded").
3. Observations: each first "called" tap stores its pace r = E / max(P, 3) (elapsed sitting
   minutes over position, floored at 3), so every call at any item informs every item of that
   bench and list segment.
4. Weights: the current roster period 1.0; the same bench in earlier periods of the courtroom
   0.5^(periods back) ("carried"); other benches 0. The same bench's history in another courtroom
   is only a labelled low-confidence hint (weight 0 toward the threshold). An unparsed bench
   header (bench_key null) gives "bench unknown" and no estimate.
5. Estimator: with effective weight W >= 20 for (bench, segment), the weighted 25th and 75th
   percentiles of r (the smallest r whose cumulative normalised weight is >= q; no
   interpolation) give the window start + q x max(P, 3) in sitting minutes, mapped to clock time
   across lunch and capped at rising ("may not be reached today" when even the lower bound passes
   rising). Below 20, the bench's pooled segments are used if they reach 20 ("pooled across list
   types"); otherwise "not enough data".
6. Reach frequency ("reached in 7 of 9 sittings", from "court rose at item K" taps) is display
   only and never colours a clash.
7. Clashes, per advocate and date, for pairs of items in different courtrooms: OVERLAP (red) iff
   both windows exist and [lo - travel, hi + travel] meets the other window; POSSIBLE_NO_DATA
   (amber) iff either window is missing, collapsed into one notice per advocate-morning.
8. Resolution: reassignment to a free, enrolled colleague of adequate seniority, ranked by prior
   appearance in the matter; only when nobody is free, a fixed "pass over / keep back" note for
   the appearing counsel. Nothing here ever proposes seeking an adjournment because counsel is
   engaged elsewhere (Order XVII Rule 1 CPC: a clash is not a ground). Client messages about
   hearings are not part of this build: the outbound client channel waits on problem P33.

Reach estimates are statistics from the firm's own appearance logs: internal, never shared with
other firms, never put to the court.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import combinations
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

MIN_WEIGHT = 20.0          # effective weight needed before a window is estimated
POSITION_FLOOR = 3         # pace = elapsed / max(position, 3)
Q_LOW, Q_HIGH = 0.25, 0.75
SAME_COMPLEX_TRAVEL = 5    # minutes between courtrooms of one complex, unless the firm sets it
UNKNOWN_TRAVEL = 30        # complexes without an entry in the travel matrix
WIDE_WINDOW_MIN = 120      # windows wider than this are flagged as too wide to plan around
HISTORY_DAYS = 365
SEGMENTS = ("fresh", "after_notice", "regular", "supplementary", "advance", "other")
TAP_KINDS = ("assembled", "called", "rose")
USABLE = ("estimated", "pooled")
NOT_EXPECTED = ("beyond_rising", "no_position", "no_courtroom")  # not part of any clash
UNALLOTTED = "not allotted"

SENIORITY_BY_ROLE = {"owner": 3, "partner": 3, "associate": 2}
# Minimum seniority to stand in, by list segment: matters on the regular (final hearing) board
# need an associate or above; mentions, fresh and after-notice matters any enrolled advocate.
SENIORITY_FOR_SEGMENT = {"regular": 2}

PASS_OVER_NOTE = (
    "No colleague is free for this window. Note for the appearing counsel: when {item} is called, "
    "ask the court to pass it over or keep it back until counsel arrives from {other}."
)
SAFEGUARD_NOTE = (
    "Reach windows are statistics from the firm's own logged calls: ranges, not promises. They stay "
    "inside the firm and are never put to the court."
)

TIMINGS_DIR = Path(__file__).resolve().parents[1] / "data" / "court_timings"
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    """A tap or request that can't be used; the message is safe to show."""


# ----------------------------------------------------------------------------- court timings


def to_minutes(value: str) -> int:
    match = _HHMM.match(str(value).strip())
    if not match:
        raise ValueError(f"Not a time of day: {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def hhmm(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    whole = int(round(minutes))
    return f"{whole // 60:02d}:{whole % 60:02d}"


@dataclass(frozen=True)
class Timings:
    sitting_start: int
    lunch_start: int
    lunch_end: int
    rising: int

    @property
    def lunch(self) -> int:
        return self.lunch_end - self.lunch_start

    @classmethod
    def parse(cls, data: dict | None) -> Timings | None:
        """Timings from {"sitting_start": "10:30", "lunch_start": ..., "lunch_end": ..., "rising": ...}."""
        if not data:
            return None
        try:
            t = cls(*(to_minutes(data[k]) for k in ("sitting_start", "lunch_start", "lunch_end", "rising")))
        except (KeyError, ValueError, TypeError):
            return None
        if not (t.sitting_start < t.lunch_start <= t.lunch_end < t.rising):
            return None
        return t


@lru_cache(maxsize=1)
def default_profiles() -> dict[str, dict]:
    """The shipped court profiles (app/data/court_timings/*.json), by court code."""
    profiles = {}
    for path in sorted(TIMINGS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles[data["code"]] = data
    return profiles


@dataclass(frozen=True)
class CourtProfile:
    code: str
    name: str | None
    complex: str | None
    timings: Timings | None
    timings_source: str | None  # "courts" | "default_profile" | None
    coverage: str | None = None


def court_profile(code: str, row: dict | None = None) -> CourtProfile:
    """The courts row wins; the shipped JSON fills in a court whose row has no complete timings."""
    default = default_profiles().get(code) or {}
    row = row or {}
    timings, source = Timings.parse(row.get("timings")), "courts"
    if timings is None:
        timings, source = Timings.parse(default.get("timings")), "default_profile"
    return CourtProfile(
        code=code,
        name=row.get("name") or default.get("name"),
        complex=row.get("complex") or default.get("complex"),
        timings=timings,
        timings_source=source if timings else None,
        coverage=default.get("coverage"),
    )


# ----------------------------------------------------------------------------- positions


def _natural(item_no) -> tuple:
    parts = re.findall(r"\d+|\D+", str(item_no or ""))
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.strip().lower()) for p in parts)


def printed_order(items: list[dict]) -> list[dict]:
    """Items of one courtroom's list in printed order: the parser's `seq`, else the item number."""
    return sorted(items, key=lambda i: (i.get("seq") is None, i.get("seq") or 0, _natural(i.get("item_no"))))


def assign_positions(items: list[dict]) -> dict[str, int | None]:
    """Position of each item (by id) in a courtroom's printed list, given in printed order.

    Connected matters ("with" an item: `connected_to` holds the lead item's id or item number)
    share the lead's position; deleted and not-to-be-taken-up items get None.
    """
    by_no = {str(i.get("item_no")): i.get("id") for i in items}
    positions: dict[str, int | None] = {}
    count = 0
    for item in items:
        if (item.get("status") or "listed") != "listed":
            positions[item["id"]] = None
            continue
        lead = item.get("connected_to")
        if lead:
            lead_id = lead if lead in positions else by_no.get(str(lead))
            if lead_id is not None and positions.get(lead_id) is not None:
                positions[item["id"]] = positions[lead_id]
                continue
        count += 1
        positions[item["id"]] = count
    return positions


# ----------------------------------------------------------------------------- sitting clock


def day_start(timings: Timings, assembled_minute: float | None = None) -> float:
    """The sitting starts at the 'bench assembled' tap when logged, else at the profile time."""
    return float(assembled_minute) if assembled_minute is not None else float(timings.sitting_start)


def elapsed_sitting(start: float, at: float, timings: Timings) -> float:
    """Sitting minutes from `start` to `at`, without the lunch interval."""
    raw = at - start
    lunch = max(0.0, min(at, timings.lunch_end) - max(start, timings.lunch_start))
    return max(0.0, raw - lunch)


def sitting_to_clock(start: float, sitting_minutes: float, timings: Timings) -> float:
    """Clock time (minutes after midnight) `sitting_minutes` into the sitting, skipping lunch."""
    before_lunch = max(0.0, timings.lunch_start - start)
    if sitting_minutes <= before_lunch:
        return start + sitting_minutes
    return max(start, timings.lunch_end) + (sitting_minutes - before_lunch)


def pace(elapsed: float, position: int) -> float:
    return elapsed / max(position, POSITION_FLOOR)


def ist_minutes(at: datetime) -> float:
    """Minutes after midnight, Indian Standard Time."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=IST)
    local = at.astimezone(IST)
    return local.hour * 60 + local.minute + local.second / 60


# ----------------------------------------------------------------------------- observations and weights


@dataclass(frozen=True)
class Observation:
    court_code: str
    courtroom: str
    bench_key: str | None
    roster_period_id: str | None
    segment: str | None
    position: int
    pace: float
    list_date: date | None = None

    @classmethod
    def from_row(cls, row: dict) -> Observation:
        return cls(
            court_code=row["court_code"], courtroom=str(row["courtroom"]), bench_key=row.get("bench_key"),
            roster_period_id=row.get("roster_period_id"), segment=row.get("segment"), position=int(row["position"]),
            pace=float(row["pace"]), list_date=_as_date(row.get("list_date")),
        )


@dataclass(frozen=True)
class Period:
    id: str
    court_code: str
    courtroom: str
    bench_key: str
    started_on: date
    bench_label: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Period:
        return cls(row["id"], row["court_code"], str(row["courtroom"]), row["bench_key"], _as_date(row["started_on"]),
                   row.get("bench_label"))


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass
class Weighting:
    weighted: list[tuple[Observation, float]]
    current_started: date | None   # when the current roster period began (None: no period yet)
    new_bench: bool                 # the bench sitting today has no period yet in this courtroom
    current_period_id: str | None


def weigh_observations(court_code: str, courtroom: str, bench_key: str, list_date: date,
                       periods: list[Period], observations: list[Observation]) -> Weighting:
    """Each observation's weight toward the window of `bench_key` in this courtroom on `list_date`."""
    room = sorted((p for p in periods if p.court_code == court_code and p.courtroom == courtroom
                   and p.started_on <= list_date), key=lambda p: p.started_on)
    current_index = len(room) - 1
    new_bench = not room or room[-1].bench_key != bench_key
    if new_bench:
        current_index = len(room)  # today's bench starts a period of its own
    index = {p.id: i for i, p in enumerate(room)}
    weighted = []
    for o in observations:
        if o.court_code != court_code or o.courtroom != courtroom or o.bench_key != bench_key:
            continue
        k = index.get(o.roster_period_id)
        if k is None or room[k].bench_key != bench_key:
            continue
        weighted.append((o, 0.5 ** (current_index - k)))
    current = None if new_bench else room[-1]
    return Weighting(weighted, current.started_on if current else None, new_bench, current.id if current else None)


def weighted_quantile(pairs: list[tuple[float, float]], q: float) -> float | None:
    """The smallest value whose cumulative normalised weight (sorted ascending) is >= q."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= q * total - 1e-9:
            return value
    return pairs[-1][0]


# ----------------------------------------------------------------------------- windows


@dataclass
class Window:
    # estimated | pooled | hint | not_enough_data | beyond_rising | bench_unknown | no_timings | no_position | no_courtroom
    state: str
    lo: float | None = None
    hi: float | None = None
    label: str = ""
    capped: bool = False
    weight: float = 0.0
    calls: int = 0
    q25: float | None = None
    q75: float | None = None
    carried: bool = False

    @property
    def usable(self) -> bool:
        return self.state in USABLE and self.lo is not None and self.hi is not None

    @property
    def wide(self) -> bool:
        return self.usable and (self.hi - self.lo) > WIDE_WINDOW_MIN

    def as_dict(self) -> dict:
        return {
            "state": self.state, "lo": hhmm(self.lo), "hi": hhmm(self.hi), "label": self.label, "capped": self.capped,
            "wide": self.wide, "weight": round(self.weight, 2), "calls": self.calls,
            "q25": None if self.q25 is None else round(self.q25, 3), "q75": None if self.q75 is None else round(self.q75, 3),
            "carried": self.carried,
        }


def _fmt_weight(w: float) -> str:
    return f"{w:.1f}".rstrip("0").rstrip(".")


def _day(d: date) -> str:
    return f"{d.day} {d:%b}"


def _project(start: float, position: int, q25: float, q75: float, timings: Timings) -> tuple[float, float, bool, bool]:
    """(lo, hi, capped, beyond_rising) in clock minutes."""
    factor = max(position, POSITION_FLOOR)
    lo = sitting_to_clock(start, q25 * factor, timings)
    hi = sitting_to_clock(start, q75 * factor, timings)
    if lo > timings.rising:
        return lo, hi, False, True
    capped = hi > timings.rising
    return lo, min(hi, timings.rising), capped, False


def estimate_window(*, court_code: str, courtroom: str, bench_key: str | None, segment: str | None,
                    position: int | None, list_date: date, timings: Timings | None, start: float | None,
                    periods: list[Period], observations: list[Observation], bench_label: str | None = None) -> Window:
    if position is None:
        return Window("no_position", label="not on today's list (deleted or not to be taken up)")
    if timings is None:
        return Window("no_timings", label="court timings not recorded: no estimate")
    if not bench_key:
        return Window("bench_unknown", label="bench unknown: not enough data")
    start = day_start(timings, start)
    w = weigh_observations(court_code, courtroom, bench_key, list_date, periods, observations)
    same_segment = [(o, wt) for o, wt in w.weighted if o.segment == segment]
    seg_weight = sum(wt for _, wt in same_segment)
    pool_weight = sum(wt for _, wt in w.weighted)
    state, chosen, weight = None, [], 0.0
    if seg_weight >= MIN_WEIGHT:
        state, chosen, weight = "estimated", same_segment, seg_weight
    elif pool_weight >= MIN_WEIGHT:
        state, chosen, weight = "pooled", w.weighted, pool_weight
    if state is None:
        bench = bench_label or "this bench"
        since = f"new bench since {_day(w.current_started or list_date)}"
        hint = _hint(court_code, courtroom, bench_key, list_date, observations, periods, start, position, timings, bench)
        if hint is not None:
            return hint
        return Window("not_enough_data", label=f"{since}: not enough data ({_fmt_weight(pool_weight)} of {int(MIN_WEIGHT)})",
                      weight=pool_weight, calls=len(w.weighted))
    q25 = weighted_quantile([(o.pace, wt) for o, wt in chosen], Q_LOW)
    q75 = weighted_quantile([(o.pace, wt) for o, wt in chosen], Q_HIGH)
    lo, hi, capped, beyond = _project(start, position, q25, q75, timings)
    carried = any(wt < 1.0 for _, wt in chosen)
    calls = len(chosen)
    if beyond:
        return Window("beyond_rising", lo=None, hi=None, label="may not be reached today", weight=weight, calls=calls,
                      q25=q25, q75=q75, carried=carried)
    positions = [o.position for o, _ in chosen]
    scope = "this roster and carried from earlier rosters" if carried else "this roster"
    pooled = "; pooled across list types" if state == "pooled" else ""
    label = (f"usually reached {hhmm(lo)}-{hhmm(hi)} before this bench (pace from {calls} calls at items "
             f"{min(positions)}-{max(positions)}, {scope}{pooled})")
    if capped:
        label += "; the court may rise before the later end"
    return Window(state, lo, hi, label, capped, weight, calls, q25, q75, carried)


def _hint(court_code, courtroom, bench_key, list_date, observations, periods, start, position, timings, bench) -> Window | None:
    """The same bench's pace in another courtroom: shown, labelled low confidence, never counted."""
    others = [o for o in observations if o.bench_key == bench_key and not (o.court_code == court_code and o.courtroom == courtroom)]
    if len(others) < MIN_WEIGHT:
        return None
    q25 = weighted_quantile([(o.pace, 1.0) for o in others], Q_LOW)
    q75 = weighted_quantile([(o.pace, 1.0) for o in others], Q_HIGH)
    lo, hi, _capped, beyond = _project(start, position, q25, q75, timings)
    if beyond:
        return Window("hint", label=f"carried from {bench}'s earlier court, low confidence: may not be reached today",
                      calls=len(others), q25=q25, q75=q75)
    return Window("hint", lo, hi, f"carried from {bench}'s earlier court, low confidence ({hhmm(lo)}-{hhmm(hi)})",
                  calls=len(others), q25=q25, q75=q75)


def reach_frequency(position: int | None, rose_positions: list[int]) -> dict | None:
    """From 'court rose at item K' taps of the current roster: display only, never used for colour."""
    if position is None or not rose_positions:
        return None
    reached = sum(1 for k in rose_positions if k >= position)
    return {"reached": reached, "sittings": len(rose_positions), "text": f"reached in {reached} of {len(rose_positions)} sittings"}


# ----------------------------------------------------------------------------- travel


class TravelMatrix:
    """The firm's complex-to-complex travel times; same complex defaults to 5 minutes."""

    def __init__(self, rows: list[dict] | None = None):
        self._minutes = {}
        for row in rows or []:
            a, b = sorted((row["from_complex"], row["to_complex"]))
            self._minutes[(a, b)] = int(row["minutes"])

    def minutes(self, a: str | None, b: str | None) -> tuple[int, bool]:
        """(minutes, known): unknown pairs get UNKNOWN_TRAVEL."""
        if a and b:
            key = tuple(sorted((a, b)))
            if key in self._minutes:
                return self._minutes[key], True
            if a == b:
                return SAME_COMPLEX_TRAVEL, True
        return UNKNOWN_TRAVEL, False


def normalize_pair(a: str, b: str) -> tuple[str, str]:
    a, b = " ".join(a.split()), " ".join(b.split())
    return (a, b) if a <= b else (b, a)


# ----------------------------------------------------------------------------- board


@dataclass
class BoardItem:
    key: str
    advocate_id: str
    court_code: str
    courtroom: str
    item_no: str
    position: int | None
    window: Window
    complex: str | None = None
    segment: str | None = None
    bench_key: str | None = None
    bench_label: str | None = None
    list_type: str | None = None
    court_case_id: str | None = None
    case_title: str | None = None
    court_name: str | None = None
    timings: Timings | None = None
    start: float | None = None
    reach: dict | None = None
    coverage: str | None = None
    item_id: str | None = None

    @property
    def room(self) -> tuple[str, str]:
        return (self.court_code, self.courtroom)

    def label(self, with_court: bool = False) -> str:
        room = f"Court {self.courtroom}" if str(self.courtroom).isdigit() else str(self.courtroom)
        prefix = f"{self.court_code} " if with_court else ""
        return f"{prefix}{room} item {self.item_no}"

    def busy_span(self) -> tuple[float, float]:
        """The window, or the whole sitting day when there is none."""
        if self.window.usable:
            return self.window.lo, self.window.hi
        if self.timings is not None:
            return day_start(self.timings, self.start), float(self.timings.rising)
        return 0.0, 24 * 60.0

    def as_dict(self) -> dict:
        return {
            "key": self.key, "item_id": self.item_id, "court_code": self.court_code, "court_name": self.court_name, "courtroom": self.courtroom,
            "complex": self.complex, "item_no": self.item_no, "position": self.position, "segment": self.segment,
            "list_type": self.list_type, "bench_label": self.bench_label or ("bench unknown" if not self.bench_key else None),
            "court_case_id": self.court_case_id, "case_title": self.case_title, "window": self.window.as_dict(),
            "reach": self.reach, "coverage": self.coverage,
        }


def _overlap(a: tuple[float, float], b: tuple[float, float], travel: float) -> bool:
    return a[0] - travel < b[1] and b[0] < a[1] + travel


@dataclass
class Clash:
    state: str  # overlap | possible_no_data
    a: BoardItem
    b: BoardItem
    travel: int
    travel_known: bool

    def text(self) -> str:
        courts = self.a.court_code != self.b.court_code
        if self.state == "overlap":
            wa = f"{hhmm(self.a.window.lo)}-{hhmm(self.a.window.hi)}"
            wb = f"{hhmm(self.b.window.lo)}-{hhmm(self.b.window.hi)}"
            apart = f"{self.travel} min apart" + ("" if self.travel_known else " (travel time not set)")
            return f"{self.a.label(courts)} ({wa}) and {self.b.label(courts)} ({wb}) overlap; {apart}"
        return f"{self.a.label(courts)} and {self.b.label(courts)}: possible clash, no data"

    def as_dict(self) -> dict:
        return {"state": self.state, "items": [self.a.key, self.b.key], "travel_minutes": self.travel,
                "travel_known": self.travel_known, "text": self.text()}


def classify(items: list[BoardItem], travel: TravelMatrix) -> tuple[list[Clash], list[Clash]]:
    """(red overlaps, amber possible clashes) for one advocate's morning."""
    red, amber = [], []
    for a, b in combinations(items, 2):
        if a.room == b.room:
            continue  # items in the same courtroom never clash
        if a.window.state in NOT_EXPECTED or b.window.state in NOT_EXPECTED:
            continue
        minutes, known = travel.minutes(a.complex, b.complex)
        if a.window.usable and b.window.usable:
            if _overlap((a.window.lo, a.window.hi), (b.window.lo, b.window.hi), minutes):
                red.append(Clash("overlap", a, b, minutes, known))
        else:
            amber.append(Clash("possible_no_data", a, b, minutes, known))
    return red, amber


def amber_notice(amber: list[Clash], treated_as_clash: bool) -> dict | None:
    if not amber:
        return None
    rooms = {i.room for c in amber for i in (c.a, c.b) if not i.window.usable}
    n = len(rooms)
    text = f"{n} courtroom{'s' if n != 1 else ''} without reach data today"
    return {"courtrooms": n, "pairs": len(amber), "text": text, "treated_as_clash": treated_as_clash}


@dataclass
class Colleague:
    user_id: str
    name: str
    role: str
    seniority: int
    enrolled: bool = True
    items: list[BoardItem] = field(default_factory=list)
    enrolment_no: str | None = None


def required_seniority(segment: str | None) -> int:
    return SENIORITY_FOR_SEGMENT.get(segment or "", 1)


def is_free(colleague: Colleague, target: BoardItem, travel: TravelMatrix) -> bool:
    span = target.busy_span()
    for item in colleague.items:
        if item.window.state in NOT_EXPECTED or item.room == target.room:
            continue
        if item.window.usable:
            minutes, _ = travel.minutes(item.complex, target.complex)
            if _overlap((item.window.lo, item.window.hi), span, minutes):
                return False
        elif not (item.complex and item.complex == target.complex):
            return False  # an item without a window counts as free time only in the same complex
    return True


def reassignment_candidates(target: BoardItem, advocate_id: str, colleagues: list[Colleague], travel: TravelMatrix,
                            *, prior_appearances: dict[tuple[str, str], int] | None = None,
                            on_vakalatnama: dict[tuple[str, str], bool] | None = None) -> list[dict]:
    """Free, enrolled colleagues of adequate seniority, those who appeared in the matter first."""
    prior_appearances = prior_appearances or {}
    on_vakalatnama = on_vakalatnama or {}
    need = required_seniority(target.segment)
    found = []
    for c in colleagues:
        if c.user_id == advocate_id or not c.enrolled or c.role == "paralegal" or c.seniority < need:
            continue
        if not is_free(c, target, travel):
            continue
        key = (target.court_case_id or "", c.user_id)
        vakalat = on_vakalatnama.get(key)
        found.append({
            "user_id": c.user_id, "name": c.name, "seniority": c.seniority, "enrolment_no": c.enrolment_no,
            "prior_appearances": prior_appearances.get(key, 0),
            "on_vakalatnama": vakalat,
            "memo_of_appearance_needed": not vakalat,
        })
    found.sort(key=lambda c: (-c["prior_appearances"], not c["on_vakalatnama"], -c["seniority"], c["name"]))
    return found


def resolve(advocate_id: str, conflicts: list[tuple[BoardItem, BoardItem, str]], colleagues: list[Colleague],
            travel: TravelMatrix, **ranking) -> list[dict]:
    """Suggestions for each conflicted item: reassignment first, the pass-over note only if nobody is free."""
    suggestions, seen = [], set()
    for item, other, reason in conflicts:
        if item.key in seen:
            continue
        seen.add(item.key)
        courts = item.court_code != other.court_code
        candidates = reassignment_candidates(item, advocate_id, colleagues, travel, **ranking)
        suggestions.append({
            "item_key": item.key,
            "item_label": item.label(courts),
            "reason": reason,
            "candidates": candidates,
            "pass_over_note": None if candidates else PASS_OVER_NOTE.format(item=item.label(courts), other=other.label(courts)),
        })
    return suggestions


def amber_opted_in(prefs: dict | None, list_date: date) -> bool:
    if not prefs:
        return False
    days = {str(d)[:10] for d in (prefs.get("amber_as_clash_dates") or [])}
    return bool(prefs.get("amber_as_clash")) or list_date.isoformat() in days


def advocate_morning(advocate_id: str, name: str, items: list[BoardItem], *, colleagues: list[Colleague],
                     travel: TravelMatrix, prefs: dict | None, list_date: date, **ranking) -> dict:
    """One advocate's strip: items in time order, red overlaps, one amber notice, suggestions."""
    items = sorted(items, key=lambda i: (i.busy_span()[0], i.court_code, i.courtroom, i.position or 0))
    red, amber = classify(items, travel)
    opted_in = amber_opted_in(prefs, list_date)
    conflicts = [(c.a, c.b, "overlap") for c in red] + [(c.b, c.a, "overlap") for c in red]
    if opted_in:
        conflicts += [(c.a, c.b, "possible_clash") for c in amber] + [(c.b, c.a, "possible_clash") for c in amber]
    strip = []
    previous = None
    for item in items:
        row = item.as_dict()
        row["travel_from_previous"] = None
        if previous is not None and previous.room != item.room:
            row["travel_from_previous"] = travel.minutes(previous.complex, item.complex)[0]
        strip.append(row)
        previous = item
    return {
        "advocate_id": advocate_id,
        "name": name,
        "items": strip,
        "clashes": [c.as_dict() for c in red],
        "amber": amber_notice(amber, opted_in),
        "suggestions": resolve(advocate_id, conflicts, colleagues, travel, **ranking) if conflicts else [],
    }


# ----------------------------------------------------------------------------- database: taps


def _single(rows: list[dict]) -> dict | None:
    return rows[0] if rows else None


def current_period(db, court_code: str, courtroom: str, bench_key: str | None, bench_label: str | None,
                   list_date: date) -> str | None:
    """The roster period for this bench in this courtroom, starting a new one when the bench changed."""
    if not bench_key:
        return None
    rows = (db.table("bench_rosters").select("*").eq("court_code", court_code).eq("courtroom", courtroom)
            .lte("started_on", list_date.isoformat()).order("started_on", desc=True).limit(1).execute().data)
    latest = _single(rows)
    if latest and latest["bench_key"] == bench_key:
        return latest["id"]
    if latest and str(latest["started_on"])[:10] == list_date.isoformat():
        return None  # two benches in one courtroom on one day: no period for the second
    row = {"court_code": court_code, "courtroom": courtroom, "bench_key": bench_key, "bench_label": bench_label,
           "started_on": list_date.isoformat()}
    return db.table("bench_rosters").insert(row).execute().data[0]["id"]


def _item_position(db, item: dict) -> int | None:
    if item.get("position") is not None:
        return int(item["position"])
    if (item.get("status") or "listed") != "listed":
        return None
    if not item.get("courtroom"):
        return None
    siblings = (db.table("cause_list_items").select("id, item_no, connected_to, status, seq")
                .eq("cause_list_id", item["cause_list_id"]).eq("courtroom", item["courtroom"]).execute().data)
    return assign_positions(printed_order(siblings)).get(item["id"])


def _profile_for(db, court_code: str) -> CourtProfile:
    row = _single(db.table("courts").select("code, name, complex, timings").eq("code", court_code).limit(1).execute().data)
    return court_profile(court_code, row)


def build_called_row(*, item: dict, position: int, at_minute: float, timings: Timings, assembled_minute: float | None) -> dict:
    """The pace observation a 'called' tap stores."""
    start = day_start(timings, assembled_minute)
    elapsed = elapsed_sitting(start, at_minute, timings)
    return {"position": position, "elapsed_sitting_min": round(elapsed, 2), "pace": round(pace(elapsed, position), 4),
            "segment": item.get("segment"), "bench_key": item.get("bench_key")}


def record_tap(db, *, user_id: str, kind: str, at: datetime, item_id: str | None = None, court_code: str | None = None,
               courtroom: str | None = None, list_date: date | None = None, position: int | None = None,
               court_case_id: str | None = None, appeared_by: str | None = None) -> dict:
    """Log a tap through the user's client (RLS): assembled, called (first call kept) or rose."""
    if kind not in TAP_KINDS:
        raise ScheduleError("tap_kind must be assembled, called or rose")
    item = None
    if item_id:
        item = _single(db.table("cause_list_items").select("*").eq("id", item_id).limit(1).execute().data)
        if item is None:
            raise ScheduleError("Cause list item not found")
        if not item.get("courtroom"):
            raise ScheduleError("This item's courtroom is not allotted yet")
        court_code, courtroom, list_date = item["court_code"], str(item["courtroom"]), _as_date(item["list_date"])
    if not (court_code and courtroom and list_date):
        raise ScheduleError("Give the cause list item, or the court, courtroom and date")
    row = {"logged_by": user_id, "court_code": court_code, "courtroom": courtroom, "list_date": list_date.isoformat(),
           "tap_kind": kind, "tapped_at": at.isoformat(), "item_id": item_id, "court_case_id": court_case_id,
           "appeared_by": appeared_by}
    if kind == "called":
        if item is None:
            raise ScheduleError("A 'called' tap needs the cause list item")
        item_position = _item_position(db, item)
        if item_position is None:
            raise ScheduleError("This item is not on the day's list (deleted or not to be taken up)")
        existing = _single(db.table("appearance_logs").select("*").eq("item_id", item_id).eq("tap_kind", "called").limit(1).execute().data)
        if existing:
            return {**existing, "already_logged": True}  # a pass-over and recall keeps the first call
        profile = _profile_for(db, court_code)
        if profile.timings is None:
            raise ScheduleError("This court's sitting hours are not recorded, so the call can't be timed")
        assembled = _single(db.table("appearance_logs").select("tapped_at").eq("court_code", court_code)
                            .eq("courtroom", courtroom).eq("list_date", list_date.isoformat()).eq("tap_kind", "assembled")
                            .limit(1).execute().data)
        assembled_minute = ist_minutes(datetime.fromisoformat(assembled["tapped_at"])) if assembled else None
        row.update(build_called_row(item=item, position=item_position, at_minute=ist_minutes(at), timings=profile.timings,
                                    assembled_minute=assembled_minute))
        row["roster_period_id"] = current_period(db, court_code, courtroom, item.get("bench_key"), item.get("bench_label"), list_date)
    else:
        existing = _single(db.table("appearance_logs").select("*").eq("court_code", court_code).eq("courtroom", courtroom)
                           .eq("list_date", list_date.isoformat()).eq("tap_kind", kind).limit(1).execute().data)
        if existing:
            return {**existing, "already_logged": True}
        if kind == "rose":
            reached = position if position is not None else (_item_position(db, item) if item else None)
            if reached is None:
                raise ScheduleError("Say which item the court rose at")
            row["position"] = int(reached)
        header = item or _room_header(db, court_code, courtroom, list_date)
        row["bench_key"] = header.get("bench_key")
        row["roster_period_id"] = current_period(db, court_code, courtroom, header.get("bench_key"), header.get("bench_label"), list_date)
    return {**db.table("appearance_logs").insert(row).execute().data[0], "already_logged": False}


def _room_header(db, court_code: str, courtroom: str, list_date: date) -> dict:
    """The bench sitting in a courtroom on a day, from that day's cause list ({} when unknown)."""
    rows = (db.table("cause_list_items").select("bench_key, bench_label").eq("court_code", court_code).eq("courtroom", courtroom)
            .eq("list_date", list_date.isoformat()).limit(1).execute().data)
    return rows[0] if rows else {}


# ----------------------------------------------------------------------------- database: the board

BOARD_MATCH_TYPES = ("exact", "probable")


def _in_chunks(query_for, ids: list[str], size: int = 150) -> list[dict]:
    rows = []
    ids = list(dict.fromkeys(i for i in ids if i))
    for i in range(0, len(ids), size):
        rows += query_for(ids[i : i + size]).execute().data
    return rows


def load_board(db, list_date: date, *, org_id: str) -> dict:
    """Everything the board needs for one date, read through the caller's client (RLS)."""
    matches = [m for m in db.table("listing_matches").select("*").eq("list_date", list_date.isoformat()).neq("state", "dismissed")
               .execute().data
               if m.get("match_type") in BOARD_MATCH_TYPES or m.get("state") == "confirmed"]
    items = _in_chunks(lambda ids: db.table("cause_list_items").select("*").in_("id", ids).eq("list_date", list_date.isoformat()),
                       [m["item_id"] for m in matches])
    lists = _in_chunks(lambda ids: db.table("cause_lists").select("id, superseded_by").in_("id", ids),
                       [i.get("cause_list_id") for i in items])
    superseded = {c["id"] for c in lists if c.get("superseded_by")}
    items = [i for i in items if i.get("cause_list_id") not in superseded]
    item_ids = {i["id"] for i in items}
    matches = [m for m in matches if m["item_id"] in item_ids]
    for item in items:
        if item.get("position") is None:
            item["position"] = _item_position(db, item)
    case_ids = [m.get("court_case_id") for m in matches]
    cases = _in_chunks(lambda ids: db.table("court_cases").select("id, title, user_id, court_name").in_("id", ids), case_ids)
    codes = sorted({i["court_code"] for i in items})
    courts = _in_chunks(lambda ids: db.table("courts").select("code, name, complex, timings").in_("code", ids), codes)
    since = (list_date - timedelta(days=HISTORY_DAYS)).isoformat()
    logs = _in_chunks(lambda ids: db.table("appearance_logs").select("*").in_("court_code", ids)
                      .gte("list_date", since).lte("list_date", list_date.isoformat()), codes)
    periods = _in_chunks(lambda ids: db.table("bench_rosters").select("*").in_("court_code", ids), codes)
    members = db.table("organization_members").select("user_id, role").eq("org_id", org_id).execute().data
    users = _in_chunks(lambda ids: db.table("users").select("id, full_name, email").in_("id", ids), [m["user_id"] for m in members])
    prefs = db.table("advocate_clash_prefs").select("*").execute().data
    travel = db.table("complex_travel_times").select("*").execute().data
    counsel = _in_chunks(lambda ids: db.table("case_counsel").select("court_case_id, user_id, on_vakalatnama").in_("court_case_id", ids), case_ids)
    past_calls = _in_chunks(lambda ids: db.table("appearance_logs").select("court_case_id, appeared_by").eq("tap_kind", "called")
                            .in_("court_case_id", ids), case_ids)
    roster = db.table("advocate_aliases").select("user_id, enrolment_no").execute().data
    return {"matches": matches, "items": items, "cases": cases, "courts": courts, "logs": logs, "periods": periods,
            "members": members, "users": users, "prefs": prefs, "travel": travel, "counsel": counsel, "past_calls": past_calls,
            "roster": roster}


def build_board(data: dict, list_date: date) -> dict:
    """The clash board for a date from loaded rows (see load_board). Pure: tests feed it directly."""
    items = {i["id"]: i for i in data["items"]}
    cases = {c["id"]: c for c in data["cases"]}
    court_rows = {r["code"]: r for r in data["courts"]}
    profiles = {code: court_profile(code, court_rows.get(code)) for code in {i["court_code"] for i in items.values()}}
    logs = data["logs"]
    observations = [Observation.from_row(r) for r in logs
                    if r["tap_kind"] == "called" and r.get("pace") is not None and _as_date(r["list_date"]) < list_date]
    periods = [Period.from_row(r) for r in data["periods"]]
    assembled = {(r["court_code"], str(r["courtroom"])): ist_minutes(datetime.fromisoformat(str(r["tapped_at"])))
                 for r in logs if r["tap_kind"] == "assembled" and _as_date(r["list_date"]) == list_date}
    rose = [r for r in logs if r["tap_kind"] == "rose" and r.get("position") is not None and _as_date(r["list_date"]) < list_date]

    board_items: dict[str, list[BoardItem]] = {}
    for m in data["matches"]:
        item = items.get(m["item_id"])
        case = cases.get(m.get("court_case_id")) or {}
        advocate = m.get("appearing_advocate_id") or case.get("user_id")
        if item is None or not advocate:
            continue
        profile = profiles[item["court_code"]]
        courtroom = str(item["courtroom"]) if item.get("courtroom") else UNALLOTTED
        start = assembled.get((item["court_code"], courtroom))
        if courtroom == UNALLOTTED:  # advance lists: no courtroom yet, so no clash either
            window = Window("no_courtroom", label="courtroom not yet allotted")
        else:
            window = estimate_window(
                court_code=item["court_code"], courtroom=courtroom, bench_key=item.get("bench_key"),
                segment=item.get("segment"), position=item.get("position"), list_date=list_date, timings=profile.timings,
                start=start, periods=periods, observations=observations, bench_label=item.get("bench_label"),
            )
        current_id = (weigh_observations(item["court_code"], courtroom, item["bench_key"], list_date, periods, []).current_period_id
                      if item.get("bench_key") else None)
        rose_positions = [int(r["position"]) for r in rose if current_id and r.get("roster_period_id") == current_id]
        board_items.setdefault(advocate, []).append(BoardItem(
            key=m["id"], advocate_id=advocate, court_code=item["court_code"], courtroom=courtroom,
            item_no=str(item.get("item_no")), position=item.get("position"), window=window, complex=profile.complex,
            segment=item.get("segment"), bench_key=item.get("bench_key"), bench_label=item.get("bench_label"),
            list_type=item.get("list_type"), court_case_id=m.get("court_case_id"), case_title=case.get("title"),
            court_name=profile.name, timings=profile.timings, start=start,
            reach=reach_frequency(item.get("position"), rose_positions), coverage=profile.coverage, item_id=item["id"],
        ))

    names = {u["id"]: u.get("full_name") or u.get("email") or "Member" for u in data["users"]}
    prefs = {p["user_id"]: p for p in data["prefs"]}
    # The firm's advocate roster (P05's advocate_aliases): once the firm keeps one, only advocates
    # on it stand in as proxies.
    roster: dict[str, str | None] = {}
    for r in data.get("roster") or []:
        roster[r["user_id"]] = roster.get(r["user_id"]) or r.get("enrolment_no")
    colleagues = []
    for member in data["members"]:
        uid = member["user_id"]
        p = prefs.get(uid) or {}
        colleagues.append(Colleague(
            user_id=uid, name=names.get(uid, "Member"), role=member["role"],
            seniority=p.get("seniority") or SENIORITY_BY_ROLE.get(member["role"], 0),
            enrolled=p.get("enrolled", True) is not False and (not roster or uid in roster),
            items=board_items.get(uid, []), enrolment_no=roster.get(uid),
        ))
    prior: dict[tuple[str, str], int] = {}
    for r in data["past_calls"]:
        if r.get("court_case_id") and r.get("appeared_by"):
            key = (r["court_case_id"], r["appeared_by"])
            prior[key] = prior.get(key, 0) + 1
    vakalat = {(r["court_case_id"], r["user_id"]): bool(r.get("on_vakalatnama")) for r in data["counsel"]}
    travel = TravelMatrix(data["travel"])
    advocates = [
        advocate_morning(uid, names.get(uid, "Member"), its, colleagues=colleagues, travel=travel, prefs=prefs.get(uid),
                         list_date=list_date, prior_appearances=prior, on_vakalatnama=vakalat)
        for uid, its in board_items.items()
    ]
    advocates.sort(key=lambda a: (-(len(a["clashes"])), a["amber"] is None, a["name"]))
    return {"date": list_date.isoformat(), "advocates": advocates, "notes": [SAFEGUARD_NOTE]}
