-- Self-serve sign-up and team invitations.
--
-- * Sign-up metadata `firm_name` names the new user's workspace ("Sharma & Associates").
-- * Owners and partners invite colleagues by email before they have an account. When someone
--   signs up with an invited email, they join those firms with the invited roles (and land in
--   the first one) instead of getting an empty personal workspace.

create table if not exists public.organization_invitations (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null references public.organizations (id) on delete cascade,
  email        text not null check (email = lower(email) and email like '%_@_%'),
  role         text not null check (role in ('owner', 'partner', 'associate', 'paralegal')),
  invited_by   uuid default auth.uid() references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null default now() + interval '14 days',
  accepted_at  timestamptz,
  unique (org_id, email)
);

create index if not exists organization_invitations_email_idx
  on public.organization_invitations (email) where accepted_at is null;

alter table public.organization_invitations enable row level security;

-- Same rules as adding members: owners invite any role; partners invite associates and paralegals.
create policy "Owners and partners see their org's invitations"
  on public.organization_invitations for select to authenticated
  using ((select public.has_org_role(org_id, array['owner', 'partner'])));

create policy "Owners and partners invite within their powers"
  on public.organization_invitations for insert to authenticated
  with check (
    (select public.has_org_role(org_id, array['owner']))
    or ((select public.has_org_role(org_id, array['partner'])) and role in ('associate', 'paralegal'))
  );

create policy "Owners and partners revoke invitations"
  on public.organization_invitations for delete to authenticated
  using (
    (select public.has_org_role(org_id, array['owner']))
    or ((select public.has_org_role(org_id, array['partner'])) and role in ('associate', 'paralegal'))
  );

revoke update on public.organization_invitations from anon, authenticated;

-- New users: profile, then pending invitations; a personal workspace only if nobody invited them.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  workspace_id uuid;
  first_org uuid;
  display_name text;
  invitation record;
begin
  insert into public.users (id, email, full_name)
  values (new.id, new.email, new.raw_user_meta_data ->> 'full_name');

  for invitation in
    select i.id, i.org_id, i.role from public.organization_invitations i
    where i.email = lower(new.email) and i.accepted_at is null and i.expires_at > now()
    order by i.created_at
  loop
    insert into public.organization_members (org_id, user_id, role)
    values (invitation.org_id, new.id, invitation.role)
    on conflict (org_id, user_id) do nothing;
    update public.organization_invitations set accepted_at = now() where id = invitation.id;
    first_org := coalesce(first_org, invitation.org_id);
  end loop;

  if first_org is not null then
    update public.users set active_org_id = first_org where id = new.id;
    return new;
  end if;

  display_name := coalesce(
    nullif(trim(new.raw_user_meta_data ->> 'firm_name'), ''),
    nullif(new.raw_user_meta_data ->> 'full_name', '') || '''s workspace',
    split_part(new.email, '@', 1) || '''s workspace'
  );
  insert into public.organizations (name, created_by)
  values (left(display_name, 200), new.id)
  returning id into workspace_id;
  insert into public.organization_members (org_id, user_id, role) values (workspace_id, new.id, 'owner');
  update public.users set active_org_id = workspace_id where id = new.id;
  return new;
end;
$$;
