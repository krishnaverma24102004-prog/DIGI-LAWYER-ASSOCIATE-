-- Hearing operations: the clash board with reach estimates (P04) and hearing briefs (P47).
-- Runs after 016 (cause_lists, cause_list_items, listing_matches) and 014 (courts).
--
-- 1. bench_rosters: roster periods of a courtroom, derived by each firm from the benches it sees
--    sitting (a new period starts when a different bench sits in the courtroom).
-- 2. appearance_logs: a junior's taps in court (bench assembled / item called / court rose). A
--    'called' tap stores its position in the day's printed list, the elapsed sitting minutes
--    (lunch excluded) and the pace E / max(P, 3) that the reach estimates are built from.
--    Per-judge pace statistics never leave the firm: every row is org-scoped, there is no shared
--    (org_id null) row, no cross-org pooling and no export route.
-- 3. complex_travel_times: the firm's travel matrix between court complexes.
-- 4. advocate_clash_prefs: 'treat possible clashes without data as clashes' (standing or per
--    day), and whether the member is an enrolled advocate available as a proxy (set by seniors).
-- 5. case_counsel: who is on the vakalatnama for a court case (a proxy who is not needs a memo
--    of appearance).
-- 6. hearing_outcomes: what happened at each hearing; the adjournment counter per party.
-- 7. hearing_briefs: one brief per court case and hearing date (regenerated when a new order
--    arrives). Visible to whoever can see the court case, so ethical walls on court_cases hold.

-- ---------------------------------------------------------------------------
-- 1. Roster periods
-- ---------------------------------------------------------------------------
create table if not exists public.bench_rosters (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  court_code   text not null references public.courts (code) on delete cascade,
  courtroom    text not null check (char_length(courtroom) between 1 and 40),
  bench_key    text not null check (char_length(bench_key) between 1 and 200),
  bench_label  text check (char_length(bench_label) <= 300),
  started_on   date not null,
  created_at   timestamptz not null default now(),
  unique (org_id, court_code, courtroom, started_on)
);

create index if not exists bench_rosters_room_idx on public.bench_rosters (org_id, court_code, courtroom, started_on);

-- ---------------------------------------------------------------------------
-- 2. Appearance logs
-- ---------------------------------------------------------------------------
create table if not exists public.appearance_logs (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  logged_by            uuid not null default auth.uid() references public.users (id) on delete cascade,
  court_code           text not null references public.courts (code) on delete cascade,
  courtroom            text not null check (char_length(courtroom) between 1 and 40),
  list_date            date not null,
  tap_kind             text not null check (tap_kind in ('assembled', 'called', 'rose')),
  tapped_at            timestamptz not null default now(),
  item_id              uuid references public.cause_list_items (id) on delete set null,
  court_case_id        uuid references public.court_cases (id) on delete set null,
  appeared_by          uuid references public.users (id) on delete set null,  -- the advocate who appeared
  bench_key            text,           -- null: the list's bench header wasn't parsed ('bench unknown')
  roster_period_id     uuid references public.bench_rosters (id) on delete set null,
  segment              text check (segment in ('fresh', 'after_notice', 'regular', 'supplementary', 'advance', 'other')),
  position             integer check (position > 0),       -- called: the item's position; rose: the position reached
  elapsed_sitting_min  numeric(7, 2) check (elapsed_sitting_min >= 0),
  pace                 numeric(9, 4) check (pace >= 0),     -- elapsed / max(position, 3)
  created_at           timestamptz not null default now(),
  check (tap_kind <> 'called' or (position is not null and elapsed_sitting_min is not null and pace is not null)),
  check (tap_kind <> 'rose' or position is not null)
);

-- First call only: a pass-over and recall keeps the first 'called' tap.
create unique index if not exists appearance_logs_first_call_idx
  on public.appearance_logs (org_id, item_id) where tap_kind = 'called' and item_id is not null;
create unique index if not exists appearance_logs_day_tap_idx
  on public.appearance_logs (org_id, court_code, courtroom, list_date, tap_kind) where tap_kind in ('assembled', 'rose');
create index if not exists appearance_logs_room_idx on public.appearance_logs (org_id, court_code, courtroom, list_date);
create index if not exists appearance_logs_case_idx on public.appearance_logs (court_case_id) where court_case_id is not null;

