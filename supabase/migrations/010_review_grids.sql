-- Bulk document review: ask the same questions of many documents and get a grid of answers,
-- each with the passage it came from (checked against the document text).
-- Visibility like transcripts and drafts: owners and partners see the org's grids, others their own.

create table if not exists public.review_grids (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id       uuid not null default auth.uid() references public.users (id) on delete cascade,
  title         text not null check (char_length(title) between 1 and 200),
  -- [{"id": "q1", "question": "Governing law?", "kind": "text|yes_no|date|amount|duration"}]
  questions     jsonb not null default '[]'::jsonb,
  document_ids  uuid[] not null default '{}',
  jurisdiction  text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger review_grids_set_updated_at
  before update on public.review_grids
  for each row execute function public.set_updated_at();

create table if not exists public.review_cells (
  grid_id      uuid not null references public.review_grids (id) on delete cascade,
  document_id  uuid not null references public.documents (id) on delete cascade,
  question_id  text not null,
  status       text not null default 'pending' check (status in ('pending', 'done', 'error')),
  answer       text,
  quote        text,      -- the passage the answer rests on, as written in the document
  verified     boolean,   -- whether that passage really is in the document
  confidence   text check (confidence in ('high', 'medium', 'low')),
  error        text,
  updated_at   timestamptz not null default now(),
  primary key (grid_id, document_id, question_id)
);

create index if not exists review_grids_org_idx on public.review_grids (org_id, created_at desc);

alter table public.review_grids enable row level security;
alter table public.review_cells enable row level security;

create policy "Org members can view permitted review grids"
  on public.review_grids for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can create own review grids"
  on public.review_grids for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted review grids"
  on public.review_grids for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Org members can delete permitted review grids"
  on public.review_grids for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

-- Cells follow their grid.
create policy "Cells follow their grid"
  on public.review_cells for all to authenticated
  using (exists (select 1 from public.review_grids g where g.id = grid_id))
  with check (exists (select 1 from public.review_grids g where g.id = grid_id));
