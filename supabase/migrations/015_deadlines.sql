-- Firm docket (P13): deadlines with their rule and inputs, an owner and a backup, a reminder
-- ladder with escalation, and a blind second check.
--
-- * A deadline rests on dates someone typed (an order date, the day a certified copy was
--   received). A second member re-enters those inputs without seeing the first entry; if both
--   agree the deadline is 'verified', otherwise 'disputed' and the earlier date governs. A firm
--   with nobody eligible re-enters its own inputs at least 12 hours later ('self_verified',
--   never shown as verified).
-- * Blindness is enforced here, not in one endpoint: clients have no direct access to
--   deadlines, deadline_entries, deadline_reminders or deadline_value_views. Reads go through
--   list_deadlines / get_deadline / my_deadline_entries / my_deadline_reminders, which mask the
--   date, candidates, inputs, basis, title and reminders for the assigned checker while the
--   check is pending. Writes go through create_deadline, submit_deadline_entry,
--   acknowledge_deadline_reminder, complete_deadline and reassign_deadline_check.
-- * The checker is chosen inside create_deadline, before anyone but the maker has seen the
--   values. Every unmasked read and every reminder delivery is recorded in
--   deadline_value_views, and nobody with such a row is ever chosen as checker.
-- * Blindness covers the deadline record only. The checker can (and should) read the matter's
--   source record: court_cases hearing and order dates, case threads, /workflows outputs.
-- * Reminders are issued by the hourly sweep (services/deadline_service.run_sweep, service
--   role, one org at a time): the ladder, leave routing, escalation, and the safety rule that
--   cancels a pending check before any reminder would reach the checker or when the due date
--   is within the deadline's safety_lead_days.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
create table if not exists public.deadlines (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid not null references public.organizations (id) on delete cascade,
  court_case_id        uuid references public.court_cases (id) on delete set null,
  thread_id            uuid references public.case_threads (id) on delete set null,
  kind                 text not null check (kind ~ '^[a-z0-9_]{2,60}$'),   -- e.g. appeal, written_statement
  title                text not null check (char_length(title) between 1 and 300),
  rule_id              text check (char_length(rule_id) <= 120),
  rule_version         integer check (rule_version > 0),
  basis                text not null default '' check (char_length(basis) <= 2000),
  hard                 boolean not null default false,       -- no condonation: daily reminders from T-5
  source               text not null check (source in ('engine', 'manual', 'cause_list', 'ai_proposed')),
  owner_id             uuid references public.users (id) on delete set null,
  backup_id            uuid references public.users (id) on delete set null,
  checker_id           uuid references public.users (id) on delete set null,
  created_by           uuid references public.users (id) on delete set null,
  check_mode           text not null default 'second' check (check_mode in ('second', 'self')),
  check_state          text not null default 'pending' check (check_state in ('none', 'pending', 'submitted', 'cancelled')),
  check_opens_at       timestamptz,
  check_note           text,     -- why the check fell back to self re-entry or couldn't be assigned
  check_cancel_reason  text,
  verification         text not null default 'unverified'
                       check (verification in ('unverified', 'verified', 'self_verified', 'disputed')),
  status               text not null default 'open' check (status in ('open', 'done')),
  candidates           date[] not null,                     -- every plausible date; the earliest governs
  effective_due_date   date not null,
  safety_lead_days     integer not null default 3 check (safety_lead_days between 0 and 60),
  done_at              timestamptz,
  done_by              uuid references public.users (id) on delete set null,
  done_evidence        text check (char_length(done_evidence) <= 2000),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  check (cardinality(candidates) >= 1)
);

create index if not exists deadlines_org_due_idx on public.deadlines (org_id, status, effective_due_date);
create index if not exists deadlines_checker_idx on public.deadlines (checker_id) where check_state = 'pending';
create index if not exists deadlines_court_case_idx on public.deadlines (court_case_id);
create index if not exists deadlines_thread_idx on public.deadlines (thread_id);

create trigger deadlines_set_updated_at
  before update on public.deadlines
  for each row execute function public.set_updated_at();

