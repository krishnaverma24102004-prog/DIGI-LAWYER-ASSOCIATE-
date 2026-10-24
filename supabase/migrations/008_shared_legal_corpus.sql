-- Shared Indian legal corpus, read by every organization:
--
--  * legal_knowledge_base rows with org_id NULL: public judgments and statutes (full text,
--    chunked and embedded), searched alongside each firm's own material;
--  * legal_authorities: an index of every known judgment (title, parties, report and neutral
--    citations), so the citation check can recognise a real case even when it wasn't among the
--    passages retrieved for a question.
--
-- Both are loaded by scripts/ingest_sc_judgments.py with the service role; users can read them
-- but never write them (the existing write policies require org_id = the caller's active org).

alter table public.legal_knowledge_base alter column org_id drop not null;

drop policy if exists "Org members can search the knowledge base" on public.legal_knowledge_base;
create policy "Org members can search the knowledge base and the shared corpus"
  on public.legal_knowledge_base for select to authenticated
  using (org_id is null or org_id = (select public.active_org_id()));

create index if not exists legal_knowledge_base_shared_source_idx
  on public.legal_knowledge_base (source_id, chunk_index) where org_id is null;

-- Search the org's material and the shared corpus together.
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
  select kb.id, kb.source_id, kb.chunk_index, kb.title, kb.content,
         kb.metadata || jsonb_build_object('shared', kb.org_id is null) as metadata,
         1 - (kb.vector_embedding <=> query_embedding) as similarity
  from public.legal_knowledge_base kb
  where (kb.org_id = target_org_id or kb.org_id is null)
    and 1 - (kb.vector_embedding <=> query_embedding) >= match_threshold
    and (
      filter_jurisdictions is null
      or coalesce(kb.metadata ->> 'jurisdiction_code', '') = ''
      or kb.metadata ->> 'jurisdiction_code' = any (filter_jurisdictions)
    )
  order by kb.vector_embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;

-- ---------------------------------------------------------------------------
-- legal_authorities: the citation index.
-- citation_keys hold normalized citations ("[2024]10SCR108", "2024INSC735") as written by
-- services/citation_service.py; name_tokens the significant words of the parties' names.
-- ---------------------------------------------------------------------------
create table if not exists public.legal_authorities (
  id              uuid primary key default gen_random_uuid(),
  kind            text not null default 'case' check (kind in ('case', 'statute')),
  court           text,
  title           text not null,
  citation        text,  -- as reported, e.g. "[2024] 10 S.C.R. 108"
  neutral_citation text,  -- e.g. "2024 INSC 735"
  decision_date   date,
  jurisdiction_code text not null default 'IN',
  citation_keys   text[] not null default '{}',
  name_tokens     text[] not null default '{}',
  source_url      text,
  source_id       uuid,  -- its full text in legal_knowledge_base, when ingested
  external_id     text unique,  -- the dataset's id, so re-running the import doesn't duplicate
  created_at      timestamptz not null default now()
);

create index if not exists legal_authorities_keys_idx on public.legal_authorities using gin (citation_keys);
create index if not exists legal_authorities_names_idx on public.legal_authorities using gin (name_tokens);

alter table public.legal_authorities enable row level security;

create policy "Everyone signed in can read the citation index"
  on public.legal_authorities for select to authenticated
  using (true);

revoke insert, update, delete on public.legal_authorities from anon, authenticated;
