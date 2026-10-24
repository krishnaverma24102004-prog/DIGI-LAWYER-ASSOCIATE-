-- Phase 4: multi-tenant organizations, role-based access, practice areas,
-- legal knowledge base (pgvector RAG) and append-only audit logs.
--
-- Tenancy model
-- -------------
-- Every row of tenant data carries an org_id. RLS only exposes rows of the caller's
-- *active* organization, resolved by public.active_org_id():
--   1. the `x-org-id` request header (the API forwards the org the user picked), else
--   2. public.users.active_org_id (their default workspace),
-- and in both cases only if the caller is a member of that org.
--
-- Roles: owner > partner > associate > paralegal.
--   owner      everything, including granting owner/partner and renaming the org
--   partner    sees all org consultations; manages associates/paralegals, practice areas, knowledge base
--   associate  own consultations and documents; can add to the knowledge base
--   paralegal  own consultations and documents
--
-- Embedding size: 768, matching the default fastembed model BAAI/bge-base-en-v1.5
-- (EMBEDDING_MODEL / EMBEDDING_DIMENSIONS in .env). Changing models with a different
-- size means altering vector_embedding and match_legal_precedents and re-ingesting.

create extension if not exists vector with schema extensions;

-- ---------------------------------------------------------------------------
-- Organizations and membership
-- ---------------------------------------------------------------------------
create table if not exists public.organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (char_length(name) between 1 and 200),
  plan_tier   text not null default 'free' check (plan_tier in ('free', 'pro', 'enterprise')),
  created_by  uuid references public.users (id) on delete set null,
  created_at  timestamptz not null default now()
);

create table if not exists public.organization_members (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null references public.organizations (id) on delete cascade,
  user_id     uuid not null references public.users (id) on delete cascade,
  role        text not null check (role in ('owner', 'partner', 'associate', 'paralegal')),
  created_at  timestamptz not null default now(),
  unique (org_id, user_id)
);

create index if not exists organization_members_user_id_idx on public.organization_members (user_id);

alter table public.users
  add column if not exists active_org_id uuid references public.organizations (id) on delete set null;

-- ---------------------------------------------------------------------------
-- Membership helpers. SECURITY DEFINER so policies can consult organization_members
-- without recursing into its own RLS. They only ever describe the calling user.
-- ---------------------------------------------------------------------------
create or replace function public.org_role(target_org uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select m.role from public.organization_members m
  where m.org_id = target_org and m.user_id = auth.uid()
$$;

create or replace function public.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.organization_members m
    where m.org_id = target_org and m.user_id = auth.uid()
  )
$$;