create table if not exists public.deadline_entries (
  id             uuid primary key default gen_random_uuid(),
  deadline_id    uuid not null references public.deadlines (id) on delete cascade,
  org_id         uuid not null references public.organizations (id) on delete cascade,
  entered_by     uuid references public.users (id) on delete set null,
  entered_at     timestamptz not null default now(),
  kind           text not null check (kind in ('first', 'check', 'self')),
  inputs         jsonb not null default '{}'::jsonb check (jsonb_typeof(inputs) = 'object'),
  computed_date  date not null
);

create index if not exists deadline_entries_deadline_idx on public.deadline_entries (deadline_id, entered_at);

create table if not exists public.deadline_reminders (
  id               uuid primary key default gen_random_uuid(),
  deadline_id      uuid not null references public.deadlines (id) on delete cascade,
  org_id           uuid not null references public.organizations (id) on delete cascade,
  target_id        uuid not null references public.users (id) on delete cascade,
  rung             text not null,          -- T-30 ... T-0, T+n when overdue
  for_date         date not null,          -- the due date the reminder was about
  level            smallint not null default 0 check (level between 0 and 2),  -- 0 ladder, 1 backup, 2 partner
  parent_id        uuid references public.deadline_reminders (id) on delete set null,
  channel          text not null default 'in_app' check (channel in ('in_app', 'whatsapp', 'email')),
  payload_class    text not null default 'member' check (payload_class in ('member', 'content_free')),
  issued_at        timestamptz not null default now(),
  delivered_at     timestamptz,
  acknowledged_at  timestamptz,
  acknowledged_by  uuid references public.users (id) on delete set null,
  escalated_at     timestamptz,
  unique (deadline_id, for_date, rung, level, target_id)
);

create index if not exists deadline_reminders_open_idx on public.deadline_reminders (org_id, target_id) where acknowledged_at is null;

create table if not exists public.deadline_value_views (
  deadline_id    uuid not null references public.deadlines (id) on delete cascade,
  user_id        uuid not null references public.users (id) on delete cascade,
  via            text not null check (via in ('entry', 'read', 'reminder')),
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  primary key (deadline_id, user_id)
);

create table if not exists public.member_absences (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id     uuid not null default auth.uid() references public.users (id) on delete cascade,
  starts_on   date not null,
  ends_on     date not null,
  note        text check (char_length(note) <= 300),
  created_by  uuid default auth.uid() references public.users (id) on delete set null,
  created_at  timestamptz not null default now(),
  check (ends_on >= starts_on and ends_on - starts_on <= 366)
);

create index if not exists member_absences_org_idx on public.member_absences (org_id, user_id, ends_on);

alter table public.deadlines enable row level security;
alter table public.deadline_entries enable row level security;
alter table public.deadline_reminders enable row level security;
alter table public.deadline_value_views enable row level security;
alter table public.member_absences enable row level security;

-- No policies and no grants: the docket tables are reachable only through the functions below.
revoke all on public.deadlines, public.deadline_entries, public.deadline_reminders, public.deadline_value_views
  from public, anon, authenticated;
grant all on public.deadlines, public.deadline_entries, public.deadline_reminders, public.deadline_value_views
  to service_role;

-- Absences: everyone in the firm sees who is away (reminders are routed around them); members
-- record their own leave, owners and partners anyone's.
create policy "Members see the firm's absences"
  on public.member_absences for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Members record leave"
  on public.member_absences for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and public.is_org_member_user(org_id, user_id)
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Members remove leave"
  on public.member_absences for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

revoke update on public.member_absences from anon, authenticated;

-- ---------------------------------------------------------------------------
-- Internal helpers (not callable by clients)
-- ---------------------------------------------------------------------------
-- India has one zone and no daylight saving, so a fixed offset is exact (and needs no tz database).
create or replace function public.ist_today()
returns date
language sql
stable
set search_path = ''
as $$
  select ((now() at time zone 'UTC') + interval '5 hours 30 minutes')::date
$$;

create or replace function public.member_absent(p_org uuid, p_user uuid, p_day date)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.member_absences a
    where a.org_id = p_org and a.user_id = p_user and p_day between a.starts_on and a.ends_on
  )
$$;

create or replace function public.deadline_masked(p_mode text, p_state text, p_checker uuid, p_uid uuid)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select coalesce(p_mode = 'second' and p_state = 'pending' and p_checker = p_uid, false)
$$;

