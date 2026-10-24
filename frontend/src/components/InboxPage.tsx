"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api, ApiError } from "@/lib/api";
import { downloadWithAuth } from "@/lib/download";

type Conversation = {
  id: string;
  wa_id: string;
  client_name: string | null;
  status: "awaiting_consent" | "intake" | "lawyer" | "closed";
  consent_at: string | null;
  transcript_id: string | null;
  last_message_at: string;
  pending_replies?: number;
};
type Message = {
  id: string;
  direction: "in" | "out";
  sender: "client" | "ai" | "lawyer" | "system";
  kind: string;
  body: string;
  created_at: string;
  status?: "sent" | "pending" | "discarded";
  hold_reasons?: string[] | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
};
type Number = { phone_number_id: string; display_number: string; greeting: string | null; enabled: boolean };
type IntakeSetting = { enabled: boolean; changed_by: string | null; changed_at: string | null; pending_request: unknown };

const HOLD_REASONS: Record<string, string> = {
  empty: "is empty",
  too_long: "is longer than an intake question",
  not_a_question: "doesn't ask anything",
  cites_law: "mentions a law, section or case",
  deadline_or_amount: "mentions a deadline or amount",
  directive: "tells the person what to do",
  guarantee: "predicts an outcome",
  legal_conclusion: "states a legal conclusion",
  explains: "explains rather than asks",
  legal_substance: "contains legal information",
};

const STATUS: Record<Conversation["status"], [string, string]> = {
  awaiting_consent: ["Awaiting consent", "bg-slate-100 text-slate-600"],
  intake: ["AI intake", "bg-indigo-100 text-indigo-800"],
  lawyer: ["With lawyer", "bg-emerald-100 text-emerald-800"],
  closed: ["Closed", "bg-slate-100 text-slate-500"],
};
const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

/** WhatsApp intake inbox: chats the AI is handling or handed over, the lawyer's replies, and number setup. */
export function InboxPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const role = workspace.orgs.find((o) => o.id === orgId)?.role;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [numbers, setNumbers] = useState<Number[]>([]);
  const [setup, setSetup] = useState(false);
  const [intake, setIntake] = useState<IntakeSetting | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    api<Conversation[]>("/api/v1/whatsapp/conversations", { token, orgId }).then(setConversations).catch((e: Error) => setError(e.message));
    api<Number[]>("/api/v1/whatsapp/numbers", { token, orgId }).then(setNumbers).catch(() => undefined);
    api<IntakeSetting>("/api/v1/intake", { token, orgId }).then(setIntake).catch(() => undefined);
  }, [token, orgId]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">WhatsApp intake</h1>
        <span className="text-sm text-slate-500">{numbers.map((n) => n.display_number).join(", ") || "No number connected"}</span>
        {role === "owner" || role === "partner" ? (
          <button onClick={() => setSetup((v) => !v)} className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            {setup ? "Close setup" : "Connect a number"}
          </button>
        ) : null}
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>
      {intake && !intake.enabled ? (
        <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">
          Public intake is off: the AI isn&apos;t answering new messages.{" "}
          <Link href="/safety" className="font-medium underline">
            Turn it on in Approvals &amp; Trash
          </Link>
        </p>
      ) : intake ? (
        <p className="border-b border-slate-200 bg-white px-4 py-1.5 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900">
          The AI only sends intake questions on its own. Replies with legal substance wait here for a lawyer&apos;s approval.
        </p>
      ) : null}
      {error ? <p className="m-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
      {setup && orgId ? <NumberSetup token={token} orgId={orgId} onSaved={() => (setSetup(false), load())} /> : null}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="max-h-60 overflow-y-auto border-b border-slate-200 bg-white md:max-h-none md:w-72 md:shrink-0 md:border-b-0 md:border-r dark:border-slate-800 dark:bg-slate-900">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelected(c.id)}
              className={`flex w-full flex-col gap-0.5 border-b border-slate-100 px-3 py-2.5 text-left dark:border-slate-800 ${
                selected === c.id ? "bg-indigo-50 dark:bg-indigo-950/40" : "hover:bg-slate-50 dark:hover:bg-slate-800/50"
              }`}
            >
              <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{c.client_name || `+${c.wa_id}`}</span>
              {c.pending_replies ? (
                <span className="self-start rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                  {c.pending_replies} awaiting approval
                </span>
              ) : null}
              <span className="flex items-center gap-2 text-xs text-slate-500">
                <span className={`rounded-full px-2 py-0.5 ${STATUS[c.status][1]}`}>{STATUS[c.status][0]}</span>
                {new Date(c.last_message_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
              </span>
            </button>
          ))}
          {conversations.length === 0 ? <p className="p-4 text-sm text-slate-500">No chats yet. Clients who message the firm&apos;s WhatsApp number appear here.</p> : null}
        </aside>
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {selected && orgId ? (
            <Chat key={selected} token={token} orgId={orgId} id={selected} intakeOn={intake?.enabled ?? true} onChanged={load} />
          ) : (
            <p className="m-auto p-6 text-sm text-slate-500">Choose a chat.</p>
          )}
        </main>
      </div>
    </div>
  );
}

