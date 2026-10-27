"""P04: clash board and reach estimates (app/services/schedule_service.py)."""

import json
import random
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import schedule_service as ss
from app.services.schedule_service import (
    BoardItem,
    Colleague,
    Observation,
    Period,
    Timings,
    TravelMatrix,
    Window,
)
from tests.conftest import ORG_ID
from tests.reference.weighted_quantile import weighted_quantile as ref_quantile
from tests.reference.weighted_quantile import window_minutes as ref_window

DLHC = Timings.parse({"sitting_start": "10:30", "lunch_start": "13:00", "lunch_end": "14:15", "rising": "16:30"})
DAY = date(2026, 11, 2)
CASE_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
PERIOD = Period("p1", "DLHC", "12", "J-A", date(2026, 10, 1), "Justice A")


def obs(position, pace_value, *, bench="J-A", period="p1", segment="regular", room="12", court="DLHC"):
    return Observation(court, room, bench, period, segment, position, pace_value, DAY - timedelta(days=1))


def window(position, observations, *, periods=(PERIOD,), segment="regular", bench="J-A", room="12", start=None,
           timings=DLHC, bench_label="Justice A"):
    return ss.estimate_window(court_code="DLHC", courtroom=room, bench_key=bench, segment=segment, position=position,
                              list_date=DAY, timings=timings, start=start, periods=list(periods), observations=observations,
                              bench_label=bench_label)


# ============================================================================ estimator


def test_mixed_item_numbers():
    """40 calls at mixed positions give the reference implementation's window to the minute."""
    positions = [2, 3, 5, 7, 12, 19, 25, 33, 41]
    calls = []
    for i in range(40):
        p = positions[i % len(positions)]
        elapsed = 3.5 * p + (i * 7) % 11 - 4 + (12 if i % 9 == 0 else 0)  # known, uneven elapsed times
        calls.append((p, max(elapsed, 1.0)))
    paces = [e / max(p, 3) for p, e in calls]
    observations = [obs(p, r) for (p, _), r in zip(calls, paces)]

    w = window(8, observations)
    q25, q75 = ref_quantile(paces, [1] * 40, 0.25), ref_quantile(paces, [1] * 40, 0.75)
    lo, hi = ref_window(630, 8, q25, q75, 780, 855)
    assert w.state == "estimated"
    assert (w.q25, w.q75) == (q25, q75)
    assert ss.hhmm(w.lo) == ss.hhmm(lo) and ss.hhmm(w.hi) == ss.hhmm(hi)
    assert abs(w.lo - lo) < 1e-9 and abs(w.hi - hi) < 1e-9
    assert "pace from 40 calls at items 2-41, this roster" in w.label

    # With unequal weights (carried periods) the service still agrees with the reference.
    weights = [1.0 if i % 3 else 0.5 for i in range(40)]
    pairs = list(zip(paces, weights))
    for q in (0.25, 0.5, 0.75):
        assert ss.weighted_quantile(pairs, q) == ref_quantile(paces, weights, q)


def test_reach_window_positions():
    """100 calls over positions 1-60 recover the generating quantiles within 2%."""
    rng = random.Random(4)
    paces = [2 + 4 * (i + 0.5) / 100 for i in range(100)]  # stratified draw from uniform(2, 6): q25 = 3, q75 = 5
    rng.shuffle(paces)
    observations = []
    for r in paces:
        p = rng.randint(1, 60)
        elapsed = r * max(p, 3)
        observations.append(obs(p, ss.pace(elapsed, p)))
    w = window(30, observations)
    assert abs(w.q25 - 3.0) / 3.0 < 0.02
    assert abs(w.q75 - 5.0) / 5.0 < 0.02
    assert w.lo == pytest.approx(630 + w.q25 * 30)  # before lunch: start + q x 30 sitting minutes
    assert w.hi == pytest.approx(630 + w.q75 * 30 + (75 if w.q75 * 30 > 150 else 0))  # shifted by lunch past 13:00


def test_position_floor():
    assert ss.pace(4, 1) == pytest.approx(4 / 3)
    row = ss.build_called_row(item={"segment": "fresh", "bench_key": "J-A"}, position=1, at_minute=634, timings=DLHC,
                              assembled_minute=None)
    assert row["elapsed_sitting_min"] == 4 and row["pace"] == pytest.approx(4 / 3, abs=1e-4)


def test_connected_matters_one_call():
    items = [{"id": f"i{n}", "item_no": str(n), "status": "listed"} for n in range(1, 14)]
    for n in range(9, 13):
        items[n - 1]["connected_to"] = "i8"
    positions = ss.assign_positions(items)
    assert positions["i8"] == 8 and all(positions[f"i{n}"] == 8 for n in range(9, 13))
    assert positions["i13"] == 9
    # Connected by item number, and deleted / not-taken-up items skipped.
    items = [{"id": "a", "item_no": "1"}, {"id": "b", "item_no": "2", "status": "deleted"},
             {"id": "c", "item_no": "3"}, {"id": "d", "item_no": "4", "connected_to": "3"},
             {"id": "e", "item_no": "5", "status": "not_to_be_taken_up"}, {"id": "f", "item_no": "6"}]
    assert ss.assign_positions(ss.printed_order(items)) == {"a": 1, "b": None, "c": 2, "d": 2, "e": None, "f": 3}


def test_lunch_excluded():
    assert ss.elapsed_sitting(630, 14 * 60 + 30, DLHC) == 165  # 240 minutes less the 75-minute lunch
    assert ss.elapsed_sitting(630, 12 * 60, DLHC) == 90
    w = window(16, [obs(10, 10.0)] * 20)  # 160 sitting minutes crosses 13:00
    assert ss.hhmm(w.lo) == "14:25" and ss.hhmm(w.hi) == "14:25"
    w = window(14, [obs(10, 10.0)] * 20)  # 140 sitting minutes: before lunch
    assert ss.hhmm(w.lo) == "12:50"


def test_rising_cap():
    beyond = window(40, [obs(10, 10.0)] * 20)  # 400 sitting minutes; the day has 285
    assert beyond.state == "beyond_rising" and beyond.label == "may not be reached today"
    partly = window(28, [obs(10, 9.0)] * 10 + [obs(10, 11.0)] * 10)  # lo 252, hi 308 sitting minutes
    assert partly.usable and partly.capped and ss.hhmm(partly.hi) == "16:30"

    a = item("a", "12", beyond, complex_="X")
    b = item("b", "31", Window("estimated", 600, 1000, "all day"), complex_="X")
    red, amber = ss.classify([a, b], TravelMatrix())
    assert red == [] and amber == []  # never red, and not a no-data notice either


def test_pooled_fallback():
    eight = [obs(5, 4.0)] * 8
    w = window(10, eight + [obs(5, 5.0, segment="fresh")] * 22)
    assert w.state == "pooled" and "pooled across list types" in w.label and w.weight == 30
    w = window(10, eight + [obs(5, 5.0, segment="fresh")] * 4)
    assert w.state == "not_enough_data" and "(12 of 20)" in w.label and not w.usable


def test_roster_change_resets_window():
    history = [obs(5, 4.0)] * 25
    assert window(10, history).usable
    # Justice B sits in the courtroom today: Justice A's calls don't count for B.
    w = window(10, history, bench="J-B", bench_label="Justice B")
    assert w.state == "not_enough_data" and "new bench since 2 Nov" in w.label and "(0 of 20)" in w.label
    # Once B's period exists (from 14 Oct), only B's calls count.
    periods = [PERIOD, Period("p2", "DLHC", "12", "J-B", date(2026, 10, 14), "Justice B")]
    w = window(10, history + [obs(5, 4.0, bench="J-B", period="p2")] * 9, periods=periods, bench="J-B")
    assert w.label == "new bench since 14 Oct: not enough data (9 of 20)"


def test_older_roster_downweighted():
    periods = [Period("p0", "DLHC", "12", "J-A", date(2026, 8, 1)), PERIOD]
    w = window(10, [obs(5, 4.0, period="p0")] * 30 + [obs(5, 4.0)] * 10, periods=periods)
    assert w.weight == 25 and w.usable and w.carried  # 10 + 0.5 x 30
    assert "carried from earlier rosters" in w.label
    # Two periods back: 10 + 0.25 x 30 = 17.5, below the threshold.
    periods = [Period("p0", "DLHC", "12", "J-A", date(2026, 8, 1)), Period("pB", "DLHC", "12", "J-B", date(2026, 9, 1)),
               PERIOD]
    w = window(10, [obs(5, 4.0, period="p0")] * 30 + [obs(5, 4.0)] * 10, periods=periods)
    assert w.state == "not_enough_data" and "(17.5 of 20)" in w.label


