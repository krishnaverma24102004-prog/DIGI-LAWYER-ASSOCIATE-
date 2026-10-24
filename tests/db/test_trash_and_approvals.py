"""Trash, approvals (maker-checker), legal hold, the public intake switch, draft approval and consent."""

import json

import pytest

pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from conftest import as_user, denied, sign_up  # noqa: E402


def one(db, user, org, sql, params=()):
    with as_user(db, user, org) as conn:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and len(row) == 1 else row


def raises(db, user, org, sql, params=(), error=psycopg.errors.InsufficientPrivilege) -> str:
    with pytest.raises(error) as info:
        with as_user(db, user, org) as conn:
            conn.execute(sql, params)
    return str(info.value)


def add_transcript(db, user, org, content="notes", thread=None) -> str:
    return str(one(db, user, org, "insert into public.transcripts (content, thread_id) values (%s, %s) returning id", [content, thread]))


def test_records_cannot_be_deleted_directly(db, firm):
    transcript = add_transcript(db, firm["owner"], firm["org"])
    for table in ["transcripts", "documents", "drafts", "review_grids", "court_cases", "case_threads"]:
        assert denied(db, firm["owner"], f"delete from public.{table}", org_id=firm["org"])
    assert one(db, firm["owner"], firm["org"], "select count(*) from public.transcripts where id = %s", [transcript]) == 1


