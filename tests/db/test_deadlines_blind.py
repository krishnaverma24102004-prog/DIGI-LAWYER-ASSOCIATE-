"""The docket's blind second check, enforced in the database (migration 015).

Allowed exposures (not leaks): the checker may read the matter's source record, i.e. the
court_cases row (hearing and order dates, provider data), the case thread, and /workflows
outputs. Blindness covers the deadline record only: deadlines, deadline_entries,
deadline_reminders, deadline_value_views and the audit rows written about them.
"""

import json
from datetime import date

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied, sign_up  # noqa: E402

from app.services import deadline_service  # noqa: E402

FIRST_DATE = date(2026, 12, 18)
ORDER_DATE = "2026-09-19"
COPY_DATE = "2026-09-24"
FIRST_INPUTS = {"order_date": ORDER_DATE, "copy_received_on": COPY_DATE}
SECRETS = [FIRST_DATE.isoformat(), FIRST_DATE.strftime("%d.%m.%Y"), ORDER_DATE, "19.09.2026", COPY_DATE, "24.09.2026"]


def one(db, user, org, sql, params=()):
    with as_user(db, user, org) as conn:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and len(row) == 1 else row


def create(db, firm, *, maker="associate", owner=None, backup="owner", due=FIRST_DATE, inputs=FIRST_INPUTS, **extra):
    params = {"p_kind": "appeal", "p_title": "Appeal against decree", "p_due_date": due, "p_owner": firm[owner or maker],
              "p_inputs": json.dumps(inputs), "p_backup": firm[backup] if backup else None, **extra}
    names = ", ".join(f"{k} => %({k})s" for k in params)
    return one(db, firm[maker], firm["org"], f"select public.create_deadline({names})", params)


def leaks(payload) -> list[str]:
    text = json.dumps(payload, default=str)
    return [s for s in SECRETS if s in text]


def admin_row(db, deadline_id, columns="*"):
    with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return cur.execute(f"select {columns} from public.deadlines where id = %s", [deadline_id]).fetchone()


def test_checker_direct_select_and_masked_rpcs(db, firm):
    org = firm["org"]
    made = create(db, firm)
    assert made["effective_due_date"] == FIRST_DATE.isoformat() and made["inputs"] == FIRST_INPUTS
    deadline = made["id"]
    assert made["checker"]["id"] == firm["partner"]  # not the owner/maker, preferably not the backup

    for table in ["deadlines", "deadline_entries", "deadline_reminders", "deadline_value_views"]:
        assert denied(db, firm["partner"], f"select * from public.{table}", org_id=org)
        assert denied(db, firm["associate"], f"insert into public.{table} default values", org_id=org)
    assert denied(db, firm["partner"], "select public.deadline_json(%s, %s)", [deadline, firm["partner"]], org)
    assert denied(db, firm["partner"], "select public.deadline_assign_check(%s, null)", [deadline], org)

    listed = one(db, firm["partner"], org, "select public.list_deadlines()")
    row = next(r for r in listed if r["id"] == deadline)
    flags = [r["masked"] for r in listed]
    assert flags == sorted(flags, reverse=True)  # awaiting-your-check rows come first: the order reveals no date
    got = one(db, firm["partner"], org, "select public.get_deadline(%s)", [deadline])
    entries = one(db, firm["partner"], org, "select public.my_deadline_entries(%s)", [deadline])
    reminders = one(db, firm["partner"], org, "select public.my_deadline_reminders()")
    for masked in (row, got):
        assert masked["display_status"] == "awaiting_your_check" and masked["masked"] is True
        assert masked["effective_due_date"] is None and masked["candidates"] is None and masked["inputs"] is None
        assert masked["title"] is None and masked["basis"] is None and masked["latest_reminder"] is None
        assert masked["input_fields"] == ["copy_received_on", "order_date"]  # names for the blank form, no values
    assert entries == []
    assert leaks([listed, got, entries, reminders]) == []
    # A masked read is not a view.
    assert db.execute("select count(*) from public.deadline_value_views where deadline_id = %s and user_id = %s",
                      [deadline, firm["partner"]]).fetchone()[0] == 0


def test_audit_rows_reveal_nothing_to_the_checker(db, firm):
    org = firm["org"]
    made = create(db, firm)
    meta = deadline_service.audit_metadata(org, made, inputs=FIRST_INPUTS, computed=FIRST_DATE)
    db.execute("insert into public.audit_logs (org_id, user_id, action, resource_type, resource_id, metadata) "
               "values (%s, %s, 'CREATE_DEADLINE', 'deadline', %s, %s)", [org, firm["associate"], made["id"], json.dumps(meta)])
    with as_user(db, firm["partner"], org) as conn:
        rows = conn.execute("select action, metadata from public.audit_logs where resource_id = %s", [made["id"]]).fetchall()
    assert rows and leaks(rows) == []


def test_values_visible_after_submit(db, firm):
    org = firm["org"]
    deadline = create(db, firm)["id"]
    checked = {"order_date": ORDER_DATE, "copy_received_on": "2026-09-22"}  # the checker reads the copy date differently
    after = one(db, firm["partner"], org, "select public.submit_deadline_entry(%s, %s, %s)",
                [deadline, json.dumps(checked), date(2026, 12, 16)])
    assert after["verification"] == "disputed" and after["display_status"] == "disputed"
    assert after["candidates"] == ["2026-12-16", FIRST_DATE.isoformat()]
    assert after["effective_due_date"] == "2026-12-16"  # the earlier date governs
    for user in ("partner", "associate"):
        entries = one(db, firm[user], org, "select public.my_deadline_entries(%s)", [deadline])
        assert sorted(e["kind"] for e in entries) == ["check", "first"]
    # Submitting twice is refused.
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        one(db, firm["partner"], org, "select public.submit_deadline_entry(%s, %s, %s)", [deadline, json.dumps(checked), FIRST_DATE])