def test_unparsed_header():
    unknown = [obs(5, 4.0, bench=None, period=None)] * 30
    w = window(10, unknown, bench=None)
    assert w.state == "bench_unknown" and "bench unknown" in w.label
    # Calls logged under an unparsed header count toward no bench.
    w = window(10, unknown)
    assert w.state == "not_enough_data" and "(0 of 20)" in w.label


def test_same_judge_from_another_courtroom_is_only_a_hint():
    elsewhere = [obs(5, 4.0, room="7", period="p7")] * 25
    periods = [PERIOD, Period("p7", "DLHC", "7", "J-A", date(2026, 9, 1))]
    w = window(10, elsewhere, periods=periods)
    assert w.state == "hint" and "low confidence" in w.label and not w.usable


def test_reach_frequency_is_display_only():
    assert ss.reach_frequency(8, [10, 12, 6, 8, 20, 30, 9, 5, 15]) == {
        "reached": 7, "sittings": 9, "text": "reached in 7 of 9 sittings"}
    assert ss.reach_frequency(8, []) is None


def test_court_profile_source_of_truth():
    row = {"code": "DLHC", "timings": {"sitting_start": "10:00", "lunch_start": "13:00", "lunch_end": "14:00", "rising": "16:00"}}
    assert ss.court_profile("DLHC", row).timings.sitting_start == 600
    assert ss.court_profile("DLHC", row).timings_source == "courts"
    fallback = ss.court_profile("DLHC", {"code": "DLHC", "timings": {}})
    assert fallback.timings == DLHC and fallback.timings_source == "default_profile"
    district = ss.court_profile("MH-PUNE-DC", None)
    assert district.timings is None and district.coverage == "manual_or_ecourtsindia_api"
    assert window(5, [obs(5, 4.0)] * 25, timings=None).state == "no_timings"


# ============================================================================ clashes and resolution


def item(key, room, w, *, complex_="Delhi HC", advocate="adv", court="DLHC", segment="fresh", case=None, item_no=None):
    return BoardItem(key=key, advocate_id=advocate, court_code=court, courtroom=room, item_no=item_no or key, position=5,
                     window=w, complex=complex_, segment=segment, court_case_id=case or f"case-{key}", timings=DLHC)


def est(lo, hi):
    return Window("estimated", ss.to_minutes(lo), ss.to_minutes(hi), "est")


NO_DATA = Window("not_enough_data", label="not enough data")


def test_clash_detection():
    travel = TravelMatrix([{"from_complex": "Saket", "to_complex": "Delhi HC", "minutes": 25}])
    a = item("8", "12", est("11:15", "12:30"))
    b = item("5", "31", est("12:40", "13:00"), complex_="Saket")
    red, amber = ss.classify([a, b], travel)
    assert [c.state for c in red] == ["overlap"] and amber == []
    assert red[0].text() == "Court 12 item 8 (11:15-12:30) and Court 31 item 5 (12:40-13:00) overlap; 25 min apart"
    c = item("5", "31", est("13:00", "13:20"), complex_="Saket")
    assert ss.classify([a, c], travel) == ([], [])
    d = item("5", "31", NO_DATA, complex_="Saket")
    red, amber = ss.classify([a, d], travel)
    assert red == [] and [x.state for x in amber] == ["possible_no_data"]


def test_same_courtroom_no_clash():
    for wa, wb in [(est("11:00", "12:00"), est("11:10", "11:50")), (NO_DATA, NO_DATA), (est("11:00", "12:00"), NO_DATA)]:
        assert ss.classify([item("1", "12", wa), item("2", "12", wb)], TravelMatrix()) == ([], [])


def colleagues(*extra):
    return [Colleague("adv", "Asha", "partner", 3), *extra]


def test_reassignment_first():
    a, b = item("8", "12", est("11:15", "12:30")), item("5", "31", est("11:40", "12:10"))
    free = Colleague("ravi", "Ravi", "associate", 2)
    strip = ss.advocate_morning("adv", "Asha", [a, b], colleagues=colleagues(free), travel=TravelMatrix(), prefs=None, list_date=DAY)
    assert len(strip["clashes"]) == 1
    assert all(s["candidates"][0]["user_id"] == "ravi" and s["pass_over_note"] is None for s in strip["suggestions"])
    # Nobody free: only then the pass-over note, and it never asks for an adjournment.
    busy = Colleague("ravi", "Ravi", "associate", 2, items=[item("x", "40", est("11:00", "13:00"), advocate="ravi")])
    strip = ss.advocate_morning("adv", "Asha", [a, b], colleagues=colleagues(busy), travel=TravelMatrix(), prefs=None, list_date=DAY)
    notes = [s["pass_over_note"] for s in strip["suggestions"]]
    assert all(n and "pass it over or keep it back" in n and "adjourn" not in n.lower() for n in notes)


