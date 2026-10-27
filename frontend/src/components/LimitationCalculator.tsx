"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

// Declared here (not in lib/types.ts): the shapes returned by /api/v1/limitation.
type Rule = {
  rule_id: string;
  version: number;
  title: string;
  basis: string;
  remedy: string;
  forum: string;
  period_label: string;
  start_event: string;
  exclusions: string[];
  condonable: boolean;
  outer_limit: { label: string; hard: boolean } | null;
  notes: string;
  active: boolean;
  signatures: { verified_by: string; verified_at: string }[];
  signatures_needed: number;
  signed_by_me: boolean;
  earlier_version_signed: boolean;
};

type Line = {
  kind: "start" | "period" | "exclusion" | "covid" | "s4" | "outer" | "final" | "warning" | "info";
  label: string;
  section?: string;
  days?: number;
  date?: string;
  hard?: boolean;
  informational?: boolean;
};

type Computation = {
  label: string;
  unverified?: boolean;
  rule: { rule_id: string; version: number; title: string; basis: string };
  lines: Line[];
  safe_date: string;
  docket_date: string;
  prescribed_end: string;
  outer_limit: { date: string; hard: boolean; label: string } | null;
  provisional: boolean;
  alternatives: { label: string; date: string; note: string }[];
  warnings: string[];
  filing?: { status: "in_time" | "needs_extension" | "barred"; message: string };
  deadlines?: { id?: string }[];
};

type Court = { code: string; name: string; state: string | null };
type CourtCase = { id: string; title: string };
type CopyApplication = {
  id: string;
  court_case_id: string | null;
  thread_id: string | null;
  court_code: string | null;
  order_date: string | null;
  applied_on: string;
  ready_on: string | null;
  delivered_on: string | null;
  status: "pending" | "ready" | "delivered" | "withdrawn";
  notes: string | null;
  days_since_applied: number;
  pending: boolean;
  next_check_on: string | null;
  check_due: boolean;
};

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const EMPTY_INPUTS = {
  start_date: "",
  copy_applied_on: "",
  copy_ready_on: "",
  copy_delivered_on: "",
  decree_copy_applied_on: "",
  decree_copy_ready_on: "",
  s14_from: "",
  s14_to: "",
  court_code: "",
  filing_on: "",
};
const EMPTY_COPY = { court_case_id: "", court_code: "", order_date: "", applied_on: "", notes: "" };

function fmt(day: string | null | undefined) {
  if (!day) return "";
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", weekday: "short" });
}

function lineTone(line: Line) {
  if (line.kind === "warning") return "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200";
  if (line.hard) return "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300";
  if (line.kind === "final") return "border-indigo-300 bg-indigo-50 font-semibold text-indigo-900 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200";
  if (line.informational) return "border-slate-200 text-slate-500 italic dark:border-slate-700";
  return "border-slate-200 text-slate-800 dark:border-slate-700 dark:text-slate-200";
}

const FILING_TONE = {
  in_time: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  needs_extension: "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  barred: "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300",
};

