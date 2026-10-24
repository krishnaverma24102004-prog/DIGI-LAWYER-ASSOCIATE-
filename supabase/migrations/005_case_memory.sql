-- Persistent case memory: a case thread groups the consultations of one matter, and its
-- messages carry what the agents should remember between sessions (session summaries,
-- key facts and risks). Access follows transcripts: active org only; owners and partners
-- see every thread in the org, associates and paralegals their own.
--
-- Also records how each uploaded document's text was obtained (text layer / OCR / vision).

create table if not exists public.case_threads (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references public.users (id) on delete cascade,
  org_id      uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  title       text not null check (char_length(title) between 1 and 200),
  status      text not null default 'open' check (status in ('open', 'closed', 'archived')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists case_threads_org_updated_idx on public.case_threads (org_id, updated_at desc);

create trigger case_threads_set_updated_at
  before update on public.case_threads
  for each row execute function public.set_updated_at();

create table if not exists public.thread_messages (
  id          uuid primary key default gen_random_uuid(),
  thread_id   uuid not null references public.case_threads (id) on delete cascade,
  role        text not null check (role in ('client', 'lawyer', 'assistant', 'system', 'session_summary')),
  content     text not null,
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists thread_messages_thread_created_idx on public.thread_messages (thread_id, created_at);

alter table public.transcripts
  add column if not exists thread_id uuid references public.case_threads (id) on delete set null;
create index if not exists transcripts_thread_id_idx on public.transcripts (thread_id);

alter table public.documents
  add column if not exists extraction jsonb not null default '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
alter table public.case_threads    enable row level security;
alter table public.thread_messages enable row level security;

create policy "Org members can view permitted case threads"
  on public.case_threads for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can open case threads"
  on public.case_threads for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted case threads"
  on public.case_threads for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Owners and partners can delete case threads"
  on public.case_threads for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

-- Messages inherit their thread's visibility: the subquery is itself filtered by the
-- case_threads policies above, so a message is reachable only through a visible thread.
create policy "Messages follow their thread (read)"
  on public.thread_messages for select to authenticated
  using (exists (select 1 from public.case_threads t where t.id = thread_messages.thread_id));

create policy "Messages follow their thread (write)"
  on public.thread_messages for insert to authenticated
  with check (exists (select 1 from public.case_threads t where t.id = thread_messages.thread_id));

-- Thread history is a record: no edits; deleting the thread deletes its messages.
revoke update on public.thread_messages from anon, authenticated;
