-- Phase 7: Stripe billing and audio usage metering, Twilio phone numbers, background
-- report storage, and a DB connection gauge for monitoring.
--
-- Billing state is written only by the server (Stripe webhooks and session metering,
-- with the service role). Members read their organization's billing and usage via RLS.

-- ---------------------------------------------------------------------------
-- Plan tiers: add "starter" (organizations.plan_tier stays service-role managed).
-- ---------------------------------------------------------------------------
alter table public.organizations drop constraint if exists organizations_plan_tier_check;
alter table public.organizations
  add constraint organizations_plan_tier_check check (plan_tier in ('free', 'starter', 'pro', 'enterprise'));

-- ---------------------------------------------------------------------------
-- billing_accounts: one per organization, mirrors its Stripe customer and subscription.
-- ---------------------------------------------------------------------------
create table if not exists public.billing_accounts (
  org_id                  uuid primary key references public.organizations (id) on delete cascade,
  stripe_customer_id      text unique,
  stripe_subscription_id  text unique,
  tier                    text check (tier in ('starter', 'pro', 'enterprise')),
  -- Stripe subscription status: active, trialing, past_due, canceled, unpaid, incomplete, ...
  status                  text not null default 'inactive',
  included_minutes        integer not null default 0 check (included_minutes >= 0),
  current_period_start    timestamptz,
  current_period_end      timestamptz,
  last_payment_at         timestamptz,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create trigger billing_accounts_set_updated_at
  before update on public.billing_accounts
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- audio_usage: one row per metered audio session (WebSocket, WebRTC or phone call).
-- ---------------------------------------------------------------------------
create table if not exists public.audio_usage (
  id                  uuid primary key default gen_random_uuid(),
  org_id              uuid not null references public.organizations (id) on delete cascade,
  user_id             uuid references public.users (id) on delete set null,
  session_id          text not null unique,
  transport           text not null check (transport in ('websocket', 'webrtc', 'telephony')),
  started_at          timestamptz not null,
  ended_at            timestamptz not null,
  duration_seconds    integer not null check (duration_seconds >= 0),
  billed_minutes      integer not null check (billed_minutes >= 0),
  stripe_reported_at  timestamptz,
  created_at          timestamptz not null default now()
);

create index if not exists audio_usage_org_started_idx on public.audio_usage (org_id, started_at desc);

-- Stripe webhook deliveries already processed (Stripe retries; handlers must be idempotent).
create table if not exists public.stripe_events (
  id            text primary key,
  type          text not null,
  processed_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- telephony_numbers: which organization answers calls to a Twilio number.
-- Calls are saved as transcripts owned by `owner_user_id` (the lawyer receiving intake).
-- ---------------------------------------------------------------------------
create table if not exists public.telephony_numbers (
  phone_number      text primary key check (phone_number ~ '^\+[1-9][0-9]{6,14}$'),  -- E.164
  org_id            uuid not null references public.organizations (id) on delete cascade,
  owner_user_id     uuid not null references public.users (id) on delete cascade,
  practice_area_id  uuid references public.practice_areas (id) on delete set null,
  jurisdiction      text,
  greeting          text check (char_length(greeting) <= 500),
  enabled           boolean not null default true,
  created_at        timestamptz not null default now()
);

create index if not exists telephony_numbers_org_idx on public.telephony_numbers (org_id);

-- Whether `target_user` belongs to `target_org` (the number's owner must be a member).
create or replace function public.is_org_member_user(target_org uuid, target_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_members m
    where m.org_id = target_org and m.user_id = target_user
  )
$$;

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
alter table public.billing_accounts  enable row level security;
alter table public.audio_usage       enable row level security;
alter table public.stripe_events     enable row level security;
alter table public.telephony_numbers enable row level security;

-- Billing and usage: owners and partners of the active org read; nobody but the server writes.
create policy "Owners and partners can view billing"
  on public.billing_accounts for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

create policy "Owners and partners can view audio usage"
  on public.audio_usage for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

revoke insert, update, delete on public.billing_accounts, public.audio_usage from anon, authenticated;
-- stripe_events has RLS on and no policies: service role only.
revoke all on public.stripe_events from anon, authenticated;

-- Phone numbers: members of the active org see them; owners and partners manage them.
create policy "Org members can view phone numbers"
  on public.telephony_numbers for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Owners and partners can add phone numbers"
  on public.telephony_numbers for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
    and (select public.is_org_member_user(org_id, owner_user_id))
  );

create policy "Owners and partners can update phone numbers"
  on public.telephony_numbers for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  )
  with check (
    org_id = (select public.active_org_id())
    and (select public.is_org_member_user(org_id, owner_user_id))
  );

create policy "Owners and partners can remove phone numbers"
  on public.telephony_numbers for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

-- ---------------------------------------------------------------------------
-- Storage: PDF reports generated by the background worker, at "<org_id>/<transcript_id>.pdf".
-- The worker uploads with the service role; members download (signed URLs) through RLS,
-- which allows the reports of transcripts they can see.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('reports', 'reports', false)
on conflict (id) do nothing;

create policy "Members can read reports of transcripts they can see"
  on storage.objects for select to authenticated
  using (
    bucket_id = 'reports'
    and exists (
      select 1 from public.transcripts t
      where t.org_id::text = (storage.foldername(name))[1]
        and name = t.org_id::text || '/' || t.id::text || '.pdf'
    )
  );

-- ---------------------------------------------------------------------------
-- Monitoring: open database connections, for the Prometheus gauge. Service role only.
-- ---------------------------------------------------------------------------
create or replace function public.db_connection_count()
returns integer
language sql
stable
security definer
set search_path = ''
as $$
  select count(*)::integer from pg_catalog.pg_stat_activity where datname = current_database()
$$;

revoke execute on function public.db_connection_count() from public, anon, authenticated;
grant execute on function public.db_connection_count() to service_role;
