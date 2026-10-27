"""Reference weighted quantile and reach window for tests/test_schedule.py.

Written independently of app/services/schedule_service.py, straight from the P04 definition:
sort by value, accumulate normalised weight, take the first value whose cumulative weight >= q.
No interpolation.
"""

from fractions import Fraction


def weighted_quantile(values, weights, q):
    pairs = sorted(zip(values, weights))
    total = sum(Fraction(w).limit_denominator(10**6) for _, w in pairs)
    running = Fraction(0)
    target = Fraction(q).limit_denominator(10**6)
    for value, weight in pairs:
        running += Fraction(weight).limit_denominator(10**6)
        if running / total >= target:
            return value
    return pairs[-1][0]


def window_minutes(start, position, q25, q75, lunch_start, lunch_end):
    """Clock minutes for [start + q25 x max(P,3), start + q75 x max(P,3)] sitting minutes."""
    out = []
    for q in (q25, q75):
        sitting = q * max(position, 3)
        clock = start + sitting
        if clock > lunch_start and start < lunch_start:
            clock += lunch_end - lunch_start
        out.append(clock)
    return tuple(out)
