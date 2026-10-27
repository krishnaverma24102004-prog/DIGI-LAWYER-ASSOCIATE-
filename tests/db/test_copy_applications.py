"""P06 Copy tracker (migration 017): copy applications are visible like court cases, linked only to
cases and threads the caller can see, and deleted only by the person who logged them."""

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied  # noqa: E402


def test_copy_applications_rls(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        case = str(conn.execute("insert into public.court_cases (title) values ('Rao v. Mehta') returning id").fetchone()[0])
        copy = str(conn.execute(
            """insert into public.copy_applications (court_case_id, order_date, applied_on)
               values (%s, '2026-10-01', '2026-10-05') returning id""", [case]).fetchone()[0])
        conn.execute("update public.copy_applications set ready_on = '2026-10-12', status = 'ready' where id = %s", [copy])
    with as_user(db, firm["partner"], org) as conn:
        partner_case = str(conn.execute("insert into public.court_cases (title) values ('Partner matter') returning id").fetchone()[0])

    def visible(user):
        with as_user(db, firm[user], org if user != "outsider" else None) as conn:
            return [str(r[0]) for r in conn.execute("select id from public.copy_applications")]

    assert visible("associate") == [copy] and visible("partner") == [copy] and visible("owner") == [copy]
    assert visible("paralegal") == [] and visible("outsider") == []

    # Dates out of order are refused by the table itself.
    with pytest.raises(psycopg.errors.CheckViolation):
        with as_user(db, firm["associate"], org) as conn:
            conn.execute("update public.copy_applications set ready_on = '2026-10-01' where id = %s", [copy])
    # A copy can't be linked to a case the caller can't see (the partner's own case, for an associate).
    assert denied(db, firm["associate"], "insert into public.copy_applications (court_case_id, applied_on) values (%s, '2026-10-05')",
                  [partner_case], org)
    # Who logged it and the firm never change.
    assert denied(db, firm["partner"], "update public.copy_applications set user_id = %s where id = %s", [firm["partner"], copy], org)
    # Only the person who logged it deletes it: a partner's delete matches no row.
    with as_user(db, firm["partner"], org) as conn:
        assert conn.execute("delete from public.copy_applications where id = %s returning id", [copy]).fetchall() == []
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("delete from public.copy_applications where id = %s returning id", [copy]).fetchall() != []
