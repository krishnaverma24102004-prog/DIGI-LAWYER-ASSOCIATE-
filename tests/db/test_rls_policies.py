"""Tenant isolation and RBAC: who can read and write what."""

import json

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied, sign_up  # noqa: E402


def test_sign_up_creates_an_owned_personal_workspace(db):
    user = sign_up(db, "solo@example.com", "Sam Solo")
    org_name, role, active = db.execute(
        """select o.name, m.role, u.active_org_id = o.id
           from public.users u join public.organization_members m on m.user_id = u.id
           join public.organizations o on o.id = m.org_id where u.id = %s""",
        [user],
    ).fetchone()
    assert (org_name, role, active) == ("Sam Solo's workspace", "owner", True)


def test_role_limits_on_managing_members(db, firm):
    newcomer = sign_up(db, "newcomer@example.com")
    insert = "insert into public.organization_members (org_id, user_id, role) values (%s, %s, %s)"
    # Associates can't add anyone; partners can't create partners or owners.
    assert denied(db, firm["associate"], insert, [firm["org"], newcomer, "paralegal"])
    assert denied(db, firm["partner"], insert, [firm["org"], newcomer, "partner"])
    assert denied(db, firm["partner"], "update public.organization_members set role = 'paralegal' where user_id = %s", [firm["owner"]]) is False
    with as_user(db, firm["owner"]) as conn:  # the partner's update above matched no rows: owner untouched
        assert conn.execute("select role from public.organization_members where user_id = %s and org_id = %s",
                            [firm["owner"], firm["org"]]).fetchone()[0] == "owner"
    assert not denied(db, firm["partner"], insert, [firm["org"], newcomer, "paralegal"])


def test_transcripts_are_scoped_to_active_org_and_role(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        row = conn.execute("insert into public.transcripts (content) values ('associate notes') returning org_id, user_id").fetchone()
        assert (str(row[0]), str(row[1])) == (org, firm["associate"])
    with as_user(db, firm["paralegal"], org) as conn:
        conn.execute("insert into public.transcripts (content) values ('paralegal notes')")

    def visible(user, org_header):
        with as_user(db, user, org_header) as conn:
            return sorted(r[0] for r in conn.execute("select content from public.transcripts"))

    assert visible(firm["owner"], org) == ["associate notes", "paralegal notes"]
    assert visible(firm["partner"], org) == ["associate notes", "paralegal notes"]
    assert visible(firm["associate"], org) == ["associate notes"]
    assert visible(firm["paralegal"], org) == ["paralegal notes"]
    # Outsiders get nothing, even when naming the org; members see nothing from it
    # while their personal workspace is active.
    assert visible(firm["outsider"], org) == []
    assert visible(firm["owner"], None) == []
    assert denied(db, firm["outsider"], "insert into public.transcripts (content, org_id) values ('x', %s)", [org], org)


def test_documents_follow_the_same_rules(db, firm):
    insert = """insert into public.documents (filename, content_type, size_bytes, char_count, extracted_text)
                values ('lease.pdf', 'application/pdf', 10, 10, 'text')"""
    with as_user(db, firm["associate"], firm["org"]) as conn:
        conn.execute(insert)
    with as_user(db, firm["paralegal"], firm["org"]) as conn:
        assert conn.execute("select count(*) from public.documents").fetchone()[0] == 0
    with as_user(db, firm["partner"], firm["org"]) as conn:
        assert conn.execute("select count(*) from public.documents").fetchone()[0] == 1


def test_knowledge_base_permissions_and_vector_search(db, firm):
    org = firm["org"]
    near = "[" + ",".join(["1"] + ["0"] * 767) + "]"
    far = "[" + ",".join(["0"] * 767 + ["1"]) + "]"
    insert = """insert into public.legal_knowledge_base (source_id, title, content, vector_embedding)
                values (gen_random_uuid(), %s, %s, %s::extensions.vector)"""
    assert denied(db, firm["paralegal"], insert, ["x", "y", near], org)
    with as_user(db, firm["associate"], org) as conn:
        conn.execute(insert, ["Tenancy Act s.12", "Deposit must be returned within 21 days.", near])
        conn.execute(insert, ["Unrelated rule", "Parking permits.", far])

    search = "select title, round(similarity::numeric, 3) from public.match_legal_precedents(%s::extensions.vector, 0.5, 3, %s)"
    with as_user(db, firm["paralegal"], org) as conn:
        assert conn.execute(search, [near, org]).fetchall() == [("Tenancy Act s.12", 1)]
    with as_user(db, firm["outsider"], org) as conn:
        assert conn.execute(search, [near, org]).fetchall() == []
    assert denied(db, firm["associate"], "delete from public.legal_knowledge_base", (), org) is False
    with as_user(db, firm["associate"], org) as conn:  # the delete above affected no rows
        assert conn.execute("select count(*) from public.legal_knowledge_base").fetchone()[0] == 2


def test_practice_areas_are_managed_by_owners_and_partners(db, firm):
    org = firm["org"]
    insert = "insert into public.practice_areas (name, custom_system_prompt) values (%s, 'Focus on injuries.')"
    assert denied(db, firm["associate"], insert, ["Personal Injury"], org)
    with as_user(db, firm["partner"], org) as conn:
        conn.execute(insert, ["Personal Injury"])
    with as_user(db, firm["paralegal"], org) as conn:
        assert conn.execute("select name, org_id::text from public.practice_areas").fetchall() == [("Personal Injury", org)]


def test_audit_log_is_append_only_and_restricted(db, firm):
    org = firm["org"]
    with as_user(db, firm["owner"], role="service_role") as conn:
        conn.execute(
            "insert into public.audit_logs (org_id, user_id, action, resource_type, ip_address) values (%s, %s, 'VIEW_TRANSCRIPT', 'transcript', '10.0.0.1')",
            [org, firm["associate"]],
        )
    with as_user(db, firm["owner"], org) as conn:
        assert conn.execute("select action from public.audit_logs").fetchall() == [("VIEW_TRANSCRIPT",)]
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("select count(*) from public.audit_logs").fetchone()[0] == 0
    assert denied(db, firm["owner"], "insert into public.audit_logs (action, resource_type) values ('x', 'y')", (), org)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):  # even the service role can't rewrite history
        with as_user(db, firm["owner"], role="service_role") as conn:
            conn.execute("delete from public.audit_logs")


