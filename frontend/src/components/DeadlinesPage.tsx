"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

type Person = { id: string; name: string } | null;

type Reminder = {
  id: string;
  rung: string;
  level: number;
  target: Person;
  channel: string;
  issued_at: string;
  delivered_at: string | null;
  acknowledged_at: string | null;
};

type Deadline = {
  id: string;
  kind: string;
  title: string | null;
  matter: { court_case_id: string | null; thread_id: string | null; label: string | null };
  effective_due_date: string | null;
  candidates: string[] | null;
  candidate_count: number | null;
  inputs: Record<string, string> | null;
  input_fields: string[];
  basis: string | null;
  rule_id: string | null;
  hard: boolean;
  source: string;
  owner: Person;
  backup: Person;
  checker: Person;
  check_mode: "second" | "self";
  check_state: "none" | "pending" | "submitted" | "cancelled";
  check_opens_at: string | null;
  check_note: string | null;
  check_cancel_reason: string | null;
  verification: string;
  status: "open" | "done";
  display_status: string;
  covered_by: Person;
  safety_lead_days: number;
  latest_reminder: Omit<Reminder, "target"> & { target: Person } | null;
  masked: boolean;
  is_checker: boolean;
  can_check: boolean;
  done_at: string | null;
  done_evidence: string | null;
};

type MyReminder = { id: string; rung: string; level: number; issued_at: string; for_date: string | null; deadline: Deadline };
type Member = { user_id: string; role: string; email: string | null; full_name: string | null };
type CourtCase = { id: string; title: string };
type Absence = { id: string; user_id: string; starts_on: string; ends_on: string; note: string | null };
type InputRow = { name: string; value: string };

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const button = "rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50";
const linkButton = "text-xs text-indigo-700 hover:underline disabled:opacity-50 dark:text-indigo-300";

