-- P05: nightly cause-list reconciliation (docs/problem-vault/meeting.json, solution P05).
--
-- 1. `cause_lists` / `cause_list_items`: every list the server ingests, with its source URL and
--    content hash for audit. Lists fetched from a court website are public court data (org_id null)
--    and readable by every signed-in user; a list a firm member forwards (a PDF behind a captcha, or
--    from a court we don't fetch) belongs to that firm (org_id set). Only the server writes them.
--    A revised list at the same URL (new hash) supersedes the old one (`superseded_by`); its items
--    are kept for audit.
-- 2. `listing_matches`: a firm's tracked matters found in a list (exact / probable) and items naming
--    a firm advocate that match no tracked matter (possibly_ours), with the appearing and fallback
--    advocate, confirmation and the escalation level. Created by the server; members claim, dismiss,
--    confirm and assign.
-- 3. `advocate_aliases`: the firm's roster as it is printed in lists (name variants, AOR codes /
--    enrolment numbers). Members manage their firm's aliases.
-- 4. `case_type_aliases`: 'Writ Petition (Civil)' -> 'WP(C)' etc. Shared, server-maintained.
-- 5. `court_cases.fallback_advocate_id`: the matter's default fallback advocate.
--
-- Parsing and matching are deterministic code (app/services/causelist_service.py), no AI.
-- The fetch and escalation jobs are server-side jobs (service role) scoped to one organization
-- at a time; they need adding to CLAUDE.md invariant 2.

-- ---------------------------------------------------------------------------
-- 1. Cause lists and their items
-- ---------------------------------------------------------------------------
create table if not exists public.cause_lists (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid references public.organizations (id) on delete cascade,  -- null: public list fetched by the server
  court_code      text not null references public.courts (code),
  list_date       date not null,
  list_type       text not null check (list_type in ('daily', 'supplementary', 'advance')),
  source_url      text,                -- null for a forwarded upload
  content_sha256  text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  fetched_at      timestamptz not null default now(),
  superseded_by   uuid references public.cause_lists (id) on delete set null,
  source          text not null default 'fetch' check (source in ('fetch', 'forwarded')),
  uploaded_by     uuid references public.users (id) on delete set null,
  filename        text,
  parser          text not null,       -- the court grammar that read it, e.g. 'SCI', 'DLHC'
  parser_version  integer not null default 1,
  page_count      integer,
  item_count      integer not null default 0,
  parse_warnings  jsonb not null default '[]'::jsonb,
  created_at      timestamptz not null default now(),
  check ((org_id is null) = (source = 'fetch'))
);

create unique index if not exists cause_lists_public_url_hash_idx
  on public.cause_lists (source_url, content_sha256) where org_id is null;
create unique index if not exists cause_lists_org_hash_idx
  on public.cause_lists (org_id, court_code, list_date, list_type, content_sha256) where org_id is not null;
create index if not exists cause_lists_court_date_idx on public.cause_lists (court_code, list_date);

create table if not exists public.cause_list_items (
  id              uuid primary key default gen_random_uuid(),
  cause_list_id   uuid not null references public.cause_lists (id) on delete cascade,
  org_id          uuid references public.organizations (id) on delete cascade,  -- copied from the list
  court_code      text not null,
  list_date       date not null,
  list_type       text not null check (list_type in ('daily', 'supplementary', 'advance')),
  courtroom       text,                -- null: not yet allotted (advance lists)
  bench_key       text,                -- normalised judges / bench id; null = bench unknown
  bench_label     text,
  segment         text not null default 'other'
                  check (segment in ('fresh', 'after_notice', 'regular', 'supplementary', 'advance', 'other')),
  item_no         text not null,
  position        integer,             -- printed rank for that courtroom in this list; connected matters share it; null when deleted
  connected_to    text,                -- item_no it is listed with
  status          text not null default 'listed' check (status in ('listed', 'deleted', 'not_to_be_taken_up')),
  case_type       text,                -- as printed
  case_type_key   text,                -- normalised (case_type_aliases applied), used for matching
  case_number     text,                -- '1234' or a range '26147-26149'
  case_year       integer,
  parties         text,
  advocates       text[] not null default '{}',
  advocate_codes  text[] not null default '{}',  -- AOR codes / enrolment numbers printed with the names
  page            integer,
  seq             integer not null default 0,    -- order within the list
  fingerprint     text,                -- hash of where and how the matter is listed (changes re-notify)
  created_at      timestamptz not null default now()
);

create index if not exists cause_list_items_list_idx on public.cause_list_items (cause_list_id, seq);
create index if not exists cause_list_items_case_idx on public.cause_list_items (court_code, list_date, case_type_key, case_number, case_year);

alter table public.cause_lists enable row level security;
alter table public.cause_list_items enable row level security;

create policy "Public lists and the firm's forwarded lists are readable"
  on public.cause_lists for select to authenticated
  using (org_id is null or org_id = (select public.active_org_id()));