-- Owners and partners see the firm's docket; others the deadlines they own, back up, check or made.
create or replace function public.deadline_visible(d public.deadlines, p_uid uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(
    d.org_id = public.active_org_id()
    and (public.has_org_role(d.org_id, array['owner', 'partner'])
         or p_uid = d.owner_id or p_uid = d.backup_id or p_uid = d.checker_id or p_uid = d.created_by),
    false)
$$;

create or replace function public.user_brief(p_user uuid)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select case when p_user is null then null else
    (select jsonb_build_object('id', u.id, 'name', coalesce(nullif(u.full_name, ''), u.email))
     from public.users u where u.id = p_user)
  end
$$;

create or replace function public.record_deadline_views(p_ids uuid[], p_uid uuid, p_via text)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
  insert into public.deadline_value_views (deadline_id, user_id, via)
  select d.id, p_uid, p_via from public.deadlines d
  where d.id = any (p_ids) and not public.deadline_masked(d.check_mode, d.check_state, d.checker_id, p_uid)
  on conflict (deadline_id, user_id) do update set last_seen_at = now()
$$;

-- The eligible checker for a deadline: another member of the firm, associate or above, with
-- access to the matter, not absent today, not the owner or the maker, who has never seen the
-- deadline's values. Preferably not the backup or the matter's own lawyer, and the least loaded.
-- p_ignore_views tells "nobody eligible" apart from "everyone eligible has already looked".
create or replace function public.deadline_pick_checker(p_deadline uuid, p_exclude uuid default null,
                                                        p_ignore_views boolean default false)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select m.user_id
  from public.deadlines d
  join public.organization_members m on m.org_id = d.org_id
  left join public.court_cases c on c.id = d.court_case_id
  left join public.case_threads t on t.id = d.thread_id
  where d.id = p_deadline
    and m.role in ('owner', 'partner', 'associate')
    and m.user_id is distinct from d.owner_id
    and m.user_id is distinct from d.created_by
    and m.user_id is distinct from p_exclude
    and not public.member_absent(d.org_id, m.user_id, public.ist_today())
    and (p_ignore_views or not exists (
      select 1 from public.deadline_value_views v where v.deadline_id = d.id and v.user_id = m.user_id))
    and not exists (select 1 from public.deadline_entries e where e.deadline_id = d.id and e.entered_by = m.user_id)
    and (m.role in ('owner', 'partner')
         or (d.court_case_id is null and d.thread_id is null)
         or c.user_id = m.user_id or t.user_id = m.user_id)
  order by (m.user_id is not distinct from d.backup_id),
           (m.user_id is not distinct from coalesce(c.user_id, t.user_id)),
           (select count(*) from public.deadlines o
            where o.checker_id = m.user_id and o.check_mode = 'second' and o.check_state = 'pending'),
           m.created_at, m.user_id
  limit 1
$$;

-- Assigns (or reassigns) the check: a second member if one is eligible, else a blind self
-- re-entry by the maker opening 12 hours later, else no check (the deadline stays unverified).
-- Returns the resulting check mode, or 'cancelled'.
create or replace function public.deadline_assign_check(p_deadline uuid, p_exclude uuid default null)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  d public.deadlines;
  v_checker uuid;
  v_note text;
begin
  select * into d from public.deadlines where id = p_deadline for update;
  if not found then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  v_checker := public.deadline_pick_checker(p_deadline, p_exclude);
  if v_checker is not null then
    update public.deadlines
    set check_mode = 'second', checker_id = v_checker, check_state = 'pending', check_opens_at = now(),
        check_note = null, check_cancel_reason = null
    where id = p_deadline;
    return 'second';
  end if;

  v_note := case when public.deadline_pick_checker(p_deadline, p_exclude, true) is not null
                 then 'all_eligible_viewed' else 'no_eligible_checker' end;
  if d.created_by is not null
     and public.org_role_of(d.org_id, d.created_by) in ('owner', 'partner', 'associate')
     and not exists (select 1 from public.deadline_entries e where e.deadline_id = d.id and e.kind = 'self') then
    update public.deadlines
    set check_mode = 'self', checker_id = d.created_by, check_state = 'pending',
        check_opens_at = now() + interval '12 hours', check_note = v_note, check_cancel_reason = null
    where id = p_deadline;
    return 'self';
  end if;
  update public.deadlines
  set check_state = 'cancelled', check_note = v_note, check_cancel_reason = v_note
  where id = p_deadline;
  return 'cancelled';
end;
$$;

create or replace function public.org_role_of(p_org uuid, p_user uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select m.role from public.organization_members m where m.org_id = p_org and m.user_id = p_user
$$;

-- One deadline as `p_uid` may see it.
create or replace function public.deadline_json(p_id uuid, p_uid uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  d public.deadlines;
  v_masked boolean;
  v_first public.deadline_entries;
  v_label text;
  v_covered jsonb;
  v_reminder jsonb;
  v_status text;
begin
  select * into d from public.deadlines where id = p_id;
  if not found then
    return null;
  end if;
  v_masked := public.deadline_masked(d.check_mode, d.check_state, d.checker_id, p_uid);
  select * into v_first from public.deadline_entries e
  where e.deadline_id = p_id and e.kind = 'first' order by e.entered_at limit 1;
  v_label := coalesce((select c.title from public.court_cases c where c.id = d.court_case_id),
                      (select t.title from public.case_threads t where t.id = d.thread_id));
  if d.status = 'open' and d.owner_id is not null and d.backup_id is not null
     and public.member_absent(d.org_id, d.owner_id, public.ist_today()) then
    v_covered := public.user_brief(d.backup_id);
  end if;
  if not v_masked then
    select jsonb_build_object('id', r.id, 'rung', r.rung, 'level', r.level, 'target', public.user_brief(r.target_id),
                              'channel', r.channel, 'issued_at', r.issued_at, 'delivered_at', r.delivered_at,
                              'acknowledged_at', r.acknowledged_at)
      into v_reminder
    from public.deadline_reminders r where r.deadline_id = p_id order by r.issued_at desc limit 1;
  end if;
  v_status := case
    when v_masked then 'awaiting_your_check'
    when d.status = 'done' then 'done'
    when d.effective_due_date < public.ist_today() then 'overdue'
    when d.verification = 'disputed' then 'disputed'
    when d.verification = 'verified' then 'verified'
    when d.verification = 'self_verified' then 'self_verified'
    when d.source = 'ai_proposed' then 'ai_proposed'
    when d.check_state = 'pending' then 'awaiting_check'
    else 'unverified'
  end;
  return jsonb_build_object(
    'id', d.id,
    'org_id', d.org_id,
    'kind', d.kind,
    'title', case when v_masked then null else d.title end,
    'matter', jsonb_build_object('court_case_id', d.court_case_id, 'thread_id', d.thread_id, 'label', v_label),
    'effective_due_date', case when v_masked then null else d.effective_due_date end,
    'candidates', case when v_masked then null else to_jsonb(d.candidates) end,
    'candidate_count', case when v_masked then null else cardinality(d.candidates) end,
    'inputs', case when v_masked then null else v_first.inputs end,
    'input_fields', coalesce((select jsonb_agg(k order by k) from jsonb_object_keys(v_first.inputs) k), '[]'::jsonb),
    'basis', case when v_masked then null else d.basis end,
    'rule_id', d.rule_id,
    'rule_version', d.rule_version,
    'hard', d.hard,
    'source', d.source,
    'owner', public.user_brief(d.owner_id),
    'backup', public.user_brief(d.backup_id),
    'checker', public.user_brief(d.checker_id),
    'created_by', d.created_by,
    'check_mode', d.check_mode,
    'check_state', d.check_state,
    'check_opens_at', d.check_opens_at,
    'check_note', d.check_note,
    'check_cancel_reason', d.check_cancel_reason,
    'verification', d.verification,
    'status', d.status,
    'display_status', v_status,
    'covered_by', v_covered,
    'safety_lead_days', d.safety_lead_days,
    'latest_reminder', v_reminder,
    'masked', v_masked,
    'is_checker', coalesce(d.checker_id = p_uid and d.check_state = 'pending', false),
    'can_check', coalesce(d.checker_id = p_uid and d.check_state = 'pending' and d.status = 'open'
                          and d.check_opens_at <= now(), false),
    'created_at', d.created_at,
    'done_at', d.done_at,
    'done_evidence', case when v_masked then null else d.done_evidence end
  );
end;
$$;

-- ---------------------------------------------------------------------------
-- Writes
-- ---------------------------------------------------------------------------
create or replace function public.create_deadline(
  p_kind text, p_title text, p_due_date date, p_owner uuid,
  p_court_case uuid default null, p_thread uuid default null,
  p_rule_id text default null, p_rule_version integer default null, p_basis text default '',
  p_inputs jsonb default '{}'::jsonb, p_hard boolean default false, p_source text default 'engine',
  p_candidates date[] default null, p_safety_lead_days integer default 3, p_backup uuid default null
)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  v_senior boolean;
  v_backup uuid := p_backup;
  v_candidates date[];
  v_id uuid;
begin
  if v_uid is null or v_org is null then
    raise exception 'Not a member of this organization' using errcode = '42501';
  end if;
  if p_due_date is null then
    raise exception 'A deadline needs a due date' using errcode = '22023';
  end if;
  if p_owner is null or public.org_role_of(v_org, p_owner) is null then
    raise exception 'The owner must be a member of this organization' using errcode = '22023';
  end if;
  if p_inputs is null or jsonb_typeof(p_inputs) <> 'object' then
    raise exception 'Inputs must be an object of named values' using errcode = '22023';
  end if;
  v_senior := public.has_org_role(v_org, array['owner', 'partner']);
  if p_court_case is not null and not exists (
       select 1 from public.court_cases c where c.id = p_court_case and c.org_id = v_org and (v_senior or c.user_id = v_uid)) then
    raise exception 'Court case not found' using errcode = 'P0002';
  end if;
  if p_thread is not null and not exists (
       select 1 from public.case_threads t where t.id = p_thread and t.org_id = v_org and (v_senior or t.user_id = v_uid)) then
    raise exception 'Case thread not found' using errcode = 'P0002';
  end if;

  if v_backup is not null then
    if v_backup = p_owner or public.org_role_of(v_org, v_backup) is null then
      raise exception 'The backup must be another member of this organization' using errcode = '22023';
    end if;
  else
    -- The maker if someone else owns it, else a senior, else any advocate; never someone on leave.
    select m.user_id into v_backup
    from public.organization_members m
    where m.org_id = v_org and m.user_id <> p_owner and m.role in ('owner', 'partner', 'associate')
      and not public.member_absent(v_org, m.user_id, public.ist_today())
    order by (m.user_id = v_uid) desc, (m.role in ('owner', 'partner')) desc, m.created_at, m.user_id
    limit 1;
  end if;

  select array_agg(x order by x) into v_candidates
  from (select distinct x from unnest(array[p_due_date] || coalesce(p_candidates, '{}'::date[])) x where x is not null) s;

  insert into public.deadlines (org_id, court_case_id, thread_id, kind, title, rule_id, rule_version, basis, hard,
                                source, owner_id, backup_id, created_by, candidates, effective_due_date, safety_lead_days)
  values (v_org, p_court_case, p_thread, p_kind, p_title, p_rule_id, p_rule_version, coalesce(p_basis, ''),
          coalesce(p_hard, false), p_source, p_owner, v_backup, v_uid, v_candidates, v_candidates[1],
          coalesce(p_safety_lead_days, 3))
  returning id into v_id;

  insert into public.deadline_entries (deadline_id, org_id, entered_by, kind, inputs, computed_date)
  values (v_id, v_org, v_uid, 'first', p_inputs, p_due_date);

  -- Chosen now, before anyone but the maker has seen the values.
  perform public.deadline_assign_check(v_id, null);
  perform public.record_deadline_views(array[v_id], v_uid, 'entry');
  return public.deadline_json(v_id, v_uid);
end;
$$;

-- The checker's blind re-entry (or the maker's self re-entry once it opens). The engine's date
-- from both entries is compared: agreement verifies, disagreement disputes and the earliest
-- candidate governs.
create or replace function public.submit_deadline_entry(p_id uuid, p_inputs jsonb, p_computed date)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  d public.deadlines;
  v_first public.deadline_entries;
  v_agree boolean;
  v_candidates date[];
begin
  select * into d from public.deadlines where id = p_id and org_id = v_org for update;
  if not found or not public.deadline_visible(d, v_uid) then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  if d.checker_id is distinct from v_uid then
    raise exception 'You are not assigned to check this deadline' using errcode = '42501';
  end if;
  if d.check_state <> 'pending' or d.status <> 'open' then
    raise exception 'This check is no longer open (%)', coalesce(d.check_cancel_reason, d.check_state)
      using errcode = '55000';
  end if;
  if d.check_opens_at > now() then
    raise exception 'check_not_open' using errcode = '55000',
      hint = 'Self re-entry opens at ' || to_char((d.check_opens_at at time zone 'UTC') + interval '5 hours 30 minutes', 'DD Mon HH24:MI') || ' IST';
  end if;
  if p_computed is null or p_inputs is null or jsonb_typeof(p_inputs) <> 'object' then
    raise exception 'Re-enter the inputs and the date they give' using errcode = '22023';
  end if;

  select * into v_first from public.deadline_entries e
  where e.deadline_id = p_id and e.kind = 'first' order by e.entered_at limit 1;
  insert into public.deadline_entries (deadline_id, org_id, entered_by, kind, inputs, computed_date)
  values (p_id, v_org, v_uid, case when d.check_mode = 'self' then 'self' else 'check' end, p_inputs, p_computed);

  v_agree := v_first.computed_date = p_computed and v_first.inputs = p_inputs;
  select array_agg(x order by x) into v_candidates
  from (select distinct x from unnest(d.candidates || p_computed) x) s;
  update public.deadlines
  set check_state = 'submitted',
      verification = case when not v_agree then 'disputed'
                          when d.check_mode = 'self' then 'self_verified' else 'verified' end,
      candidates = v_candidates,
      effective_due_date = v_candidates[1]
  where id = p_id;
  perform public.record_deadline_views(array[p_id], v_uid, 'entry');
  return public.deadline_json(p_id, v_uid);
end;
$$;

-- Acknowledging any reminder acknowledges every open reminder of that deadline (someone is on it).
create or replace function public.acknowledge_deadline_reminder(p_reminder uuid)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  r public.deadline_reminders;
  d public.deadlines;
  v_count integer;
begin
  select * into r from public.deadline_reminders where id = p_reminder and org_id = v_org;
  if not found then
    raise exception 'Reminder not found' using errcode = 'P0002';
  end if;
  select * into d from public.deadlines where id = r.deadline_id;
  if r.target_id is distinct from v_uid
     and not (public.deadline_visible(d, v_uid) and not public.deadline_masked(d.check_mode, d.check_state, d.checker_id, v_uid)) then
    raise exception 'Reminder not found' using errcode = 'P0002';
  end if;
  update public.deadline_reminders
  set acknowledged_at = now(), acknowledged_by = v_uid, delivered_at = coalesce(delivered_at, now())
  where deadline_id = r.deadline_id and acknowledged_at is null and issued_at <= now();
  get diagnostics v_count = row_count;
  return jsonb_build_object('deadline_id', r.deadline_id, 'acknowledged', v_count);
end;
$$;

create or replace function public.complete_deadline(p_id uuid, p_evidence text)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  d public.deadlines;
begin
  select * into d from public.deadlines where id = p_id and org_id = v_org for update;
  if not found or not public.deadline_visible(d, v_uid) then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  if public.deadline_masked(d.check_mode, d.check_state, d.checker_id, v_uid) then
    raise exception 'Submit your check first' using errcode = '42501';
  end if;
  if not (v_uid = d.owner_id or v_uid = d.backup_id or public.has_org_role(v_org, array['owner', 'partner'])) then
    raise exception 'Only the owner, the backup or a partner can mark this done' using errcode = '42501';
  end if;
  if d.status = 'done' then
    raise exception 'Already done' using errcode = '55000';
  end if;
  if char_length(btrim(coalesce(p_evidence, ''))) < 3 then
    raise exception 'Say how it was done (filing number, diary number, receipt)' using errcode = '22023';
  end if;
  update public.deadlines
  set status = 'done', done_at = now(), done_by = v_uid, done_evidence = left(btrim(p_evidence), 2000),
      check_state = case when check_state = 'pending' then 'cancelled' else check_state end,
      check_cancel_reason = case when check_state = 'pending' then 'completed' else check_cancel_reason end
  where id = p_id;
  update public.deadline_reminders set acknowledged_at = now(), acknowledged_by = v_uid
  where deadline_id = p_id and acknowledged_at is null;
  return public.deadline_json(p_id, v_uid);
end;
$$;

-- The owner or a partner moves a pending (or cancelled) check to someone else, e.g. when the
-- checker is on leave. Nobody who has seen the values is eligible.
create or replace function public.reassign_deadline_check(p_id uuid)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  d public.deadlines;
begin
  select * into d from public.deadlines where id = p_id and org_id = v_org;
  if not found or not public.deadline_visible(d, v_uid) then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  if not (v_uid = d.owner_id or public.has_org_role(v_org, array['owner', 'partner'])) then
    raise exception 'Only the owner or a partner can reassign the check' using errcode = '42501';
  end if;
  if d.status <> 'open' or d.check_state not in ('pending', 'cancelled') or d.verification <> 'unverified' then
    raise exception 'This deadline has no open check to reassign' using errcode = '55000';
  end if;
  if d.check_cancel_reason in ('reminder_to_checker', 'due_within_lead') then
    raise exception 'The check was cancelled for safety; it can''t be reopened' using errcode = '55000';
  end if;
  perform public.deadline_assign_check(p_id, d.checker_id);
  return public.deadline_json(p_id, v_uid);
end;
$$;

-- ---------------------------------------------------------------------------
-- Reads
-- ---------------------------------------------------------------------------
-- The docket. Rows awaiting the caller's check come first (and masked), the rest by date, so the
-- order itself says nothing about a masked row's date. Unmasked reads are recorded as views.
create or replace function public.list_deadlines(p_court_case uuid default null, p_thread uuid default null,
                                                 p_include_done boolean default false)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  v_ids uuid[];
begin
  if v_uid is null or v_org is null then
    raise exception 'Not a member of this organization' using errcode = '42501';
  end if;
  select coalesce(array_agg(x.id order by x.masked desc, x.sort_date, x.created_at), '{}'::uuid[]) into v_ids
  from (
    select d.id, d.created_at,
           public.deadline_masked(d.check_mode, d.check_state, d.checker_id, v_uid) as masked,
           case when public.deadline_masked(d.check_mode, d.check_state, d.checker_id, v_uid)
                then null else d.effective_due_date end as sort_date
    from public.deadlines d
    where d.org_id = v_org
      and (p_court_case is null or d.court_case_id = p_court_case)
      and (p_thread is null or d.thread_id = p_thread)
      and (coalesce(p_include_done, false) or d.status = 'open')
      and public.deadline_visible(d, v_uid)
    order by masked desc, sort_date, d.created_at
    limit 500
  ) x;
  perform public.record_deadline_views(v_ids, v_uid, 'read');
  return (select coalesce(jsonb_agg(public.deadline_json(u.id, v_uid) order by u.ord), '[]'::jsonb)
          from unnest(v_ids) with ordinality as u(id, ord));
end;
$$;

create or replace function public.get_deadline(p_id uuid)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  d public.deadlines;
begin
  select * into d from public.deadlines where id = p_id and org_id = public.active_org_id();
  if not found or not public.deadline_visible(d, v_uid) then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  perform public.record_deadline_views(array[p_id], v_uid, 'read');
  return public.deadline_json(p_id, v_uid);
end;
$$;

-- Entries: only your own while the check is pending; everyone's (who can see the deadline) after.
create or replace function public.my_deadline_entries(p_id uuid)
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  d public.deadlines;
begin
  select * into d from public.deadlines where id = p_id and org_id = public.active_org_id();
  if not found or not public.deadline_visible(d, v_uid) then
    raise exception 'Deadline not found' using errcode = 'P0002';
  end if;
  perform public.record_deadline_views(array[p_id], v_uid, 'read');
  return (
    select coalesce(jsonb_agg(jsonb_build_object(
             'id', e.id, 'kind', e.kind, 'entered_by', public.user_brief(e.entered_by), 'entered_at', e.entered_at,
             'inputs', e.inputs, 'computed_date', e.computed_date) order by e.entered_at), '[]'::jsonb)
    from public.deadline_entries e
    where e.deadline_id = p_id and (d.check_state <> 'pending' or e.entered_by = v_uid)
  );
end;
$$;

-- The caller's unacknowledged reminders (in-app delivery: listing them marks them delivered).
create or replace function public.my_deadline_reminders()
returns jsonb
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_org uuid := public.active_org_id();
  v_ids uuid[];
begin
  if v_uid is null or v_org is null then
    raise exception 'Not a member of this organization' using errcode = '42501';
  end if;
  update public.deadline_reminders set delivered_at = now()
  where org_id = v_org and target_id = v_uid and acknowledged_at is null and delivered_at is null;
  select coalesce(array_agg(distinct r.deadline_id), '{}'::uuid[]) into v_ids
  from public.deadline_reminders r where r.org_id = v_org and r.target_id = v_uid and r.acknowledged_at is null;
  perform public.record_deadline_views(v_ids, v_uid, 'reminder');
  return (
    select coalesce(jsonb_agg(jsonb_build_object(
             'id', r.id, 'rung', r.rung, 'level', r.level, 'channel', r.channel, 'issued_at', r.issued_at,
             'delivered_at', r.delivered_at, 'for_date', case when m.masked then null else r.for_date end,
             'deadline', public.deadline_json(r.deadline_id, v_uid)) order by r.issued_at desc), '[]'::jsonb)
    from public.deadline_reminders r
    join public.deadlines d on d.id = r.deadline_id
    cross join lateral (select public.deadline_masked(d.check_mode, d.check_state, d.checker_id, v_uid) as masked) m
    where r.org_id = v_org and r.target_id = v_uid and r.acknowledged_at is null and d.status = 'open'
  );
end;
$$;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
revoke execute on function public.member_absent(uuid, uuid, date) from public, anon, authenticated;
revoke execute on function public.deadline_visible(public.deadlines, uuid) from public, anon, authenticated;
revoke execute on function public.user_brief(uuid) from public, anon, authenticated;
revoke execute on function public.record_deadline_views(uuid[], uuid, text) from public, anon, authenticated;
revoke execute on function public.deadline_pick_checker(uuid, uuid, boolean) from public, anon, authenticated;
revoke execute on function public.deadline_assign_check(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.org_role_of(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.deadline_json(uuid, uuid) from public, anon, authenticated;
grant execute on function public.deadline_assign_check(uuid, uuid) to service_role;

revoke execute on function public.create_deadline(text, text, date, uuid, uuid, uuid, text, integer, text, jsonb, boolean,
                                                  text, date[], integer, uuid) from public, anon;
revoke execute on function public.submit_deadline_entry(uuid, jsonb, date) from public, anon;
revoke execute on function public.acknowledge_deadline_reminder(uuid) from public, anon;
revoke execute on function public.complete_deadline(uuid, text) from public, anon;
revoke execute on function public.reassign_deadline_check(uuid) from public, anon;
revoke execute on function public.list_deadlines(uuid, uuid, boolean) from public, anon;
revoke execute on function public.get_deadline(uuid) from public, anon;
revoke execute on function public.my_deadline_entries(uuid) from public, anon;
revoke execute on function public.my_deadline_reminders() from public, anon;
grant execute on function public.create_deadline(text, text, date, uuid, uuid, uuid, text, integer, text, jsonb, boolean,
                                                 text, date[], integer, uuid) to authenticated;
grant execute on function public.submit_deadline_entry(uuid, jsonb, date) to authenticated;
grant execute on function public.acknowledge_deadline_reminder(uuid) to authenticated;
grant execute on function public.complete_deadline(uuid, text) to authenticated;
grant execute on function public.reassign_deadline_check(uuid) to authenticated;
grant execute on function public.list_deadlines(uuid, uuid, boolean) to authenticated;
grant execute on function public.get_deadline(uuid) to authenticated;
grant execute on function public.my_deadline_entries(uuid) to authenticated;
grant execute on function public.my_deadline_reminders() to authenticated;