def test_reassignment_ranking():
    target = item("8", "12", est("11:15", "12:30"), segment="regular", case="case-1")
    team = [
        Colleague("p1", "Zoya", "partner", 3),
        Colleague("a1", "Bina", "associate", 2),
        Colleague("a2", "Chetan", "associate", 2),
        Colleague("j1", "Dev", "associate", 1),  # junior: not for the regular (final hearing) board
        Colleague("para", "Esha", "paralegal", 0),
        Colleague("off", "Farah", "associate", 2, enrolled=False),
        Colleague("same", "Gopal", "associate", 2, items=[item("y", "3", NO_DATA, advocate="same")]),  # same complex: free
        Colleague("far", "Hari", "associate", 2, items=[item("z", "3", NO_DATA, advocate="far", complex_="Rohini")]),
    ]
    ranked = ss.reassignment_candidates(target, "adv", team, TravelMatrix(),
                                        prior_appearances={("case-1", "a2"): 3, ("case-1", "a1"): 1},
                                        on_vakalatnama={("case-1", "a1"): True})
    assert [c["user_id"] for c in ranked] == ["a2", "a1", "p1", "same"]
    assert ranked[0]["memo_of_appearance_needed"] and not ranked[1]["memo_of_appearance_needed"]


def test_amber_opt_in():
    a, b = item("8", "12", est("11:15", "12:30")), item("5", "31", NO_DATA, complex_="Saket")
    team = colleagues(Colleague("ravi", "Ravi", "associate", 2))
    off = ss.advocate_morning("adv", "Asha", [a, b], colleagues=team, travel=TravelMatrix(), prefs=None, list_date=DAY)
    assert off["clashes"] == [] and off["suggestions"] == []
    assert off["amber"]["text"] == "1 courtroom without reach data today" and not off["amber"]["treated_as_clash"]
    for prefs in ({"amber_as_clash_dates": [DAY.isoformat()]}, {"amber_as_clash": True}):
        on = ss.advocate_morning("adv", "Asha", [a, b], colleagues=team, travel=TravelMatrix(), prefs=prefs, list_date=DAY)
        assert on["amber"]["treated_as_clash"] and on["suggestions"] and on["suggestions"][0]["reason"] == "possible_clash"
    other_day = {"amber_as_clash_dates": [(DAY + timedelta(days=1)).isoformat()]}
    assert ss.advocate_morning("adv", "Asha", [a, b], colleagues=team, travel=TravelMatrix(), prefs=other_day,
                               list_date=DAY)["suggestions"] == []


def test_adjourn_never_suggested_in_200_random_scenarios():
    rng = random.Random(11)
    complexes = ["Delhi HC", "Saket", "Tis Hazari"]
    travel = TravelMatrix([{"from_complex": "Delhi HC", "to_complex": "Saket", "minutes": 35},
                           {"from_complex": "Saket", "to_complex": "Tis Hazari", "minutes": 45}])
    for _ in range(200):
        def random_window():
            if rng.random() < 0.35:
                return Window(rng.choice(["not_enough_data", "bench_unknown", "hint", "beyond_rising"]))
            lo = rng.randint(630, 900)
            return Window("estimated", lo, lo + rng.randint(5, 90))

        items = [item(str(i), str(rng.randint(1, 6)), random_window(), complex_=rng.choice(complexes)) for i in range(rng.randint(2, 6))]
        team = [Colleague(f"c{i}", f"C{i}", rng.choice(["partner", "associate", "paralegal"]), rng.randint(0, 3),
                          items=[item(f"c{i}-{j}", str(rng.randint(1, 6)), random_window(), advocate=f"c{i}") for j in range(rng.randint(0, 3))])
                for i in range(rng.randint(0, 4))]
        prefs = {"amber_as_clash": rng.random() < 0.5}
        strip = ss.advocate_morning("adv", "Asha", items, colleagues=team, travel=travel, prefs=prefs, list_date=DAY)
        assert "adjourn" not in json.dumps(strip).lower()


def test_no_ai_in_schedule(monkeypatch):
    from app.services import anthropic_service

    calls = []
    for name in ("_aparse", "_parse_sync", "_get_client", "_get_sync_client"):
        monkeypatch.setattr(anthropic_service, name, lambda *a, _n=name, **k: calls.append(_n))
    simulate(days=3)
    assert calls == []
    source = open(ss.__file__, encoding="utf-8").read()
    assert "anthropic" not in source


