"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

type FieldSpec = { key: string; label: string; type: string; required?: boolean; help?: string };
type Pack = { id: string; name: string; area: string; description: string; fields: FieldSpec[] };
type Deadline = { label: string; date: string; days_left: number; status: "done" | "missed" | "due_soon" | "upcoming"; basis: string };
type Outcome = {
  name: string;
  summary: string;
  deadlines: Deadline[];
  flags: { severity: string; message: string }[];
  next_steps: string[];
  checklist: string[];
  draft: { doc_type: string; facts: string; instructions: string } | null;
};

const field = "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const STATUS: Record<Deadline["status"], string> = {
  done: "border-slate-300 text-slate-500",
  missed: "border-red-500 text-red-700 dark:text-red-400",
  due_soon: "border-amber-500 text-amber-700 dark:text-amber-400",
  upcoming: "border-emerald-500 text-emerald-700 dark:text-emerald-400",
};

function when(d: Deadline) {
  if (d.status === "done") return "done";
  if (d.days_left < 0) return `${-d.days_left} days ago`;
  return d.days_left === 0 ? "today" : `in ${d.days_left} days`;
}

/** Matter packs: statutory deadlines computed in code, checklists, and a first draft. */
export function WorkflowsPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const router = useRouter();
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const [packs, setPacks] = useState<Pack[]>([]);
  const [packId, setPackId] = useState<string | null>(null);
  const [inputs, setInputs] = useState<Record<string, string | boolean>>({});
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pack = packs.find((p) => p.id === packId) ?? null;

  useEffect(() => {
    if (!orgId) return;
    api<Pack[]>("/api/v1/workflows", { token, orgId }).then(setPacks).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  function choose(id: string) {
    setPackId(id);
    setInputs({});
    setOutcome(null);
    setError(null);
  }

  async function evaluate(e: React.FormEvent) {
    e.preventDefault();
    if (!pack) return;
    setError(null);
    try {
      setOutcome(await api<Outcome>(`/api/v1/workflows/${pack.id}/evaluate`, { token, orgId, method: "POST", body: { inputs } }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function draft() {
    if (!outcome?.draft) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api<{ id: string }>("/api/v1/drafting/generate", {
        token,
        orgId,
        method: "POST",
        body: { ...outcome.draft, jurisdiction: "IN" },
      });
      router.push(`/studio?tab=drafts&draft=${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Workflows</h1>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-col gap-4 overflow-y-auto p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {packs.map((p) => (
            <button
              key={p.id}
              onClick={() => choose(p.id)}
              className={`rounded-xl border p-4 text-left ${
                p.id === packId
                  ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40"
                  : "border-slate-200 bg-white hover:border-indigo-300 dark:border-slate-800 dark:bg-slate-900"
              }`}
            >
              <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{p.area}</div>
              <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{p.name}</div>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{p.description}</p>
            </button>
          ))}
        </div>

        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}

        {pack ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <form onSubmit={evaluate} className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <h2 className="font-medium text-slate-900 dark:text-slate-100">{pack.name}</h2>
              {pack.fields.map((f) => (
                <label key={f.key} className="flex flex-col gap-1 text-sm">
                  <span className="text-slate-700 dark:text-slate-300">
                    {f.label}
                    {f.required ? <span className="text-red-600"> *</span> : null}
                  </span>
                  {f.type === "boolean" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(inputs[f.key])}
                      onChange={(e) => setInputs((v) => ({ ...v, [f.key]: e.target.checked }))}
                      className="h-4 w-4 accent-indigo-600"
                    />
                  ) : (
                    <input
                      className={field}
                      type={f.type === "date" ? "date" : "text"}
                      inputMode={f.type === "amount" || f.type === "number" ? "decimal" : undefined}
                      required={f.required}
                      value={String(inputs[f.key] ?? "")}
                      onChange={(e) => setInputs((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  )}
                  {f.help ? <span className="text-xs text-slate-500">{f.help}</span> : null}
                </label>
              ))}
              <button className="self-start rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">Work it out</button>
            </form>

            {outcome ? (
              <section className="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <p className="font-medium text-slate-900 dark:text-slate-100">{outcome.summary}</p>
                {outcome.flags.map((f, i) => (
                  <p key={i} className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
                    ⚠ {f.message}
                  </p>
                ))}
                {outcome.deadlines.length ? (
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Deadlines</h3>
                    <ol className="mt-2 flex flex-col gap-2">
                      {outcome.deadlines.map((d) => (
                        <li key={d.label} className={`border-l-4 pl-3 ${STATUS[d.status]}`}>
                          <div className="text-sm font-medium">
                            {new Date(d.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} · {d.label}{" "}
                            <span className="font-normal">({when(d)})</span>
                          </div>
                          <div className="text-xs text-slate-500">{d.basis}</div>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
                {outcome.next_steps.length ? (
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Next steps</h3>
                    <ul className="mt-2 list-disc pl-5 text-sm text-slate-700 dark:text-slate-300">
                      {outcome.next_steps.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Checklist</h3>
                  <ul className="mt-2 flex flex-col gap-1 text-sm text-slate-700 dark:text-slate-300">
                    {outcome.checklist.map((c) => (
                      <li key={c}>
                        <label className="flex items-start gap-2">
                          <input type="checkbox" className="mt-0.5 accent-indigo-600" /> {c}
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
                {outcome.draft ? (
                  <button
                    onClick={draft}
                    disabled={busy}
                    className="self-start rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy ? "Drafting…" : outcome.draft.doc_type === "bail_application" ? "Draft the bail application" : "Draft the notice"}
                  </button>
                ) : null}
                <p className="text-xs text-slate-500">Dates are computed from the statute; check them against the record before filing.</p>
              </section>
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}