type Decision = { message: Message; send: boolean; text?: string };

function Chat({ token, orgId, id, intakeOn, onChanged }: { token: string; orgId: string; id: string; intakeOn: boolean; onChanged: () => void }) {
  const [conversation, setConversation] = useState<(Conversation & { messages: Message[] }) | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [intakeBlocked, setIntakeBlocked] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [busy, setBusy] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Conversation & { messages: Message[] }>(`/api/v1/whatsapp/conversations/${id}`, { token, orgId })
      .then(setConversation)
      .catch((e: Error) => setError(e.message));
  }, [token, orgId, id]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setError(null);
    try {
      await api(`/api/v1/whatsapp/conversations/${id}/reply`, { token, orgId, method: "POST", body: { text } });
      setText("");
      load();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function setStatus(status: string) {
    setError(null);
    setIntakeBlocked(false);
    try {
      await api(`/api/v1/whatsapp/conversations/${id}/status`, { token, orgId, method: "POST", body: { status } });
    } catch (err) {
      setError((err as Error).message);
      setIntakeBlocked(status === "intake" && err instanceof ApiError && err.status === 409 && /intake/i.test(err.message));
    }
    load();
    onChanged();
  }

  async function settle() {
    if (!decision) return;
    setBusy(true);
    setDecisionError(null);
    try {
      await api(`/api/v1/whatsapp/conversations/${id}/held/${decision.message.id}`, {
        token,
        orgId,
        method: "POST",
        body: decision.send ? { send: true, ...(decision.text !== undefined ? { text: decision.text } : {}) } : { send: false },
      });
      setDecision(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDecision(null);
        setError(`${err.message} The chat has been reloaded.`);
      } else if (err instanceof ApiError && err.status === 502) {
        setDecisionError(`WhatsApp didn't accept the message: ${err.message} (Replies can only be sent within 24 hours of the client's last message.)`);
      } else {
        setDecisionError((err as Error).message);
      }
    } finally {
      setBusy(false);
      load();
      onChanged();
    }
  }

  if (!conversation) return <p className="p-4 text-sm text-slate-500">{error ?? "Loading…"}</p>;
  const who = { client: "Client", ai: "AI assistant", lawyer: "Lawyer", system: "Automatic" } as const;

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-2 text-sm dark:border-slate-800 dark:bg-slate-900">
        <span className="font-medium text-slate-900 dark:text-slate-100">{conversation.client_name || `+${conversation.wa_id}`}</span>
        <span className="text-xs text-slate-500">+{conversation.wa_id}</span>
        <div className="ml-auto flex gap-3 text-xs">
          {conversation.status === "intake" ? (
            <button onClick={() => setStatus("lawyer")} className="text-indigo-700 hover:underline dark:text-indigo-300">Take over</button>
          ) : conversation.status === "lawyer" && conversation.consent_at ? (
            <button
              onClick={() => setStatus("intake")}
              title={intakeOn ? undefined : "Public intake is turned off for the firm"}
              className="text-indigo-700 hover:underline dark:text-indigo-300"
            >
              Hand back to AI
            </button>
          ) : null}
          {conversation.status !== "closed" ? (
            <button onClick={() => setStatus("closed")} className="text-slate-500 hover:underline">Close</button>
          ) : null}
          {conversation.transcript_id ? (
            <button
              onClick={() =>
                downloadWithAuth(`/api/v1/transcripts/${conversation.transcript_id}/pdf`, token, orgId, "intake.pdf").catch((e: Error) => setError(e.message))
              }
              className="text-indigo-700 hover:underline dark:text-indigo-300"
            >
              Intake report (PDF)
            </button>
          ) : null}
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-4">
        {conversation.messages.map((m) => {
          const time = new Date(m.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
          if (m.status === "pending") {
            return (
              <HeldReply
                key={m.id}
                message={m}
                time={time}
                onSend={(edited) => {
                  setDecisionError(null);
                  setDecision({ message: m, send: true, text: edited });
                }}
                onDiscard={() => {
                  setDecisionError(null);
                  setDecision({ message: m, send: false });
                }}
              />
            );
          }
          if (m.status === "discarded") {
            return (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md border border-dashed border-slate-300 bg-slate-100 px-3.5 py-2 text-sm text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-500">
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide">AI draft · {time} · Discarded</div>
                  <span className="line-through">{m.body}</span>
                </div>
              </div>
            );
          }
          return (
            <div key={m.id} className={`flex ${m.direction === "in" ? "justify-start" : "justify-end"}`}>
              <div
                className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${
                  m.direction === "in"
                    ? "rounded-bl-md border border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    : m.sender === "lawyer"
                      ? "rounded-br-md bg-emerald-600 text-white"
                      : "rounded-br-md bg-indigo-600 text-white"
                }`}
              >
                <div className="mb-0.5 text-[10px] uppercase tracking-wide opacity-70">
                  {who[m.sender]} · {time}
                  {m.reviewed_at ? " · Reviewed" : ""}
                </div>
                {m.body}
              </div>
            </div>
          );
        })}
      </div>
      {error ? (
        <p className="px-4 text-sm text-red-600">
          {error}
          {intakeBlocked ? (
            <>
              {" "}
              <Link href="/safety" className="underline">
                Approvals &amp; Trash
              </Link>
            </>
          ) : null}
        </p>
      ) : null}
      {decision?.send ? (
        <ConfirmDialog
          title={decision.text !== undefined ? "Send your edited reply?" : "Send the AI draft?"}
          facts={[
            { label: "What happens", value: "This text is sent to the client on WhatsApp under the firm's name." },
            { label: "Who sees it", value: "The client." },
          ]}
          confirmLabel="Send to client"
          busy={busy}
          error={decisionError}
          onConfirm={settle}
          onCancel={() => setDecision(null)}
        >
          <p className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-200 p-2 dark:border-slate-700">
            {decision.text ?? decision.message.body}
          </p>
        </ConfirmDialog>
      ) : decision ? (
        <ConfirmDialog
          title="Discard the AI draft?"
          facts={[
            { label: "What happens", value: "The draft is never sent. It stays in this chat, marked Discarded." },
            { label: "Who sees it", value: "Only the firm's lawyers, in this inbox." },
          ]}
          confirmLabel="Discard"
          danger
          busy={busy}
          error={decisionError}
          onConfirm={settle}
          onCancel={() => setDecision(null)}
        />
      ) : null}
      <form onSubmit={send} className="flex gap-2 border-t border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <input className={`${field} flex-1`} placeholder="Reply as the lawyer (the AI then stops replying in this chat)" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">Send</button>
      </form>
    </>
  );
}

function HeldReply({ message, time, onSend, onDiscard }: { message: Message; time: string; onSend: (text?: string) => void; onDiscard: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.body);
  const reasons = (message.hold_reasons ?? []).map((r) => HOLD_REASONS[r] ?? r.replace(/_/g, " "));
  const button = "rounded-lg px-2.5 py-1 text-xs font-medium";

  return (
    <div className="flex justify-end">
      <div className="w-full max-w-[80%] rounded-2xl rounded-br-md border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-sm text-slate-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-slate-100">
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-300">
          AI draft — not sent to the client · {time}
        </div>
        {editing ? (
          <textarea className={`${field} w-full`} rows={Math.min(12, draft.split("\n").length + 2)} value={draft} onChange={(e) => setDraft(e.target.value)} />
        ) : (
          <p className="whitespace-pre-wrap">{message.body}</p>
        )}
        {reasons.length ? <p className="mt-1.5 text-xs text-amber-900 dark:text-amber-200">Held because it {reasons.join("; ")}.</p> : null}
        <div className="mt-2 flex flex-wrap gap-2">
          {editing ? (
            <>
              <button onClick={() => onSend(draft.trim())} disabled={!draft.trim()} className={`${button} bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50`}>
                Send edited
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setDraft(message.body);
                }}
                className={`${button} text-slate-600 hover:bg-amber-100 dark:text-slate-300 dark:hover:bg-amber-900/40`}
              >
                Cancel edit
              </button>
            </>
          ) : (
            <>
              <button onClick={() => onSend()} className={`${button} bg-emerald-600 text-white hover:bg-emerald-700`}>
                Send as is
              </button>
              <button
                onClick={() => setEditing(true)}
                className={`${button} border border-amber-300 text-amber-900 hover:bg-amber-100 dark:border-amber-800 dark:text-amber-200 dark:hover:bg-amber-900/40`}
              >
                Edit &amp; send
              </button>
            </>
          )}
          <button onClick={onDiscard} className={`${button} ml-auto text-red-700 hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950/40`}>
            Discard
          </button>
        </div>
      </div>
    </div>
  );
}

function NumberSetup({ token, orgId, onSaved }: { token: string; orgId: string; onSaved: () => void }) {
  const [form, setForm] = useState({ phone_number_id: "", display_number: "", greeting: "" });
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/api/v1/whatsapp/numbers", { token, orgId, method: "POST", body: { ...form, greeting: form.greeting || null, jurisdiction: "IN" } });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form onSubmit={save} className="m-3 grid gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-3 dark:border-slate-800 dark:bg-slate-900">
      <input className={field} required placeholder="Phone number ID (from Meta)" value={form.phone_number_id} onChange={(e) => setForm({ ...form, phone_number_id: e.target.value })} />
      <input className={field} required placeholder="Number, e.g. +919876543210" value={form.display_number} onChange={(e) => setForm({ ...form, display_number: e.target.value })} />
      <input className={field} placeholder="Greeting (optional)" value={form.greeting} onChange={(e) => setForm({ ...form, greeting: e.target.value })} />
      <button className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 sm:col-span-3 sm:justify-self-start">Save</button>
      <p className="text-xs text-slate-500 sm:col-span-3">
        In Meta&apos;s WhatsApp dashboard, set the webhook to <code>/api/v1/whatsapp/webhook</code> on this API&apos;s public address and subscribe to
        messages. Incoming chats go to you.
      </p>
      {error ? <p className="text-sm text-red-600 sm:col-span-3">{error}</p> : null}
    </form>
  );
}
