"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

type Offence = {
  rule_id: string;
  kind: "offence" | "special_period";
  code: string;
  section: string;
  title: string;
  basis: string;
  max_years: number | null;
  min_years: number | null;
  life: boolean;
  death: boolean;
  active: boolean;
};

type CustodyFile = {
  id: string;
  accused_name: string;
  matter: string | null;
  offence_date: string;
  fir_date: string | null;
  investigation_started_on: string | null;
  arrest_date: string;
  first_remand_date: string | null;
  sections: string[];
  custody_type: "police" | "judicial" | "released";
  chargesheet_filed_on: string | null;
  default_bail_applied_on: string | null;
  first_time_offender: boolean | null;
  other_pending_cases: boolean | null;
  special_statute: "NDPS_COMMERCIAL" | "UAPA" | null;
  docket: Record<string, { id: string; due_date: string; done?: boolean }>;
};

type Flag = { code: string; severity: string; message: string };

type Result = {
  codes: { substantive: string | null; procedural: string; explanation: string };
  punishment: { max_years: number | null; min_years: number | null; life: boolean; death: boolean; deciding_section: string | null };
  days_in_custody: number | null;
  in_custody: boolean;
  preview: boolean;
  label: string | null;
  unverified_rules: string[];
  disclaimer: string;
  default_bail: {
    provision: string;
    days: number | null;
    period_ends: string | null;
    accrues_on: string | null;
    status: string | null;
    basis: string | null;
    notes: string[];
    evidence?: string;
    days_left: number | null;
  };
  undertrial: {
    provision: string;
    date: string | null;
    share: string | null;
    excluded: boolean;
    explanation: string | null;
    basis: string | null;
    checklist: { item: string; confirmed: boolean; excludes?: boolean }[];
    alternative: { provision: string; date: string | null; more_favourable: boolean; basis: string } | null;
  };
  apply_today: boolean;
  flags: Flag[];
  badges: string[];
};

type Entry = { file: CustodyFile; result: Result | null; blocked: { code: string; message: string } | null };

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const EMPTY = {
  accused_name: "",
  matter: "",
  offence_date: "",
  fir_date: "",
  investigation_started_on: "",
  arrest_date: "",
  first_remand_date: "",
  chargesheet_filed_on: "",
  custody_type: "judicial",
  first_time_offender: "",
  other_pending_cases: "",
  special_statute: "",
};