-- ---------------------------------------------------------------------------
-- 3. Travel times between court complexes (stored once per unordered pair)
-- ---------------------------------------------------------------------------
create table if not exists public.complex_travel_times (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  from_complex  text not null check (char_length(from_complex) between 1 and 200),
  to_complex    text not null check (char_length(to_complex) between 1 and 200),
  minutes       integer not null check (minutes between 0 and 600),
  updated_by    uuid default auth.uid() references public.users (id) on delete set null,
  updated_at    timestamptz not null default now(),
  check (from_complex <= to_complex),
  unique (org_id, from_complex, to_complex)
);

-- ---------------------------------------------------------------------------
-- 4. Clash preferences and proxy availability
-- ---------------------------------------------------------------------------
create table if not exists public.advocate_clash_prefs (
  id                    uuid primary key default gen_random_uuid(),
  org_id                uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id               uuid not null default auth.uid() references public.users (id) on delete cascade,
  amber_as_clash        boolean not null default false,       -- standing preference
  amber_as_clash_dates  date[] not null default '{}',         -- 'treat as clash' for these days
  enrolled              boolean not null default true,        -- an enrolled advocate who may appear as proxy
  seniority             smallint check (seniority between 1 and 3),  -- null: from the firm role
  updated_at            timestamptz not null default now(),
  unique (org_id, user_id)
);

-- Members set their own clash preferences; only owners and partners set enrolment and seniority.
create or replace function public.guard_clash_prefs()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user not in ('anon', 'authenticated') then
    return new;
  end if;
  if not public.has_org_role(new.org_id, array['owner', 'partner']) then
    if tg_op = 'INSERT' then
      new.enrolled := true;
      new.seniority := null;
    else
      new.enrolled := old.enrolled;
      new.seniority := old.seniority;
    end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists advocate_clash_prefs_guard on public.advocate_clash_prefs;
create trigger advocate_clash_prefs_guard
  before insert or update on public.advocate_clash_prefs
  for each row execute function public.guard_clash_prefs();

-- ---------------------------------------------------------------------------
-- 5. Counsel on record
-- ---------------------------------------------------------------------------
create table if not exists public.case_counsel (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  court_case_id   uuid not null references public.court_cases (id) on delete cascade,
  user_id         uuid not null references public.users (id) on delete cascade,
  on_vakalatnama  boolean not null default false,
  created_at      timestamptz not null default now(),
  unique (court_case_id, user_id)
);

-- ---------------------------------------------------------------------------
-- 6. Hearing outcomes (adjournment counter)
-- ---------------------------------------------------------------------------
create table if not exists public.hearing_outcomes (
  id                        uuid primary key default gen_random_uuid(),
  org_id                    uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  court_case_id             uuid not null references public.court_cases (id) on delete cascade,
  hearing_date              date not null,
  outcome                   text not null check (outcome in ('heard', 'adjourned', 'passed_over', 'not_reached', 'part_heard',
                                                             'reserved', 'disposed', 'other')),
  adjourned_at_instance_of  text check (adjourned_at_instance_of in ('petitioner', 'respondent', 'both', 'court', 'unknown')),
  note                      text check (char_length(note) <= 1000),
  recorded_by               uuid default auth.uid() references public.users (id) on delete set null,
  created_at                timestamptz not null default now(),
  check (outcome = 'adjourned' or adjourned_at_instance_of is null),
  unique (court_case_id, hearing_date)
);

-- ---------------------------------------------------------------------------
-- 7. Hearing briefs
-- ---------------------------------------------------------------------------
create table if not exists public.hearing_briefs (
  id                    uuid primary key default gen_random_uuid(),
  org_id                uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  court_case_id         uuid not null references public.court_cases (id) on delete cascade,
  hearing_date          date not null,
  listing_match_id      uuid references public.listing_matches (id) on delete set null,
  trigger               text not null check (trigger in ('listing_match', 'next_hearing_date', 'manual')),
  order_key             text,          -- identifies the order the AI section was built from
  order_date            date,
  sections              jsonb not null default '{}'::jsonb,   -- deterministic sections
  ai_section            jsonb,                                -- directions with verified quotes
  ai_status             text not null check (ai_status in ('done', 'not_configured', 'no_order', 'unreliable_text', 'failed')),
  discarded_unverified  integer not null default 0 check (discarded_unverified >= 0),
  generated_by          uuid references public.users (id) on delete set null,  -- null: the nightly job
  generated_at          timestamptz not null default now(),
  unique (court_case_id, hearing_date)
);

