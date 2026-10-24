-- Jurisdiction-aware knowledge search, and generated legal drafts.

-- ---------------------------------------------------------------------------
-- Knowledge search with an optional jurisdiction filter. Passages are tagged at upload
-- with metadata.jurisdiction_code (IN, US, US-CA, UK...). With a filter, results are
-- passages tagged with one of the codes plus untagged firm material.
-- Replaces the 4-argument version from migration 004 (dropped so PostgREST sees one function).
-- ---------------------------------------------------------------------------
drop function if exists public.match_legal_precedents(extensions.vector, float, int, uuid);

create or replace function public.match_legal_precedents(
  query_embedding extensions.vector(768),
  match_threshold float,
  match_count int,
  target_org_id uuid,
  filter_jurisdictions text[] default null
)
returns table (
  id uuid,
  source_id uuid,
  chunk_index integer,
  title text,
  content text,
  metadata jsonb,
  similarity float
)
language sql
stable
security invoker
set search_path = public, extensions
as $$
  select kb.id, kb.source_id, kb.chunk_index, kb.title, kb.content, kb.metadata,
         1 - (kb.vector_embedding <=> query_embedding) as similarity
  from public.legal_knowledge_base kb
  where kb.org_id = target_org_id
    and 1 - (kb.vector_embedding <=> query_embedding) >= match_threshold
    and (
      filter_jurisdictions is null
      or coalesce(kb.metadata ->> 'jurisdiction_code', '') = ''
      or kb.metadata ->> 'jurisdiction_code' = any (filter_jurisdictions)
    )
  order by kb.vector_embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;

create index if not exists legal_knowledge_base_jurisdiction_idx
  on public.legal_knowledge_base ((metadata ->> 'jurisdiction_code'));

-- ---------------------------------------------------------------------------
-- Drafts: legal notices, bail applications, cease & desist letters, NDAs, affidavits.
-- Same visibility as transcripts: active org; owners/partners see all, others their own.
-- ---------------------------------------------------------------------------
create table if not exists public.drafts (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  user_id       uuid not null default auth.uid() references public.users (id) on delete cascade,
  thread_id     uuid references public.case_threads (id) on delete set null,
  doc_type      text not null,
  jurisdiction  text,
  title         text not null check (char_length(title) between 1 and 300),
  -- {"sections": [{"heading": str|null, "paragraphs": [str]}], "signature_block": [...]}
  content       jsonb not null,
  variables     jsonb not null default '{}'::jsonb,
  missing       jsonb not null default '[]'::jsonb,
  status        text not null default 'draft' check (status in ('draft', 'final')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists drafts_org_updated_idx on public.drafts (org_id, updated_at desc);

create trigger drafts_set_updated_at
  before update on public.drafts
  for each row execute function public.set_updated_at();

alter table public.drafts enable row level security;

create policy "Org members can view permitted drafts"
  on public.drafts for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can create own drafts"
  on public.drafts for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted drafts"
  on public.drafts for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Org members can delete permitted drafts"
  on public.drafts for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );
