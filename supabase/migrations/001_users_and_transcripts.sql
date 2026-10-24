-- Run in Supabase: Dashboard -> SQL Editor -> paste -> Run
-- (or `supabase db push` if you use the Supabase CLI).
--
-- Auth accounts live in Supabase's built-in auth.users table. public.users is the
-- app's profile table, one row per auth user, created automatically on sign-up.

-- ---------------------------------------------------------------------------
-- Shared: keep updated_at current
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
create table if not exists public.users (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text unique,
  full_name   text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create trigger users_set_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

-- Create the profile row whenever someone signs up through Supabase Auth.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.users (id, email, full_name)
  values (new.id, new.email, new.raw_user_meta_data ->> 'full_name');
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- transcripts
-- ---------------------------------------------------------------------------
create table if not exists public.transcripts (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references public.users (id) on delete cascade,
  title       text,
  content     text not null,
  source      text,
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists transcripts_user_id_created_at_idx
  on public.transcripts (user_id, created_at desc);

create trigger transcripts_set_updated_at
  before update on public.transcripts
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- With RLS enabled and no matching policy, access is denied by default.
-- Policies apply to the `authenticated` role only, so anonymous requests see nothing.
-- The service_role key bypasses RLS entirely (server-side use only).
-- `(select auth.uid())` is wrapped in a subselect so Postgres evaluates it once per query.
-- ---------------------------------------------------------------------------
alter table public.users       enable row level security;
alter table public.transcripts enable row level security;

-- users: read and update only your own profile. Inserts come from the sign-up
-- trigger (security definer), deletes cascade from auth.users.
create policy "Users can view own profile"
  on public.users for select
  to authenticated
  using ((select auth.uid()) = id);

create policy "Users can update own profile"
  on public.users for update
  to authenticated
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

-- transcripts: full CRUD, but only on rows you own.
create policy "Users can view own transcripts"
  on public.transcripts for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users can insert own transcripts"
  on public.transcripts for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "Users can update own transcripts"
  on public.transcripts for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Users can delete own transcripts"
  on public.transcripts for delete
  to authenticated
  using ((select auth.uid()) = user_id);