create index if not exists hearing_briefs_org_date_idx on public.hearing_briefs (org_id, hearing_date);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
alter table public.bench_rosters        enable row level security;
alter table public.appearance_logs      enable row level security;
alter table public.complex_travel_times enable row level security;
alter table public.advocate_clash_prefs enable row level security;
alter table public.case_counsel         enable row level security;
alter table public.hearing_outcomes     enable row level security;
alter table public.hearing_briefs       enable row level security;

-- Roster periods and appearance logs: the whole firm reads them (estimates pool every call the
-- firm logged); members log taps as themselves; nothing is shared with other firms.
create policy "Members read their firm's roster periods"
  on public.bench_rosters for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members record roster periods"
  on public.bench_rosters for insert to authenticated
  with check (org_id = (select public.active_org_id()));

create policy "Members read their firm's appearance logs"
  on public.appearance_logs for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members log taps as themselves"
  on public.appearance_logs for insert to authenticated
  with check (org_id = (select public.active_org_id()) and logged_by = (select auth.uid()));

create policy "The logger or a senior removes a mistaken tap"
  on public.appearance_logs for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (logged_by = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

revoke update on public.appearance_logs from anon, authenticated;
revoke update, delete on public.bench_rosters from anon, authenticated;

create policy "Members read the travel matrix"
  on public.complex_travel_times for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members add travel times"
  on public.complex_travel_times for insert to authenticated
  with check (org_id = (select public.active_org_id()));

create policy "Members correct travel times"
  on public.complex_travel_times for update to authenticated
  using (org_id = (select public.active_org_id()))
  with check (org_id = (select public.active_org_id()));

create policy "Seniors remove travel times"
  on public.complex_travel_times for delete to authenticated
  using (org_id = (select public.active_org_id())
         and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])));

create policy "Members read the firm's clash preferences"
  on public.advocate_clash_prefs for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members set their own preferences; seniors set anyone's"
  on public.advocate_clash_prefs for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Members update their own preferences; seniors anyone's"
  on public.advocate_clash_prefs for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

revoke delete on public.advocate_clash_prefs from anon, authenticated;

-- Counsel, outcomes and briefs follow the court case: visible and writable to whoever can see it.
create policy "Counsel on cases the member can see"
  on public.case_counsel for select to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id));

create policy "Record counsel on visible cases"
  on public.case_counsel for insert to authenticated
  with check (org_id = (select public.active_org_id())
              and exists (select 1 from public.court_cases c where c.id = case_counsel.court_case_id and c.org_id = case_counsel.org_id));

create policy "Update counsel on visible cases"
  on public.case_counsel for update to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id))
  with check (org_id = (select public.active_org_id()));

create policy "Remove counsel on visible cases"
  on public.case_counsel for delete to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id));

create policy "Outcomes of visible cases"
  on public.hearing_outcomes for select to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id));

create policy "Record outcomes of visible cases"
  on public.hearing_outcomes for insert to authenticated
  with check (org_id = (select public.active_org_id())
              and exists (select 1 from public.court_cases c where c.id = hearing_outcomes.court_case_id and c.org_id = hearing_outcomes.org_id));

create policy "Correct outcomes of visible cases"
  on public.hearing_outcomes for update to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id))
  with check (org_id = (select public.active_org_id()));

revoke delete on public.hearing_outcomes from anon, authenticated;

create policy "Briefs of visible cases"
  on public.hearing_briefs for select to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id));

create policy "Generate briefs of visible cases"
  on public.hearing_briefs for insert to authenticated
  with check (org_id = (select public.active_org_id())
              and exists (select 1 from public.court_cases c where c.id = hearing_briefs.court_case_id and c.org_id = hearing_briefs.org_id));

create policy "Regenerate briefs of visible cases"
  on public.hearing_briefs for update to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.court_cases c where c.id = court_case_id))
  with check (org_id = (select public.active_org_id()));

revoke delete on public.hearing_briefs from anon, authenticated;
