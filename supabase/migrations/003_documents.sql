-- Uploaded contracts / case documents, and a link from transcripts to the document
-- discussed in the consultation.

create table if not exists public.documents (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null default auth.uid() references public.users (id) on delete cascade,
  filename        text not null,
  content_type    text not null,
  size_bytes      integer not null,
  page_count      integer,
  char_count      integer not null,
  extracted_text  text not null,
  created_at      timestamptz not null default now()
);

create index if not exists documents_user_id_created_at_idx
  on public.documents (user_id, created_at desc);

alter table public.documents enable row level security;

create policy "Users can view own documents"
  on public.documents for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "Users can insert own documents"
  on public.documents for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

create policy "Users can delete own documents"
  on public.documents for delete
  to authenticated
  using ((select auth.uid()) = user_id);

-- A deleted document leaves its consultations in place, just unlinked.
alter table public.transcripts
  add column if not exists document_id uuid references public.documents (id) on delete set null;

create index if not exists transcripts_document_id_idx on public.transcripts (document_id);
