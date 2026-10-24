-- Adds the AI-generated post-consultation summary to transcripts.
-- Existing RLS policies on public.transcripts already cover the new column.

alter table public.transcripts
  add column if not exists summary text;
