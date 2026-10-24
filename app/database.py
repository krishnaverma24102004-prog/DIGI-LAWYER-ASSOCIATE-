"""Supabase client configuration.

Two kinds of clients:

* ``get_supabase_admin()`` - uses the service role key. It BYPASSES Row-Level
  Security, so only use it for trusted server-side jobs (e.g. n8n callbacks,
  admin tasks) and always filter by user explicitly.
* ``get_supabase_for_user(token, org_id)`` - uses the anon key plus the caller's JWT, so
  every query runs as that user and RLS policies are enforced by Postgres. `org_id` is
  sent as the `x-org-id` header, which public.active_org_id() uses to scope tenant data
  (after checking membership). Prefer this for anything triggered by an end-user request.
"""

from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from app.core.config import get_settings


class SupabaseConfigError(RuntimeError):
    pass


def _require(value: str, name: str) -> str:
    if not value:
        raise SupabaseConfigError(f"{name} is not set. Add it to your .env file.")
    return value


@lru_cache
def get_supabase_admin() -> Client:
    settings = get_settings()
    return create_client(
        _require(settings.supabase_url, "SUPABASE_URL"),
        _require(settings.supabase_service_role_key, "SUPABASE_SERVICE_ROLE_KEY"),
    )


def get_supabase_for_user(access_token: str, org_id: str | None = None) -> Client:
    settings = get_settings()
    client = create_client(
        _require(settings.supabase_url, "SUPABASE_URL"),
        _require(settings.supabase_anon_key, "SUPABASE_ANON_KEY"),
        # The user's JWT on every request (database and Storage), so auth.uid() resolves in RLS policies.
        options=ClientOptions(headers={"Authorization": f"Bearer {access_token}", **({"x-org-id": org_id} if org_id else {})}),
    )
    client.postgrest.auth(access_token)
    return client
