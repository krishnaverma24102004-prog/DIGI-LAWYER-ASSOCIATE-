-- Safety rails for the firm's own actions.
--
-- * Trash: deleting a consultation, document, draft, review grid, court case, case thread or
--   knowledge source moves a snapshot of it to `trash_items` for 30 days, where it can be
--   restored. After that a daily job purges the snapshot and keeps a tombstone (who deleted what,
--   who approved, when it was erased, and a SHA-256 of what was erased) as the erasure record.
--   Direct deletes on those tables are revoked: `trash_item()` is the only way to remove them.
-- * Approvals (maker-checker): associates and paralegals ask a partner or owner to delete client
--   records; enabling public intake, making someone an owner and erasing from the trash early
--   need a second senior. In a firm with a single owner/partner, that person decides alone.
-- * Legal hold on case threads and court cases blocks deleting them and the records linked to them.
-- * Public intake (AI answering WhatsApp messages and phone calls) is off until a firm turns it on.
-- * Drafts record who approved them (cleared when the text changes); case threads record the
--   client's consent to AI processing; AI WhatsApp replies can wait for a lawyer's approval.

-- ---------------------------------------------------------------------------
-- Columns
-- ---------------------------------------------------------------------------
alter table public.organizations
  add column if not exists public_intake_enabled boolean not null default false,
  add column if not exists public_intake_changed_by uuid references public.users (id) on delete set null,
  add column if not exists public_intake_changed_at timestamptz;

alter table public.case_threads
  add column if not exists legal_hold boolean not null default false,
  add column if not exists legal_hold_by uuid references public.users (id) on delete set null,
  add column if not exists legal_hold_at timestamptz,
  add column if not exists legal_hold_reason text check (char_length(legal_hold_reason) <= 500),
  add column if not exists ai_consent_at timestamptz,
  add column if not exists ai_consent_by uuid references public.users (id) on delete set null,
  add column if not exists ai_consent_method text check (ai_consent_method in ('verbal', 'written', 'whatsapp', 'phone'));

alter table public.court_cases
  add column if not exists legal_hold boolean not null default false,
  add column if not exists legal_hold_by uuid references public.users (id) on delete set null,
  add column if not exists legal_hold_at timestamptz,
  add column if not exists legal_hold_reason text check (char_length(legal_hold_reason) <= 500);

alter table public.drafts
  add column if not exists approved_by uuid references public.users (id) on delete set null,
  add column if not exists approved_at timestamptz,
  -- The facts a generated draft was built from, for its self-check (services/draft_check.py).
  add column if not exists fact_basis jsonb not null default '{}'::jsonb;

alter table public.whatsapp_messages
  add column if not exists status text not null default 'sent' check (status in ('sent', 'pending', 'discarded')),
  add column if not exists reviewed_by uuid references public.users (id) on delete set null,
  add column if not exists reviewed_at timestamptz,
  add column if not exists hold_reasons text[] not null default '{}';  -- why an AI reply waits for a lawyer

-- The law a contract's own clause says governs it (services/governing_law.py), found at upload.
alter table public.documents
  add column if not exists governing_law jsonb;

-- How a review answer's quote was found in the document: word for word, or a close match (the
-- quote's differing words listed for the lawyer to check).
alter table public.review_cells
  add column if not exists quote_match text check (quote_match in ('exact', 'close')),
  add column if not exists quote_differs text[] not null default '{}';

create index if not exists whatsapp_messages_pending_idx
  on public.whatsapp_messages (conversation_id) where status = 'pending';

-- Legal hold changes only through set_legal_hold() (which records who and why).
create or replace function public.guard_legal_hold()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (new.legal_hold, new.legal_hold_by, new.legal_hold_at, new.legal_hold_reason)
     is distinct from (old.legal_hold, old.legal_hold_by, old.legal_hold_at, old.legal_hold_reason)
     and coalesce(current_setting('app.legal_hold_change', true), '') <> 'on'
     and current_user in ('anon', 'authenticated') then
    raise exception 'Legal hold can only be changed by an owner or partner' using errcode = '42501';
  end if;
  return new;
end;
$$;

drop trigger if exists case_threads_guard_legal_hold on public.case_threads;
create trigger case_threads_guard_legal_hold
  before update on public.case_threads
  for each row execute function public.guard_legal_hold();

