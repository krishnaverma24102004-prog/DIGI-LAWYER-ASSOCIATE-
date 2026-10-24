"use client";

import { useEffect, useState } from "react";

export type ConfirmFact = { label: string; value: string };

/**
 * Confirmation for an action that matters: says what will happen, who will see it and what it
 * costs, and for irreversible ones asks the user to type a word first.
 */
export function ConfirmDialog({
  title,
  facts,
  children,
  confirmLabel,
  danger = false,
  typed,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  facts?: ConfirmFact[];
  children?: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  typed?: string; // the word to type before confirming (irreversible actions)
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [entered, setEntered] = useState("");
  const ready = !typed || entered.trim().toUpperCase() === typed.toUpperCase();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onCancel()}>
      <form
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && !busy) onConfirm();
        }}
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl dark:bg-slate-900"
      >
        <h2 id="confirm-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h2>
        {children ? <div className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-300">{children}</div> : null}
        {facts?.length ? (
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/60">
            {facts.map((f) => (
              <div key={f.label} className="contents">
                <dt className="font-medium text-slate-500 dark:text-slate-400">{f.label}</dt>
                <dd className="text-slate-800 dark:text-slate-200">{f.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {typed ? (
          <label className="mt-3 block text-sm text-slate-700 dark:text-slate-300">
            Type <span className="font-mono font-semibold">{typed}</span> to confirm
            <input
              autoFocus
              value={entered}
              onChange={(e) => setEntered(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-sm dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
        ) : null}
        {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
            Cancel
          </button>
          <button
            type="submit"
            autoFocus={!typed}
            disabled={!ready || busy}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${
              danger ? "bg-red-600 hover:bg-red-700" : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

/** The question every Delete button asks: the record goes to the Trash for 30 days. */
export function deleteFacts(what: string, seniorNeeded: boolean): ConfirmFact[] {
  return [
    { label: "What happens", value: seniorNeeded ? `A partner or owner is asked to approve deleting this ${what}.` : `The ${what} moves to the Trash.` },
    { label: "Undo", value: "Restorable from Approvals & Trash for 30 days; erased after that." },
    { label: "Blocked if", value: "The matter is under legal hold." },
  ];
}