def board_data(roster=()):
    """Advocate adv has items in Courts 12 and 31 (same complex) that overlap; two colleagues are free."""
    timings = {"sitting_start": "10:30", "lunch_start": "13:00", "lunch_end": "14:15", "rising": "16:30"}
    logs = [{"court_code": "DLHC", "courtroom": room, "list_date": "2026-10-30", "tap_kind": "called", "bench_key": f"J-{room}",
             "roster_period_id": f"p{room}", "segment": "regular", "position": 5, "pace": 4.0} for room in ("12", "31") for _ in range(20)]
    items = [{"id": f"i{room}", "court_code": "DLHC", "courtroom": room, "list_date": DAY.isoformat(), "bench_key": f"J-{room}",
              "segment": "fresh", "item_no": "8", "position": 8, "status": "listed"} for room in ("12", "31")]
    items.append({"id": "iadv", "court_code": "DLHC", "courtroom": None, "list_date": DAY.isoformat(), "bench_key": None,
                  "segment": "advance", "item_no": "3", "position": 3, "status": "listed", "list_type": "advance"})
    return {
        "items": items,
        "matches": [{"id": f"m{i['id']}", "item_id": i["id"], "court_case_id": "c1", "match_type": "exact", "state": "open",
                     "appearing_advocate_id": "adv"} for i in items],
        "cases": [{"id": "c1", "title": "Matter", "user_id": "adv"}],
        "courts": [{"code": "DLHC", "name": "Delhi HC", "complex": "HC", "timings": timings}],
        "logs": logs,
        "periods": [{"id": f"p{room}", "court_code": "DLHC", "courtroom": room, "bench_key": f"J-{room}", "started_on": "2026-10-01"}
                    for room in ("12", "31")],
        "members": [{"user_id": u, "role": r} for u, r in (("adv", "partner"), ("ravi", "associate"), ("sana", "associate"))],
        "users": [{"id": u, "full_name": u.title()} for u in ("adv", "ravi", "sana")],
        "prefs": [], "travel": [], "counsel": [], "past_calls": [], "roster": list(roster),
    }


def test_proxies_come_from_the_firms_roster_and_unallotted_items_never_clash():
    strip = ss.build_board(board_data(), DAY)["advocates"][0]
    assert len(strip["items"]) == 3 and len(strip["clashes"]) == 1 and strip["amber"] is None
    unallotted = next(i for i in strip["items"] if i["courtroom"] == ss.UNALLOTTED)
    assert unallotted["window"]["state"] == "no_courtroom"
    assert {c["user_id"] for c in strip["suggestions"][0]["candidates"]} == {"ravi", "sana"}
    # Once the firm keeps an advocate roster, only advocates on it are offered.
    strip = ss.build_board(board_data(roster=[{"user_id": "sana", "enrolment_no": "D/1234/2015"}]), DAY)["advocates"][0]
    assert [(c["user_id"], c["enrolment_no"]) for c in strip["suggestions"][0]["candidates"]] == [("sana", "D/1234/2015")]


# ============================================================================ cold start (a synthetic firm)

COURTS = {"TSTA": "Complex A", "TSTB": "Complex B", "TSTC": "Complex C"}
TRAVEL_ROWS = [{"from_complex": "Complex A", "to_complex": "Complex B", "minutes": 25},
               {"from_complex": "Complex A", "to_complex": "Complex C", "minutes": 40},
               {"from_complex": "Complex B", "to_complex": "Complex C", "minutes": 30}]
TIMINGS = {"sitting_start": "10:30", "lunch_start": "13:00", "lunch_end": "14:15", "rising": "16:30"}
LIST_LENGTH = 70
EARLY, CLASH, MIDDLE, LATE = (1, 6), (8, 20), (28, 34), (60, 70)  # position bands of the firm's matters


def sitting_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def run_courtroom_day(rng, firm_positions: set[int], T: Timings):
    """Actual call times (clock minutes) and durations, with non-linear effects the estimator doesn't
    model: late assembly, a long first matter, part-heard blocks, and a judge rising early."""
    assembled = T.sitting_start + rng.uniform(0, 10)
    rising = T.lunch_start if rng.random() < 0.05 else T.rising
    part_heard = rng.randint(5, 50) if rng.random() < 0.1 else None
    sitting, calls = 0.0, {}
    for p in range(1, LIST_LENGTH + 1):
        clock = ss.sitting_to_clock(assembled, sitting, T)
        if clock >= rising:
            break
        if p == 1 and rng.random() < 0.15:
            duration = rng.uniform(20, 35)
        elif p == part_heard:
            duration = rng.uniform(45, 75)
        elif p in firm_positions:
            duration = rng.uniform(6, 15)
        else:
            duration = rng.choice([1, 2, 2, 3, 3, 4, 5, 6, 8])
        calls[p] = (clock, duration)
        sitting += duration
    return assembled, calls


