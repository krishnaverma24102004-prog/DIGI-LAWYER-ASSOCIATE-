"""Wave 0 foundations: server-owned eCourts fields, court calendars, and firm sign-off of rule tables."""

import json

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied  # noqa: E402


def test_users_cannot_forge_provider_data(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        case = str(conn.execute(
            """insert into public.court_cases (title, source, provider_data, last_synced_at, next_hearing_date)
               values ('State v. Rao', 'ecourtsindia', '{"orders": []}', now(), '2026-11-02') returning id""").fetchone()[0])
        row = conn.execute("select source, provider_data, last_synced_at from public.court_cases where id = %s", [case]).fetchone()
        assert row == ("manual", None, None)
        conn.execute("update public.court_cases set source = 'ecourtsindia', provider_data = '{}' where id = %s", [case])
        assert conn.execute("select source, provider_data from public.court_cases where id = %s", [case]).fetchone() == ("manual", None)

    # The server stores the provider's record; a user's later edit marks that field as no longer confirmed.
    db.execute("""update public.court_cases set source = 'ecourtsindia', provider_data = %s, next_hearing_date = '2026-11-05',
                  case_status = 'Pending' where id = %s""", [json.dumps({"orders": []}), case])
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("update public.court_cases set next_hearing_date = '2026-11-09', notes = 'client informed' where id = %s", [case])
        source, edited, confirmed_date, confirmed_status = conn.execute(
            """select c.source, c.user_edited_fields, public.provider_confirmed(c, 'next_hearing_date'),
                      public.provider_confirmed(c, 'case_status')
               from public.court_cases c where id = %s""", [case]).fetchone()
        assert (source, edited, confirmed_date, confirmed_status) == ("ecourtsindia", ["next_hearing_date"], False, True)


def test_court_calendars_shared_and_per_firm(db, firm):
    org = firm["org"]
    db.execute("insert into public.courts (code, name, complex) values ('DLHC', 'Delhi High Court', 'Sher Shah Road')")
    db.execute("""insert into public.court_calendars (court_code, day, reason, source_url)
                  values ('DLHC', '2026-11-08', 'Diwali', 'https://delhihighcourt.nic.in/calendar')""")
    assert denied(db, firm["owner"], "insert into public.courts (code, name) values ('FAKE', 'x')", org_id=org)
    # A firm records a sudden closure, with its source; a closure without a source is refused.
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("""insert into public.court_calendars (org_id, court_code, day, reason, source_url)
                        values (%s, 'DLHC', '2026-11-20', 'Bar association strike', 'https://example.org/notice')""", [org])
    assert denied(db, firm["associate"], "insert into public.court_calendars (org_id, court_code, day, reason) values (%s, 'DLHC', '2026-11-21', 'x')",
                  [org], org)
    with as_user(db, firm["paralegal"], org) as conn:
        days = sorted(str(r[0]) for r in conn.execute("select day from public.court_calendars where court_code = 'DLHC'"))
        assert days == ["2026-11-08", "2026-11-20"]
    with as_user(db, firm["outsider"]) as conn:
        assert [str(r[0]) for r in conn.execute("select day from public.court_calendars where court_code = 'DLHC'")] == ["2026-11-08"]


def test_a_rule_applies_once_two_members_sign_it(db, firm):
    org = firm["org"]
    check = "select public.rule_active('limitation', 'appeal_hc_decree', 1)"
    sign = "insert into public.rule_verifications (registry, rule_id, version) values ('limitation', 'appeal_hc_decree', 1)"
    with as_user(db, firm["partner"], org) as conn:
        conn.execute(sign)
        assert conn.execute(check).fetchone()[0] is False
    assert denied(db, firm["paralegal"], sign, org_id=org)
    assert denied(db, firm["partner"], "insert into public.rule_verifications (registry, rule_id, version, verified_by) values ('limitation', 'x', 1, %s)",
                  [firm["owner"]], org)
    with as_user(db, firm["associate"], org) as conn:
        conn.execute(sign)
        assert conn.execute(check).fetchone()[0] is True
        # Another version, or the same rule in another firm, is not covered.
        assert conn.execute("select public.rule_active('limitation', 'appeal_hc_decree', 2)").fetchone()[0] is False
    with as_user(db, firm["outsider"]) as conn:
        assert conn.execute(check).fetchone()[0] is False
