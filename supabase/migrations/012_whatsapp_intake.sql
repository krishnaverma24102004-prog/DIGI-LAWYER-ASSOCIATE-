-- WhatsApp intake: clients message the firm's WhatsApp Business number; the AI takes the intake
-- (after the client consents), the lawyer reads the chat and can take over at any time.
-- Written by the server (the Meta webhook has no user session, like phone calls); read through RLS.

create table if not exists public.whatsapp_numbers (
  phone_number_id   text primary key,                 -- Meta's id for the business number
  display_number    text not null check (display_number ~ '^\+[1-9][0-9]{6,14}$'),
  org_id            uuid not null references public.organizations (id) on delete cascade,
  owner_user_id     uuid not null references public.users (id) on delete cascade,
  practice_area_id  uuid references public.practice_areas (id) on delete set null,
  jurisdiction      text,
  greeting          text check (char_length(greeting) <= 1000),
  enabled           boolean not null default true,
  created_at        timestamptz not null default now()
);

create table if not exists public.whatsapp_conversations (
  id               uuid primary key default gen_random_uuid(),
  org_id           uuid not null references public.organizations (id) on delete cascade,
  phone_number_id  text not null references public.whatsapp_numbers (phone_number_id) on delete cascade,
  owner_user_id    uuid not null references public.users (id) on delete cascade,
  wa_id            text not null,  -- the client's WhatsApp number (digits, with country code)
  client_name      text,
  status           text not null default 'awaiting_consent'
                   check (status in ('awaiting_consent', 'intake', 'lawyer', 'closed')),
  consent_at       timestamptz,
  agent_state      jsonb not null default '{}'::jsonb,
  transcript_id    uuid references public.transcripts (id) on delete set null,
  last_message_at  timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  unique (phone_number_id, wa_id)
);

create index if not exists whatsapp_conversations_org_idx on public.whatsapp_conversations (org_id, last_message_at desc);

create table if not exists public.whatsapp_messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.whatsapp_conversations (id) on delete cascade,
  wa_message_id    text unique,  -- Meta's id: webhook retries are ignored
  direction        text not null check (direction in ('in', 'out')),
  sender           text not null check (sender in ('client', 'ai', 'lawyer', 'system')),
  kind             text not null default 'text',
  body             text not null default '',
  created_at       timestamptz not null default now()
);

create index if not exists whatsapp_messages_conversation_idx on public.whatsapp_messages (conversation_id, created_at);

alter table public.whatsapp_numbers       enable row level security;
alter table public.whatsapp_conversations enable row level security;
alter table public.whatsapp_messages      enable row level security;

create policy "Org members can view WhatsApp numbers"
  on public.whatsapp_numbers for select to authenticated
  using (org_id = (select public.active_org_id()));

create policy "Owners and partners manage WhatsApp numbers"
  on public.whatsapp_numbers for all to authenticated
  using (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
  )
  with check (
    org_id = (select public.active_org_id())
    and (select public.has_org_role((select public.active_org_id()), array['owner', 'partner']))
    and (select public.is_org_member_user(org_id, owner_user_id))
  );

-- Chats: the number's owner (the lawyer receiving intake) and the firm's owners and partners.
create policy "Number owner and seniors read WhatsApp conversations"
  on public.whatsapp_conversations for select to authenticated
  using (
    org_id = (select public.active_org_id())
    and (owner_user_id = (select auth.uid())
         or (select public.has_org_role((select public.active_org_id()), array['owner', 'partner'])))
  );

create policy "Messages follow their conversation"
  on public.whatsapp_messages for select to authenticated
  using (exists (select 1 from public.whatsapp_conversations c where c.id = conversation_id));

revoke insert, update, delete on public.whatsapp_conversations, public.whatsapp_messages from anon, authenticated;