drop trigger if exists court_cases_guard_legal_hold on public.court_cases;
create trigger court_cases_guard_legal_hold
  before update on public.court_cases
  for each row execute function public.guard_legal_hold();

-- Consent is recorded as given by the signed-in lawyer, at the time it was recorded.
create or replace function public.stamp_ai_consent()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.ai_consent_at is distinct from old.ai_consent_at then
    if new.ai_consent_at is null then
      new.ai_consent_by := null;
      new.ai_consent_method := null;
    else
      new.ai_consent_at := now();
      new.ai_consent_by := coalesce(auth.uid(), new.ai_consent_by);
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists case_threads_stamp_ai_consent on public.case_threads;
create trigger case_threads_stamp_ai_consent
  before update on public.case_threads
  for each row execute function public.stamp_ai_consent();

-- A draft's approval names the approver and the time, and lapses when the draft changes.
create or replace function public.stamp_draft_approval()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if current_user in ('anon', 'authenticated') then  -- restoring from the trash keeps the approval
      new.approved_by := null;
      new.approved_at := null;
    end if;
  elsif new.approved_at is not null and old.approved_at is null then
    new.approved_at := now();
    new.approved_by := coalesce(auth.uid(), new.approved_by);
  elsif new.approved_at is null then
    new.approved_by := null;
  elsif (new.content, new.variables, new.title) is distinct from (old.content, old.variables, old.title) then
    new.approved_at := null;
    new.approved_by := null;
  else
    new.approved_at := old.approved_at;
    new.approved_by := old.approved_by;
  end if;
  return new;
end;
$$;

drop trigger if exists drafts_stamp_approval on public.drafts;
create trigger drafts_stamp_approval
  before insert or update on public.drafts
  for each row execute function public.stamp_draft_approval();

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
-- How many owners and partners the org has.
create or replace function public.senior_count(target_org uuid)
returns integer
language sql
stable
security definer
set search_path = ''
as $$
  select count(*)::integer from public.organization_members m
  where m.org_id = target_org and m.role in ('owner', 'partner')
$$;

