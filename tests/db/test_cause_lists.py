"""P05 (migration 016): public lists are readable by everyone signed in, forwarded lists and matches
by the firm only; the server writes lists and matches; members confirm, claim and manage aliases."""

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied, sign_up  # noqa: E402

SHA = "a" * 64


@pytest.fixture(scope="module")
def lists(db, firm):
    org = firm["org"]
    other = sign_up(db, "rival@example.com", "Rival")
    with as_user(db, other) as conn:
        rival_org = str(conn.execute("select id from public.create_organization('Rival LLP')").fetchone()[0])
    with as_user(db, firm["associate"], org) as conn:
        own_case = str(conn.execute("insert into public.court_cases (title, case_number) values ('A v. B', 'SLP(C) 1/2026') returning id").fetchone()[0])
    with as_user(db, firm["partner"], org) as conn:
        partner_case = str(conn.execute("insert into public.court_cases (title, case_number) values ('C v. D', 'SLP(C) 2/2026') returning id").fetchone()[0])
    with as_user(db, other, rival_org) as conn:
        rival_case = str(conn.execute("insert into public.court_cases (title) values ('E v. F') returning id").fetchone()[0])

    # The server (no user role) stores a public list and a list the firm forwarded.
    db.execute("insert into public.courts (code, name) values ('SCI', 'Supreme Court of India') on conflict do nothing")
    public = str(db.execute(
        """insert into public.cause_lists (court_code, list_date, list_type, source_url, content_sha256, parser)
           values ('SCI', '2026-10-28', 'daily', 'https://api.sci.gov.in/jonew/cl/2026-10-28/M_J_1.pdf', %s, 'SCI') returning id""",
        [SHA]).fetchone()[0])
    forwarded = str(db.execute(
        """insert into public.cause_lists (org_id, court_code, list_date, list_type, content_sha256, source, parser)
           values (%s, 'SCI', '2026-10-28', 'supplementary', %s, 'forwarded', 'SCI') returning id""", [org, SHA]).fetchone()[0])
    items = []
    for list_id, item_org, no in ((public, None, "1"), (public, None, "2"), (forwarded, org, "3")):
        items.append(str(db.execute(
            """insert into public.cause_list_items (cause_list_id, org_id, court_code, list_date, list_type, item_no, case_type, case_number, case_year)
               values (%s, %s, 'SCI', '2026-10-28', 'daily', %s, 'SLP(C)', %s, 2026) returning id""",
            [list_id, item_org, no, no]).fetchone()[0]))
    matches = {}
    for name, item, case, kind in (("own", items[0], own_case, "exact"), ("partner", items[1], partner_case, "exact"),
                                   ("possibly", items[2], None, "possibly_ours")):
        matches[name] = str(db.execute(
            """insert into public.listing_matches (org_id, item_id, cause_list_id, court_case_id, match_type, reason, court_code, list_date, list_type,
                                                   appearing_advocate_id)
               values (%s, %s, (select cause_list_id from public.cause_list_items where id = %s), %s, %s, 'test', 'SCI', '2026-10-28', 'daily', %s)
               returning id""",
            [org, item, item, case, kind, firm["partner"] if name == "partner" else firm["associate"]]).fetchone()[0])
    return {"org": org, "rival": other, "rival_org": rival_org, "rival_case": rival_case, "public": public,
            "forwarded": forwarded, "matches": matches}


def test_public_lists_for_everyone_forwarded_lists_for_the_firm(db, firm, lists):
    with as_user(db, lists["rival"], lists["rival_org"]) as conn:
        assert [r[0] for r in conn.execute("select id::text from public.cause_lists")] == [lists["public"]]
        assert conn.execute("select count(*) from public.cause_list_items").fetchone()[0] == 2
        assert conn.execute("select count(*) from public.listing_matches").fetchone()[0] == 0
    with as_user(db, firm["paralegal"], lists["org"]) as conn:
        assert conn.execute("select count(*) from public.cause_lists").fetchone()[0] == 2
        assert conn.execute("select count(*) from public.cause_list_items").fetchone()[0] == 3
    # Only the server writes lists and items.
    assert denied(db, firm["owner"], "insert into public.cause_lists (court_code, list_date, list_type, content_sha256, parser) "
                                     "values ('SCI', '2026-10-29', 'daily', %s, 'SCI')", [SHA], lists["org"])
    assert denied(db, firm["owner"], "update public.cause_list_items set status = 'deleted'", org_id=lists["org"])


def test_matches_visible_to_those_who_work_on_them(db, firm, lists):
    m = lists["matches"]
    with as_user(db, firm["partner"], lists["org"]) as conn:
        assert {r[0] for r in conn.execute("select id::text from public.listing_matches")} == set(m.values())
    with as_user(db, firm["associate"], lists["org"]) as conn:
        assert {r[0] for r in conn.execute("select id::text from public.listing_matches")} == {m["own"], m["possibly"]}


def test_members_confirm_and_claim_but_cannot_touch_server_fields(db, firm, lists):
    m = lists["matches"]
    with as_user(db, firm["associate"], lists["org"]) as conn:
        conn.execute("update public.listing_matches set state = 'confirmed', confirmed_by = %s where id = %s", [firm["owner"], m["own"]])
        state, by = conn.execute("select state, confirmed_by::text from public.listing_matches where id = %s", [m["own"]]).fetchone()
        assert (state, by) == ("confirmed", firm["associate"])  # recorded as the person who confirmed
    assert denied(db, firm["associate"], "update public.listing_matches set escalation_level = 0 where id = %s", [m["own"]], lists["org"])
    assert denied(db, firm["associate"], "update public.listing_matches set court_case_id = %s where id = %s",
                  [lists["rival_case"], m["possibly"]], lists["org"])
    assert denied(db, firm["associate"], "update public.listing_matches set fallback_advocate_id = %s where id = %s",
                  [lists["rival"], m["possibly"]], lists["org"])
    assert denied(db, firm["owner"], "delete from public.listing_matches", org_id=lists["org"])


def test_aliases_are_the_firms(db, firm, lists):
    sql = "insert into public.advocate_aliases (user_id, alias, enrolment_no) values (%s, %s, '2217')"
    with as_user(db, firm["paralegal"], lists["org"]) as conn:
        conn.execute(sql, [firm["associate"], "Rishi Matoliya"])
    assert denied(db, firm["paralegal"], sql, [lists["rival"], "Rival Person"], lists["org"])
    with as_user(db, lists["rival"], lists["rival_org"]) as conn:
        assert conn.execute("select count(*) from public.advocate_aliases").fetchone()[0] == 0