def pick(rng, taken: set[int], lo: int, hi: int) -> int:
    free = [p for p in range(lo, hi + 1) if p not in taken]
    p = rng.choice(free)
    taken.add(p)
    return p


def simulate(days=15, seed=3):
    """A firm of 10 advocates, each with 6 matters in 3 of 12 courtrooms per sitting day. Two
    advocates a day are given genuinely clashing mornings; the others' matters are spread out."""
    rng = random.Random(seed)
    T = Timings.parse(TIMINGS)
    rooms = [(c, str(r)) for c in COURTS for r in range(1, 5)]
    advocates = [f"adv-{i}" for i in range(10)]
    dates = sitting_days(date(2026, 11, 2), days)
    periods = [{"id": f"p-{c}-{r}", "court_code": c, "courtroom": r, "bench_key": f"{c}-{r}-J", "bench_label": f"Justice {c}{r}",
                "started_on": dates[0].isoformat()} for c, r in rooms]
    base = {
        "courts": [{"code": c, "name": c, "complex": cx, "timings": TIMINGS} for c, cx in COURTS.items()],
        "periods": periods, "travel": TRAVEL_ROWS, "prefs": [], "counsel": [], "past_calls": [],
        "members": [{"user_id": a, "role": "associate"} for a in advocates],
        "users": [{"id": a, "full_name": a} for a in advocates],
    }
    logs, days_out = [], []
    for index, day in enumerate(dates):
        taken = {room: set() for room in rooms}
        plan = []  # (advocate, room, position)
        clashers = {advocates[(2 * index) % 10], advocates[(2 * index + 1) % 10]}
        for a, adv in enumerate(advocates):
            # Each courtroom is one advocate's early room, another's middle room and a third's late room.
            r1, r2, r3 = (rooms[(a + index + k) % len(rooms)] for k in (0, 4, 8))
            if adv in clashers:
                p = rng.randint(CLASH[0], CLASH[1] - 4)
                q = p + rng.randint(0, 1)
                plan += [(adv, r1, pick(rng, taken[r1], p, p)), (adv, r1, pick(rng, taken[r1], p + 3, p + 3)),
                         (adv, r2, pick(rng, taken[r2], q, q)), (adv, r2, pick(rng, taken[r2], q + 3, q + 3))]
            else:
                plan += [(adv, r1, pick(rng, taken[r1], *EARLY)), (adv, r1, pick(rng, taken[r1], *EARLY)),
                         (adv, r2, pick(rng, taken[r2], *MIDDLE)), (adv, r2, pick(rng, taken[r2], *MIDDLE))]
            plan += [(adv, r3, pick(rng, taken[r3], *LATE)), (adv, r3, pick(rng, taken[r3], *LATE))]
        truth = {room: run_courtroom_day(rng, taken[room], T) for room in rooms}

        items, matches, cases, actual = [], [], [], {}
        for adv, (court, room), position in plan:
            item_id, match_id, case_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            items.append({"id": item_id, "cause_list_id": f"cl-{court}-{room}-{day}", "court_code": court, "courtroom": room,
                          "list_date": day.isoformat(), "bench_key": f"{court}-{room}-J", "bench_label": f"Justice {court}{room}",
                          "segment": "regular", "list_type": "daily", "item_no": str(position), "position": position,
                          "status": "listed"})
            matches.append({"id": match_id, "item_id": item_id, "court_case_id": case_id, "match_type": "exact",
                            "state": "confirmed", "appearing_advocate_id": adv, "list_date": day.isoformat()})
            cases.append({"id": case_id, "title": f"Matter {position}", "user_id": adv})
            actual[match_id] = truth[(court, room)][1].get(position)
        board = ss.build_board({**base, "items": items, "matches": matches, "cases": cases, "logs": list(logs)}, day)
        days_out.append({"board": board, "actual": actual})

        # The evening's logs: the bench-assembled tap and about 3 of the firm's calls per courtroom.
        for (court, room), (assembled, calls) in truth.items():
            logs.append({"court_code": court, "courtroom": room, "list_date": day.isoformat(), "tap_kind": "assembled",
                         "tapped_at": datetime(day.year, day.month, day.day, int(assembled // 60), int(assembled % 60),
                                               tzinfo=ss.IST).isoformat()})
            reached = [p for p in sorted(taken[(court, room)]) if p in calls]
            for p in rng.sample(reached, min(3, len(reached))):
                elapsed = ss.elapsed_sitting(assembled, calls[p][0], T)
                logs.append({"court_code": court, "courtroom": room, "list_date": day.isoformat(), "tap_kind": "called",
                             "bench_key": f"{court}-{room}-J", "roster_period_id": f"p-{court}-{room}", "segment": "regular",
                             "position": p, "elapsed_sitting_min": elapsed, "pace": ss.pace(elapsed, p)})
    return days_out


def true_overlap(a, b, travel):
    if a is None or b is None:
        return False  # one of them was never reached
    (ta, da), (tb, db) = a, b
    return ta - travel < tb + db and tb < ta + da + travel


def test_cold_start_3_weeks():
    days = simulate()
    first = days[0]["board"]["advocates"]
    assert sum(len(a["clashes"]) for a in first) == 0
    assert all(a["amber"] is not None and isinstance(a["amber"], dict) for a in first)  # one notice per morning
    assert sum(len(a["suggestions"]) for a in first) == 0

    red, true_red = 0, 0
    for day in days[10:]:
        for strip in day["board"]["advocates"]:
            for clash in strip["clashes"]:
                red += 1
                a, b = (day["actual"][k] for k in clash["items"])
                true_red += true_overlap(a, b, clash["travel_minutes"])
    assert red >= 8
    assert true_red / red >= 0.8

    last = days[-1]["board"]["advocates"]
    quiet = sum(1 for a in last if not a["clashes"] and a["amber"] is None)
    assert quiet / len(last) >= 0.7


# ============================================================================ taps and the API


class Query:
    def __init__(self, tables, name):
        self.tables, self.name, self.filters, self.op, self.payload = tables, name, [], "select", None
        self._order, self._limit = None, None

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) == str(val))
        return self

    def neq(self, col, val):
        self.filters.append(lambda r: r.get(col) != val)
        return self

    def in_(self, col, vals):
        vals = {str(v) for v in vals}
        self.filters.append(lambda r: str(r.get(col)) in vals)
        return self

    def gte(self, col, val):
        self.filters.append(lambda r: str(r.get(col) or "") >= str(val))
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: str(r.get(col) or "") <= str(val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def upsert(self, row, on_conflict=""):
        self.op, self.payload, self.keys = "upsert", row, on_conflict.split(",")
        return self

    def update(self, fields):
        self.op, self.payload = "update", fields
        return self

    def execute(self):
        from types import SimpleNamespace

        rows = self.tables.setdefault(self.name, [])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "select":
            if self._order:
                hits = sorted(hits, key=lambda r: str(r.get(self._order[0]) or ""), reverse=self._order[1])
            return SimpleNamespace(data=[dict(r) for r in hits[: self._limit]])
        if self.op == "insert":
            row = {"id": str(uuid.uuid4()), **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.op == "upsert":
            found = next((r for r in rows if all(r.get(k) == self.payload.get(k) for k in self.keys)), None)
            if found:
                found.update(self.payload)
                return SimpleNamespace(data=[dict(found)])
            row = {"id": str(uuid.uuid4()), **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        for r in hits:
            r.update(self.payload)
        return SimpleNamespace(data=[dict(r) for r in hits])


class FakeDB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}

    def table(self, name):
        return Query(self.tables, name)


def at(hh, mm, day=DAY):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=ss.IST)


def list_items(day=DAY, bench="J-A"):
    return [{"id": f"i{n}", "cause_list_id": "cl1", "court_code": "DLHC", "courtroom": "12", "list_date": day.isoformat(),
             "bench_key": bench, "bench_label": "Justice A", "segment": "regular", "item_no": str(n), "position": None,
             "status": "listed"} for n in range(1, 11)]


def test_called_tap_records_pace_and_keeps_the_first_call():
    db = FakeDB(cause_list_items=list_items(), courts=[{"code": "DLHC", "name": "Delhi HC", "complex": "HC", "timings": {}}])
    ss.record_tap(db, user_id="u1", kind="assembled", at=at(10, 40), court_code="DLHC", courtroom="12", list_date=DAY)
    row = ss.record_tap(db, user_id="u1", kind="called", at=at(11, 10), item_id="i8")
    assert row["position"] == 8 and row["elapsed_sitting_min"] == 30 and row["pace"] == pytest.approx(30 / 8)
    assert row["roster_period_id"] and not row["already_logged"]
    again = ss.record_tap(db, user_id="u1", kind="called", at=at(12, 0), item_id="i8")  # pass over and recall
    assert again["already_logged"] and again["elapsed_sitting_min"] == 30
    rose = ss.record_tap(db, user_id="u1", kind="rose", at=at(16, 20), item_id="i10")
    assert rose["position"] == 10 and rose["roster_period_id"] == row["roster_period_id"]
    # A new bench in the courtroom starts a new roster period.
    nxt = DAY + timedelta(days=1)
    db.tables["cause_list_items"] += [{**i, "id": "n" + i["id"], "list_date": nxt.isoformat(), "bench_key": "J-B",
                                       "cause_list_id": "cl2"} for i in list_items()]
    new = ss.record_tap(db, user_id="u1", kind="called", at=at(11, 0, nxt), item_id="ni3")
    assert new["roster_period_id"] != row["roster_period_id"] and len(db.tables["bench_rosters"]) == 2
    with pytest.raises(ss.ScheduleError):
        ss.record_tap(db, user_id="u1", kind="called", at=at(11, 0), court_code="DLHC", courtroom="12", list_date=DAY)


@pytest.fixture
def hearings_client(monkeypatch):
    from app.dependencies.auth import CurrentUser, get_current_user
    from app.routers import hearings

    db = FakeDB(
        cause_list_items=list_items(), courts=[{"code": "DLHC", "name": "Delhi HC", "complex": "HC", "timings": {}}],
        cause_lists=[{"id": "cl1", "superseded_by": None}],
        listing_matches=[{"id": "m1", "item_id": "i8", "court_case_id": CASE_ID, "match_type": "exact", "state": "open",
                          "appearing_advocate_id": None, "ingested_at": DAY.isoformat(), "list_date": DAY.isoformat()}],
        court_cases=[{"id": CASE_ID, "title": "Sharma v. Joshi", "user_id": "owner-1", "court_name": "Delhi HC"}],
        organization_members=[{"org_id": ORG_ID, "user_id": "owner-1", "role": "owner"}],
        users=[{"id": "owner-1", "full_name": "Asha"}],
    )
    monkeypatch.setattr("app.dependencies.org.get_supabase_for_user", lambda *a, **k: db)
    app = FastAPI()
    app.include_router(hearings.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="owner-1", email="a@example.com", access_token="t")
    return TestClient(app), db


def test_hearings_api_board_taps_travel_and_prefs(hearings_client, audit_log):
    client, db = hearings_client
    board = client.get(f"/api/v1/hearings/board?date={DAY.isoformat()}").json()
    strip = board["advocates"][0]
    assert strip["name"] == "Asha" and strip["items"][0]["position"] == 8
    assert strip["items"][0]["window"]["state"] == "not_enough_data"

    response = client.post("/api/v1/hearings/taps", json={"kind": "called", "item_id": "i8", "at": at(11, 0).isoformat()})
    assert response.status_code == 201 and response.json()["pace"] == pytest.approx(30 / 8)
    assert client.post("/api/v1/hearings/taps", json={"kind": "called"}).status_code == 422

    saved = client.put("/api/v1/hearings/travel-times", json={"from_complex": "Saket", "to_complex": "HC", "minutes": 35}).json()
    assert (saved["from_complex"], saved["to_complex"]) == ("HC", "Saket")
    assert client.put("/api/v1/hearings/travel-times", json={"from_complex": "HC", "to_complex": "Saket", "minutes": 40}).json()["minutes"] == 40
    assert len(db.tables["complex_travel_times"]) == 1

    prefs = client.put("/api/v1/hearings/prefs", json={"amber_as_clash_dates": [DAY.isoformat()]}).json()
    assert prefs["amber_as_clash_dates"] == [DAY.isoformat()]
    outcome = client.post("/api/v1/hearings/outcomes", json={"court_case_id": CASE_ID, "hearing_date": "2026-10-20",
                                                             "outcome": "adjourned", "adjourned_at_instance_of": "respondent"})
    assert outcome.status_code == 201
    counts = client.get(f"/api/v1/hearings/outcomes?court_case_id={CASE_ID}").json()
    assert counts["adjournments"]["respondent"] == 1