create or replace function public.has_org_role(target_org uuid, allowed_roles text[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(public.org_role(target_org) = any (allowed_roles), false)
$$;

create or replace function public.shares_org_with(other_user uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.organization_members mine
    join public.organization_members theirs on theirs.org_id = mine.org_id
    where mine.user_id = auth.uid() and theirs.user_id = other_user
  )
$$;

create or replace function public.active_org_id()
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  header_value text;
  requested uuid;
begin
  if auth.uid() is null then
    return null;
  end if;

  begin
    header_value := current_setting('request.headers', true)::json ->> 'x-org-id';
  exception when others then
    header_value := null;
  end;

  if header_value is not null and header_value <> '' then
    begin
      requested := header_value::uuid;
    exception when invalid_text_representation then
      return null;
    end;
  else
    select u.active_org_id into requested from public.users u where u.id = auth.uid();
  end if;

  if requested is not null and public.is_org_member(requested) then
    return requested;
  end if;
  return null;
end;
$$;

-- Creates an organization and makes the caller its owner, atomically.
create or replace function public.create_organization(org_name text)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  org public.organizations;
begin
  if auth.uid() is null then
    raise exception 'not authenticated' using errcode = '42501';
  end if;
  insert into public.organizations (name, created_by) values (org_name, auth.uid()) returning * into org;
  insert into public.organization_members (org_id, user_id, role) values (org.id, auth.uid(), 'owner');
  return org;
end;
$$;

revoke execute on function public.create_organization(text) from public, anon;
grant execute on function public.create_organization(text) to authenticated;

-- New sign-ups get a personal workspace they own, set as their active org.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  workspace_id uuid;
  display_name text;
begin
  insert into public.users (id, email, full_name)
  values (new.id, new.email, new.raw_user_meta_data ->> 'full_name');

  display_name := coalesce(nullif(new.raw_user_meta_data ->> 'full_name', ''), split_part(new.email, '@', 1), 'My');
  insert into public.organizations (name, created_by)
  values (left(display_name, 180) || '''s workspace', new.id)
  returning id into workspace_id;
  insert into public.organization_members (org_id, user_id, role) values (workspace_id, new.id, 'owner');
  update public.users set active_org_id = workspace_id where id = new.id;
  return new;
end;
$$;

-- Existing users: same personal workspace.
do $$
declare
  u record;
  workspace_id uuid;
begin
  for u in
    select pu.id, pu.email, pu.full_name from public.users pu
    where not exists (select 1 from public.organization_members m where m.user_id = pu.id)
  loop
    insert into public.organizations (name, created_by)
    values (left(coalesce(nullif(u.full_name, ''), split_part(u.email, '@', 1), 'My'), 180) || '''s workspace', u.id)
    returning id into workspace_id;
    insert into public.organization_members (org_id, user_id, role) values (workspace_id, u.id, 'owner');
    update public.users set active_org_id = workspace_id where id = u.id;
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- Practice areas: per-org prompt templates and risk rules
-- ---------------------------------------------------------------------------
create table if not exists public.practice_areas (
  id                     uuid primary key default gen_random_uuid(),
  org_id                 uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  name                   text not null check (char_length(name) between 1 and 120),
  description            text check (char_length(description) <= 1000),
  custom_system_prompt   text not null default '' check (char_length(custom_system_prompt) <= 8000),
  risk_evaluation_rules  jsonb not null default '{}'::jsonb check (jsonb_typeof(risk_evaluation_rules) = 'object'),
  created_by             uuid default auth.uid() references public.users (id) on delete set null,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  unique (org_id, name)
);

create trigger practice_areas_set_updated_at
  before update on public.practice_areas
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Legal knowledge base (RAG). Long texts are stored as chunks sharing a source_id.
-- ---------------------------------------------------------------------------
create table if not exists public.legal_knowledge_base (
  id                uuid primary key default gen_random_uuid(),
  org_id            uuid not null default public.active_org_id() references public.organizations (id) on delete cascade,
  source_id         uuid not null,
  chunk_index       integer not null default 0,
  title             text not null check (char_length(title) between 1 and 300),
  content           text not null,
  vector_embedding  extensions.vector(768) not null,
  metadata          jsonb not null default '{}'::jsonb,
  created_by        uuid default auth.uid() references public.users (id) on delete set null,
  created_at        timestamptz not null default now()
);

create index if not exists legal_knowledge_base_org_source_idx
  on public.legal_knowledge_base (org_id, source_id, chunk_index);
create index if not exists legal_knowledge_base_embedding_idx
  on public.legal_knowledge_base using hnsw (vector_embedding extensions.vector_cosine_ops);

-- Cosine-similarity search within one org. SECURITY INVOKER: the caller's RLS still
-- applies, so a user can only ever match rows of their own active organization.
create or replace function public.match_legal_precedents(
  query_embedding extensions.vector(768),
  match_threshold float,
  match_count int,
  target_org_id uuid
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
  order by kb.vector_embedding <=> query_embedding
  limit least(greatest(match_count, 1), 50);
$$;

-- ---------------------------------------------------------------------------
-- Audit log: append-only. Written by the API with the service role; owners and
-- partners can read their org's entries. No foreign keys, so entries outlive the
-- users and organizations they mention.
-- ---------------------------------------------------------------------------
create table if not exists public.audit_logs (
  id             bigint generated always as identity primary key,
  org_id         uuid,
  user_id        uuid,
  action         text not null,
  resource_type  text not null,
  resource_id    text,
  ip_address     inet,
  metadata       jsonb not null default '{}'::jsonb,
  "timestamp"    timestamptz not null default now()
);

create index if not exists audit_logs_org_timestamp_idx on public.audit_logs (org_id, "timestamp" desc);

create or replace function public.prevent_audit_log_changes()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'audit_logs is append-only' using errcode = '42501';
end;
$$;

create trigger audit_logs_append_only
  before update or delete on public.audit_logs
  for each row execute function public.prevent_audit_log_changes();

-- ---------------------------------------------------------------------------
-- Tenant columns on existing tables
-- ---------------------------------------------------------------------------
alter table public.transcripts add column if not exists org_id uuid references public.organizations (id) on delete cascade;
alter table public.transcripts add column if not exists practice_area_id uuid references public.practice_areas (id) on delete set null;
alter table public.documents add column if not exists org_id uuid references public.organizations (id) on delete cascade;

update public.transcripts t set org_id = u.active_org_id from public.users u where t.user_id = u.id and t.org_id is null;
update public.documents d set org_id = u.active_org_id from public.users u where d.user_id = u.id and d.org_id is null;

alter table public.transcripts alter column org_id set not null;
alter table public.transcripts alter column org_id set default public.active_org_id();
alter table public.documents alter column org_id set not null;
alter table public.documents alter column org_id set default public.active_org_id();

create index if not exists transcripts_org_created_idx on public.transcripts (org_id, created_at desc);
create index if not exists documents_org_created_idx on public.documents (org_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- `(select ...)` around the helper calls lets Postgres evaluate them once per query.
-- ---------------------------------------------------------------------------
alter table public.organizations        enable row level security;
alter table public.organization_members enable row level security;
alter table public.practice_areas       enable row level security;
alter table public.legal_knowledge_base enable row level security;
alter table public.audit_logs           enable row level security;

-- organizations: members see their orgs; only owners rename. plan_tier is billing-managed
-- (service role only), enforced with a column grant.
create policy "Members can view their organizations"
  on public.organizations for select to authenticated
  using (public.is_org_member(id));

create policy "Owners can update their organization"
  on public.organizations for update to authenticated
  using (public.org_role(id) = 'owner')
  with check (public.org_role(id) = 'owner');

revoke insert, update, delete on public.organizations from anon, authenticated;
grant update (name) on public.organizations to authenticated;

-- organization_members: see co-members of any org you belong to. Owners manage anyone;
-- partners manage associates and paralegals only; anyone can leave.
create policy "Members can view co-members"
  on public.organization_members for select to authenticated
  using (public.is_org_member(org_id));

create policy "Owners and partners can add members"
  on public.organization_members for insert to authenticated
  with check (
    case public.org_role(org_id)
      when 'owner' then true
      when 'partner' then role in ('associate', 'paralegal')
      else false
    end
  );

create policy "Owners and partners can change roles"
  on public.organization_members for update to authenticated
  using (
    case public.org_role(org_id)
      when 'owner' then true
      when 'partner' then role in ('associate', 'paralegal')
      else false
    end
  )
  with check (
    case public.org_role(org_id)
      when 'owner' then true
      when 'partner' then role in ('associate', 'paralegal')
      else false
    end
  );

create policy "Owners and partners can remove members; anyone can leave"
  on public.organization_members for delete to authenticated
  using (
    user_id = (select auth.uid())
    or case public.org_role(org_id)
         when 'owner' then true
         when 'partner' then role in ('associate', 'paralegal')
         else false
       end
  );

-- users: also visible to people you share an organization with (for member lists).
create policy "Users can view co-member profiles"
  on public.users for select to authenticated
  using (public.shares_org_with(id));

-- transcripts and documents: active org only. Owners and partners see the whole org;
-- associates and paralegals see their own.
drop policy if exists "Users can view own transcripts" on public.transcripts;
drop policy if exists "Users can insert own transcripts" on public.transcripts;
drop policy if exists "Users can update own transcripts" on public.transcripts;
drop policy if exists "Users can delete own transcripts" on public.transcripts;

create policy "Org members can view permitted transcripts"
  on public.transcripts for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can create own transcripts"
  on public.transcripts for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can update permitted transcripts"
  on public.transcripts for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Org members can delete permitted transcripts"
  on public.transcripts for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

drop policy if exists "Users can view own documents" on public.documents;
drop policy if exists "Users can insert own documents" on public.documents;
drop policy if exists "Users can delete own documents" on public.documents;

create policy "Org members can view permitted documents"
  on public.documents for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Org members can upload own documents"
  on public.documents for insert to authenticated
  with check (org_id = (select public.active_org_id()) and user_id = (select auth.uid()));

create policy "Org members can delete permitted documents"
  on public.documents for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

-- practice_areas: everyone in the org can use them; owners and partners manage them.
create policy "Org members can view practice areas"
  on public.practice_areas for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Owners and partners can create practice areas"
  on public.practice_areas for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

create policy "Owners and partners can update practice areas"
  on public.practice_areas for update to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  )
  with check (org_id = (select public.active_org_id()));

create policy "Owners and partners can delete practice areas"
  on public.practice_areas for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

-- legal_knowledge_base: readable by the org; owners, partners and associates add;
-- owners and partners delete. Rows are immutable (no update policy).
create policy "Org members can search the knowledge base"
  on public.legal_knowledge_base for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Owners, partners and associates can add knowledge"
  on public.legal_knowledge_base for insert to authenticated
  with check (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner', 'associate']))
  );

create policy "Owners and partners can delete knowledge"
  on public.legal_knowledge_base for delete to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

-- audit_logs: owners and partners read their active org's log. No insert/update/delete
-- policies: only the service role writes, and the trigger blocks changes for everyone.
create policy "Owners and partners can read the audit log"
  on public.audit_logs for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  );

revoke insert, update, delete on public.audit_logs from anon, authenticated;