def test_agreement_verifies(db, firm):
    org = firm["org"]
    deadline = create(db, firm)["id"]
    after = one(db, firm["partner"], org, "select public.submit_deadline_entry(%s, %s, %s)",
                [deadline, json.dumps(FIRST_INPUTS), FIRST_DATE])
    assert (after["verification"], after["candidates"]) == ("verified", [FIRST_DATE.isoformat()])
    # Only the assigned checker can submit.
    deadline = create(db, firm)["id"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        one(db, firm["owner"], org, "select public.submit_deadline_entry(%s, %s, %s)", [deadline, json.dumps(FIRST_INPUTS), FIRST_DATE])


def test_viewer_never_checker(db, firm):
    org = firm["org"]
    deadline = create(db, firm)["id"]
    assert admin_row(db, deadline, "checker_id")["checker_id"] is not None
    # The owner (backup) opens the docket, so has seen the values; the partner-checker is then replaced.
    one(db, firm["owner"], org, "select public.list_deadlines()")
    after = one(db, firm["owner"], org, "select public.reassign_deadline_check(%s)", [deadline])
    # Nobody unviewed and eligible remains (paralegals don't check): the maker re-enters blind, 12 h later.
    assert after["check_mode"] == "self" and after["checker"]["id"] == firm["associate"]
    assert after["check_note"] == "all_eligible_viewed"
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        one(db, firm["associate"], org, "select public.submit_deadline_entry(%s, %s, %s)",
            [deadline, json.dumps(FIRST_INPUTS), FIRST_DATE])
    db.execute("update public.deadlines set check_opens_at = now() - interval '1 minute' where id = %s", [deadline])
    done = one(db, firm["associate"], org, "select public.submit_deadline_entry(%s, %s, %s)",
               [deadline, json.dumps(FIRST_INPUTS), FIRST_DATE])
    assert done["verification"] == "self_verified" and done["display_status"] == "self_verified"

    # Someone who hasn't looked is still eligible on reassignment.
    deadline = create(db, firm)["id"]
    after = one(db, firm["associate"], org, "select public.reassign_deadline_check(%s)", [deadline])
    assert after["check_mode"] == "second" and after["checker"]["id"] == firm["owner"]


def test_one_member_firm_self_verifies(db):
    solo = sign_up(db, "solo@example.com", "Solo Advocate")
    org = str(db.execute("select active_org_id from public.users where id = %s", [solo]).fetchone()[0])
    made = one(db, solo, org, "select public.create_deadline(p_kind => 'written_statement', p_title => 'WS', "
                              "p_due_date => %s, p_owner => %s, p_inputs => %s)", [FIRST_DATE, solo, json.dumps(FIRST_INPUTS)])
    assert (made["check_mode"], made["check_note"], made["can_check"]) == ("self", "no_eligible_checker", False)
    assert made["effective_due_date"] == FIRST_DATE.isoformat()  # self mode hides nothing from the maker
    opens = admin_row(db, made["id"], "check_opens_at - created_at as gap")["gap"]
    assert opens.total_seconds() >= 12 * 3600


def test_visibility_and_cross_org_isolation(db, firm):
    org = firm["org"]
    deadline = create(db, firm)["id"]
    # A paralegal who isn't on the deadline doesn't see it; nor does another firm.
    assert all(r["id"] != deadline for r in one(db, firm["paralegal"], org, "select public.list_deadlines()"))
    with pytest.raises(psycopg.errors.NoDataFound):
        one(db, firm["paralegal"], org, "select public.get_deadline(%s)", [deadline])
    outsider_org = str(db.execute("select active_org_id from public.users where id = %s", [firm["outsider"]]).fetchone()[0])
    assert all(r["id"] != deadline for r in one(db, firm["outsider"], outsider_org, "select public.list_deadlines()"))
    for fn in ("get_deadline", "my_deadline_entries", "complete_deadline"):
        args = "%s, 'filed'" if fn == "complete_deadline" else "%s"
        with pytest.raises(psycopg.errors.NoDataFound):
            one(db, firm["outsider"], outsider_org, f"select public.{fn}({args})", [deadline])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        one(db, firm["outsider"], org, "select public.list_deadlines()")  # not a member: no active org
    # The owner/partner sees the firm's docket with values.
    seen = next(r for r in one(db, firm["owner"], org, "select public.list_deadlines()") if r["id"] == deadline)
    assert seen["effective_due_date"] == FIRST_DATE.isoformat()


def test_matter_link_and_access(db, firm):
    org = firm["org"]
    with as_user(db, firm["partner"], org) as conn:
        case = str(conn.execute("insert into public.court_cases (title) values ('Rao v. Mehta') returning id").fetchone()[0])
    # An associate can't attach a deadline to a matter they can't see.
    with pytest.raises(psycopg.errors.NoDataFound):
        create(db, firm, p_court_case=case)
    made = create(db, firm, maker="partner", owner="associate", backup="owner", p_court_case=case)
    assert made["matter"] == {"court_case_id": case, "thread_id": None, "label": "Rao v. Mehta"}
    assert [r["id"] for r in one(db, firm["partner"], org, "select public.list_deadlines(p_court_case => %s)", [case])] == [made["id"]]


def test_acknowledge_and_complete(db, firm):
    org = firm["org"]
    deadline = create(db, firm)["id"]
    reminder = str(db.execute(
        "insert into public.deadline_reminders (deadline_id, org_id, target_id, rung, for_date) "
        "values (%s, %s, %s, 'T-30', %s) returning id", [deadline, org, firm["associate"], FIRST_DATE]).fetchone()[0])
    mine = one(db, firm["associate"], org, "select public.my_deadline_reminders()")
    assert [r["id"] for r in mine] == [reminder] and mine[0]["delivered_at"] is not None
    with pytest.raises(psycopg.errors.NoDataFound):
        one(db, firm["paralegal"], org, "select public.acknowledge_deadline_reminder(%s)", [reminder])
    assert one(db, firm["associate"], org, "select public.acknowledge_deadline_reminder(%s)", [reminder])["acknowledged"] == 1
    # The masked checker can't close it; the owner can, with evidence.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        one(db, firm["partner"], org, "select public.complete_deadline(%s, 'filed')", [deadline])
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        one(db, firm["associate"], org, "select public.complete_deadline(%s, '')", [deadline])
    done = one(db, firm["associate"], org, "select public.complete_deadline(%s, 'Filed, diary no. 4411/2026')", [deadline])
    assert (done["status"], done["check_state"], done["check_cancel_reason"]) == ("done", "cancelled", "completed")


def test_absences(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("insert into public.member_absences (user_id, starts_on, ends_on) values (%s, current_date, current_date + 3)",
                     [firm["associate"]])
    assert denied(db, firm["associate"], "insert into public.member_absences (user_id, starts_on, ends_on) "
                                         "values (%s, current_date, current_date)", [firm["paralegal"]], org)
    with as_user(db, firm["partner"], org) as conn:
        conn.execute("insert into public.member_absences (user_id, starts_on, ends_on) values (%s, current_date, current_date)",
                     [firm["paralegal"]])
        assert conn.execute("select count(*) from public.member_absences").fetchone()[0] == 2
    # While the owner of a deadline is away the docket shows who covers it.
    made = create(db, firm, maker="partner", owner="associate", backup="owner")
    assert made["covered_by"]["id"] == firm["owner"]
    db.execute("delete from public.member_absences where org_id = %s", [org])
