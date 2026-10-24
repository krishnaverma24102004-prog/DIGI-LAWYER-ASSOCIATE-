# Digi Lawyer – client app

Next.js 16 (App Router) + Tailwind CSS 4.

- `src/components/ChatRoom.tsx`: split-screen session: conversation (typed + hold-to-talk) and the live case file
- `src/components/CaseFile.tsx`: legal risks, knowledge-base citations, web sources, key facts, open questions
- `src/hooks/useVoiceSession.ts`: WebRTC client: mic up, AI voice down, JSON events over the `events` data channel
- `src/hooks/useAuth.ts`: Supabase sign-in
- `src/app/studio/page.tsx`, `src/components/DocumentStudio.tsx`: Document Studio
  - `studio/RedlineViewer.tsx`: side-by-side redline, AI risk cards, per-clause decisions, negotiated version
  - `studio/ClauseEditor.tsx`: edit drafts clause by clause, AI revisions (accept/reject), .docx/PDF export
  - `studio/GenerateDraftModal.tsx`: generate notices and pleadings from a case
- `src/components/JurisdictionPicker.tsx`: IN / US / US state / UK, remembered across pages

## Run

```bash
copy .env.local.example .env.local   # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY
npm install
npm run dev
```

Open http://localhost:3000. The API (repo root) must be running, with this origin in its `CORS_ORIGINS`.
Microphone access needs `localhost` or HTTPS.

`npm run lint` and `npm run build` should both pass.
