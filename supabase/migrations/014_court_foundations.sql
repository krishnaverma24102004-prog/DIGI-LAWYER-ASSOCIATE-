-- Wave 0: shared foundations for the court-operations features (docs/problem-vault/meeting/final-plan.md).
--
-- Migration register (assigned in wave order, never by proposal):
--   014 court_foundations   server-owned eCourts fields, courts and court calendars, rule sign-off
--   015 deadlines           firm docket: deadlines, blind second check, reminders (P13)
--   016 cause_lists         cause lists, listing matches, advocate aliases, appearance logs (P05, P04)
--   017 limitation          certified-copy applications (P06)
--   018 custody             custody files for default bail and s.479 BNSS (P14)
--   019 hearing_briefs      briefs generated when a matter is listed (P47)
--
-- 1. eCourts data on court_cases is written by the server only. A row's `source = 'ecourtsindia'`
--    and its provider data mean "this came from the provider", so users can't set them: on insert
--    and update by a user they are forced back, and when a user edits a field the provider also
--    fills (hearing dates, status, parties...), its name is added to `user_edited_fields`, so
--    later features know that value is no longer provider-confirmed. The API writes provider data
--    with the service role, scoped to the case and its org (CLAUDE.md invariant 2).
-- 2. `courts` (profiles: name, complex, sitting hours) and `court_calendars` (days a court is
--    closed, each with its source) shared by the limitation engine (s.4 Limitation Act), the
--    docket and the hearing-time estimates. Shared rows (org_id null) are maintained by the server;
--    a firm can add its own closures (a sudden local holiday) with a source.
-- 3. `rule_verifications`: statutory rule tables (limitation periods, punishments for default
--    bail) ship as drafts and only apply in a firm once two of its members have signed the rule's
--    current version, so the vendor's table is never presented to a firm as settled law.

-- ---------------------------------------------------------------------------
-- 1. Server-owned eCourts fields
-- ---------------------------------------------------------------------------
alter table public.court_cases
  add column if not exists user_edited_fields text[] not null default '{}';

create or replace function public.guard_provider_fields()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_field text;
  v_edited text[];
begin
  if current_user not in ('anon', 'authenticated') then
    return new;  -- the server (service role) writes provider data
  end if;
  if tg_op = 'INSERT' then
    new.source := 'manual';
    new.provider_data := null;
    new.last_synced_at := null;
    new.sync_error := null;
    new.user_edited_fields := '{}';
    return new;
  end if;
  new.source := old.source;
  new.provider_data := old.provider_data;
  new.last_synced_at := old.last_synced_at;
  new.sync_error := old.sync_error;
  v_edited := old.user_edited_fields;
  if old.source = 'ecourtsindia' then
    foreach v_field in array array['title', 'court_name', 'case_number', 'case_status', 'petitioners', 'respondents',
                                   'next_hearing_date', 'last_hearing_date'] loop
      if (to_jsonb(new) -> v_field) is distinct from (to_jsonb(old) -> v_field) and not v_field = any (v_edited) then
        v_edited := v_edited || v_field;
      end if;
    end loop;
  end if;
  new.user_edited_fields := v_edited;
  return new;
end;
$$;

drop trigger if exists court_cases_guard_provider_fields on public.court_cases;
create trigger court_cases_guard_provider_fields
  before insert or update on public.court_cases
  for each row execute function public.guard_provider_fields();

-- Whether a court case field holds the provider's value (not typed or changed by a user).
create or replace function public.provider_confirmed(p_case public.court_cases, p_field text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select p_case.source = 'ecourtsindia' and not (p_field = any (p_case.user_edited_fields))
$$;

-- ---------------------------------------------------------------------------
-- 2. Courts and court calendars
-- ---------------------------------------------------------------------------
create table if not exists public.courts (
  code          text primary key check (code ~ '^[A-Z0-9_-]{2,40}$'),  -- e.g. DLHC, SCI, MH-PUNE-DC
  name          text not null,
  complex       text,                -- the building, for travel times between courtrooms
  state         text,
  -- {"sitting_start": "10:30", "lunch_start": "13:00", "lunch_end": "14:15", "rising": "16:30"}
  timings       jsonb not null default '{}'::jsonb,
  source_url    text,
  created_at    timestamptz not null default now()
);

create table if not exists public.court_calendars (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid references public.organizations (id) on delete cascade,  -- null: shared, from the court's calendar
  court_code   text not null references public.courts (code) on delete cascade,
  day          date not null,
  closed       boolean not null default true,
  reason       text not null check (char_length(reason) between 1 and 200),
  source_url   text,                 -- the court's published calendar or notice
  entered_by   uuid default auth.uid() references public.users (id) on delete set null,
  verified_by  uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now()
);

create unique index if not exists court_calendars_shared_day_idx on public.court_calendars (court_code, day) where org_id is null;
create unique index if not exists court_calendars_org_day_idx on public.court_calendars (org_id, court_code, day) where org_id is not null;

alter table public.courts enable row level security;
alter table public.court_calendars enable row level security;

create policy "Everyone signed in can read courts"
  on public.courts for select to authenticated using (true);

create policy "Shared calendars and the firm's own closures are readable"
  on public.court_calendars for select to authenticated
  using (org_id is null or org_id = (select public.active_org_id()));

-- A firm records an ad hoc closure (with its source); owners and partners correct them.
create policy "Members add their firm's closures"
  on public.court_calendars for insert to authenticated
  with check (org_id = (select public.active_org_id()) and source_url is not null);

create policy "Seniors correct their firm's closures"
  on public.court_calendars for update to authenticated
  using (org_id = (select public.active_org_id())
         and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  with check (org_id = (select public.active_org_id()));

revoke insert, update, delete on public.courts from anon, authenticated;
revoke delete on public.court_calendars from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Firm sign-off of statutory rule tables
-- ---------------------------------------------------------------------------
create table if not exists public.rule_verifications (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  registry     text not null check (registry in ('limitation', 'offence_punishments', 'custody')),
  rule_id      text not null check (char_length(rule_id) between 1 and 120),
  version      integer not null check (version > 0),
  verified_by  uuid not null default auth.uid() references public.users (id) on delete cascade,
  note         text check (char_length(note) <= 1000),
  verified_at  timestamptz not null default now(),
  unique (org_id, registry, rule_id, version, verified_by)
);

alter table public.rule_verifications enable row level security;

create policy "Members see their firm's sign-offs"
  on public.rule_verifications for select to authenticated
  using (org_id = (select public.active_org_id()));

-- Associates and above sign rules (paralegals don't); each person signs only for themselves.
create policy "Advocates sign rules for themselves"
  on public.rule_verifications for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and verified_by = (select auth.uid())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner', 'associate']))
  );

revoke update, delete on public.rule_verifications from anon, authenticated;

-- A rule version applies in a firm once two different members have signed it.
create or replace function public.rule_active(p_registry text, p_rule_id text, p_version integer)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select count(distinct v.verified_by) >= 2
  from public.rule_verifications v
  where v.org_id = public.active_org_id() and v.registry = p_registry and v.rule_id = p_rule_id and v.version = p_version
$$;
