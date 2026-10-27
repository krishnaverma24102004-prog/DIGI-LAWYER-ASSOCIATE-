"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgentStatus } from "@/components/AgentStatus";
import { CaseFile } from "@/components/CaseFile";
import { JurisdictionPicker } from "@/components/JurisdictionPicker";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";
import type { CaseThread, ChatMessage, CitationCheck, PracticeArea } from "@/lib/types";

const NEW_THREAD = "__new__";
const CONSENT_VALID_DAYS = 365;

function consentValid(thread: CaseThread | undefined): boolean {
  if (!thread?.ai_consent_at) return false;
  return Date.now() - new Date(thread.ai_consent_at).getTime() < CONSENT_VALID_DAYS * 86_400_000;
}

/** Before a consultation: the client agrees to AI processing, or the session keeps notes only. */
function ConsentDialog({ onChoose, onCancel }: { onChoose: (consent: "verbal" | "written" | null) => void; onCancel: () => void }) {
  const option = "w-full rounded-xl border px-4 py-3 text-left text-sm transition hover:border-indigo-400 dark:border-slate-700";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onCancel}>
      <div role="dialog" aria-modal="true" aria-labelledby="consent-title" onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl dark:bg-slate-900">
        <h2 id="consent-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Has the client agreed to AI assistance?
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Tell the client: the conversation is transcribed and analysed by AI for the lawyer; identity numbers are hidden from the AI. Their answer is
          remembered on this case for 12 months.
        </p>
        <div className="mt-4 flex flex-col gap-2">
          <button onClick={() => onChoose("verbal")} className={`${option} border-indigo-200 bg-indigo-50 dark:bg-indigo-950/30`}>
            <span className="font-medium text-slate-900 dark:text-slate-100">Yes, the client agreed</span>
            <span className="block text-xs text-slate-500">Verbal consent, recorded with your name and the time</span>
          </button>
          <button onClick={() => onChoose("written")} className={`${option} border-slate-200`}>
            <span className="font-medium text-slate-900 dark:text-slate-100">Yes, in writing</span>
            <span className="block text-xs text-slate-500">The client signed or emailed their consent</span>
          </button>
          <button onClick={() => onChoose(null)} className={`${option} border-slate-200`}>
            <span className="font-medium text-slate-900 dark:text-slate-100">No: notes only</span>
            <span className="block text-xs text-slate-500">No AI and no speech-to-text; your typed notes are saved</span>
          </button>
        </div>
      </div>
    </div>
  );
}

const select =
  "min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

function Bubble({ message }: { message: ChatMessage }) {
  const mine = message.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${
          mine
            ? "rounded-br-md bg-indigo-600 text-white"
            : "rounded-bl-md border border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        }`}
      >
        {message.text}
        {message.redactions?.length ? (
          <div className="mt-1 text-[11px] text-indigo-100" title={`The AI saw ${message.redactions.join(", ")} instead`}>
            {message.redactions.length} personal identifier{message.redactions.length > 1 ? "s" : ""} hidden from the AI
          </div>
        ) : null}
        {message.disclaimer ? (
          <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">Disclaimer added: this read like legal advice.</div>
        ) : null}
        {message.citations?.length ? <CitationSummary checks={message.citations} /> : null}
      </div>
    </div>
  );
}

function CitationSummary({ checks }: { checks: CitationCheck[] }) {
  const flagged = checks.filter((c) => c.status === "invalid" || c.status === "unverified");
  const verified = checks.length - flagged.length;
  const details = checks.map((c) => `${c.text}: ${c.label ?? c.status}${c.note ? ` (${c.note})` : ""}`).join("\n");
  return (
    <div
      title={details}
      className={`mt-1 text-[11px] ${flagged.length ? "text-amber-600 dark:text-amber-400" : "text-emerald-600 dark:text-emerald-400"}`}
    >
      {verified ? `${verified} citation${verified > 1 ? "s" : ""} checked` : ""}
      {verified && flagged.length ? " · " : ""}
      {flagged.length ? `${flagged.length} not found in the sources: check before relying on it` : ""}
    </div>
  );
}