create policy "Public list items and the firm's forwarded list items are readable"
  on public.cause_list_items for select to authenticated
  using (org_id is null or org_id = (select public.active_org_id()));

revoke insert, update, delete on public.cause_lists, public.cause_list_items from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Matches between list items and a firm's matters
-- ---------------------------------------------------------------------------
create table if not exists public.listing_matches (
  id                     uuid primary key default gen_random_uuid(),
  org_id                 uuid not null references public.organizations (id) on delete cascade,
  item_id                uuid not null references public.cause_list_items (id) on delete cascade,
  cause_list_id          uuid not null references public.cause_lists (id) on delete cascade,
  court_case_id          uuid references public.court_cases (id) on delete cascade,
  match_type             text not null check (match_type in ('exact', 'probable', 'possibly_ours')),
  reason                 text not null,
  state                  text not null default 'open' check (state in ('open', 'claimed', 'dismissed', 'confirmed')),
  appearing_advocate_id  uuid references public.users (id) on delete set null,
  fallback_advocate_id   uuid references public.users (id) on delete set null,
  confirmed_by           uuid references public.users (id) on delete set null,
  confirmed_at           timestamptz,
  escalation_level       integer not null default 0 check (escalation_level between 0 and 3),
  ingested_at            timestamptz not null default now(),  -- the escalation clock runs from here
  escalated_at           timestamptz,
  court_code             text not null,
  list_date              date not null,
  list_type              text not null check (list_type in ('daily', 'supplementary', 'advance')),
  previous_hearing_date  date,          -- court_cases.next_hearing_date before an exact match set it
  hearing_date_set       boolean not null default false,
  notified_at            timestamptz,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index if not exists listing_matches_org_date_idx on public.listing_matches (org_id, list_date);
create index if not exists listing_matches_list_idx on public.listing_matches (cause_list_id, org_id);
create index if not exists listing_matches_case_idx on public.listing_matches (court_case_id);

create trigger listing_matches_set_updated_at
  before update on public.listing_matches
  for each row execute function public.set_updated_at();

-- Membership and case ownership checks for the guard below (definer: an associate can't see a
-- partner's case through RLS, but may still link a 'possibly ours' item to it).
create or replace function public.listing_member(p_org uuid, p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.organization_members m where m.org_id = p_org and m.user_id = p_user)
$$;

create or replace function public.listing_case_in_org(p_case uuid, p_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.court_cases c where c.id = p_case and c.org_id = p_org)
$$;

-- A member's update: a linked case must be the firm's, assigned advocates must be its members,
-- and a confirmation is recorded as theirs, now. (Not security definer: current_user tells the
-- server's writes apart from a user's.)
create or replace function public.guard_listing_match_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user not in ('anon', 'authenticated') then
    return new;  -- the server
  end if;
  if new.court_case_id is distinct from old.court_case_id and new.court_case_id is not null
     and not public.listing_case_in_org(new.court_case_id, new.org_id) then
    raise exception 'That case is not in this organization' using errcode = '42501';
  end if;
  if (new.appearing_advocate_id is distinct from old.appearing_advocate_id and new.appearing_advocate_id is not null
      and not public.listing_member(new.org_id, new.appearing_advocate_id))
     or (new.fallback_advocate_id is distinct from old.fallback_advocate_id and new.fallback_advocate_id is not null
      and not public.listing_member(new.org_id, new.fallback_advocate_id)) then
    raise exception 'Advocates must be members of this organization' using errcode = '42501';
  end if;
  if new.state = 'confirmed' and old.state is distinct from 'confirmed' then
    new.confirmed_by := auth.uid();
    new.confirmed_at := now();
  elsif new.state <> 'confirmed' then
    new.confirmed_by := null;
    new.confirmed_at := null;
  else
    new.confirmed_by := old.confirmed_by;
    new.confirmed_at := old.confirmed_at;
  end if;
  return new;
end;
$$;

drop trigger if exists listing_matches_guard_update on public.listing_matches;
create trigger listing_matches_guard_update
  before update on public.listing_matches
  for each row execute function public.guard_listing_match_update();

alter table public.listing_matches enable row level security;

-- Owners and partners see the firm's board; others see matters they appear in or are fallback for,
-- matters on their own cases, and unclaimed items ('Possibly ours') someone has to claim.
create policy "Members see the firm's listings they work on"
  on public.listing_matches for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and ((select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
         or appearing_advocate_id = (select auth.uid())
         or fallback_advocate_id = (select auth.uid())
         or court_case_id is null
         or exists (select 1 from public.court_cases c where c.id = court_case_id and c.user_id = (select auth.uid())))
  );

create policy "Members claim, dismiss, confirm and assign the firm's listings"
  on public.listing_matches for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and ((select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
         or appearing_advocate_id = (select auth.uid())
         or fallback_advocate_id = (select auth.uid())
         or court_case_id is null
         or exists (select 1 from public.court_cases c where c.id = court_case_id and c.user_id = (select auth.uid())))
  )
  with check (org_id = (select public.active_org_id()));

revoke insert, update, delete on public.listing_matches from anon, authenticated;
grant update (state, court_case_id, appearing_advocate_id, fallback_advocate_id, confirmed_by, confirmed_at)
  on public.listing_matches to authenticated;

-- ---------------------------------------------------------------------------
-- 3. The firm's advocate roster as printed in lists
-- ---------------------------------------------------------------------------
create table if not exists public.advocate_aliases (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id       uuid not null references public.users (id) on delete cascade,
  alias         text not null check (char_length(alias) between 3 and 120),
  enrolment_no  text check (char_length(enrolment_no) between 1 and 40),  -- e.g. D/1234/2010, or an SC AOR code
  created_by    uuid default auth.uid() references public.users (id) on delete set null,
  created_at    timestamptz not null default now(),
  unique (org_id, user_id, alias)
);

create index if not exists advocate_aliases_org_idx on public.advocate_aliases (org_id);

alter table public.advocate_aliases enable row level security;

create policy "Members see their firm's advocate aliases"
  on public.advocate_aliases for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members add aliases for their firm's members"
  on public.advocate_aliases for insert to authenticated
  with check (org_id = (select public.active_org_id()) and public.listing_member(org_id, user_id));

create policy "Members correct their firm's aliases"
  on public.advocate_aliases for update to authenticated
  using (org_id = (select public.active_org_id()))
  with check (org_id = (select public.active_org_id()) and public.listing_member(org_id, user_id));

create policy "Members remove their firm's aliases"
  on public.advocate_aliases for delete to authenticated
  using (org_id = (select public.active_org_id()));

-- ---------------------------------------------------------------------------
-- 4. Case-type aliases (shared)
-- ---------------------------------------------------------------------------
create table if not exists public.case_type_aliases (
  id          uuid primary key default gen_random_uuid(),
  court_code  text references public.courts (code) on delete cascade,  -- null: all courts
  alias       text not null,       -- normalised: upper case, no dots or spaces
  canonical   text not null,       -- normalised
  created_at  timestamptz not null default now()
);

create unique index if not exists case_type_aliases_alias_idx on public.case_type_aliases (coalesce(court_code, ''), alias);

alter table public.case_type_aliases enable row level security;

create policy "Everyone signed in can read case-type aliases"
  on public.case_type_aliases for select to authenticated using (true);

revoke insert, update, delete on public.case_type_aliases from anon, authenticated;

-- Same list as causelists.DEFAULT_CASE_TYPE_ALIASES (tests/test_causelists.py checks they agree).
insert into public.case_type_aliases (court_code, alias, canonical) values
  (null, 'WRITPETITION(CIVIL)', 'WP(C)'),
  (null, 'WRITPETITION(C)', 'WP(C)'),
  (null, 'WRITPETITION(CRIMINAL)', 'WP(CRL)'),
  (null, 'WP(CRIMINAL)', 'WP(CRL)'),
  (null, 'SPECIALLEAVEPETITION(CIVIL)', 'SLP(C)'),
  (null, 'SPECIALLEAVEPETITION(C)', 'SLP(C)'),
  (null, 'SPECIALLEAVEPETITION(CRIMINAL)', 'SLP(CRL)'),
  (null, 'SLP(CRIMINAL)', 'SLP(CRL)'),
  (null, 'CIVILAPPEAL', 'CA'),
  (null, 'CRIMINALAPPEAL', 'CRLA'),
  (null, 'CRLAPPEAL', 'CRLA'),
  (null, 'LETTERSPATENTAPPEAL', 'LPA'),
  (null, 'BAILAPPLICATION', 'BAILAPPLN'),
  (null, 'BAILAPPL', 'BAILAPPLN'),
  (null, 'CONTEMPTCASE(CIVIL)', 'CONTCAS(C)'),
  (null, 'CONTEMPTCASE(C)', 'CONTCAS(C)'),
  (null, 'CONTEMPTPETITION(CIVIL)', 'CONMT(C)'),
  (null, 'TRANSFERPETITION(CIVIL)', 'TP(C)'),
  (null, 'TRANSFERPETITION(CRIMINAL)', 'TP(CRL)'),
  (null, 'CRIMINALMISCCASE', 'CRLMC'),
  (null, 'CRLMISC(MAIN)', 'CRLMC'),
  (null, 'CIVILSUIT(COMM)', 'CS(COMM)'),
  (null, 'COMMERCIALSUIT', 'CS(COMM)'),
  (null, 'REGULARFIRSTAPPEAL', 'RFA'),
  (null, 'REGULARSECONDAPPEAL', 'RSA'),
  (null, 'DIARYNO', 'DIARY')
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- 5. A matter's default fallback advocate
-- ---------------------------------------------------------------------------
alter table public.court_cases
  add column if not exists fallback_advocate_id uuid references public.users (id) on delete set null;
