"use client";

import { useEffect, useState } from "react";

import type { DraftChecklist, DraftMismatch } from "@/lib/types";

export type ExportFormat = "docx" | "pdf";
export type UnresolvedChoice = "keep" | "remove";

const MISMATCH_LABELS: Record<DraftMismatch["kind"], string> = {
  amount: "Amount",
  date: "Date",
  reference: "Reference",
  provided_value: "Value",
};

function Heading({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {children}
      {count !== undefined ? <span className="ml-1.5 font-normal normal-case text-slate-400">({count})</span> : null}
    </h3>
  );
}

/**
 * What to look at before a draft leaves the firm: citations the check couldn't confirm, values
 * not found in the confirmed facts, unfilled placeholders and whether a lawyer has approved it.
 * Never blocks the export. With no `format` it is a plain "Check draft" view that can still export.
 */
export function ExportChecklist({
  checklist,
  format,
  busy,
  error,
  onApprove,
  onExport,
  onClose,
}: {
  checklist: DraftChecklist;
  format: ExportFormat | null;
  busy: boolean;
  error: string | null;
  onApprove: () => void;
  onExport: (format: ExportFormat, unresolved: UnresolvedChoice, approveFirst: boolean) => void;
  onClose: () => void;
}) {
  const [unresolved, setUnresolved] = useState<UnresolvedChoice>("keep");
  const { approved, unresolved_citations: citations, mismatches, missing } = checklist;
  const formats: ExportFormat[] = format ? [format] : ["docx", "pdf"];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="checklist-title"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl bg-white shadow-xl dark:bg-slate-900"
      >
        <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <h2 id="checklist-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {format ? `Before exporting .${format}` : "Draft check"}
          </h2>
          {checklist.clear ? <p className="mt-1 text-sm text-emerald-600">No open points found.</p> : null}
        </div>

        <div className="flex min-h-0 flex-col gap-5 overflow-y-auto px-5 py-4 text-sm">
          <section>
            <Heading>Review</Heading>
            {approved ? (
              <p className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">Approved by a lawyer.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <span className="flex-1">Not approved yet. The export will be marked “AI draft · unreviewed” on every page.</span>
                {!format ? (
                  <button onClick={onApprove} disabled={busy} className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">
                    Approve
                  </button>
                ) : null}
              </div>
            )}
          </section>

          {citations.length ? (
            <section>
              <Heading count={citations.length}>Citations not confirmed</Heading>
              <ul className="flex flex-col gap-1.5">
                {citations.map((c, i) => (
                  <li key={`${c.text}-${i}`} className="rounded-md border-l-4 border-red-400 bg-slate-50 px-2.5 py-1.5 dark:bg-slate-800/60">
                    <div className="font-medium text-slate-800 dark:text-slate-200">{c.text}</div>
                    <div className="text-xs text-slate-500">
                      {c.label ?? c.status}
                      {c.note ? ` · ${c.note}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
              <div role="radiogroup" aria-label="Unconfirmed citations" className="mt-2 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
                {(
                  [
                    ["keep", "Keep them"],
                    ["remove", "Replace with a placeholder"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    role="radio"
                    aria-checked={unresolved === value}
                    onClick={() => setUnresolved(value)}
                    className={`rounded-md px-2 py-1.5 text-xs ${unresolved === value ? "bg-white font-medium text-slate-900 shadow-sm dark:bg-slate-950 dark:text-white" : "text-slate-600 dark:text-slate-300"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {unresolved === "remove" ? <p className="mt-1 text-xs text-slate-500">Each becomes “[●citation to be confirmed●]” in the exported file.</p> : null}
            </section>
          ) : null}

          <section>
            <Heading count={checklist.fact_basis_recorded ? mismatches.length : undefined}>Check before sending</Heading>
            {!checklist.fact_basis_recorded ? (
              <p className="text-slate-500">Self-check of facts isn’t available for this draft (written by hand, with no recorded facts to compare).</p>
            ) : mismatches.length ? (
              <ul className="flex flex-col gap-1.5">
                {mismatches.map((m, i) => (
                  <li key={`${m.value}-${i}`} className="rounded-md border-l-4 border-amber-400 bg-slate-50 px-2.5 py-1.5 dark:bg-slate-800/60">
                    <div className="text-slate-800 dark:text-slate-200">{m.message}</div>
                    <div className="text-xs text-slate-500">
                      {MISMATCH_LABELS[m.kind]}: <span className="font-mono">{m.value}</span>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-emerald-600">Amounts, dates and references match the confirmed facts.</p>
            )}
          </section>

          {missing.length ? (
            <section>
              <Heading count={missing.length}>Still to fill in</Heading>
              <ul className="flex flex-col gap-1">
                {missing.map((m) => (
                  <li key={m} className="rounded-md border-l-4 border-amber-400 bg-slate-50 px-2.5 py-1 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                    {m}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {error ? <p className="text-red-600">{error}</p> : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          <button onClick={onClose} disabled={busy} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
            {format ? "Cancel" : "Close"}
          </button>
          {formats.map((f) =>
            approved ? (
              <button key={f} onClick={() => onExport(f, unresolved, false)} disabled={busy} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                {busy ? "Working…" : `Export .${f}`}
              </button>
            ) : (
              <div key={f} className="flex gap-2">
                <button
                  onClick={() => onExport(f, unresolved, false)}
                  disabled={busy}
                  className="rounded-lg border border-amber-400 px-3 py-1.5 text-sm text-amber-800 disabled:opacity-50 dark:text-amber-200"
                >
                  Export .{f} as unreviewed
                </button>
                {format ? (
                  <button onClick={() => onExport(f, unresolved, true)} disabled={busy} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
                    {busy ? "Working…" : "Approve and export"}
                  </button>
                ) : null}
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
}