-- Whether the caller is the org's only owner/partner (who then decides alone).
create or replace function public.is_sole_senior(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select public.has_org_role(target_org, array['owner', 'partner']) and public.senior_count(target_org) = 1
$$;

-- ---------------------------------------------------------------------------
-- Approval requests (maker-checker)
-- ---------------------------------------------------------------------------
create table if not exists public.approval_requests (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null references public.organizations (id) on delete cascade,
  action         text not null check (action in ('delete', 'enable_intake', 'make_owner', 'purge')),
  target_kind    text not null,
  target_id      text not null,
  target_label   text check (char_length(target_label) <= 300),
  payload        jsonb not null default '{}'::jsonb,
  reason         text check (char_length(reason) <= 1000),
  requested_by   uuid references public.users (id) on delete set null,
  requested_at   timestamptz not null default now(),
  expires_at     timestamptz not null default now() + interval '7 days',
  status         text not null default 'pending'
                 check (status in ('pending', 'approved', 'rejected', 'cancelled', 'executed', 'failed')),
  decided_by     uuid references public.users (id) on delete set null,
  decided_at     timestamptz,
  decision_note  text check (char_length(decision_note) <= 1000),
  executed_at    timestamptz,
  error          text,
  check (decided_by is null or decided_by is distinct from requested_by)
);

create index if not exists approval_requests_org_status_idx on public.approval_requests (org_id, status, requested_at desc);
create unique index if not exists approval_requests_one_pending_idx
  on public.approval_requests (org_id, action, target_kind, target_id) where status = 'pending';

alter table public.approval_requests enable row level security;

-- Seniors see the firm's requests; everyone sees their own.
create policy "Requesters and seniors read approval requests"
  on public.approval_requests for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (requested_by = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

revoke insert, update, delete on public.approval_requests from anon, authenticated;

-- Roles that may ask for, and decide, each kind of request.
create or replace function public.requester_roles(p_action text)
returns text[]
language sql
immutable
set search_path = ''
as $$
  select case p_action
    when 'delete' then array['owner', 'partner', 'associate', 'paralegal']
    when 'enable_intake' then array['owner', 'partner']
    else array['owner']
  end
$$;

create or replace function public.approver_roles(p_action text)
returns text[]
language sql
immutable
set search_path = ''
as $$
  select case when p_action = 'make_owner' then array['owner'] else array['owner', 'partner'] end
$$;

create or replace function public.request_approval(
  p_action text, p_target_kind text, p_target_id text, p_target_label text default null,
  p_payload jsonb default '{}'::jsonb, p_reason text default null
)
returns public.approval_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_row public.approval_requests;
begin
  if auth.uid() is null or v_org is null then
    raise exception 'Not a member of this organization' using errcode = '42501';
  end if;
  if p_action not in ('delete', 'enable_intake', 'make_owner', 'purge') then
    raise exception 'Unknown action %', p_action using errcode = '22023';
  end if;
  if not public.has_org_role(v_org, public.requester_roles(p_action)) then
    raise exception 'Only % can request this', array_to_string(public.requester_roles(p_action), ' or ')
      using errcode = '42501';
  end if;

  select * into v_row from public.approval_requests r
  where r.org_id = v_org and r.action = p_action and r.target_kind = p_target_kind
    and r.target_id = p_target_id and r.status = 'pending';
  if found then
    if v_row.expires_at > now() then
      return v_row;
    end if;
    update public.approval_requests set status = 'cancelled', error = 'expired' where id = v_row.id;
  end if;

  insert into public.approval_requests (org_id, action, target_kind, target_id, target_label, payload, reason, requested_by)
  values (v_org, p_action, p_target_kind, p_target_id, left(p_target_label, 300), coalesce(p_payload, '{}'::jsonb),
          left(p_reason, 1000), auth.uid())
  returning * into v_row;
  return v_row;
end;
$$;

-- Approve or reject. The decider can't be the requester.
create or replace function public.decide_approval(p_id uuid, p_approve boolean, p_note text default null)
returns public.approval_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_row public.approval_requests;
begin
  select * into v_row from public.approval_requests r where r.id = p_id and r.org_id = v_org for update;
  if not found then
    raise exception 'Approval request not found' using errcode = 'P0002';
  end if;
  if not public.has_org_role(v_org, public.approver_roles(v_row.action)) then
    raise exception 'Only % can decide this request', array_to_string(public.approver_roles(v_row.action), ' or ')
      using errcode = '42501';
  end if;
  if v_row.requested_by = auth.uid() then
    raise exception 'Someone other than the requester must decide' using errcode = '42501';
  end if;
  if v_row.status <> 'pending' then
    raise exception 'This request is already %', v_row.status using errcode = '55000';
  end if;
  if v_row.expires_at <= now() then
    update public.approval_requests set status = 'cancelled', error = 'expired' where id = p_id;
    raise exception 'This request has expired' using errcode = '55000';
  end if;

  update public.approval_requests
  set status = case when p_approve then 'approved' else 'rejected' end,
      decided_by = auth.uid(), decided_at = now(), decision_note = left(p_note, 1000)
  where id = p_id
  returning * into v_row;
  return v_row;
end;
$$;

-- The requester withdraws a pending request.
create or replace function public.cancel_approval(p_id uuid)
returns boolean
language sql
security definer
set search_path = ''
as $$
  with cancelled as (
    update public.approval_requests set status = 'cancelled'
    where id = p_id and org_id = public.active_org_id() and requested_by = auth.uid() and status = 'pending'
    returning 1
  )
  select exists (select 1 from cancelled)
$$;

-- The approver records the outcome of carrying out an approved request.
create or replace function public.complete_approval(p_id uuid, p_ok boolean, p_error text default null)
returns boolean
language sql
security definer
set search_path = ''
as $$
  with done as (
    update public.approval_requests
    set status = case when p_ok then 'executed' else 'failed' end,
        executed_at = case when p_ok then now() end, error = left(p_error, 1000)
    where id = p_id and org_id = public.active_org_id() and decided_by = auth.uid() and status = 'approved'
    returning 1
  )
  select exists (select 1 from done)
$$;

-- Consumes an approved request for exactly this action and target, decided by the caller.
create or replace function public.use_approval(p_id uuid, p_org uuid, p_action text, p_target_kind text, p_target_id text)
returns public.approval_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_row public.approval_requests;
begin
  update public.approval_requests set status = 'executed', executed_at = now()
  where id = p_id and org_id = p_org and action = p_action and target_kind = p_target_kind
    and target_id = p_target_id and status = 'approved' and decided_by = auth.uid()
  returning * into v_row;
  if not found then
    raise exception 'No approved request matches this action' using errcode = '42501';
  end if;
  return v_row;
end;
$$;

revoke execute on function public.use_approval(uuid, uuid, text, text, text) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Public intake switch
-- ---------------------------------------------------------------------------
-- Turning intake off: any owner or partner. Turning it on: the firm's only senior, or a
-- second senior approving a request (p_approval).
create or replace function public.set_public_intake(p_enabled boolean, p_approval uuid default null)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
begin
  if v_org is null or not public.has_org_role(v_org, array['owner', 'partner']) then
    raise exception 'Only owners and partners can change public intake' using errcode = '42501';
  end if;
  if p_enabled and not public.is_sole_senior(v_org) then
    if p_approval is null then
      raise exception 'approval_required' using errcode = '42501',
        hint = 'Another owner or partner must approve turning on public intake';
    end if;
    perform public.use_approval(p_approval, v_org, 'enable_intake', 'organization', v_org::text);
  end if;
  update public.organizations
  set public_intake_enabled = p_enabled, public_intake_changed_by = auth.uid(), public_intake_changed_at = now()
  where id = v_org;
  return p_enabled;
end;
$$;

-- ---------------------------------------------------------------------------
-- Legal hold
-- ---------------------------------------------------------------------------
create or replace function public.set_legal_hold(p_kind text, p_id uuid, p_hold boolean, p_reason text default null)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_count integer;
begin
  if v_org is null or not public.has_org_role(v_org, array['owner', 'partner']) then
    raise exception 'Only owners and partners can place or lift a legal hold' using errcode = '42501';
  end if;
  perform set_config('app.legal_hold_change', 'on', true);
  if p_kind = 'case_thread' then
    update public.case_threads
    set legal_hold = p_hold, legal_hold_by = auth.uid(), legal_hold_at = now(),
        legal_hold_reason = case when p_hold then left(p_reason, 500) end
    where id = p_id and org_id = v_org;
  elsif p_kind = 'court_case' then
    update public.court_cases
    set legal_hold = p_hold, legal_hold_by = auth.uid(), legal_hold_at = now(),
        legal_hold_reason = case when p_hold then left(p_reason, 500) end
    where id = p_id and org_id = v_org;
  else
    raise exception 'Legal hold applies to case threads and court cases' using errcode = '22023';
  end if;
  get diagnostics v_count = row_count;
  perform set_config('app.legal_hold_change', '', true);
  if v_count = 0 then
    raise exception 'Not found' using errcode = 'P0002';
  end if;
  return p_hold;
end;
$$;

-- Whether a case thread is on hold (null thread: no).
create or replace function public.thread_on_hold(p_thread uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce((select t.legal_hold from public.case_threads t where t.id = p_thread), false)
$$;

-- ---------------------------------------------------------------------------
-- Trash
-- ---------------------------------------------------------------------------
create table if not exists public.trash_items (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organizations (id) on delete cascade,
  kind             text not null check (kind in ('transcript', 'document', 'draft', 'review_grid',
                                                 'court_case', 'case_thread', 'knowledge_source')),
  item_id          uuid not null,
  title            text,
  owner_user_id    uuid references public.users (id) on delete set null,  -- whose record it was
  snapshot         jsonb,          -- {"row": ..., "children": [...], "links": {...}}; null once purged
  snapshot_sha256  text not null,
  reason           text check (char_length(reason) <= 1000),
  deleted_by       uuid references public.users (id) on delete set null,
  deleted_at       timestamptz not null default now(),
  approval_id      uuid references public.approval_requests (id) on delete set null,
  requested_by     uuid references public.users (id) on delete set null,
  purge_after      timestamptz not null default now() + interval '30 days',
  restored_at      timestamptz,
  restored_by      uuid references public.users (id) on delete set null,
  purged_at        timestamptz,
  purged_by        uuid references public.users (id) on delete set null  -- null: the retention job
);

create index if not exists trash_items_org_idx on public.trash_items (org_id, deleted_at desc);
create index if not exists trash_items_purge_idx on public.trash_items (purge_after) where purged_at is null and restored_at is null;

alter table public.trash_items enable row level security;

create policy "Seniors, deleters and owners read the trash"
  on public.trash_items for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (deleted_by = (select auth.uid()) or owner_user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

revoke insert, update, delete on public.trash_items from anon, authenticated;

-- Records may only leave through trash_item().
revoke delete on public.transcripts, public.documents, public.drafts, public.review_grids,
  public.court_cases, public.case_threads from anon, authenticated;

-- Kinds associates and paralegals may trash themselves (their own working files). Client
-- records (consultations, documents, court cases) need a partner's or owner's approval;
-- case threads and knowledge sources are deleted by seniors only.
create or replace function public.self_trashable(p_kind text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p_kind in ('draft', 'review_grid')
$$;

-- Moves one record (with its dependent rows) to the trash. Returns the trash item id.
-- Errors: 42501 not allowed / approval_required, P0002 not found, 55006 legal hold.
create or replace function public.trash_item(p_kind text, p_id uuid, p_reason text default null, p_approval uuid default null)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_uid uuid := auth.uid();
  v_senior boolean;
  v_row jsonb;
  v_children jsonb := '[]'::jsonb;
  v_links jsonb := '{}'::jsonb;
  v_owner uuid;
  v_title text;
  v_thread uuid;
  v_held boolean := false;
  v_snapshot jsonb;
  v_approval public.approval_requests;
  v_trash uuid;
begin
  if v_uid is null or v_org is null then
    raise exception 'Not a member of this organization' using errcode = '42501';
  end if;
  v_senior := public.has_org_role(v_org, array['owner', 'partner']);

  if p_kind = 'transcript' then
    select to_jsonb(t), t.user_id, coalesce(t.title, 'Consultation'), t.thread_id
      into v_row, v_owner, v_title, v_thread
      from public.transcripts t where t.id = p_id and t.org_id = v_org;
    v_held := public.thread_on_hold(v_thread);
  elsif p_kind = 'document' then
    select to_jsonb(d), d.user_id, d.filename into v_row, v_owner, v_title
      from public.documents d where d.id = p_id and d.org_id = v_org;
    select exists (select 1 from public.transcripts t
                   where t.document_id = p_id and public.thread_on_hold(t.thread_id)) into v_held;
    select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb) into v_children
      from public.review_cells c where c.document_id = p_id;
    select jsonb_build_object('transcripts', coalesce(jsonb_agg(t.id), '[]'::jsonb)) into v_links
      from public.transcripts t where t.document_id = p_id;
  elsif p_kind = 'draft' then
    select to_jsonb(d), d.user_id, d.title, d.thread_id into v_row, v_owner, v_title, v_thread
      from public.drafts d where d.id = p_id and d.org_id = v_org;
    v_held := public.thread_on_hold(v_thread);
  elsif p_kind = 'review_grid' then
    select to_jsonb(g), g.user_id, g.title into v_row, v_owner, v_title
      from public.review_grids g where g.id = p_id and g.org_id = v_org;
    select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb) into v_children
      from public.review_cells c where c.grid_id = p_id;
  elsif p_kind = 'court_case' then
    select to_jsonb(c), c.user_id, c.title, c.thread_id, c.legal_hold into v_row, v_owner, v_title, v_thread, v_held
      from public.court_cases c where c.id = p_id and c.org_id = v_org;
    v_held := coalesce(v_held, false) or public.thread_on_hold(v_thread);
  elsif p_kind = 'case_thread' then
    select to_jsonb(t), t.user_id, t.title, t.legal_hold into v_row, v_owner, v_title, v_held
      from public.case_threads t where t.id = p_id and t.org_id = v_org;
    select coalesce(jsonb_agg(to_jsonb(m) order by m.created_at), '[]'::jsonb) into v_children
      from public.thread_messages m where m.thread_id = p_id;
    v_links := jsonb_build_object(
      'transcripts', (select coalesce(jsonb_agg(x.id), '[]'::jsonb) from public.transcripts x where x.thread_id = p_id),
      'drafts', (select coalesce(jsonb_agg(x.id), '[]'::jsonb) from public.drafts x where x.thread_id = p_id),
      'court_cases', (select coalesce(jsonb_agg(x.id), '[]'::jsonb) from public.court_cases x where x.thread_id = p_id));
  elsif p_kind = 'knowledge_source' then
    select coalesce(jsonb_agg(to_jsonb(k) order by k.chunk_index), '[]'::jsonb),
           (array_agg(k.created_by order by k.chunk_index))[1], (array_agg(k.title order by k.chunk_index))[1]
      into v_children, v_owner, v_title
      from public.legal_knowledge_base k where k.source_id = p_id and k.org_id = v_org;
    if jsonb_array_length(v_children) > 0 then
      v_row := jsonb_build_object('source_id', p_id);
    end if;
  else
    raise exception 'Unknown kind %', p_kind using errcode = '22023';
  end if;

  -- What the caller may see: the same rule as the tables' read policies.
  if v_row is null or (p_kind not in ('knowledge_source') and not v_senior and v_owner is distinct from v_uid) then
    raise exception 'Not found' using errcode = 'P0002';
  end if;
  if v_held then
    raise exception 'legal_hold' using errcode = '55006',
      hint = 'This record is under legal hold. A partner or owner must lift the hold before it can be deleted.';
  end if;

  if p_approval is not null then
    v_approval := public.use_approval(p_approval, v_org, 'delete', p_kind, p_id::text);
  elsif not v_senior and not public.self_trashable(p_kind) then
    raise exception 'approval_required' using errcode = '42501',
      hint = 'A partner or owner must approve deleting this record';
  end if;

  v_snapshot := jsonb_build_object('row', v_row, 'children', v_children, 'links', v_links);
  insert into public.trash_items (org_id, kind, item_id, title, owner_user_id, snapshot, snapshot_sha256,
                                  reason, deleted_by, approval_id, requested_by)
  values (v_org, p_kind, p_id, left(v_title, 300), v_owner, v_snapshot,
          encode(sha256(convert_to(v_snapshot::text, 'UTF8')), 'hex'),
          left(coalesce(p_reason, v_approval.reason), 1000), v_uid, v_approval.id,
          coalesce(v_approval.requested_by, v_uid))
  returning id into v_trash;

  if p_kind = 'transcript' then delete from public.transcripts where id = p_id;
  elsif p_kind = 'document' then delete from public.documents where id = p_id;
  elsif p_kind = 'draft' then delete from public.drafts where id = p_id;
  elsif p_kind = 'review_grid' then delete from public.review_grids where id = p_id;
  elsif p_kind = 'court_case' then delete from public.court_cases where id = p_id;
  elsif p_kind = 'case_thread' then delete from public.case_threads where id = p_id;
  elsif p_kind = 'knowledge_source' then delete from public.legal_knowledge_base where source_id = p_id and org_id = v_org;
  end if;
  return v_trash;
end;
$$;

-- Puts a trashed record back, with its dependent rows and links (where those still exist).
create or replace function public.restore_trash_item(p_id uuid)
returns public.trash_items
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_item public.trash_items;
  v_row jsonb;
  v_id uuid;
begin
  select * into v_item from public.trash_items i where i.id = p_id and i.org_id = v_org for update;
  if not found then
    raise exception 'Not found' using errcode = 'P0002';
  end if;
  if not (public.has_org_role(v_org, array['owner', 'partner'])
          or (v_item.deleted_by = auth.uid() and v_item.owner_user_id = auth.uid())) then
    raise exception 'Only a partner or owner can restore this' using errcode = '42501';
  end if;
  if v_item.restored_at is not null or v_item.purged_at is not null or v_item.snapshot is null then
    raise exception 'This item has already been %', case when v_item.restored_at is not null then 'restored' else 'erased' end
      using errcode = '55000';
  end if;

  v_row := v_item.snapshot -> 'row';
  v_id := v_item.item_id;
  begin
    if v_item.kind = 'transcript' then
      insert into public.transcripts select * from jsonb_populate_record(null::public.transcripts, v_row);
    elsif v_item.kind = 'document' then
      insert into public.documents select * from jsonb_populate_record(null::public.documents, v_row);
      insert into public.review_cells
        select c.* from jsonb_populate_recordset(null::public.review_cells, v_item.snapshot -> 'children') c
        where exists (select 1 from public.review_grids g where g.id = c.grid_id)
        on conflict do nothing;
      update public.transcripts set document_id = v_id
        where document_id is null
          and id in (select (jsonb_array_elements_text(v_item.snapshot -> 'links' -> 'transcripts'))::uuid);
    elsif v_item.kind = 'draft' then
      insert into public.drafts select * from jsonb_populate_record(null::public.drafts, v_row);
    elsif v_item.kind = 'review_grid' then
      insert into public.review_grids select * from jsonb_populate_record(null::public.review_grids, v_row);
      insert into public.review_cells
        select c.* from jsonb_populate_recordset(null::public.review_cells, v_item.snapshot -> 'children') c
        where exists (select 1 from public.documents d where d.id = c.document_id)
        on conflict do nothing;
    elsif v_item.kind = 'court_case' then
      insert into public.court_cases select * from jsonb_populate_record(null::public.court_cases, v_row);
    elsif v_item.kind = 'case_thread' then
      insert into public.case_threads select * from jsonb_populate_record(null::public.case_threads, v_row);
      insert into public.thread_messages
        select * from jsonb_populate_recordset(null::public.thread_messages, v_item.snapshot -> 'children');
      update public.transcripts set thread_id = v_id where thread_id is null
        and id in (select (jsonb_array_elements_text(v_item.snapshot -> 'links' -> 'transcripts'))::uuid);
      update public.drafts set thread_id = v_id where thread_id is null
        and id in (select (jsonb_array_elements_text(v_item.snapshot -> 'links' -> 'drafts'))::uuid);
      update public.court_cases set thread_id = v_id where thread_id is null
        and id in (select (jsonb_array_elements_text(v_item.snapshot -> 'links' -> 'court_cases'))::uuid);
    elsif v_item.kind = 'knowledge_source' then
      insert into public.legal_knowledge_base
        select * from jsonb_populate_recordset(null::public.legal_knowledge_base, v_item.snapshot -> 'children');
    end if;
  exception
    when unique_violation then
      raise exception 'A record with the same id or case number exists again; it can''t be restored over it'
        using errcode = '23505';
    when foreign_key_violation then
      raise exception 'Something this record belonged to (its author or organization) no longer exists'
        using errcode = '23503';
  end;

  update public.trash_items set restored_at = now(), restored_by = auth.uid(), snapshot = null
  where id = p_id returning * into v_item;
  return v_item;
end;
$$;

-- Erases a trashed item's snapshot before the retention period ends (a client's erasure
-- request, for example): an owner asks and another owner or partner approves and erases;
-- an owner who is the firm's only senior erases alone.
create or replace function public.purge_trash_item(p_id uuid, p_approval uuid default null)
returns public.trash_items
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid := public.active_org_id();
  v_item public.trash_items;
begin
  if v_org is null or not public.has_org_role(v_org, array['owner', 'partner']) then
    raise exception 'Only owners and partners can erase from the trash' using errcode = '42501';
  end if;
  select * into v_item from public.trash_items i where i.id = p_id and i.org_id = v_org for update;
  if not found or v_item.snapshot is null then
    raise exception 'Not found' using errcode = 'P0002';
  end if;
  if p_approval is not null then
    perform public.use_approval(p_approval, v_org, 'purge', 'trash_item', p_id::text);
  elsif not (public.is_sole_senior(v_org) and public.has_org_role(v_org, array['owner'])) then
    raise exception 'approval_required' using errcode = '42501',
      hint = 'An owner asks and another owner or partner approves erasing this before its retention period ends';
  end if;
  update public.trash_items set snapshot = null, purged_at = now(), purged_by = auth.uid()
  where id = p_id returning * into v_item;
  return v_item;
end;
$$;

-- Retention job (service role): erases snapshots past their retention period, except records
-- whose case thread has since been put under legal hold.
create or replace function public.purge_expired_trash()
returns setof public.trash_items
language sql
security definer
set search_path = ''
as $$
  update public.trash_items i set snapshot = null, purged_at = now()
  where i.purged_at is null and i.restored_at is null and i.purge_after <= now()
    and not public.thread_on_hold(nullif(i.snapshot -> 'row' ->> 'thread_id', '')::uuid)
  returning i.*
$$;

revoke execute on function public.purge_expired_trash() from public, anon, authenticated;
grant execute on function public.purge_expired_trash() to service_role;