function fmt(day: string | null | undefined) {
  if (!day) return "—";
  return new Date(day).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function tri(value: string): boolean | null {
  return value === "yes" ? true : value === "no" ? false : null;
}

function triValue(value: boolean | null): string {
  return value === true ? "yes" : value === false ? "no" : "";
}

function Badge({ text, tone = "slate" }: { text: string; tone?: "slate" | "red" | "amber" | "emerald" | "indigo" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    red: "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
    emerald: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
  };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{text}</span>;
}

function badgeTone(text: string): "red" | "amber" | "emerald" | "indigo" | "slate" {
  if (text.startsWith("Apply today") || text.startsWith("Right lost") || text.startsWith("Not eligible: other")) return "red";
  if (text.includes("check s. 531") || text.includes("not entered") || text.includes("Not eligible if") || text.includes("not confirmed")) return "amber";
  if (text.startsWith("one-third")) return "emerald";
  return "indigo";
}

function DefaultBailCell({ r }: { r: Result }) {
  const d = r.default_bail;
  if (d.status === "unknown") return <span className="text-xs text-slate-500">Sections not in the table</span>;
  if (d.status === "right_lost") return <Badge text="Right lost: chargesheet filed" tone="red" />;
  if (d.status === "chargesheet_filed") return <span className="text-xs text-slate-500">Chargesheet filed in time</span>;
  if (d.status === "availed") return <Badge text="Application made" tone="emerald" />;
  return (
    <div>
      <div className="whitespace-nowrap font-medium text-slate-900 dark:text-slate-100">{fmt(d.accrues_on)}</div>
      <div className="text-xs text-slate-500">
        {d.provision} · {d.days} days
      </div>
      {d.status === "accrued" ? (
        <Badge text="Apply today" tone="red" />
      ) : d.days_left !== null && d.status === "running" ? (
        <span className={`text-xs ${d.days_left <= 5 ? "text-red-600" : "text-slate-500"}`}>in {d.days_left} days</span>
      ) : null}
    </div>
  );
}

function UndertrialCell({ r }: { r: Result }) {
  const u = r.undertrial;
  if (!u.date) return <span className="text-xs text-slate-500">{u.explanation ?? "—"}</span>;
  return (
    <div>
      <div className={`whitespace-nowrap font-medium ${u.excluded ? "text-slate-400 line-through" : "text-slate-900 dark:text-slate-100"}`}>{fmt(u.date)}</div>
      <div className="text-xs text-slate-500">
        {u.provision} · {u.share}
      </div>
      {u.alternative?.date ? (
        <div className="text-xs text-slate-500">
          Alt.: {u.alternative.provision} {fmt(u.alternative.date)}
          {u.alternative.more_favourable ? " (more favourable)" : ""}
        </div>
      ) : null}
    </div>
  );
}

/** Every client in custody with the default-bail and s. 479 BNSS dates, computed from the firm's signed punishment table. */
export function CustodyBoard({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const role = workspace.orgs.find((o) => o.id === orgId)?.role;
  const senior = role === "owner" || role === "partner";
  const [entries, setEntries] = useState<Entry[]>([]);
  const [offences, setOffences] = useState<Offence[]>([]);
  const [form, setForm] = useState(EMPTY);
  const [sections, setSections] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showReleased, setShowReleased] = useState(false);
  const [order, setOrder] = useState({ order_date: "", extended_to_days: "" });

  const load = useCallback(() => {
    if (!orgId) return;
    const query = `?preview=${senior ? "true" : "false"}${showReleased ? "&include_released=true" : ""}`;
    api<Entry[]>(`/api/v1/custody${query}`, { token, orgId }).then(setEntries).catch((e: Error) => setError(e.message));
  }, [token, orgId, senior, showReleased]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!orgId) return;
    api<Offence[]>("/api/v1/custody/offences", { token, orgId }).then(setOffences).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  const offenceById = useMemo(() => Object.fromEntries(offences.map((o) => [o.rule_id, o])), [offences]);
  const pickable = offences.filter((o) => o.kind === "offence");

  async function run(id: string, action: () => Promise<unknown>, done?: string) {
    setBusy(id);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function add(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = { sections, custody_type: form.custody_type };
    for (const key of ["accused_name", "matter", "offence_date", "fir_date", "investigation_started_on", "arrest_date", "first_remand_date", "chargesheet_filed_on"] as const) {
      if (form[key].trim()) body[key] = form[key].trim();
    }
    body.first_time_offender = tri(form.first_time_offender);
    body.other_pending_cases = tri(form.other_pending_cases);
    if (form.special_statute) body.special_statute = form.special_statute;
    run("add", async () => {
      await api("/api/v1/custody", { token, orgId, method: "POST", body });
      setForm(EMPTY);
      setSections([]);
      setAdding(false);
    });
  }

  function patch(file: CustodyFile, body: Record<string, unknown>) {
    return run(file.id, () => api(`/api/v1/custody/${file.id}`, { token, orgId, method: "PATCH", body }));
  }

  const applyToday = entries.filter((e) => e.result?.apply_today).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Custody board</h1>
        <button onClick={() => setAdding((v) => !v)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
          + Add custody file
        </button>
        <label className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={showReleased} onChange={(e) => setShowReleased(e.target.checked)} />
          Show released
        </label>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 overflow-y-auto p-4">
        <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-400">
          Dates are computations for the advocate to check against the statute and the record. The punishment table applies once two members of the firm have
          signed each entry; until then owners and partners see a labelled preview. Custody data stays in the firm and is never sent to an AI model.
        </p>
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p> : null}
        {applyToday ? (
          <p className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white">
            {applyToday} {applyToday === 1 ? "client needs" : "clients need"} an application today.
          </p>
        ) : null}

        {adding ? (
          <form onSubmit={add} className="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-3 dark:border-slate-800 dark:bg-slate-900">
            <input required className={field} placeholder="Accused" value={form.accused_name} onChange={(e) => setForm({ ...form, accused_name: e.target.value })} />
            <input className={field} placeholder="Matter, e.g. State v. Kumar (FIR 112/2025)" value={form.matter} onChange={(e) => setForm({ ...form, matter: e.target.value })} />
            <select className={field} value={form.custody_type} onChange={(e) => setForm({ ...form, custody_type: e.target.value })}>
              <option value="judicial">Judicial custody</option>
              <option value="police">Police custody</option>
              <option value="released">Released</option>
            </select>
            {(
              [
                ["offence_date", "Offence date (IPC or BNS)", true],
                ["fir_date", "FIR registered (CrPC or BNSS)", false],
                ["investigation_started_on", "Complaint filed (complaint cases)", false],
                ["arrest_date", "Arrest", true],
                ["first_remand_date", "First remand", false],
                ["chargesheet_filed_on", "Chargesheet filed", false],
              ] as const
            ).map(([key, label, required]) => (
              <label key={key} className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
                {label}
                <input type="date" required={required} className={field} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </label>
            ))}
            <label className="flex flex-col gap-1 text-xs text-slate-600 sm:col-span-3 dark:text-slate-300">
              Sections charged (punishment comes from the table)
              <select
                multiple
                className={`${field} h-36`}
                value={sections}
                onChange={(e) => setSections(Array.from(e.target.selectedOptions, (o) => o.value))}
              >
                {["BNS", "IPC", "NDPS"].map((code) => (
                  <optgroup key={code} label={code}>
                    {pickable
                      .filter((o) => o.code === code)
                      .map((o) => (
                        <option key={o.rule_id} value={o.rule_id}>
                          {o.rule_id}: {o.title}
                          {o.death ? " · death" : o.life ? " · life" : o.max_years ? ` · up to ${o.max_years}y` : ""}
                          {o.min_years ? ` · min ${o.min_years}y` : ""}
                          {o.active ? "" : " · unsigned"}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
              First-time offender (lawyer-confirmed)
              <select className={field} value={form.first_time_offender} onChange={(e) => setForm({ ...form, first_time_offender: e.target.value })}>
                <option value="">Not confirmed</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
              Other cases pending (s. 479(2))
              <select className={field} value={form.other_pending_cases} onChange={(e) => setForm({ ...form, other_pending_cases: e.target.value })}>
                <option value="">Not confirmed</option>
                <option value="no">None pending</option>
                <option value="yes">Other cases pending</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
              Special statute
              <select className={field} value={form.special_statute} onChange={(e) => setForm({ ...form, special_statute: e.target.value })}>
                <option value="">None</option>
                <option value="NDPS_COMMERCIAL">NDPS (s. 36A(4): commercial quantity, ss. 19/24/27A)</option>
                <option value="UAPA">UAPA (s. 43D(2))</option>
              </select>
            </label>
            <button disabled={busy === "add"} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 sm:col-span-3">
              {busy === "add" ? "Saving…" : "Save custody file"}
            </button>
          </form>
        ) : null}

        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
              <tr>
                <th className="px-3 py-2">Accused</th>
                <th className="px-3 py-2">Offence / FIR / remand</th>
                <th className="px-3 py-2">In custody</th>
                <th className="px-3 py-2">Default bail</th>
                <th className="px-3 py-2">s. 479 BNSS</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {entries.map(({ file, result, blocked }) => (
                <FileRows
                  key={file.id}
                  file={file}
                  result={result}
                  blocked={blocked}
                  offenceById={offenceById}
                  expanded={open === file.id}
                  busy={busy === file.id}
                  onToggle={() => setOpen(open === file.id ? null : file.id)}
                  onPatch={(body) => patch(file, body)}
                  onDocket={() =>
                    run(file.id, () => api(`/api/v1/custody/${file.id}/docket`, { token, orgId, method: "POST" }), "Dates saved to the docket.")
                  }
                  order={order}
                  setOrder={setOrder}
                  onOrder={() =>
                    run(
                      file.id,
                      async () => {
                        await api(`/api/v1/custody/${file.id}/extension-orders`, {
                          token,
                          orgId,
                          method: "POST",
                          body: { order_date: order.order_date, extended_to_days: Number(order.extended_to_days) },
                        });
                        setOrder({ order_date: "", extended_to_days: "" });
                      },
                      "Extension order recorded.",
                    )
                  }
                />
              ))}
              {entries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                    No clients in custody. Add a custody file to watch its default-bail and s. 479 dates.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}

function FileRows({
  file,
  result,
  blocked,
  offenceById,
  expanded,
  busy,
  onToggle,
  onPatch,
  onDocket,
  order,
  setOrder,
  onOrder,
}: {
  file: CustodyFile;
  result: Result | null;
  blocked: Entry["blocked"];
  offenceById: Record<string, Offence>;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onPatch: (body: Record<string, unknown>) => void;
  onDocket: () => void;
  order: { order_date: string; extended_to_days: string };
  setOrder: (o: { order_date: string; extended_to_days: string }) => void;
  onOrder: () => void;
}) {
  const red = result?.apply_today;
  const special = file.special_statute || file.sections.some((s) => s.startsWith("NDPS-2"));
  return (
    <>
      <tr className={`align-top ${red ? "bg-red-50 dark:bg-red-950/30" : ""}`}>
        <td className="px-3 py-2">
          <div className="font-medium text-slate-900 dark:text-slate-100">{file.accused_name}</div>
          {file.matter ? <div className="text-xs text-slate-500">{file.matter}</div> : null}
          <div className="text-xs text-slate-500">
            {file.sections.map((s) => (offenceById[s] ? `${s} (${offenceById[s].title})` : s)).join(", ") || "No sections"}
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {result?.preview ? <Badge text={result.label ?? "UNVERIFIED"} tone="red" /> : null}
            {result?.badges.map((b) => <Badge key={b} text={b} tone={badgeTone(b)} />)}
          </div>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
          <div>Offence {fmt(file.offence_date)}</div>
          <div>FIR {fmt(file.fir_date)}</div>
          <div>Remand {fmt(file.first_remand_date)}</div>
          {result ? (
            <div className="text-slate-500">
              {result.codes.substantive} · {result.codes.procedural}
            </div>
          ) : null}
        </td>
        <td className="px-3 py-2 text-slate-700 dark:text-slate-200">
          {result?.days_in_custody != null ? `${result.days_in_custody} days` : file.custody_type === "released" ? "Released" : "—"}
          <div className="text-xs text-slate-500">{file.chargesheet_filed_on ? `Chargesheet ${fmt(file.chargesheet_filed_on)}` : "No chargesheet"}</div>
        </td>
        {blocked ? (
          <td colSpan={2} className="px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            {blocked.message}
          </td>
        ) : result ? (
          <>
            <td className="px-3 py-2">
              <DefaultBailCell r={result} />
            </td>
            <td className="px-3 py-2">
              <UndertrialCell r={result} />
            </td>
          </>
        ) : (
          <td colSpan={2} />
        )}
        <td className="whitespace-nowrap px-3 py-2 text-right">
          <button onClick={onToggle} className="text-xs text-indigo-700 hover:underline dark:text-indigo-300">
            {expanded ? "Close" : "Details"}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={6} className="bg-slate-50 px-4 py-3 text-sm dark:bg-slate-800/40">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-2">
                {result ? (
                  <>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{result.codes.explanation}</p>
                    {result.default_bail.basis ? (
                      <p className="text-xs text-slate-700 dark:text-slate-200">
                        <span className="font-semibold">Default bail. </span>
                        {result.default_bail.basis}
                      </p>
                    ) : null}
                    {result.default_bail.evidence ? <p className="text-xs text-slate-500">{result.default_bail.evidence}</p> : null}
                    {result.default_bail.notes.map((n) => (
                      <p key={n} className="text-xs text-amber-700 dark:text-amber-300">
                        {n}
                      </p>
                    ))}
                    {result.undertrial.basis ? (
                      <p className="text-xs text-slate-700 dark:text-slate-200">
                        <span className="font-semibold">Undertrial release. </span>
                        {result.undertrial.basis}
                      </p>
                    ) : null}
                    {result.undertrial.explanation ? <p className="text-xs text-slate-600 dark:text-slate-300">{result.undertrial.explanation}</p> : null}
                    {result.undertrial.alternative ? <p className="text-xs text-slate-500">{result.undertrial.alternative.basis}</p> : null}
                    {result.undertrial.checklist.length ? (
                      <ul className="text-xs text-slate-600 dark:text-slate-300">
                        {result.undertrial.checklist.map((c) => (
                          <li key={c.item}>
                            {c.excludes ? "✗" : c.confirmed ? "✓" : "○"} {c.item}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {result.flags.map((f) => (
                      <p key={f.code + f.message} className={`text-xs ${f.severity === "high" ? "text-red-700 dark:text-red-300" : "text-amber-700 dark:text-amber-300"}`}>
                        {f.message}
                      </p>
                    ))}
                    <p className="text-xs italic text-slate-500">{result.disclaimer}</p>
                  </>
                ) : (
                  <p className="text-xs text-slate-500">{blocked?.message}</p>
                )}
              </div>
              <div className="flex flex-col gap-2 text-xs text-slate-600 dark:text-slate-300">
                {(
                  [
                    ["chargesheet_filed_on", "Chargesheet filed on", file.chargesheet_filed_on],
                    ["default_bail_applied_on", "Default-bail application made on", file.default_bail_applied_on],
                    ["fir_date", "FIR registered on", file.fir_date],
                    ["first_remand_date", "First remand on", file.first_remand_date],
                  ] as const
                ).map(([key, label, value]) => (
                  <label key={key} className="flex items-center justify-between gap-2">
                    {label}
                    <input
                      type="date"
                      defaultValue={value ?? ""}
                      onBlur={(e) => e.target.value !== (value ?? "") && onPatch({ [key]: e.target.value || null })}
                      className="rounded border border-slate-200 bg-transparent px-1 dark:border-slate-700"
                    />
                  </label>
                ))}
                {(
                  [
                    ["first_time_offender", "First-time offender", file.first_time_offender],
                    ["other_pending_cases", "Other cases pending", file.other_pending_cases],
                  ] as const
                ).map(([key, label, value]) => (
                  <label key={key} className="flex items-center justify-between gap-2">
                    {label}
                    <select
                      value={triValue(value)}
                      onChange={(e) => onPatch({ [key]: tri(e.target.value) })}
                      className="rounded border border-slate-200 bg-transparent px-1 dark:border-slate-700"
                    >
                      <option value="">Not confirmed</option>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </label>
                ))}
                <label className="flex items-center justify-between gap-2">
                  Custody
                  <select
                    value={file.custody_type}
                    onChange={(e) => onPatch({ custody_type: e.target.value })}
                    className="rounded border border-slate-200 bg-transparent px-1 dark:border-slate-700"
                  >
                    <option value="judicial">Judicial</option>
                    <option value="police">Police</option>
                    <option value="released">Released</option>
                  </select>
                </label>
                {special ? (
                  <div className="flex flex-wrap items-center gap-2">
                    Extension order
                    <input
                      type="date"
                      value={order.order_date}
                      onChange={(e) => setOrder({ ...order, order_date: e.target.value })}
                      className="rounded border border-slate-200 bg-transparent px-1 dark:border-slate-700"
                    />
                    <input
                      placeholder="extended to (days)"
                      inputMode="numeric"
                      value={order.extended_to_days}
                      onChange={(e) => setOrder({ ...order, extended_to_days: e.target.value })}
                      className="w-32 rounded border border-slate-200 bg-transparent px-1 dark:border-slate-700"
                    />
                    <button
                      disabled={busy || !order.order_date || !order.extended_to_days}
                      onClick={onOrder}
                      className="text-indigo-700 hover:underline disabled:opacity-50 dark:text-indigo-300"
                    >
                      Record
                    </button>
                  </div>
                ) : null}
                <div className="mt-1 flex flex-wrap items-center gap-3">
                  <button
                    disabled={busy || !result || result.preview}
                    title={result?.preview ? "Unsigned punishment table entries can't be docketed" : undefined}
                    onClick={onDocket}
                    className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy ? "Saving…" : "Save to docket"}
                  </button>
                  {Object.entries(file.docket ?? {}).map(([kind, d]) => (
                    <span key={kind} className="text-slate-500">
                      {kind === "default_bail" ? "Default bail" : "s. 479"} docketed for {fmt(d.due_date)}
                      {d.done ? " (closed)" : ""}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
