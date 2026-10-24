"""Fixtures for tests/db: the real migrations on a local Postgres + pgvector.

Needs the optional dev dependencies `pgserver` and `psycopg[binary]` (requirements-dev.txt);
skipped otherwise. Each test acts as a user the way PostgREST does: `role authenticated`,
the JWT claims, and the request headers (where the API passes `x-org-id`).
"""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

try:
    import pgserver
    import psycopg
except ImportError:  # the test modules skip themselves
    pgserver = psycopg = None

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
SHIM = Path(__file__).with_name("supabase_shim.sql")


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    with psycopg.connect(server.get_uri(), autocommit=True) as conn:
        conn.execute(SHIM.read_text(encoding="utf-8"))
        for migration in MIGRATIONS:
            conn.execute(migration.read_text(encoding="utf-8"))
        yield conn
    server.cleanup()


def sign_up(db, email, full_name=None) -> str:
    row = db.execute(
        "insert into auth.users (email, raw_user_meta_data) values (%s, %s) returning id",
        [email, json.dumps({"full_name": full_name} if full_name else {})],
    ).fetchone()
    return str(row[0])


@contextmanager
def as_user(db, user_id, org_id=None, role="authenticated"):
    """Run statements as a PostgREST request from `user_id`, with an optional x-org-id header."""
    with db.transaction():
        db.execute(f"set local role {role}")
        db.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps({"sub": user_id, "role": role})])
        db.execute("select set_config('request.headers', %s, true)", [json.dumps({"x-org-id": org_id} if org_id else {})])
        yield db


def denied(db, user_id, sql, params=(), org_id=None) -> bool:
    try:
        with as_user(db, user_id, org_id) as conn:
            conn.execute(sql, params)
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException):
        return True
    return False


@pytest.fixture(scope="module")
def firm(db):
    """A firm with an owner, a partner, an associate, a paralegal, plus an outsider."""
    users = {name: sign_up(db, f"{name}@example.com", name.title()) for name in
             ["owner", "partner", "associate", "paralegal", "outsider"]}
    with as_user(db, users["owner"]) as conn:
        org_id = str(conn.execute("select id from public.create_organization('Acme Legal LLP')").fetchone()[0])
        for name in ["partner", "associate", "paralegal"]:
            conn.execute(
                "insert into public.organization_members (org_id, user_id, role) values (%s, %s, %s)",
                [org_id, users[name], name],
            )
    return {"org": org_id, **users}
