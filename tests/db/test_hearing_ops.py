"""Migration 019: hearing operations (P04 clash board, P47 hearing briefs) under RLS."""

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied, sign_up  # noqa: E402


@pytest.fixture(scope="module")
def setup(db, firm):
    org = firm["org"]
    db.execute("""insert into public.courts (code, name, complex, timings) values ('HOPS', 'Test High Court', 'Test complex',
                  '{"sitting_start": "10:30", "lunch_start": "13:00", "lunch_end": "14:15", "rising": "16:30"}')
                  on conflict (code) do nothing""")
    with as_user(db, firm["associate"], org) as conn:
        own = str(conn.execute("insert into public.court_cases (title) values ('Associate v. State') returning id").fetchone()[0])
    with as_user(db, firm["partner"], org) as conn:
        partners = str(conn.execute("insert into public.court_cases (title) values ('Partner v. Union') returning id").fetchone()[0])
    other = sign_up(db, "rival-owner@example.com", "Rival")
    with as_user(db, other) as conn:
        rival_org = str(conn.execute("select id from public.create_organization('Rival Chambers')").fetchone()[0])
    return {"org": org, "own_case": own, "partners_case": partners, "rival": other, "rival_org": rival_org}


def test_appearance_logs_stay_inside_the_firm(db, firm, setup):
    org = setup["org"]
    with as_user(db, firm["associate"], org) as conn:
        period = conn.execute("""insert into public.bench_rosters (court_code, courtroom, bench_key, started_on)
                                 values ('HOPS', '12', 'J-A', '2026-10-01') returning id""").fetchone()[0]
        conn.execute("""insert into public.appearance_logs (court_code, courtroom, list_date, tap_kind, bench_key, roster_period_id,
                        segment, position, elapsed_sitting_min, pace) values ('HOPS', '12', '2026-11-02', 'called', 'J-A', %s,
                        'regular', 8, 30, 3.75)""", [period])
        # A 'called' tap without its pace is refused.
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("""insert into public.appearance_logs (court_code, courtroom, list_date, tap_kind)
                                values ('HOPS', '12', '2026-11-02', 'called')""")
    with as_user(db, firm["paralegal"], org) as conn:
        assert conn.execute("select count(*) from public.appearance_logs").fetchone()[0] == 1
        assert conn.execute("select count(*) from public.bench_rosters").fetchone()[0] == 1
    # Org B can't read org A's appearance logs or roster periods (no cross-firm 'judge speed' data).
    with as_user(db, setup["rival"], setup["rival_org"]) as conn:
        assert conn.execute("select count(*) from public.appearance_logs").fetchone()[0] == 0
        assert conn.execute("select count(*) from public.bench_rosters").fetchone()[0] == 0
    assert denied(db, setup["rival"], """insert into public.appearance_logs (org_id, court_code, courtroom, list_date, tap_kind)
                                         values (%s, 'HOPS', '12', '2026-11-02', 'assembled')""", [org], setup["rival_org"])
    # Taps are logged as oneself, and are not edited in place.
    assert denied(db, firm["associate"], """insert into public.appearance_logs (court_code, courtroom, list_date, tap_kind, logged_by)
                                            values ('HOPS', '12', '2026-11-03', 'assembled', %s)""", [firm["partner"]], org)
    assert denied(db, firm["associate"], "update public.appearance_logs set pace = 1", org_id=org)


def test_proxy_availability_is_set_by_seniors(db, firm, setup):
    org = setup["org"]
    with as_user(db, firm["associate"], org) as conn:
        row = conn.execute("""insert into public.advocate_clash_prefs (amber_as_clash, enrolled, seniority)
                              values (true, false, 3) returning amber_as_clash, enrolled, seniority""").fetchone()
        assert row == (True, True, None)  # an associate can't change their own enrolment or seniority
    with as_user(db, firm["partner"], org) as conn:
        conn.execute("update public.advocate_clash_prefs set seniority = 2 where user_id = %s", [firm["associate"]])
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("select seniority from public.advocate_clash_prefs where user_id = %s",
                            [firm["associate"]]).fetchone()[0] == 2
        conn.execute("update public.advocate_clash_prefs set seniority = 3 where user_id = %s", [firm["associate"]])
        assert conn.execute("select seniority from public.advocate_clash_prefs where user_id = %s",
                            [firm["associate"]]).fetchone()[0] == 2
        # Nobody edits a colleague's preferences except seniors.
        assert conn.execute("update public.advocate_clash_prefs set amber_as_clash = false where user_id = %s returning id",
                            [firm["partner"]]).fetchall() == []


def test_briefs_and_outcomes_follow_the_case(db, firm, setup):
    org = setup["org"]
    with as_user(db, firm["partner"], org) as conn:
        conn.execute("""insert into public.hearing_briefs (court_case_id, hearing_date, trigger, ai_status, sections)
                        values (%s, '2026-11-02', 'manual', 'no_order', '{}')""", [setup["partners_case"]])
        conn.execute("""insert into public.hearing_outcomes (court_case_id, hearing_date, outcome, adjourned_at_instance_of)
                        values (%s, '2026-10-01', 'adjourned', 'respondent')""", [setup["partners_case"]])
        # One brief per case and hearing date.
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute("""insert into public.hearing_briefs (court_case_id, hearing_date, trigger, ai_status)
                                values (%s, '2026-11-02', 'manual', 'no_order')""", [setup["partners_case"]])
    # An associate who can't see the partner's case can't see its brief either (ethical walls hold).
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("select count(*) from public.hearing_briefs").fetchone()[0] == 0
        assert conn.execute("select count(*) from public.hearing_outcomes").fetchone()[0] == 0
        conn.execute("""insert into public.hearing_briefs (court_case_id, hearing_date, trigger, ai_status)
                        values (%s, '2026-11-02', 'manual', 'no_order')""", [setup["own_case"]])
    assert denied(db, firm["associate"], """insert into public.hearing_briefs (court_case_id, hearing_date, trigger, ai_status)
                                            values (%s, '2026-11-09', 'manual', 'no_order')""", [setup["partners_case"]], org)
    assert denied(db, firm["partner"], "delete from public.hearing_briefs", org_id=org)
    with as_user(db, setup["rival"], setup["rival_org"]) as conn:
        assert conn.execute("select count(*) from public.hearing_briefs").fetchone()[0] == 0


def test_travel_times_are_one_row_per_pair(db, firm, setup):
    org = setup["org"]
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("insert into public.complex_travel_times (from_complex, to_complex, minutes) values ('A', 'B', 25)")
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("insert into public.complex_travel_times (from_complex, to_complex, minutes) values ('B', 'A', 25)")
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("delete from public.complex_travel_times returning id").fetchall() == []  # seniors only
