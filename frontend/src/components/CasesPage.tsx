"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog, deleteFacts } from "@/components/ConfirmDialog";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api, ApiError, type DeleteOutcome } from "@/lib/api";

type CourtCase = {
  id: string;
  cnr: string | null;
  title: string;
  court_name: string | null;
  case_number: string | null;
  case_status: string | null;
  next_hearing_date: string | null;
  last_hearing_date: string | null;
  client_name: string | null;
  client_phone: string | null;
  last_synced_at: string | null;
  sync_error: string | null;
  reminded_for_date: string | null;
  legal_hold: boolean;
  legal_hold_reason: string | null;
  thread_id: string | null;
};

type Dialog = { kind: "delete" | "hold" | "lift" | "sync"; c: CourtCase };

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const SKIP_SYNC_CONFIRM = "dl.cases.skipSyncConfirm";
const EMPTY = { cnr: "", title: "", court_name: "", case_number: "", next_hearing_date: "", client_name: "", client_phone: "" };

function readSkipSync() {
  try {
    return sessionStorage.getItem(SKIP_SYNC_CONFIRM) === "1";
  } catch {
    return false;
  }
}

function daysUntil(day: string) {
  const start = new Date(new Date().toDateString()).getTime();
  return Math.round((new Date(day).getTime() - start) / 86_400_000);
}

function HearingBadge({ day }: { day: string | null }) {
  if (!day) return <span className="text-xs text-slate-400">No date</span>;
  const n = daysUntil(day);
  const label = n < 0 ? `${-n}d ago` : n === 0 ? "Today" : n === 1 ? "Tomorrow" : `in ${n} days`;
  const tone = n < 0 ? "bg-slate-100 text-slate-500" : n <= 1 ? "bg-red-100 text-red-800" : n <= 7 ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800";
  return (
    <span className="whitespace-nowrap text-sm">
      {new Date(day).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}{" "}
      <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>{label}</span>
    </span>
  );
}