def test_seniors_trash_and_restore_with_children(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        thread = str(conn.execute("insert into public.case_threads (title) values ('Mehta v. Builder') returning id").fetchone()[0])
        conn.execute("insert into public.thread_messages (thread_id, role, content) values (%s, 'client', 'Flat not delivered')", [thread])
        case = str(conn.execute("insert into public.court_cases (title, thread_id) values ('Mehta v. Builder', %s) returning id", [thread]).fetchone()[0])
    transcript = add_transcript(db, firm["associate"], org, "consultation", thread)

    # Associates can't delete case threads, even with no hold.
    assert "approval_required" in raises(db, firm["associate"], org, "select public.trash_item('case_thread', %s)", [thread])

    trash = str(one(db, firm["partner"], org, "select public.trash_item('case_thread', %s, 'duplicate matter')", [thread]))
    with as_user(db, firm["partner"], org) as conn:
        assert conn.execute("select count(*) from public.case_threads where id = %s", [thread]).fetchone()[0] == 0
        assert conn.execute("select thread_id from public.court_cases where id = %s", [case]).fetchone()[0] is None
        kind, title, reason, sha, purge_days = conn.execute(
            "select kind, title, reason, snapshot_sha256, extract(day from purge_after - deleted_at) from public.trash_items where id = %s",
            [trash]).fetchone()
        assert (kind, title, reason, len(sha), int(purge_days)) == ("case_thread", "Mehta v. Builder", "duplicate matter", 64, 30)

    restored = one(db, firm["partner"], org, "select (public.restore_trash_item(%s)).restored_at is not null", [trash])
    assert restored is True
    with as_user(db, firm["associate"], org) as conn:
        assert conn.execute("select count(*) from public.thread_messages where thread_id = %s", [thread]).fetchone()[0] == 1
        assert str(conn.execute("select thread_id from public.court_cases where id = %s", [case]).fetchone()[0]) == thread
        assert str(conn.execute("select thread_id from public.transcripts where id = %s", [transcript]).fetchone()[0]) == thread
    # A restored item can't be restored twice.
    raises(db, firm["partner"], org, "select public.restore_trash_item(%s)", [trash], psycopg.errors.ObjectNotInPrerequisiteState)


def test_associates_trash_own_drafts_but_need_approval_for_client_records(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        draft = str(conn.execute(
            "insert into public.drafts (doc_type, title, content) values ('legal_notice', 'Notice', '{}') returning id").fetchone()[0])
    trash = str(one(db, firm["associate"], org, "select public.trash_item('draft', %s)", [draft]))
    # They can restore their own deletion; a paralegal can't even see it.
    assert one(db, firm["paralegal"], org, "select count(*) from public.trash_items where id = %s", [trash]) == 0
    assert one(db, firm["associate"], org, "select (public.restore_trash_item(%s)).kind", [trash]) == "draft"

    transcript = add_transcript(db, firm["associate"], org, "client consultation")
    assert "approval_required" in raises(db, firm["associate"], org, "select public.trash_item('transcript', %s)", [transcript])
    # Someone else's record is simply not found.
    raises(db, firm["paralegal"], org, "select public.trash_item('transcript', %s)", [transcript], psycopg.errors.NoDataFound)

    request = str(one(db, firm["associate"], org,
                      "select (public.request_approval('delete', 'transcript', %s, 'client consultation', '{}', 'test entry')).id",
                      [transcript]))
    # Asking twice returns the same pending request.
    assert str(one(db, firm["associate"], org, "select (public.request_approval('delete', 'transcript', %s)).id", [transcript])) == request
    # Requesters can't approve their own request, and associates can't approve at all.
    raises(db, firm["associate"], org, "select public.decide_approval(%s, true)", [request])
    # An approval decided by someone else can't be used by the caller.
    assert one(db, firm["owner"], org, "select (public.decide_approval(%s, true, 'ok')).status", [request]) == "approved"
    raises(db, firm["partner"], org, "select public.trash_item('transcript', %s, null, %s)", [transcript, request])
    trash = str(one(db, firm["owner"], org, "select public.trash_item('transcript', %s, null, %s)", [transcript, request]))
    with as_user(db, firm["owner"], org) as conn:
        requested_by, deleted_by, reason = conn.execute(
            "select requested_by, deleted_by, reason from public.trash_items where id = %s", [trash]).fetchone()
        assert (str(requested_by), str(deleted_by), reason) == (firm["associate"], firm["owner"], "test entry")
        assert conn.execute("select status from public.approval_requests where id = %s", [request]).fetchone()[0] == "executed"
    # The associate sees the trashed record (it was theirs) but can't restore what a senior deleted.
    assert one(db, firm["associate"], org, "select count(*) from public.trash_items where id = %s", [trash]) == 1
    raises(db, firm["associate"], org, "select public.restore_trash_item(%s)", [trash])


def test_requests_can_be_rejected_or_cancelled(db, firm):
    org = firm["org"]
    transcript = add_transcript(db, firm["paralegal"], org)
    request = str(one(db, firm["paralegal"], org, "select (public.request_approval('delete', 'transcript', %s)).id", [transcript]))
    assert one(db, firm["partner"], org, "select (public.decide_approval(%s, false, 'keep it')).status", [request]) == "rejected"
    raises(db, firm["owner"], org, "select public.decide_approval(%s, true)", [request], psycopg.errors.ObjectNotInPrerequisiteState)
    second = str(one(db, firm["paralegal"], org, "select (public.request_approval('delete', 'transcript', %s)).id", [transcript]))
    assert second != request
    assert one(db, firm["partner"], org, "select public.cancel_approval(%s)", [second]) is False  # only the requester
    assert one(db, firm["paralegal"], org, "select public.cancel_approval(%s)", [second]) is True
    # Requests and their rows are written only through the functions.
    assert denied(db, firm["owner"], "update public.approval_requests set status = 'approved'", org_id=org)
    assert denied(db, firm["owner"], "insert into public.trash_items (org_id, kind, item_id, snapshot_sha256) values (%s, 'draft', gen_random_uuid(), 'x')", [org], org)


def test_legal_hold_blocks_deletion_of_the_matter_and_its_records(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        thread = str(conn.execute("insert into public.case_threads (title) values ('State v. Rao') returning id").fetchone()[0])
        case = str(conn.execute("insert into public.court_cases (title, thread_id) values ('State v. Rao', %s) returning id", [thread]).fetchone()[0])
        draft = str(conn.execute(
            "insert into public.drafts (doc_type, title, content, thread_id) values ('bail_application', 'Bail', '{}', %s) returning id",
            [thread]).fetchone()[0])
    transcript = add_transcript(db, firm["associate"], org, "bail consultation", thread)

    assert denied(db, firm["associate"], "update public.case_threads set legal_hold = true where id = %s", [thread], org)
    raises(db, firm["associate"], org, "select public.set_legal_hold('case_thread', %s, true)", [thread])
    assert one(db, firm["partner"], org, "select public.set_legal_hold('case_thread', %s, true, 'FIR registered')", [thread]) is True
    with as_user(db, firm["owner"], org) as conn:
        hold_by, reason = conn.execute("select legal_hold_by, legal_hold_reason from public.case_threads where id = %s", [thread]).fetchone()
        assert (str(hold_by), reason) == (firm["partner"], "FIR registered")

    for kind, item in [("case_thread", thread), ("court_case", case), ("draft", draft), ("transcript", transcript)]:
        message = raises(db, firm["owner"], org, "select public.trash_item(%s, %s)", [kind, item], psycopg.errors.ObjectInUse)
        assert "legal_hold" in message

    one(db, firm["owner"], org, "select public.set_legal_hold('case_thread', %s, false)", [thread])
    one(db, firm["owner"], org, "select public.set_legal_hold('court_case', %s, true, 'appeal pending')", [case])
    raises(db, firm["owner"], org, "select public.trash_item('court_case', %s)", [case], psycopg.errors.ObjectInUse)
    assert one(db, firm["owner"], org, "select public.trash_item('draft', %s)", [draft]) is not None


def test_knowledge_sources_go_to_the_trash_with_their_vectors(db, firm):
    org = firm["org"]
    vector = "[" + ",".join(["0.5"] + ["0"] * 767) + "]"
    with as_user(db, firm["associate"], org) as conn:
        source = str(conn.execute("select gen_random_uuid()").fetchone()[0])
        for index in range(2):
            conn.execute("""insert into public.legal_knowledge_base (source_id, chunk_index, title, content, vector_embedding)
                            values (%s, %s, 'Firm playbook', %s, %s::extensions.vector)""", [source, index, f"chunk {index}", vector])
    assert "approval_required" in raises(db, firm["associate"], org, "select public.trash_item('knowledge_source', %s)", [source])
    trash = str(one(db, firm["partner"], org, "select public.trash_item('knowledge_source', %s)", [source]))
    assert one(db, firm["partner"], org, "select count(*) from public.legal_knowledge_base where source_id = %s", [source]) == 0
    assert one(db, firm["partner"], org, "select title from public.trash_items where id = %s", [trash]) == "Firm playbook"
    one(db, firm["partner"], org, "select public.restore_trash_item(%s)", [trash])
    with as_user(db, firm["paralegal"], org) as conn:
        rows = conn.execute("select chunk_index, vector_embedding::text from public.legal_knowledge_base where source_id = %s order by 1",
                            [source]).fetchall()
        assert [r[0] for r in rows] == [0, 1] and rows[0][1].startswith("[0.5,0")


def test_retention_job_erases_snapshots_and_keeps_the_record(db, firm):
    org = firm["org"]
    with as_user(db, firm["owner"], org) as conn:
        grid = str(conn.execute("insert into public.review_grids (title) values ('NDA batch') returning id").fetchone()[0])
    trash = str(one(db, firm["owner"], org, "select public.trash_item('review_grid', %s)", [grid]))
    assert denied(db, firm["owner"], "select public.purge_expired_trash()", org_id=org)
    db.execute("update public.trash_items set purge_after = now() - interval '1 minute' where id = %s", [trash])
    with as_user(db, firm["owner"], None, role="service_role") as conn:
        purged = [str(r[0]) for r in conn.execute("select id from public.purge_expired_trash()")]
    assert trash in purged
    with as_user(db, firm["owner"], org) as conn:
        snapshot, purged_at, sha = conn.execute(
            "select snapshot, purged_at, snapshot_sha256 from public.trash_items where id = %s", [trash]).fetchone()
        assert snapshot is None and purged_at is not None and len(sha) == 64
    assert "erased" in raises(db, firm["owner"], org, "select public.restore_trash_item(%s)", [trash], psycopg.errors.ObjectNotInPrerequisiteState)


def test_early_erasure_needs_a_second_senior(db, firm):
    org = firm["org"]
    with as_user(db, firm["owner"], org) as conn:
        grid = str(conn.execute("insert into public.review_grids (title) values ('Leases') returning id").fetchone()[0])
    trash = str(one(db, firm["owner"], org, "select public.trash_item('review_grid', %s)", [grid]))
    assert "approval_required" in raises(db, firm["owner"], org, "select public.purge_trash_item(%s)", [trash])
    raises(db, firm["partner"], org, "select public.request_approval('purge', 'trash_item', %s)", [trash])  # owners ask
    request = str(one(db, firm["owner"], org, "select (public.request_approval('purge', 'trash_item', %s)).id", [trash]))
    one(db, firm["partner"], org, "select public.decide_approval(%s, true)", [request])
    purged_by = one(db, firm["partner"], org, "select (public.purge_trash_item(%s, %s)).purged_by", [trash, request])
    assert str(purged_by) == firm["partner"]


def test_public_intake_is_off_until_a_second_senior_approves(db, firm):
    org = firm["org"]
    assert one(db, firm["owner"], org, "select public_intake_enabled from public.organizations where id = %s", [org]) is False
    assert denied(db, firm["owner"], "update public.organizations set public_intake_enabled = true where id = %s", [org], org)
    assert "approval_required" in raises(db, firm["owner"], org, "select public.set_public_intake(true)")
    raises(db, firm["associate"], org, "select public.request_approval('enable_intake', 'organization', %s)", [org])
    request = str(one(db, firm["partner"], org, "select (public.request_approval('enable_intake', 'organization', %s)).id", [org]))
    one(db, firm["owner"], org, "select public.decide_approval(%s, true)", [request])
    raises(db, firm["partner"], org, "select public.set_public_intake(true, %s)", [request])  # only the approver uses it
    assert one(db, firm["owner"], org, "select public.set_public_intake(true, %s)", [request]) is True
    # The approval is spent; turning off needs nobody else.
    assert one(db, firm["partner"], org, "select public.set_public_intake(false)") is False
    assert "No approved request" in raises(db, firm["owner"], org, "select public.set_public_intake(true, %s)", [request])
    with as_user(db, firm["owner"], org) as conn:
        enabled, changed_by = conn.execute(
            "select public_intake_enabled, public_intake_changed_by from public.organizations where id = %s", [org]).fetchone()
        assert (enabled, str(changed_by)) == (False, firm["partner"])


def test_a_firms_only_senior_decides_alone(db):
    solo = sign_up(db, "solo-advocate@example.com", "Asha")
    with as_user(db, solo) as conn:
        org = str(conn.execute("select active_org_id from public.users where id = %s", [solo]).fetchone()[0])
        assert conn.execute("select public.set_public_intake(true)").fetchone()[0] is True
        grid = str(conn.execute("insert into public.review_grids (title) values ('x') returning id").fetchone()[0])
        trash = str(conn.execute("select public.trash_item('review_grid', %s)", [grid]).fetchone()[0])
        assert conn.execute("select (public.purge_trash_item(%s)).purged_at is not null", [trash]).fetchone()[0] is True
    assert org


def test_draft_approval_is_stamped_and_lapses_on_edit(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        draft = str(conn.execute(
            """insert into public.drafts (doc_type, title, content, approved_at, approved_by)
               values ('nda', 'NDA', '{"sections": []}', now(), %s) returning id""", [firm["owner"]]).fetchone()[0])
        assert conn.execute("select approved_at from public.drafts where id = %s", [draft]).fetchone()[0] is None
        conn.execute("update public.drafts set approved_at = '2020-01-01', approved_by = %s where id = %s", [firm["owner"], draft])
        approved_by, recent = conn.execute(
            "select approved_by, approved_at > now() - interval '1 minute' from public.drafts where id = %s", [draft]).fetchone()
        assert (str(approved_by), recent) == (firm["associate"], True)
        conn.execute("update public.drafts set status = 'final' where id = %s", [draft])
        assert conn.execute("select approved_by is not null from public.drafts where id = %s", [draft]).fetchone()[0]
        conn.execute("""update public.drafts set content = '{"sections": [{"heading": "1"}]}' where id = %s""", [draft])
        assert conn.execute("select approved_at, approved_by from public.drafts where id = %s", [draft]).fetchone() == (None, None)


def test_consent_is_recorded_as_the_signed_in_lawyer(db, firm):
    org = firm["org"]
    with as_user(db, firm["associate"], org) as conn:
        thread = str(conn.execute("insert into public.case_threads (title) values ('Consent test') returning id").fetchone()[0])
        conn.execute("update public.case_threads set ai_consent_at = '2001-01-01', ai_consent_by = %s, ai_consent_method = 'verbal' where id = %s",
                     [firm["owner"], thread])
        by, recent, method = conn.execute(
            "select ai_consent_by, ai_consent_at > now() - interval '1 minute', ai_consent_method from public.case_threads where id = %s",
            [thread]).fetchone()
        assert (str(by), recent, method) == (firm["associate"], True, "verbal")
        conn.execute("update public.case_threads set ai_consent_at = null where id = %s", [thread])
        assert conn.execute("select ai_consent_by, ai_consent_method from public.case_threads where id = %s", [thread]).fetchone() == (None, None)
    assert json  # imported for parity with the other DB tests