def test_only_owners_rename_and_nobody_self_upgrades_plan(db, firm):
    org = firm["org"]
    assert denied(db, firm["owner"], "update public.organizations set plan_tier = 'enterprise' where id = %s", [org])
    with as_user(db, firm["partner"]) as conn:
        assert conn.execute("update public.organizations set name = 'Hijacked' where id = %s returning id", [org]).fetchone() is None
    with as_user(db, firm["owner"]) as conn:
        assert conn.execute("update public.organizations set name = 'Acme Legal' where id = %s returning name", [org]).fetchone() == ("Acme Legal",)


def test_case_threads_and_messages_follow_transcript_rules(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        thread = str(conn.execute("insert into public.case_threads (title) values ('Kumar v. Landlord') returning id").fetchone()[0])
        conn.execute("insert into public.thread_messages (thread_id, role, content) values (%s, 'session_summary', 'Deposit withheld.')", [thread])

    def messages(user):
        with as_user(db, user, org) as conn:
            return [r[0] for r in conn.execute("select content from public.thread_messages where thread_id = %s", [thread])]

    assert messages(firm["associate"]) == ["Deposit withheld."]
    assert messages(firm["partner"]) == ["Deposit withheld."]
    assert messages(firm["paralegal"]) == []
    assert messages(firm["outsider"]) == []
    # Nobody can slip a message into a thread they can't see, or rewrite history.
    assert denied(db, firm["paralegal"], "insert into public.thread_messages (thread_id, role, content) values (%s, 'lawyer', 'x')", [thread], org)
    assert denied(db, firm["associate"], "update public.thread_messages set content = 'changed'", (), org)


def test_knowledge_search_filters_by_jurisdiction(db, firm):
    org = firm["org"]
    vec = "[" + ",".join(["0", "1"] + ["0"] * 766) + "]"
    insert = """insert into public.legal_knowledge_base (source_id, title, content, vector_embedding, metadata)
                values (gen_random_uuid(), %s, 'text', %s::extensions.vector, %s::jsonb)"""
    with as_user(db, firm["partner"], org) as conn:
        for title, code in [("BNS s.103", "IN"), ("Cal. Civ. Code 1950.5", "US-CA"), ("42 USC 1983", "US"),
                            ("Companies Act 2006 s 172", "UK"), ("Firm intake checklist", None)]:
            conn.execute(insert, [title, vec, json.dumps({"jurisdiction_code": code} if code else {})])

    def titles(filter_codes):
        with as_user(db, firm["paralegal"], org) as conn:
            rows = conn.execute(
                "select title from public.match_legal_precedents(%s::extensions.vector, 0.9, 20, %s, %s)", [vec, org, filter_codes]
            ).fetchall()
        return sorted(r[0] for r in rows)

    assert titles(["US-CA", "US"]) == ["42 USC 1983", "Cal. Civ. Code 1950.5", "Firm intake checklist"]
    assert titles(["IN"]) == ["BNS s.103", "Firm intake checklist"]
    assert len(titles(None)) == 5


def test_drafts_follow_transcript_visibility(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("insert into public.drafts (doc_type, title, content) values ('legal_notice', 'Notice to landlord', '{}')")

    def visible(user):
        with as_user(db, user, org) as conn:
            return [r[0] for r in conn.execute("select title from public.drafts")]

    assert visible(firm["associate"]) == ["Notice to landlord"]
    assert visible(firm["owner"]) == ["Notice to landlord"]
    assert visible(firm["paralegal"]) == []
    assert visible(firm["outsider"]) == []


def test_co_members_can_see_each_others_profiles(db, firm):
    with as_user(db, firm["paralegal"]) as conn:
        emails = {r[0] for r in conn.execute("select email from public.users")}
    assert {"owner@example.com", "partner@example.com", "associate@example.com", "paralegal@example.com"} <= emails
    assert "outsider@example.com" not in emails


# ----------------------------------------------------------------------------- Phase 7 (migration 007)


def test_billing_and_usage_are_server_written_and_senior_readable(db, firm):
    org = firm["org"]
    with as_user(db, firm["owner"], role="service_role") as conn:
        conn.execute(
            "insert into public.billing_accounts (org_id, stripe_customer_id, tier, status, included_minutes) values (%s, 'cus_1', 'pro', 'active', 1500)",
            [org],
        )
        conn.execute(
            """insert into public.audio_usage (org_id, user_id, session_id, transport, started_at, ended_at, duration_seconds, billed_minutes)
               values (%s, %s, 'sess-1', 'webrtc', now() - interval '5 minutes', now(), 300, 5)""",
            [org, firm["associate"]],
        )
        conn.execute("update public.organizations set plan_tier = 'starter' where id = %s", [org])  # new tier accepted

    def read(user, table):
        with as_user(db, user, org) as conn:
            return conn.execute(f"select count(*) from public.{table}").fetchone()[0]

    for table in ("billing_accounts", "audio_usage"):
        assert read(firm["owner"], table) == 1
        assert read(firm["partner"], table) == 1
        assert read(firm["associate"], table) == 0
        assert read(firm["outsider"], table) == 0
    assert denied(db, firm["owner"], "update public.billing_accounts set included_minutes = 99999", (), org)
    assert denied(db, firm["owner"], "insert into public.audio_usage (org_id, session_id, transport, started_at, ended_at, duration_seconds, billed_minutes) values (%s, 'x', 'webrtc', now(), now(), 0, 0)", [org], org)
    assert denied(db, firm["owner"], "select * from public.stripe_events", (), org)


def test_phone_numbers_are_managed_by_seniors_for_members(db, firm):
    org = firm["org"]
    insert = "insert into public.telephony_numbers (phone_number, org_id, owner_user_id) values (%s, %s, %s)"
    assert denied(db, firm["associate"], insert, ["+14155550100", org, firm["associate"]], org)
    # The receiving lawyer must belong to the organization.
    assert denied(db, firm["partner"], insert, ["+14155550101", org, firm["outsider"]], org)
    with pytest.raises(psycopg.errors.CheckViolation):  # E.164 only
        with as_user(db, firm["partner"], org) as conn:
            conn.execute(insert, ["not-a-number", org, firm["associate"]])
    with as_user(db, firm["partner"], org) as conn:
        conn.execute(insert, ["+14155550102", org, firm["associate"]])
    with as_user(db, firm["paralegal"], org) as conn:
        assert conn.execute("select phone_number from public.telephony_numbers").fetchall() == [("+14155550102",)]
    with as_user(db, firm["outsider"], org) as conn:
        assert conn.execute("select count(*) from public.telephony_numbers").fetchone()[0] == 0


def test_report_files_follow_transcript_visibility(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        transcript = str(conn.execute("insert into public.transcripts (content) values ('call') returning id").fetchone()[0])
    db.execute("insert into storage.objects (bucket_id, name) values ('reports', %s)", [f"{org}/{transcript}.pdf"])
    db.execute("insert into storage.objects (bucket_id, name) values ('reports', %s)", [f"{org}/stray.pdf"])

    def files(user):
        with as_user(db, user, org) as conn:
            return [r[0] for r in conn.execute("select name from storage.objects where bucket_id = 'reports'")]

    assert files(firm["associate"]) == [f"{org}/{transcript}.pdf"]
    assert files(firm["owner"]) == [f"{org}/{transcript}.pdf"]
    assert files(firm["paralegal"]) == []
    assert files(firm["outsider"]) == []


def test_db_connection_gauge_is_service_role_only(db, firm):
    assert denied(db, firm["owner"], "select public.db_connection_count()")
    with as_user(db, firm["owner"], role="service_role") as conn:
        assert conn.execute("select public.db_connection_count()").fetchone()[0] >= 1


def test_shared_corpus_is_readable_by_all_and_writable_by_none(db, firm):
    org = firm["org"]
    vec = "[" + ",".join(["1"] + ["0"] * 767) + "]"
    with as_user(db, firm["owner"], role="service_role") as conn:
        conn.execute(
            """insert into public.legal_knowledge_base (org_id, source_id, title, content, vector_embedding, metadata)
               values (null, gen_random_uuid(), 'Shared SC judgment', 'Cheque dishonour', %s::extensions.vector, '{}')""",
            [vec],
        )
        conn.execute(
            "insert into public.legal_authorities (title, citation_keys, name_tokens, external_id) values ('A v. B', '{2024INSC1}', '{alpha,beta}', 'sc:x')"
        )
    with as_user(db, firm["paralegal"], org) as conn:
        hits = conn.execute(
            "select title, metadata->>'shared' from public.match_legal_precedents(%s::extensions.vector, 0.9, 5, %s)", [vec, org]
        ).fetchall()
        assert ("Shared SC judgment", "true") in hits
        assert conn.execute("select count(*) from public.legal_authorities where citation_keys && '{2024INSC1}'").fetchone()[0] == 1
    with as_user(db, firm["outsider"]) as conn:  # any signed-in user, in any org
        assert conn.execute("select count(*) from public.legal_knowledge_base where org_id is null").fetchone()[0] == 1
    # Nobody but the server writes or deletes shared material.
    assert denied(db, firm["owner"], "insert into public.legal_authorities (title, external_id) values ('x', 'y')", (), org)
    with as_user(db, firm["owner"], org) as conn:
        assert conn.execute("delete from public.legal_knowledge_base where org_id is null returning id").fetchall() == []
    assert denied(db, firm["owner"],
                  "insert into public.legal_knowledge_base (org_id, source_id, title, content, vector_embedding) values (null, gen_random_uuid(), 'x', 'y', %s::extensions.vector)",
                  [vec], org)


def test_invited_people_join_the_firm_when_they_sign_up(db, firm):
    org = firm["org"]
    invite = "insert into public.organization_invitations (org_id, email, role) values (%s, %s, %s)"
    # Partners can invite associates and paralegals, not partners; associates can't invite.
    assert denied(db, firm["partner"], invite, [org, "newpartner@example.com", "partner"], org)
    assert denied(db, firm["associate"], invite, [org, "x@example.com", "paralegal"], org)
    with as_user(db, firm["partner"], org) as conn:
        conn.execute(invite, [org, "junior@example.com", "associate"])
    with as_user(db, firm["paralegal"], org) as conn:  # only managers see invitations
        assert conn.execute("select count(*) from public.organization_invitations").fetchone()[0] == 0

    junior = sign_up(db, "Junior@Example.com", "Jaya Junior")
    role, active = db.execute(
        """select m.role, u.active_org_id::text from public.organization_members m join public.users u on u.id = m.user_id
           where m.user_id = %s and m.org_id = %s""", [junior, org]).fetchone()
    assert (role, active) == ("associate", org)
    # No empty personal workspace for someone who was invited.
    assert db.execute("select count(*) from public.organization_members where user_id = %s", [junior]).fetchone()[0] == 1
    assert db.execute("select accepted_at is not null from public.organization_invitations where email = 'junior@example.com'").fetchone()[0]


def test_firm_name_names_the_new_workspace(db):
    user = db.execute(
        "insert into auth.users (email, raw_user_meta_data) values ('founder@example.com', %s) returning id",
        ['{"full_name": "Asha Rao", "firm_name": "Rao & Associates"}'],
    ).fetchone()[0]
    assert db.execute(
        "select o.name from public.organizations o join public.organization_members m on m.org_id = o.id where m.user_id = %s", [user]
    ).fetchone()[0] == "Rao & Associates"


def test_review_grids_follow_transcript_visibility(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        doc = str(conn.execute("""insert into public.documents (filename, content_type, size_bytes, char_count, extracted_text)
                                  values ('nda.pdf', 'application/pdf', 1, 1, 'x') returning id""").fetchone()[0])
        grid = str(conn.execute("insert into public.review_grids (title, document_ids) values ('NDAs', %s) returning id", [[doc]]).fetchone()[0])
        conn.execute("insert into public.review_cells (grid_id, document_id, question_id) values (%s, %s, 'q1')", [grid, doc])

    def cells(user):
        with as_user(db, user, org) as conn:
            return conn.execute("select count(*) from public.review_cells").fetchone()[0]

    assert cells(firm["associate"]) == 1 and cells(firm["partner"]) == 1
    assert cells(firm["paralegal"]) == 0 and cells(firm["outsider"]) == 0
    assert denied(db, firm["paralegal"], "insert into public.review_cells (grid_id, document_id, question_id) values (%s, %s, 'q2')", [grid, doc], org)


def test_court_cases_follow_transcript_visibility(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        conn.execute("insert into public.court_cases (title, cnr, next_hearing_date) values ('State v. Kumar', 'MHPU010012342026', '2026-10-24')")
    def titles(user):
        with as_user(db, user, org) as conn:
            return [r[0] for r in conn.execute("select title from public.court_cases")]
    assert titles(firm["associate"]) == ["State v. Kumar"] and titles(firm["partner"]) == ["State v. Kumar"]
    assert titles(firm["paralegal"]) == [] and titles(firm["outsider"]) == []
    with pytest.raises(psycopg.errors.CheckViolation):
        with as_user(db, firm["associate"], org) as conn:
            conn.execute("insert into public.court_cases (title, cnr) values ('x', 'bad-cnr')")


def test_whatsapp_chats_are_server_written_and_owner_readable(db, firm):
    org = firm["org"]
    with as_user(db, firm["partner"], org) as conn:
        conn.execute("insert into public.whatsapp_numbers (phone_number_id, display_number, org_id, owner_user_id) values ('1098', '+919800000000', %s, %s)",
                     [org, firm["associate"]])
    assert denied(db, firm["associate"],
                  "insert into public.whatsapp_numbers (phone_number_id, display_number, org_id, owner_user_id) values ('1099', '+919800000001', %s, %s)",
                  [org, firm["associate"]], org)
    with as_user(db, firm["owner"], role="service_role") as conn:
        conv = str(conn.execute(
            "insert into public.whatsapp_conversations (org_id, phone_number_id, owner_user_id, wa_id) values (%s, '1098', %s, '919811111111') returning id",
            [org, firm["associate"]]).fetchone()[0])
        conn.execute("insert into public.whatsapp_messages (conversation_id, wa_message_id, direction, sender, body) values (%s, 'w1', 'in', 'client', 'hi')", [conv])

    def visible(user):
        with as_user(db, user, org) as conn:
            return conn.execute("select count(*) from public.whatsapp_messages").fetchone()[0]

    assert visible(firm["associate"]) == 1 and visible(firm["owner"]) == 1  # the number's lawyer, and seniors
    assert visible(firm["paralegal"]) == 0 and visible(firm["outsider"]) == 0
    assert denied(db, firm["owner"], "insert into public.whatsapp_messages (conversation_id, direction, sender, body) values (%s, 'out', 'lawyer', 'x')", [conv], org)