/** The firm's cases in court: hearing diary, eCourts sync, and WhatsApp reminders to clients. */
export function CasesPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const role = workspace.orgs.find((o) => o.id === orgId)?.role;
  const senior = role === "owner" || role === "partner";
  const seniorNeeded = role === "associate" || role === "paralegal";
  const [cases, setCases] = useState<CourtCase[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [holdReason, setHoldReason] = useState("");
  const [skipSync, setSkipSync] = useState(false);

  const load = useCallback(() => {
    if (!orgId) return;
    api<CourtCase[]>("/api/v1/cases", { token, orgId }).then(setCases).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  useEffect(load, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy("add");
    setError(null);
    const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim() !== ""));
    try {
      await api("/api/v1/cases", { token, orgId, method: "POST", body });
      setForm(EMPTY);
      setAdding(false);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function act(id: string, run: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    setNotice(null);
    try {
      await run();
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function sync(c: CourtCase) {
    return act(c.id, () => api(`/api/v1/cases/${c.id}/sync`, { token, orgId, method: "POST" }));
  }

  function open(next: Dialog) {
    if (next.kind === "sync" && readSkipSync()) {
      sync(next.c);
      return;
    }
    setDialog(next);
    setDialogError(null);
    setHoldReason("");
    setSkipSync(false);
  }

  const close = useCallback(() => setDialog(null), []);

  async function confirm() {
    if (!dialog) return;
    const { kind, c } = dialog;
    if (kind === "sync") {
      if (skipSync) {
        try {
          sessionStorage.setItem(SKIP_SYNC_CONFIRM, "1");
        } catch {
          // Storage unavailable: ask again next time.
        }
      }
      setDialog(null);
      sync(c);
      return;
    }
    setDialogBusy(true);
    setDialogError(null);
    setNotice(null);
    try {
      if (kind === "delete") {
        const outcome = await api<DeleteOutcome>(`/api/v1/cases/${c.id}`, { token, orgId, method: "DELETE" });
        setNotice(outcome.message);
      } else {
        const hold = kind === "hold";
        const reason = holdReason.trim();
        await api("/api/v1/legal-hold", {
          token,
          orgId,
          method: "PUT",
          body: { kind: "court_case", id: c.id, hold, ...(hold && reason ? { reason } : {}) },
        });
        setNotice(hold ? `Legal hold placed on ${c.title}.` : `Legal hold lifted from ${c.title}.`);
      }
      setDialog(null);
      load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "legal_hold") {
        setDialog(null);
        setError(err.message);
        load();
      } else {
        setDialogError((err as Error).message);
      }
    } finally {
      setDialogBusy(false);
    }
  }

  const upcoming = cases.filter((c) => c.next_hearing_date && daysUntil(c.next_hearing_date) >= 0 && daysUntil(c.next_hearing_date) <= 7);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Cases &amp; hearings</h1>
        <button onClick={() => setAdding((v) => !v)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
          + Add case
        </button>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 overflow-y-auto p-4">
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
            {notice}{" "}
            <Link href="/safety" className="underline">
              Approvals &amp; Trash
            </Link>
          </p>
        ) : null}

        {adding ? (
          <form onSubmit={add} className="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 dark:border-slate-800 dark:bg-slate-900">
            <input className={field} placeholder="CNR (16 characters, optional)" value={form.cnr} onChange={(e) => setForm({ ...form, cnr: e.target.value })} />
            <input className={field} placeholder="Title, e.g. Sharma v. Joshi (s. 138)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <input className={field} placeholder="Court" value={form.court_name} onChange={(e) => setForm({ ...form, court_name: e.target.value })} />
            <input className={field} placeholder="Case number" value={form.case_number} onChange={(e) => setForm({ ...form, case_number: e.target.value })} />
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              Next hearing
              <input type="date" className={field} value={form.next_hearing_date} onChange={(e) => setForm({ ...form, next_hearing_date: e.target.value })} />
            </label>
            <input className={field} placeholder="Client name" value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
            <input
              className={field}
              placeholder="Client WhatsApp (for reminders), e.g. 98123 45678"
              value={form.client_phone}
              onChange={(e) => setForm({ ...form, client_phone: e.target.value })}
            />
            <button disabled={busy === "add"} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {busy === "add" ? "Adding…" : "Add case"}
            </button>
            <p className="text-xs text-slate-500 sm:col-span-2">
              With a CNR and eCourts data configured, the court, parties and hearing dates are filled in and kept in sync. Clients with a WhatsApp
              number get a reminder before each hearing.
            </p>
          </form>
        ) : null}

        <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">This week ({upcoming.length})</h2>
          {upcoming.length ? (
            <ul className="mt-2 flex flex-col gap-1.5">
              {upcoming.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <HearingBadge day={c.next_hearing_date} />
                  <span className="font-medium text-slate-900 dark:text-slate-100">{c.title}</span>
                  <span className="text-slate-500">{c.court_name}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No hearings in the next 7 days.</p>
          )}
        </section>

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
              <tr>
                <th className="px-3 py-2">Case</th>
                <th className="px-3 py-2">Court</th>
                <th className="px-3 py-2">Next hearing</th>
                <th className="px-3 py-2">Client</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {cases.map((c) => (
                <tr key={c.id} className="align-top">
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-900 dark:text-slate-100">
                      {c.title}
                      {c.legal_hold ? (
                        <span
                          title={c.legal_hold_reason ? `Legal hold: ${c.legal_hold_reason}` : "Legal hold"}
                          className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                        >
                          Legal hold
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs text-slate-500">
                      {[c.case_number, c.cnr, c.case_status].filter(Boolean).join(" · ")}
                    </div>
                    {c.sync_error ? <div className="text-xs text-amber-700">Sync: {c.sync_error}</div> : null}
                  </td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{c.court_name}</td>
                  <td className="px-3 py-2">
                    <HearingBadge day={c.next_hearing_date} />
                    <input
                      type="date"
                      aria-label="Change next hearing"
                      defaultValue={c.next_hearing_date ?? ""}
                      onBlur={(e) =>
                        e.target.value !== (c.next_hearing_date ?? "") &&
                        act(c.id, () => api(`/api/v1/cases/${c.id}`, { token, orgId, method: "PATCH", body: { next_hearing_date: e.target.value || null } }))
                      }
                      className="mt-1 block rounded border border-slate-200 bg-transparent px-1 text-xs dark:border-slate-700"
                    />
                  </td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                    {c.client_name}
                    {c.client_phone ? <div className="text-xs text-slate-500">{c.client_phone}</div> : null}
                    {c.reminded_for_date && c.reminded_for_date === c.next_hearing_date ? (
                      <div className="text-xs text-emerald-600">Reminder sent</div>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {c.cnr ? (
                      <button
                        disabled={busy === c.id}
                        onClick={() => open({ kind: "sync", c })}
                        className="mr-3 text-xs text-indigo-700 hover:underline disabled:opacity-50 dark:text-indigo-300"
                      >
                        {busy === c.id ? "Syncing…" : "Sync"}
                      </button>
                    ) : null}
                    {senior ? (
                      <button
                        onClick={() => open({ kind: c.legal_hold ? "lift" : "hold", c })}
                        className="mr-3 text-xs text-slate-600 hover:underline dark:text-slate-300"
                      >
                        {c.legal_hold ? "Lift hold" : "Place hold…"}
                      </button>
                    ) : null}
                    <button
                      disabled={c.legal_hold}
                      title={c.legal_hold ? "Under legal hold: a partner or owner must lift the hold before this case can be removed" : undefined}
                      onClick={() => open({ kind: "delete", c })}
                      className="text-xs text-red-600 hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {cases.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-500">
                    No cases yet. Add one with its CNR or next hearing date.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </main>

      {dialog?.kind === "delete" ? (
        <ConfirmDialog
          title={`Stop tracking ${dialog.c.title}?`}
          facts={deleteFacts("case", seniorNeeded)}
          confirmLabel={seniorNeeded ? "Request deletion" : "Move to Trash"}
          danger
          busy={dialogBusy}
          error={dialogError}
          onConfirm={confirm}
          onCancel={close}
        />
      ) : null}

      {dialog?.kind === "hold" ? (
        <ConfirmDialog
          title={`Place ${dialog.c.title} under legal hold?`}
          facts={[
            { label: "What happens", value: "The case and the records linked to its case thread can't be deleted while the hold is on." },
            { label: "Who can lift it", value: "Owners and partners." },
          ]}
          confirmLabel="Place hold"
          busy={dialogBusy}
          error={dialogError}
          onConfirm={confirm}
          onCancel={close}
        >
          <label className="block">
            Reason (recorded with the hold)
            <input
              autoFocus
              value={holdReason}
              onChange={(e) => setHoldReason(e.target.value)}
              placeholder="e.g. Litigation pending, preservation notice received"
              className={`mt-1 w-full ${field}`}
            />
          </label>
        </ConfirmDialog>
      ) : null}

      {dialog?.kind === "lift" ? (
        <ConfirmDialog
          title={`Lift the legal hold on ${dialog.c.title}?`}
          facts={[
            { label: "What happens", value: "The case and the records linked to its case thread can be deleted again." },
            ...(dialog.c.legal_hold_reason ? [{ label: "Hold reason", value: dialog.c.legal_hold_reason }] : []),
          ]}
          confirmLabel="Lift hold"
          busy={dialogBusy}
          error={dialogError}
          onConfirm={confirm}
          onCancel={close}
        />
      ) : null}

      {dialog?.kind === "sync" ? (
        <ConfirmDialog
          title={`Sync ${dialog.c.title} with eCourts?`}
          facts={[
            { label: "What happens", value: "Fetches the latest status and hearing dates from eCourtsIndia." },
            { label: "Cost", value: "Uses one eCourtsIndia API credit." },
            { label: "Who sees it", value: "The case's details are sent to eCourtsIndia only as the CNR." },
          ]}
          confirmLabel="Sync"
          onConfirm={confirm}
          onCancel={close}
        >
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={skipSync} onChange={(e) => setSkipSync(e.target.checked)} />
            Don&apos;t ask again this session
          </label>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