/** Limitation calculator (dates computed in code from rules the firm has signed) and the Copy tracker. */
export function LimitationCalculator({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const role = workspace.orgs.find((o) => o.id === orgId)?.role;
  const senior = role === "owner" || role === "partner";

  const [rules, setRules] = useState<Rule[]>([]);
  const [courts, setCourts] = useState<Court[]>([]);
  const [cases, setCases] = useState<CourtCase[]>([]);
  const [copies, setCopies] = useState<CopyApplication[]>([]);
  const [ruleId, setRuleId] = useState("");
  const [inputs, setInputs] = useState(EMPTY_INPUTS);
  const [result, setResult] = useState<Computation | null>(null);
  const [docketTitle, setDocketTitle] = useState("");
  const [docketCase, setDocketCase] = useState("");
  const [copyForm, setCopyForm] = useState(EMPTY_COPY);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    const fail = (e: Error) => setError(e.message);
    api<{ rules: Rule[] }>("/api/v1/limitation/rules", { token, orgId }).then((r) => setRules(r.rules)).catch(fail);
    api<Court[]>("/api/v1/limitation/courts", { token, orgId }).then(setCourts).catch(fail);
    api<CourtCase[]>("/api/v1/cases", { token, orgId }).then(setCases).catch(fail);
    api<CopyApplication[]>("/api/v1/limitation/copy-applications", { token, orgId }).then(setCopies).catch(fail);
  }, [token, orgId]);

  useEffect(load, [load]);

  const active = rules.filter((r) => r.active);
  const drafts = rules.filter((r) => !r.active);
  const rule = rules.find((r) => r.rule_id === ruleId) ?? null;
  const set = (key: keyof typeof EMPTY_INPUTS) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setInputs({ ...inputs, [key]: e.target.value });

  function body(extra: Record<string, unknown> = {}) {
    const values: Record<string, unknown> = { rule_id: ruleId };
    for (const [key, value] of Object.entries(inputs)) {
      if (value && key !== "s14_from" && key !== "s14_to") values[key] = value;
    }
    if (inputs.s14_from && inputs.s14_to) values.s14_periods = [{ from: inputs.s14_from, to: inputs.s14_to }];
    if (rule && !rule.active) values.preview = true;
    return { ...values, ...extra };
  }

  async function compute(e?: React.FormEvent) {
    e?.preventDefault();
    if (!ruleId || !inputs.start_date) return;
    setBusy("compute");
    setError(null);
    setNotice(null);
    try {
      setResult(await api<Computation>("/api/v1/limitation/compute", { token, orgId, method: "POST", body: body() }));
    } catch (err) {
      setResult(null);
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function saveToDocket() {
    if (!result) return;
    setBusy("docket");
    setError(null);
    try {
      const saved = await api<Computation>("/api/v1/limitation/compute", {
        token,
        orgId,
        method: "POST",
        body: body({ save_to_docket: true, title: docketTitle.trim() || undefined, court_case_id: docketCase || undefined }),
      });
      setResult(saved);
      setNotice(`Saved to the docket for ${fmt(saved.docket_date)}${saved.deadlines && saved.deadlines.length > 1 ? " (with the outer limit)" : ""}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function copyAction(id: string, run: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await run();
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function addCopy(e: React.FormEvent) {
    e.preventDefault();
    const payload = Object.fromEntries(Object.entries(copyForm).filter(([, v]) => v.trim() !== ""));
    copyAction("add-copy", async () => {
      await api("/api/v1/limitation/copy-applications", { token, orgId, method: "POST", body: payload });
      setCopyForm(EMPTY_COPY);
    });
  }

  function fillFromCopy(c: CopyApplication) {
    setInputs({
      ...inputs,
      start_date: inputs.start_date || c.order_date || "",
      copy_applied_on: c.applied_on,
      copy_ready_on: c.ready_on ?? "",
      copy_delivered_on: c.delivered_on ?? "",
      court_code: c.court_code ?? inputs.court_code,
    });
    if (c.court_case_id) setDocketCase(c.court_case_id);
    setNotice("Copy dates filled in. Pick the remedy and compute.");
  }

  const caseTitle = (id: string | null) => cases.find((c) => c.id === id)?.title ?? "";
  const showDecreeCopy = rule?.exclusions.includes("s12_3");
  const showCopy = rule?.exclusions.includes("s12_2");
  const showS14 = rule?.exclusions.includes("s14");

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/cases" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Cases
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Limitation</h1>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 overflow-y-auto p-4">
        <p className="text-xs text-slate-500">
          Dates are computed in code from rules your firm has signed off, and shown line by line. They are a computation for a lawyer to
          check, not legal advice. Where an input or the law is uncertain, the earlier date is used.
        </p>
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p>
        ) : null}

        <div className="grid gap-4 lg:grid-cols-2">
          <form onSubmit={compute} className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Calculator</h2>
            <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
              Remedy
              <select
                className={field}
                value={ruleId}
                onChange={(e) => {
                  setRuleId(e.target.value);
                  setResult(null);
                }}
              >
                <option value="">{active.length ? "Choose a remedy…" : "No rule is signed off yet"}</option>
                {active.length ? (
                  <optgroup label="Signed off by your firm">
                    {active.map((r) => (
                      <option key={r.rule_id} value={r.rule_id}>
                        {r.title} ({r.period_label})
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {senior && drafts.length ? (
                  <optgroup label="Draft rules: preview only, not for reliance">
                    {drafts.map((r) => (
                      <option key={r.rule_id} value={r.rule_id}>
                        {r.title} (draft)
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
            </label>
            {rule ? (
              <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
                <div>
                  <span className="font-medium">{rule.forum}</span> · {rule.period_label} · version {rule.version}
                  {rule.condonable ? "" : " · delay cannot be condoned"}
                </div>
                <div className="mt-1">{rule.basis}</div>
                {rule.notes ? <div className="mt-1 text-slate-500">{rule.notes}</div> : null}
                {!rule.active ? (
                  <div className="mt-1 font-semibold text-red-700 dark:text-red-300">UNVERIFIED RULE: not for reliance. It can&apos;t be saved to the docket.</div>
                ) : null}
              </div>
            ) : null}

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                {rule?.start_event ?? "Date of judgment / order / service"}
                <input type="date" required className={field} value={inputs.start_date} onChange={set("start_date")} />
              </label>
              <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                Court (for s. 4 closures)
                <select className={field} value={inputs.court_code} onChange={set("court_code")}>
                  <option value="">No court: s. 4 not checked</option>
                  {courts.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              {showCopy ? (
                <>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    Certified copy applied for
                    <input type="date" className={field} value={inputs.copy_applied_on} onChange={set("copy_applied_on")} />
                  </label>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    Copy ready (notified)
                    <input type="date" className={field} value={inputs.copy_ready_on} onChange={set("copy_ready_on")} />
                  </label>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    Copy delivered
                    <input type="date" className={field} value={inputs.copy_delivered_on} onChange={set("copy_delivered_on")} />
                  </label>
                </>
              ) : null}
              {showDecreeCopy ? (
                <>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    Decree copy applied for
                    <input type="date" className={field} value={inputs.decree_copy_applied_on} onChange={set("decree_copy_applied_on")} />
                  </label>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    Decree copy ready
                    <input type="date" className={field} value={inputs.decree_copy_ready_on} onChange={set("decree_copy_ready_on")} />
                  </label>
                </>
              ) : null}
              {showS14 ? (
                <>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    s. 14: other proceeding from
                    <input type="date" className={field} value={inputs.s14_from} onChange={set("s14_from")} />
                  </label>
                  <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                    s. 14: to
                    <input type="date" className={field} value={inputs.s14_to} onChange={set("s14_to")} />
                  </label>
                </>
              ) : null}
              <label className="flex flex-col gap-1 text-sm text-slate-600 dark:text-slate-300">
                Filed on (optional: check a filing)
                <input type="date" className={field} value={inputs.filing_on} onChange={set("filing_on")} />
              </label>
            </div>
            <div className="flex gap-2">
              <button
                disabled={!ruleId || !inputs.start_date || busy === "compute"}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {busy === "compute" ? "Computing…" : "Compute"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setInputs(EMPTY_INPUTS);
                  setResult(null);
                }}
                className="text-sm text-slate-500 hover:underline"
              >
                Clear
              </button>
            </div>
          </form>

          <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Worked computation</h2>
            {result ? (
              <>
                {result.unverified ? (
                  <p className="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white">UNVERIFIED RULE: not for reliance</p>
                ) : null}
                <div className="flex flex-wrap items-end gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Safe date{result.provisional ? " (provisional)" : ""}</div>
                    <div className="text-2xl font-semibold text-slate-900 dark:text-slate-100">{fmt(result.safe_date)}</div>
                  </div>
                  {result.alternatives.map((a) => (
                    <div key={a.label} title={a.note}>
                      <div className="text-xs text-slate-500">{a.label}</div>
                      <div className="text-sm text-slate-600 dark:text-slate-300">{fmt(a.date)} (not docketed)</div>
                    </div>
                  ))}
                </div>
                {result.outer_limit ? (
                  <p
                    className={`rounded-lg px-3 py-2 text-sm ${result.outer_limit.hard ? "bg-red-50 font-medium text-red-800 dark:bg-red-950/40 dark:text-red-300" : "bg-slate-50 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300"}`}
                  >
                    {result.outer_limit.hard ? "Hard limit: " : "Outer limit: "}
                    {fmt(result.outer_limit.date)}. {result.outer_limit.label}
                  </p>
                ) : null}
                {result.filing ? <p className={`rounded-lg px-3 py-2 text-sm ${FILING_TONE[result.filing.status]}`}>{result.filing.message}</p> : null}
                <ol className="flex flex-col gap-1.5">
                  {result.lines.map((line, i) => (
                    <li key={i} className={`rounded-lg border px-3 py-1.5 text-sm ${lineTone(line)}`}>
                      <div className="flex flex-wrap items-baseline gap-x-3">
                        <span className="flex-1">{line.label}</span>
                        {line.days !== undefined && line.kind !== "period" && line.kind !== "outer" ? (
                          <span className="whitespace-nowrap text-xs">{line.days >= 0 ? `+${line.days}` : line.days} days</span>
                        ) : null}
                        {line.date ? <span className="whitespace-nowrap text-xs">{fmt(line.date)}</span> : null}
                      </div>
                      {line.section ? <div className="text-xs opacity-70">{line.section}</div> : null}
                    </li>
                  ))}
                </ol>
                <p className="text-xs text-slate-500">{result.label}</p>
                {!result.unverified ? (
                  <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
                    <input
                      className={`${field} flex-1`}
                      placeholder={`Docket title (default: ${result.rule.title})`}
                      value={docketTitle}
                      onChange={(e) => setDocketTitle(e.target.value)}
                    />
                    <select className={field} value={docketCase} onChange={(e) => setDocketCase(e.target.value)}>
                      <option value="">No case linked</option>
                      {cases.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.title}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={saveToDocket}
                      disabled={busy === "docket"}
                      className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy === "docket" ? "Saving…" : `Save ${fmt(result.docket_date)} to docket`}
                    </button>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-slate-500">Pick a remedy, enter the dates and compute. Each step is shown with its section and days.</p>
            )}
          </section>
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Draft rules: need two sign-offs ({drafts.length})</h2>
          <p className="mt-1 text-xs text-slate-500">
            Rules ship as drafts. A rule applies in your firm once two members (associates or above) have signed its current version.
            {senior ? " Owners and partners can preview a draft; previews are labelled and can't be docketed." : ""}
          </p>
          {drafts.length ? (
            <ul className="mt-2 flex flex-col gap-1.5">
              {drafts.map((r) => (
                <li key={r.rule_id} className="flex flex-wrap items-baseline gap-2 text-sm">
                  <span className="font-medium text-slate-900 dark:text-slate-100">{r.title}</span>
                  <span className="text-xs text-slate-500">
                    v{r.version} · {r.signatures.length}/2 signed{r.signed_by_me ? " (including you)" : ""}
                    {r.earlier_version_signed ? " · an earlier version was signed: the rule changed" : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">Every rule is signed off.</p>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Copy tracker ({copies.filter((c) => c.pending).length} pending)
          </h2>
          <form onSubmit={addCopy} className="mt-2 grid gap-2 sm:grid-cols-5">
            <select
              required
              className={field}
              value={copyForm.court_case_id}
              onChange={(e) => setCopyForm({ ...copyForm, court_case_id: e.target.value })}
            >
              <option value="">Case…</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <select className={field} value={copyForm.court_code} onChange={(e) => setCopyForm({ ...copyForm, court_code: e.target.value })}>
              <option value="">Court…</option>
              {courts.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
            <label className="flex flex-col text-xs text-slate-500">
              Order date
              <input type="date" className={field} value={copyForm.order_date} onChange={(e) => setCopyForm({ ...copyForm, order_date: e.target.value })} />
            </label>
            <label className="flex flex-col text-xs text-slate-500">
              Applied on
              <input
                type="date"
                required
                className={field}
                value={copyForm.applied_on}
                onChange={(e) => setCopyForm({ ...copyForm, applied_on: e.target.value })}
              />
            </label>
            <button
              disabled={busy === "add-copy"}
              className="self-end rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Log copy application
            </button>
          </form>

          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
                <tr>
                  <th className="px-3 py-2">Case</th>
                  <th className="px-3 py-2">Applied</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Ready / delivered</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {copies.map((c) => (
                  <tr key={c.id} className="align-top">
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-900 dark:text-slate-100">{caseTitle(c.court_case_id) || "Case thread"}</div>
                      <div className="text-xs text-slate-500">{[c.court_code, c.order_date ? `order ${fmt(c.order_date)}` : null].filter(Boolean).join(" · ")}</div>
                    </td>
                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                      {fmt(c.applied_on)}
                      <div className="text-xs text-slate-500">{c.days_since_applied} days ago</div>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${c.pending ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}
                      >
                        {c.status}
                      </span>
                      {c.pending && c.next_check_on ? (
                        <div className={`mt-1 text-xs ${c.check_due ? "font-medium text-red-700 dark:text-red-300" : "text-slate-500"}`}>
                          {c.check_due ? "Check the copy section today" : `Check the copy section on ${fmt(c.next_check_on)}`}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <label className="block text-xs text-slate-500">
                        Ready
                        <input
                          type="date"
                          defaultValue={c.ready_on ?? ""}
                          onBlur={(e) =>
                            e.target.value !== (c.ready_on ?? "") &&
                            copyAction(c.id, () =>
                              api(`/api/v1/limitation/copy-applications/${c.id}`, { token, orgId, method: "PATCH", body: { ready_on: e.target.value || null } }),
                            )
                          }
                          className="ml-1 rounded border border-slate-200 bg-transparent px-1 text-xs dark:border-slate-700"
                        />
                      </label>
                      <label className="mt-1 block text-xs text-slate-500">
                        Delivered
                        <input
                          type="date"
                          defaultValue={c.delivered_on ?? ""}
                          onBlur={(e) =>
                            e.target.value !== (c.delivered_on ?? "") &&
                            copyAction(c.id, () =>
                              api(`/api/v1/limitation/copy-applications/${c.id}`, {
                                token,
                                orgId,
                                method: "PATCH",
                                body: { delivered_on: e.target.value || null },
                              }),
                            )
                          }
                          className="ml-1 rounded border border-slate-200 bg-transparent px-1 text-xs dark:border-slate-700"
                        />
                      </label>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">
                      <button onClick={() => fillFromCopy(c)} className="mr-3 text-xs text-indigo-700 hover:underline dark:text-indigo-300">
                        Use in calculator
                      </button>
                      <button
                        disabled={busy === c.id}
                        onClick={() =>
                          copyAction(c.id, () => api(`/api/v1/limitation/copy-applications/${c.id}`, { token, orgId, method: "DELETE" }))
                        }
                        className="text-xs text-red-600 hover:underline disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {copies.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-500">
                      No copy applications. Log one when you apply for a certified copy: the limitation date stays provisional until the
                      copy-ready date is entered.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