const STATUS: Record<string, { label: string; tone: string }> = {
  verified: { label: "Verified", tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" },
  self_verified: { label: "Self-verified", tone: "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300" },
  awaiting_check: { label: "Awaiting check", tone: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300" },
  awaiting_your_check: { label: "Awaiting your check", tone: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300" },
  ai_proposed: { label: "AI-proposed", tone: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300" },
  disputed: { label: "Disputed", tone: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" },
  overdue: { label: "Overdue", tone: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" },
  unverified: { label: "Unverified", tone: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300" },
  done: { label: "Done", tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
};

const ROW_TONE: Record<string, string> = {
  overdue: "border-l-4 border-l-red-500",
  disputed: "border-l-4 border-l-amber-500",
  unverified: "border-l-4 border-l-orange-400",
  ai_proposed: "border-l-4 border-l-violet-500",
  awaiting_check: "border-l-4 border-l-sky-400",
  awaiting_your_check: "border-l-4 border-l-indigo-500",
  verified: "border-l-4 border-l-emerald-500",
  self_verified: "border-l-4 border-l-teal-500",
  done: "border-l-4 border-l-slate-300 opacity-70",
};

const EMPTY_FORM = { title: "", kind: "", due_date: "", owner_id: "", backup_id: "", court_case_id: "", basis: "", hard: false, safety_lead_days: "3" };

function today() {
  return new Date(new Date().toDateString()).getTime();
}

function daysUntil(day: string) {
  return Math.round((new Date(`${day}T00:00:00`).getTime() - today()) / 86_400_000);
}

function fmtDay(day: string) {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function fmtTime(at: string) {
  return new Date(at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function label(kind: string) {
  return kind.replaceAll("_", " ");
}

/** The signed-in user's id: the `sub` claim of the Supabase access token (only used to show buttons; the API decides). */
function tokenSubject(token: string): string | null {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return (JSON.parse(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), "="))) as { sub?: string }).sub ?? null;
  } catch {
    return null;
  }
}

function isDateField(name: string) {
  return /date|_on$|_at$|day/i.test(name);
}

function DueBadge({ day }: { day: string }) {
  const n = daysUntil(day);
  const text = n < 0 ? `${-n}d overdue` : n === 0 ? "Today" : n === 1 ? "Tomorrow" : `${n} days left`;
  const tone = n < 0 ? "bg-red-100 text-red-800" : n <= 3 ? "bg-red-100 text-red-800" : n <= 7 ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800";
  return (
    <span className="whitespace-nowrap text-sm font-medium text-slate-900 dark:text-slate-100">
      {fmtDay(day)} <span className={`rounded-full px-2 py-0.5 text-xs font-normal ${tone}`}>{text}</span>
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "bg-slate-100 text-slate-700" };
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${s.tone}`}>{s.label}</span>;
}

/** Why a check isn't (or is no longer) a second person's blind re-entry. */
function checkExplanation(d: Deadline): string | null {
  if (d.check_state === "cancelled") {
    if (d.check_cancel_reason === "reminder_to_checker") return "Check cancelled: a reminder had to reach the checker, so they now see the date.";
    if (d.check_cancel_reason === "due_within_lead") return `Check cancelled: due within ${d.safety_lead_days} days, so everyone is reminded with the date.`;
    if (d.check_cancel_reason === "completed") return null;
  }
  if (d.check_note === "all_eligible_viewed") return "Re-check impossible: every eligible member has already seen the values.";
  if (d.check_note === "no_eligible_checker") return "Nobody else can check it (associate or above, with access to the matter, not on leave).";
  return null;
}

/** The firm docket: every open deadline with its rule, inputs, owner, backup, reminders and blind second check. */
export function DeadlinesPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const role = workspace.orgs.find((o) => o.id === orgId)?.role;
  const senior = role === "owner" || role === "partner";
  const [deadlines, setDeadlines] = useState<Deadline[]>([]);
  const [reminders, setReminders] = useState<MyReminder[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [cases, setCases] = useState<CourtCase[]>([]);
  const [absences, setAbsences] = useState<Absence[]>([]);
  const me = useMemo(() => tokenSubject(token), [token]);
  const [includeDone, setIncludeDone] = useState(false);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [inputs, setInputs] = useState<InputRow[]>([{ name: "order_date", value: "" }]);
  const [checking, setChecking] = useState<Deadline | null>(null);
  const [checkInputs, setCheckInputs] = useState<Record<string, string>>({});
  const [checkDate, setCheckDate] = useState("");
  const [completing, setCompleting] = useState<Deadline | null>(null);
  const [evidence, setEvidence] = useState("");
  const [leave, setLeave] = useState({ starts_on: "", ends_on: "", note: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    const fail = (e: Error) => setError(e.message);
    api<Deadline[]>(`/api/v1/deadlines${includeDone ? "?include_done=true" : ""}`, { token, orgId }).then(setDeadlines).catch(fail);
    api<MyReminder[]>("/api/v1/deadlines/reminders", { token, orgId }).then(setReminders).catch(fail);
    api<Absence[]>("/api/v1/deadlines/absences", { token, orgId }).then(setAbsences).catch(fail);
  }, [token, orgId, includeDone]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!orgId) return;
    api<Member[]>(`/api/v1/organizations/${orgId}/members`, { token, orgId }).then(setMembers).catch(() => setMembers([]));
    api<CourtCase[]>("/api/v1/cases", { token, orgId }).then(setCases).catch(() => setCases([]));
  }, [token, orgId]);

  const name = (id: string) => {
    const m = members.find((x) => x.user_id === id);
    return m?.full_name || m?.email || "A colleague";
  };

  async function act(key: string, run: () => Promise<unknown>, message?: string) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await run();
      if (message) setNotice(message);
      load();
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      title: form.title.trim(),
      kind: form.kind.trim() || "deadline",
      due_date: form.due_date,
      basis: form.basis.trim(),
      hard: form.hard,
      safety_lead_days: Number(form.safety_lead_days) || 0,
      inputs: Object.fromEntries(inputs.filter((r) => r.name.trim() && r.value.trim()).map((r) => [r.name.trim(), r.value.trim()])),
      ...(form.owner_id ? { owner_id: form.owner_id } : {}),
      ...(form.backup_id ? { backup_id: form.backup_id } : {}),
      ...(form.court_case_id ? { court_case_id: form.court_case_id } : {}),
    };
    const ok = await act("add", () => api("/api/v1/deadlines", { token, orgId, method: "POST", body }), "Deadline added. A colleague has been asked to re-enter its inputs blind.");
    if (ok) {
      setForm(EMPTY_FORM);
      setInputs([{ name: "order_date", value: "" }]);
      setAdding(false);
    }
  }

  function startCheck(d: Deadline) {
    setChecking(d);
    setCheckInputs(Object.fromEntries(d.input_fields.map((f) => [f, ""])));
    setCheckDate("");
    setDialogError(null);
  }

  async function submitCheck(e: React.FormEvent) {
    e.preventDefault();
    if (!checking) return;
    setBusy("check");
    setDialogError(null);
    try {
      const after = await api<Deadline>(`/api/v1/deadlines/${checking.id}/check`, {
        token,
        orgId,
        method: "POST",
        body: { inputs: Object.fromEntries(Object.entries(checkInputs).filter(([, v]) => v.trim())), ...(checkDate ? { due_date: checkDate } : {}) },
      });
      setChecking(null);
      setNotice(
        after.verification === "disputed"
          ? "Your entry differs from the first one. The deadline is disputed and the earlier date governs; both of you are flagged."
          : after.verification === "self_verified"
            ? "Your re-entry matches. The deadline is self-verified."
            : "Your entry matches. The deadline is verified.",
      );
      load();
    } catch (err) {
      setDialogError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function complete() {
    if (!completing) return;
    setBusy("complete");
    setDialogError(null);
    try {
      await api(`/api/v1/deadlines/${completing.id}/complete`, { token, orgId, method: "POST", body: { evidence: evidence.trim() } });
      setCompleting(null);
      setNotice("Marked done.");
      load();
    } catch (err) {
      setDialogError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function addLeave(e: React.FormEvent) {
    e.preventDefault();
    const body = { starts_on: leave.starts_on, ends_on: leave.ends_on || leave.starts_on, ...(leave.note.trim() ? { note: leave.note.trim() } : {}) };
    if (await act("leave", () => api("/api/v1/deadlines/absences", { token, orgId, method: "POST", body }), "Leave recorded. Your reminders go to your backups meanwhile.")) {
      setLeave({ starts_on: "", ends_on: "", note: "" });
    }
  }

  const awaiting = deadlines.filter((d) => d.masked);
  const docket = deadlines.filter((d) => !d.masked);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Deadlines</h1>
        <button onClick={() => setAdding((v) => !v)} className={button}>
          + Add deadline
        </button>
        <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={includeDone} onChange={(e) => setIncludeDone(e.target.checked)} />
          Show done
        </label>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 overflow-y-auto p-4">
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p> : null}

        {adding ? (
          <form onSubmit={add} className="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 dark:border-slate-800 dark:bg-slate-900">
            <input required className={field} placeholder="Title, e.g. First appeal against decree" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <input className={field} placeholder="Kind, e.g. appeal, written statement" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} />
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              Due date
              <input required type="date" className={field} value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
            </label>
            <select className={field} value={form.court_case_id} onChange={(e) => setForm({ ...form, court_case_id: e.target.value })}>
              <option value="">No court case</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <select className={field} value={form.owner_id} onChange={(e) => setForm({ ...form, owner_id: e.target.value })}>
              <option value="">Owner: me</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  Owner: {m.full_name || m.email} ({m.role})
                </option>
              ))}
            </select>
            <select className={field} value={form.backup_id} onChange={(e) => setForm({ ...form, backup_id: e.target.value })}>
              <option value="">Backup: choose for me</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  Backup: {m.full_name || m.email} ({m.role})
                </option>
              ))}
            </select>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Inputs the date rests on</span>
              {inputs.map((row, i) => (
                <div key={i} className="flex flex-wrap gap-2">
                  <input
                    className={field}
                    placeholder="e.g. order_date"
                    value={row.name}
                    onChange={(e) => setInputs(inputs.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))}
                  />
                  <input
                    type={isDateField(row.name) ? "date" : "text"}
                    className={field}
                    value={row.value}
                    onChange={(e) => setInputs(inputs.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))}
                  />
                  <button type="button" className={linkButton} onClick={() => setInputs(inputs.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </div>
              ))}
              <button type="button" className={`${linkButton} self-start`} onClick={() => setInputs([...inputs, { name: "", value: "" }])}>
                + Add input
              </button>
            </div>
            <textarea
              className={`${field} sm:col-span-2`}
              rows={2}
              placeholder="Basis, e.g. 90 days from the decree (Art. 116 Limitation Act), copy period excluded"
              value={form.basis}
              onChange={(e) => setForm({ ...form, basis: e.target.value })}
            />
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <input type="checkbox" checked={form.hard} onChange={(e) => setForm({ ...form, hard: e.target.checked })} />
              Hard deadline (no condonation): remind daily from 5 days before
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              Stop the blind check
              <input
                type="number"
                min={0}
                max={60}
                className={`${field} w-20`}
                value={form.safety_lead_days}
                onChange={(e) => setForm({ ...form, safety_lead_days: e.target.value })}
              />
              days before it is due
            </label>
            <button disabled={busy === "add"} className={button}>
              {busy === "add" ? "Adding…" : "Add deadline"}
            </button>
            <p className="text-xs text-slate-500 sm:col-span-2">
              Another member re-enters these inputs without seeing yours. If you disagree, both dates are kept and reminders run to the earlier one.
            </p>
          </form>
        ) : null}

        {reminders.length ? (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/60 dark:bg-amber-950/30">
            <h2 className="text-xs font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">Your reminders ({reminders.length})</h2>
            <ul className="mt-2 flex flex-col gap-1.5">
              {reminders.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm text-slate-800 dark:text-slate-200">
                  <span className="rounded bg-white px-1.5 py-0.5 font-mono text-xs dark:bg-slate-900">{r.rung}</span>
                  {r.level ? <span className="text-xs text-red-700 dark:text-red-300">escalated to you</span> : null}
                  <span className="font-medium">{r.deadline.title ?? label(r.deadline.kind)}</span>
                  {r.deadline.matter.label ? <span className="text-slate-500">{r.deadline.matter.label}</span> : null}
                  {r.for_date ? <DueBadge day={r.for_date} /> : null}
                  <button
                    disabled={busy === r.id}
                    onClick={() => act(r.id, () => api(`/api/v1/deadlines/reminders/${r.id}/acknowledge`, { token, orgId, method: "POST" }), "Acknowledged.")}
                    className="ml-auto rounded-lg border border-amber-300 bg-white px-2 py-0.5 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-800 dark:bg-slate-900 dark:text-amber-200"
                  >
                    Acknowledge
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {awaiting.length ? (
          <section className="rounded-xl border border-indigo-200 bg-white p-4 dark:border-indigo-900/60 dark:bg-slate-900">
            <h2 className="text-xs font-bold uppercase tracking-wide text-indigo-700 dark:text-indigo-300">Awaiting your check ({awaiting.length})</h2>
            <p className="mt-1 text-xs text-slate-500">
              Re-enter the inputs from the source documents (the order, the copy application). You can&apos;t see the first entry until you submit.
            </p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {awaiting.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-slate-900 dark:text-slate-100">
                    Awaiting your check: <span className="font-medium">{d.matter.label ?? "No matter linked"}</span> – {label(d.kind)}
                  </span>
                  {d.matter.court_case_id ? (
                    <Link href="/cases" className="text-xs text-slate-500 hover:underline">
                      Open case
                    </Link>
                  ) : null}
                  <button onClick={() => startCheck(d)} className={`ml-auto ${button} py-1 text-xs`}>
                    Start check
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="flex flex-wrap gap-1.5 text-xs">
          {["overdue", "disputed", "unverified", "ai_proposed", "awaiting_check", "self_verified", "verified"].map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
              <tr>
                <th className="px-3 py-2">Due</th>
                <th className="px-3 py-2">Deadline</th>
                <th className="px-3 py-2">Rule &amp; inputs</th>
                <th className="px-3 py-2">People</th>
                <th className="px-3 py-2">Check &amp; reminders</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {docket.map((d) => {
                const why = checkExplanation(d);
                const r = d.latest_reminder;
                const selfPending = d.check_mode === "self" && d.check_state === "pending" && d.is_checker;
                const canManage = senior || d.owner?.id === me || d.backup?.id === me;
                return (
                  <tr key={d.id} id={d.id} className={`align-top ${ROW_TONE[d.display_status] ?? ""}`}>
                    <td className="px-3 py-2">
                      {d.effective_due_date ? <DueBadge day={d.effective_due_date} /> : null}
                      {(d.candidate_count ?? 0) > 1 ? (
                        <div className="mt-1 text-xs font-bold text-amber-800 dark:text-amber-300" title={(d.candidates ?? []).map(fmtDay).join(" / ")}>
                          earliest of {d.candidate_count} candidate dates
                        </div>
                      ) : null}
                      <div className="mt-1">
                        <StatusBadge status={d.display_status} />
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900 dark:text-slate-100">{d.title}</div>
                      <div className="text-xs text-slate-500">
                        {[label(d.kind), d.matter.label, d.hard ? "hard" : null, d.source !== "manual" ? d.source.replace("_", " ") : null].filter(Boolean).join(" · ")}
                      </div>
                      {d.status === "done" && d.done_evidence ? <div className="text-xs text-slate-500">Done: {d.done_evidence}</div> : null}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      {d.rule_id ? <div className="font-mono">{d.rule_id}</div> : null}
                      {d.basis ? <div>{d.basis}</div> : null}
                      {Object.entries(d.inputs ?? {}).map(([k, v]) => (
                        <div key={k}>
                          {label(k)}: {/^\d{4}-\d{2}-\d{2}$/.test(v) ? fmtDay(v) : v}
                        </div>
                      ))}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      <div>Owner: {d.owner?.name ?? "—"}</div>
                      <div>Backup: {d.backup?.name ?? "—"}</div>
                      {d.covered_by ? <div className="font-medium text-amber-700 dark:text-amber-300">Covered by {d.covered_by.name}</div> : null}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      {d.check_state === "pending" && d.check_mode === "second" ? <div>Checker: {d.checker?.name}</div> : null}
                      {selfPending ? (
                        d.can_check ? (
                          <div>Re-enter the inputs to self-verify.</div>
                        ) : (
                          <div>Re-enter the dates tomorrow to self-verify (available from {d.check_opens_at ? fmtTime(d.check_opens_at) : "later"}).</div>
                        )
                      ) : null}
                      {d.check_mode === "self" && d.check_state === "pending" && !d.is_checker ? <div>Self re-entry by {d.checker?.name}</div> : null}
                      {why ? <div className="text-amber-700 dark:text-amber-300">{why}</div> : null}
                      {r ? (
                        <div className="mt-1">
                          {r.rung}
                          {r.level ? ` (escalated)` : ""} to {r.target?.name}: {r.acknowledged_at ? `acknowledged ${fmtTime(r.acknowledged_at)}` : r.delivered_at ? `seen ${fmtTime(r.delivered_at)}, not acknowledged` : "not yet seen"}
                        </div>
                      ) : (
                        <div className="mt-1 text-slate-400">No reminder yet</div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      {selfPending && d.can_check ? (
                        <button onClick={() => startCheck(d)} className={`mr-3 ${linkButton}`}>
                          Start check
                        </button>
                      ) : null}
                      {r && !r.acknowledged_at && d.status === "open" ? (
                        <button
                          disabled={busy === r.id}
                          onClick={() => act(r.id, () => api(`/api/v1/deadlines/reminders/${r.id}/acknowledge`, { token, orgId, method: "POST" }), "Acknowledged.")}
                          className={`mr-3 ${linkButton}`}
                        >
                          Acknowledge
                        </button>
                      ) : null}
                      {canManage && d.status === "open" && d.verification === "unverified" && ["pending", "cancelled"].includes(d.check_state) &&
                      !["reminder_to_checker", "due_within_lead"].includes(d.check_cancel_reason ?? "") ? (
                        <button
                          disabled={busy === `re-${d.id}`}
                          onClick={() => act(`re-${d.id}`, () => api(`/api/v1/deadlines/${d.id}/reassign-check`, { token, orgId, method: "POST" }), "Check reassigned.")}
                          className="mr-3 text-xs text-slate-600 hover:underline disabled:opacity-50 dark:text-slate-300"
                        >
                          Reassign check
                        </button>
                      ) : null}
                      {canManage && d.status === "open" ? (
                        <button
                          onClick={() => {
                            setCompleting(d);
                            setEvidence("");
                            setDialogError(null);
                          }}
                          className="text-xs font-medium text-emerald-700 hover:underline dark:text-emerald-300"
                        >
                          Mark done
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
              {docket.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                    No open deadlines. Add one, or generate them from a workflow.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Leave</h2>
          <p className="mt-1 text-xs text-slate-500">While someone is away their reminders go to the backup, and nobody on leave is asked to check.</p>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {absences.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-900 dark:text-slate-100">{name(a.user_id)}</span>
                <span className="text-slate-600 dark:text-slate-300">
                  {fmtDay(a.starts_on)}
                  {a.ends_on !== a.starts_on ? ` – ${fmtDay(a.ends_on)}` : ""}
                </span>
                {a.note ? <span className="text-xs text-slate-500">{a.note}</span> : null}
                {senior || a.user_id === me ? (
                  <button
                    onClick={() => act(`abs-${a.id}`, () => api(`/api/v1/deadlines/absences/${a.id}`, { token, orgId, method: "DELETE" }))}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Remove
                  </button>
                ) : null}
              </li>
            ))}
            {absences.length === 0 ? <li className="text-slate-500">Nobody is on leave.</li> : null}
          </ul>
          <form onSubmit={addLeave} className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            I&apos;m away from
            <input required type="date" className={field} value={leave.starts_on} onChange={(e) => setLeave({ ...leave, starts_on: e.target.value })} />
            to
            <input type="date" className={field} value={leave.ends_on} onChange={(e) => setLeave({ ...leave, ends_on: e.target.value })} />
            <input className={field} placeholder="Note (optional)" value={leave.note} onChange={(e) => setLeave({ ...leave, note: e.target.value })} />
            <button disabled={busy === "leave"} className={button}>
              Record leave
            </button>
          </form>
        </section>
      </main>

      {checking ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={() => busy !== "check" && setChecking(null)}>
          <form
            onSubmit={submitCheck}
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-md flex-col gap-3 rounded-xl bg-white p-5 shadow-xl dark:bg-slate-900"
          >
            <h2 className="font-semibold text-slate-900 dark:text-slate-100">
              {checking.check_mode === "self" ? "Self re-entry" : "Blind check"}: {checking.matter.label ?? label(checking.kind)} – {label(checking.kind)}
            </h2>
            <p className="text-xs text-slate-500">
              Enter the inputs from the source documents, not from memory. {checking.rule_id ? `Rule: ${checking.rule_id}.` : ""}
            </p>
            {checking.input_fields.map((f) => (
              <label key={f} className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                {label(f)}
                <input
                  required
                  type={isDateField(f) ? "date" : "text"}
                  className={field}
                  value={checkInputs[f] ?? ""}
                  onChange={(e) => setCheckInputs({ ...checkInputs, [f]: e.target.value })}
                />
              </label>
            ))}
            <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
              The date these inputs give
              <input type="date" className={field} value={checkDate} onChange={(e) => setCheckDate(e.target.value)} />
              <span className="text-xs text-slate-500">Leave empty when the rule computes it.</span>
            </label>
            {dialogError ? <p className="text-sm text-red-600">{dialogError}</p> : null}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setChecking(null)} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                Cancel
              </button>
              <button disabled={busy === "check"} className={button}>
                {busy === "check" ? "Submitting…" : "Submit check"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {completing ? (
        <ConfirmDialog
          title={`Mark "${completing.title ?? label(completing.kind)}" done?`}
          facts={[
            { label: "What happens", value: "Reminders stop and the deadline leaves the open docket." },
            { label: "Record", value: "Say how it was done: filing or diary number, receipt, or order." },
          ]}
          confirmLabel="Mark done"
          busy={busy === "complete"}
          error={dialogError}
          onConfirm={complete}
          onCancel={() => setCompleting(null)}
        >
          <input
            autoFocus
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="e.g. Filed on e-filing portal, diary no. 4411/2026"
            className={`w-full ${field}`}
          />
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