export function ChatRoom({ token, email, onSignOut }: { token: string; email: string | null; onSignOut: () => void }) {
  const { state, audioRef, connect, sendText, startTalking, stopTalking, interrupt, recordConsent, end } = useVoiceSession();
  const [askConsent, setAskConsent] = useState(false);
  const live = state.status === "connected" || state.status === "connecting" || state.status === "ending";

  const { orgs, orgId, setOrgId, jurisdiction, setJurisdiction, error: workspaceError } = useWorkspace(token);
  const [areas, setAreas] = useState<PracticeArea[]>([]);
  const [areaId, setAreaId] = useState("");
  const [threads, setThreads] = useState<CaseThread[]>([]);
  const [threadId, setThreadId] = useState("");
  const [voice, setVoice] = useState(true);
  const [draft, setDraft] = useState("");
  const [talking, setTalking] = useState(false);
  const [tab, setTab] = useState<"chat" | "case">("chat");
  const [loadError, setLoadError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // The selected org's practice areas and case threads.
  const loadThreads = useCallback(
    () => (orgId ? api<CaseThread[]>("/api/v1/case-threads?status=open", { token, orgId }).then(setThreads) : Promise.resolve()),
    [orgId, token],
  );

  useEffect(() => {
    if (!orgId) return;
    api<PracticeArea[]>("/api/v1/practice-areas", { token, orgId }).then(setAreas).catch(() => setAreas([]));
    loadThreads().catch(() => setThreads([]));
  }, [orgId, token, loadThreads]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [state.messages.length, state.interim]);

  function changeOrg(id: string) {
    setOrgId(id);
    setAreaId("");
    setThreadId("");
  }

  async function chooseThread(value: string) {
    if (value !== NEW_THREAD) return setThreadId(value);
    const title = window.prompt('Name this case (e.g. "Kumar – deposit dispute")')?.trim();
    if (!title) return;
    try {
      const thread = await api<CaseThread>("/api/v1/case-threads", { token, orgId, method: "POST", body: { title } });
      await loadThreads();
      setThreadId(thread.id);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }

  function start() {
    // Consent given on this case within 12 months still holds; otherwise ask before anything is analysed.
    if (consentValid(threads.find((t) => t.id === threadId))) return begin(null);
    setAskConsent(true);
  }

  function begin(consent: "verbal" | "written" | null) {
    setAskConsent(false);
    connect({ token, orgId, practiceAreaId: areaId || null, threadId: threadId || null, voice, jurisdiction, consent });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || state.status !== "connected") return;
    sendText(text);
    setDraft("");
  }

  function pressTalk() {
    if (state.status !== "connected" || talking) return;
    setTalking(true);
    startTalking();
  }

  function releaseTalk() {
    if (!talking) return;
    setTalking(false);
    stopTalking();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <audio ref={audioRef} autoPlay hidden />
      {askConsent ? <ConsentDialog onChoose={begin} onCancel={() => setAskConsent(false)} /> : null}

      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
        <span className="mr-2 font-semibold text-slate-900 dark:text-slate-100">Digi Lawyer</span>
        <select aria-label="Organization" className={select} value={orgId ?? ""} onChange={(e) => changeOrg(e.target.value)} disabled={live}>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} ({o.role})
            </option>
          ))}
        </select>
        <select aria-label="Practice area" className={select} value={areaId} onChange={(e) => setAreaId(e.target.value)} disabled={live}>
          <option value="">General</option>
          {areas.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select aria-label="Case" className={select} value={threadId} onChange={(e) => chooseThread(e.target.value)} disabled={live}>
          <option value="">No case thread</option>
          {threads.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
          <option value={NEW_THREAD}>+ New case…</option>
        </select>
        <JurisdictionPicker value={jurisdiction} onChange={setJurisdiction} disabled={live} />
        <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={voice} onChange={(e) => setVoice(e.target.checked)} disabled={live} className="accent-indigo-600" />
          Spoken replies
        </label>
        <div className="ml-auto flex items-center gap-2">
          <Link href={`/studio?jurisdiction=${jurisdiction}`} className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Document Studio
          </Link>
          <Link href="/cases" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Cases
          </Link>
          <Link href="/inbox" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            WhatsApp
          </Link>
          <Link href="/workflows" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Workflows
          </Link>
          <Link href="/review" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Bulk Review
          </Link>
          <details className="relative text-sm">
            <summary className="cursor-pointer list-none text-indigo-700 hover:underline dark:text-indigo-300">Court desk ▾</summary>
            <div className="absolute right-0 z-20 mt-2 flex w-56 flex-col rounded-xl border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
              {[
                ["/board", "Tonight's board", "cause lists and appearances"],
                ["/hearings", "Hearings", "clashes and hearing briefs"],
                ["/deadlines", "Deadlines", "firm docket, blind check"],
                ["/limitation", "Limitation", "calculator and copy tracker"],
                ["/custody", "Custody", "default bail and s.479 dates"],
                ["/rules", "Rule sign-off", "check the rule tables"],
              ].map(([href, label, hint]) => (
                <Link key={href} href={href} className="rounded-lg px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800">
                  <span className="block font-medium text-slate-800 dark:text-slate-100">{label}</span>
                  <span className="block text-xs text-slate-500">{hint}</span>
                </Link>
              ))}
            </div>
          </details>
          <Link href="/team" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Team
          </Link>
          <Link href="/safety" className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Approvals &amp; Trash
          </Link>
          {live ? (
            <button
              onClick={end}
              disabled={state.status === "ending"}
              className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
            >
              {state.status === "ending" ? "Saving…" : "End session"}
            </button>
          ) : (
            <button onClick={start} disabled={!orgId} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              Start session
            </button>
          )}
          <button onClick={onSignOut} className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" title={email ?? undefined}>
            Sign out
          </button>
        </div>
      </header>

      <div className="flex border-b border-slate-200 bg-white text-sm lg:hidden dark:border-slate-800 dark:bg-slate-900">
        {(["chat", "case"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 ${tab === t ? "border-b-2 border-indigo-600 font-medium text-indigo-700 dark:text-indigo-300" : "text-slate-500"}`}
          >
            {t === "chat" ? "Conversation" : "Case file"}
          </button>
        ))}
      </div>

      <main className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {/* Left: the conversation */}
        <section className={`${tab === "chat" ? "flex" : "hidden"} min-h-0 flex-col lg:flex`}>
          <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
            {state.messages.length === 0 ? (
              <div className="m-auto max-w-sm text-center text-sm text-slate-500">
                {state.status === "idle" || state.status === "ended"
                  ? "Choose a practice area and case, then start a session. Type, or hold the mic button and speak."
                  : state.status === "connecting"
                    ? "Connecting…"
                    : "Listening. Type a message or hold the mic button to talk."}
              </div>
            ) : (
              state.messages.map((m) => <Bubble key={m.id} message={m} />)
            )}
            {state.interim ? <div className="self-end text-sm italic text-slate-400">{state.interim}…</div> : null}
          </div>

          <div className="flex flex-col gap-2 border-t border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
            {state.consentRequired && state.status === "connected" ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <span className="min-w-0 flex-1">AI is off: the client&apos;s consent isn&apos;t recorded. Typed notes are saved.</span>
                <button onClick={() => recordConsent("verbal")} className="rounded-lg bg-amber-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-amber-700">
                  Client agreed
                </button>
                <button onClick={() => recordConsent("written")} className="rounded-lg px-2.5 py-1 text-xs font-medium text-amber-800 hover:underline dark:text-amber-200">
                  In writing
                </button>
              </div>
            ) : null}
            {state.consent && state.status === "connected" ? (
              <p className="text-xs text-slate-500">
                Consent: {state.consent.method}, {new Date(state.consent.at).toLocaleDateString()}
                {state.consent.source === "case_thread" ? " (on this case)" : ""}
              </p>
            ) : null}
            <AgentStatus stage={state.stage} message={state.stageMessage} speaking={state.speaking} />
            {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
            {loadError || workspaceError ? <p className="text-sm text-red-600">{loadError ?? workspaceError}</p> : null}
            {state.notices.slice(-2).map((n, i) => (
              <p key={i} className="text-xs text-slate-500">
                {n}
              </p>
            ))}
            {state.status === "ended" && state.transcriptId ? (
              <p className="text-xs text-emerald-600">Session saved to the case file.</p>
            ) : null}
            {threadId && threadId !== NEW_THREAD ? (
              <Link
                href={`/studio?generate=legal_notice&thread=${threadId}&jurisdiction=${jurisdiction}`}
                className="self-start text-xs font-medium text-indigo-700 hover:underline dark:text-indigo-300"
              >
                Draft a legal notice from this case →
              </Link>
            ) : null}

            <form onSubmit={submit} className="flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) submit(e);
                }}
                rows={1}
                placeholder={state.status === "connected" ? "Type a message…" : "Start a session to chat"}
                disabled={state.status !== "connected"}
                className="max-h-32 min-h-[44px] flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none focus:border-indigo-500 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
              />
              <button
                type="submit"
                disabled={state.status !== "connected" || !draft.trim()}
                className="h-11 rounded-xl bg-slate-900 px-4 text-sm font-medium text-white disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900"
              >
                Send
              </button>
              <button
                type="button"
                aria-label="Hold to talk"
                aria-pressed={talking}
                title={state.status === "connected" && !state.micAvailable ? "No microphone available" : undefined}
                disabled={state.status !== "connected" || !state.micAvailable}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  pressTalk();
                }}
                onPointerUp={releaseTalk}
                onPointerCancel={releaseTalk}
                onKeyDown={(e) => {
                  if ((e.key === " " || e.key === "Enter") && !e.repeat) {
                    e.preventDefault();
                    pressTalk();
                  }
                }}
                onKeyUp={(e) => {
                  if (e.key === " " || e.key === "Enter") releaseTalk();
                }}
                onContextMenu={(e) => e.preventDefault()}
                className={`h-11 shrink-0 touch-none select-none rounded-xl px-4 text-sm font-medium text-white transition disabled:opacity-40 ${
                  talking ? "scale-105 bg-red-600 shadow-lg shadow-red-600/30" : "bg-indigo-600 hover:bg-indigo-700"
                }`}
              >
                {talking ? "● Listening…" : "Hold to talk"}
              </button>
            </form>
            {state.speaking ? (
              <button onClick={interrupt} className="self-start text-xs text-slate-500 underline">
                Stop speaking
              </button>
            ) : null}
          </div>
        </section>

        {/* Right: the live case file */}
        <aside
          className={`${tab === "case" ? "block" : "hidden"} min-h-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4 lg:block dark:border-slate-800 dark:bg-slate-950`}
        >
          <CaseFile analysis={state.analysis} citations={state.citations} webSources={state.webSources} webQueries={state.webQueries} />
        </aside>
      </main>
    </div>
  );
}
