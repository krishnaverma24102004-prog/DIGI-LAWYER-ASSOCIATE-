-- Custody watch (P14): every client in custody, with the dates for default bail
-- (s. 167(2) CrPC / s. 187(3) BNSS) and undertrial release (s. 479 BNSS) computed in code
-- (app/services/custody_service.py) from the punishment table (app/data/offence_punishments.json).
--
-- Custody data is personal data of an accused person, treated with heightened safeguards: it is
-- kept under the org's RLS like court cases (owners and partners see the firm's files, others the
-- files they created or are counsel / backup on), and it is never sent to an AI model.
--
-- The daily 07:00 IST sweep (custody_service.recompute_all) writes `computed`, `docket` and
-- `history` with the service role, scoped to one organization (invariant 2, server-side job).

create table if not exists public.custody_files (
  id                        uuid primary key default gen_random_uuid(),
  org_id                    uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id                   uuid not null default auth.uid() references public.users (id) on delete cascade,
  counsel_id                uuid references public.users (id) on delete set null,
  backup_id                 uuid references public.users (id) on delete set null,
  court_case_id             uuid references public.court_cases (id) on delete set null,
  thread_id                 uuid references public.case_threads (id) on delete set null,
  matter                    text check (char_length(matter) <= 300),
  accused_name              text not null check (char_length(accused_name) between 1 and 200),
  -- offence_date decides IPC or BNS (punishment lookup only); the investigation start decides
  -- CrPC or BNSS (s. 531 BNSS): investigation_started_on, else fir_date, else arrest_date (flagged).
  offence_date              date not null,
  fir_date                  date,
  fir_number                text check (char_length(fir_number) <= 100),
  police_station            text check (char_length(police_station) <= 200),
  investigation_started_on  date,
  complaint_case            boolean not null default false,
  arrest_date               date not null,
  first_remand_date         date,
  sections                  text[] not null default '{}' check (cardinality(sections) <= 20),
  custody_type              text not null default 'judicial' check (custody_type in ('police', 'judicial', 'released')),
  -- earlier, interrupted detention: [{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}] (s. 479 counts total detention)
  custody_periods           jsonb not null default '[]'::jsonb check (jsonb_typeof(custody_periods) = 'array'),
  chargesheet_filed_on      date,
  default_bail_applied_on   date,
  -- confirmed by the lawyer; null = not confirmed yet
  first_time_offender       boolean,
  other_pending_cases       boolean,
  accused_delay_days        integer check (accused_delay_days between 0 and 10000),
  special_statute           text check (special_statute in ('NDPS_COMMERCIAL', 'UAPA')),
  notes                     text check (char_length(notes) <= 5000),
  computed                  jsonb,                 -- the last computation (sweep or save)
  computed_at               timestamptz,
  docket                    jsonb not null default '{}'::jsonb,   -- kind -> {id, due_date} of the P13 deadline
  history                   jsonb not null default '[]'::jsonb,   -- accrued / right lost / docketed events
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);

create index if not exists custody_files_org_idx on public.custody_files (org_id, custody_type);

drop trigger if exists custody_files_set_updated_at on public.custody_files;
create trigger custody_files_set_updated_at
  before update on public.custody_files
  for each row execute function public.set_updated_at();

-- Special-statute extensions (NDPS s. 36A(4), UAPA s. 43D(2)) apply only with the order's date.
create table if not exists public.custody_extension_orders (
  id                uuid primary key default gen_random_uuid(),
  org_id            uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  custody_file_id   uuid not null references public.custody_files (id) on delete cascade,
  order_date        date not null,
  extended_to_days  integer not null check (extended_to_days between 1 and 400),
  court             text check (char_length(court) <= 200),
  note              text check (char_length(note) <= 1000),
  created_by        uuid not null default auth.uid() references public.users (id) on delete cascade,
  created_at        timestamptz not null default now()
);

create index if not exists custody_extension_orders_file_idx on public.custody_extension_orders (custody_file_id);

alter table public.custody_files enable row level security;
alter table public.custody_extension_orders enable row level security;

-- Who may see a custody file: owners and partners of its org, its creator, counsel and backup.
create policy "Org members can view permitted custody files"
  on public.custody_files for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and ((select auth.uid()) in (user_id, counsel_id, backup_id)
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can add own custody files"
  on public.custody_files for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted custody files"
  on public.custody_files for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and ((select auth.uid()) in (user_id, counsel_id, backup_id)
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Seniors can delete custody files"
  on public.custody_files for delete to authenticated
  using (org_id = (select public.active_org_id())
         and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])));

create policy "Extension orders follow their custody file"
  on public.custody_extension_orders for select to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.custody_files f where f.id = custody_file_id));

create policy "Extension orders are added to visible custody files"
  on public.custody_extension_orders for insert to authenticated
  with check (org_id = (select public.active_org_id()) and created_by = (select auth.uid())
              and exists (select 1 from public.custody_files f where f.id = custody_file_id and f.org_id = (select public.active_org_id())));

create policy "Extension orders are removed from visible custody files"
  on public.custody_extension_orders for delete to authenticated
  using (org_id = (select public.active_org_id())
         and exists (select 1 from public.custody_files f where f.id = custody_file_id));

revoke update on public.custody_extension_orders from anon, authenticated;
