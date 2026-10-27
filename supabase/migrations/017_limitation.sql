-- P06 limitation engine: certified-copy applications (the Copy tracker).
--
-- s. 12(2) Limitation Act excludes the time from a copy application to the day the copy is ready,
-- so the limitation date of an appeal, review or revision stays provisional until the copy-ready
-- date is known. Copying sections publish no data we can read, so a clerk enters the dates here
-- and the tracker chases pending copies (a "check the copy section" reminder every 3 working days).
--
-- Rows are working records of the firm, visible like court_cases (migration 011): owners and
-- partners see the org's, others their own. Each row links to a court case and/or a case thread
-- the caller can see (checked in the policies). Only the person who logged a row deletes it.
--
-- The limitation rules themselves are data (app/data/limitation_rules.json) and apply per firm once
-- two members have signed a rule version (rule_verifications / rule_active, migration 014).

create table if not exists public.copy_applications (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id         uuid not null default auth.uid() references public.users (id) on delete cascade,
  court_case_id   uuid references public.court_cases (id) on delete set null,
  thread_id       uuid references public.case_threads (id) on delete set null,
  court_code      text references public.courts (code) on delete set null,
  order_date      date,              -- the judgment / decree / order the copy is of
  applied_on      date not null,
  ready_on        date,              -- the day the copying section notified the copy as ready
  delivered_on    date,
  status          text not null default 'pending' check (status in ('pending', 'ready', 'delivered', 'withdrawn')),
  notes           text check (char_length(notes) <= 2000),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check (order_date is null or applied_on >= order_date),
  check (ready_on is null or ready_on >= applied_on),
  check (delivered_on is null or delivered_on >= applied_on),
  check (delivered_on is null or ready_on is null or delivered_on >= ready_on)
);

create index if not exists copy_applications_org_status_idx on public.copy_applications (org_id, status, applied_on);
create index if not exists copy_applications_case_idx on public.copy_applications (court_case_id) where court_case_id is not null;

drop trigger if exists copy_applications_set_updated_at on public.copy_applications;
create trigger copy_applications_set_updated_at
  before update on public.copy_applications
  for each row execute function public.set_updated_at();

alter table public.copy_applications enable row level security;

-- Visibility as for court cases: owners and partners see the firm's, others their own.
create policy "Org members can view permitted copy applications"
  on public.copy_applications for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

-- A linked case or thread must be one the caller can see (their RLS applies inside the subquery).
create policy "Org members can log copy applications"
  on public.copy_applications for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and user_id = (select auth.uid())
    and (court_case_id is null or exists (select 1 from public.court_cases c where c.id = court_case_id))
    and (thread_id is null or exists (select 1 from public.case_threads t where t.id = thread_id))
  );

create policy "Org members can update permitted copy applications"
  on public.copy_applications for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (
    org_id = (select public.active_org_id())
    and (court_case_id is null or exists (select 1 from public.court_cases c where c.id = court_case_id))
    and (thread_id is null or exists (select 1 from public.case_threads t where t.id = thread_id))
  );

-- Working records, not matter records: no Trash, but only the person who logged the row deletes it.
create policy "Members delete the copy applications they logged"
  on public.copy_applications for delete to authenticated
  using (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

-- Who logged a row and which firm it belongs to never change.
revoke update on public.copy_applications from anon, authenticated;
grant update (court_case_id, thread_id, court_code, order_date, applied_on, ready_on, delivered_on, status, notes)
  on public.copy_applications to authenticated;
