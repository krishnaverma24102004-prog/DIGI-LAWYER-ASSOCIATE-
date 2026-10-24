-- Court case tracker: the firm's cases in court, with hearing dates kept in sync from eCourts data
-- (via a provider API, or entered by hand) and reminders before each hearing.
-- Visibility like transcripts: owners and partners see the org's cases, others their own.

create table if not exists public.court_cases (
  id                 uuid primary key default gen_random_uuid(),
  org_id             uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id            uuid not null default auth.uid() references public.users (id) on delete cascade,
  thread_id          uuid references public.case_threads (id) on delete set null,
  cnr                text check (cnr ~ '^[A-Z0-9]{16}$'),  -- eCourts Case Number Record
  title              text not null check (char_length(title) between 1 and 300),
  court_name         text,
  case_number        text,
  case_status        text,
  petitioners        text[] not null default '{}',
  respondents        text[] not null default '{}',
  next_hearing_date  date,
  last_hearing_date  date,
  client_name        text,
  client_phone       text check (client_phone ~ '^\+[1-9][0-9]{6,14}$'),  -- E.164, for WhatsApp reminders
  notes              text,
  source             text not null default 'manual' check (source in ('manual', 'ecourtsindia')),
  provider_data      jsonb,          -- the provider's last response (orders, hearing history)
  last_synced_at     timestamptz,
  sync_error         text,
  reminded_for_date  date,           -- the hearing the client was last reminded about
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (org_id, cnr)
);

create index if not exists court_cases_org_next_idx on public.court_cases (org_id, next_hearing_date);

create trigger court_cases_set_updated_at
  before update on public.court_cases
  for each row execute function public.set_updated_at();

alter table public.court_cases enable row level security;

create policy "Org members can view permitted court cases"
  on public.court_cases for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can add own court cases"
  on public.court_cases for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted court cases"
  on public.court_cases for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Org members can delete permitted court cases"
  on public.court_cases for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );
