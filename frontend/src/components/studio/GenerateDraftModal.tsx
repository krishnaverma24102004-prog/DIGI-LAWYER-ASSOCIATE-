"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { CaseThread, Draft, DraftTemplate, StoredDocument } from "@/lib/types";

const DOC_TYPES: { value: string; label: string }[] = [
  { value: "legal_notice", label: "Legal notice / demand letter" },
  { value: "bail_application", label: "Bail application" },
  { value: "cease_and_desist", label: "Cease and desist" },
  { value: "nda", label: "Non-disclosure agreement" },
  { value: "affidavit", label: "Affidavit" },
];

function family(code: string): string {
  return code.startsWith("US") ? "US" : code;
}

/** One-click pleading generator: fills a template from the case session and documents. */
export function GenerateDraftModal({
  token,
  orgId,
  jurisdiction,
  initialThreadId,
  initialDocType,
  onClose,
  onGenerated,
}: {
  token: string;
  orgId: string | null;
  jurisdiction: string;
  initialThreadId: string | null;
  initialDocType: string | null;
  onClose: () => void;
  onGenerated: (draft: Draft) => void;
}) {
  const [docType, setDocType] = useState(initialDocType ?? "legal_notice");
  const [threadId, setThreadId] = useState(initialThreadId ?? "");
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [facts, setFacts] = useState("");
  const [instructions, setInstructions] = useState("");
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [templates, setTemplates] = useState<DraftTemplate[]>([]);
  const [threads, setThreads] = useState<CaseThread[]>([]);
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<DraftTemplate[]>("/api/v1/drafting/types", { token, orgId }).then(setTemplates).catch(() => undefined);
    if (!orgId) return;
    api<CaseThread[]>("/api/v1/case-threads?status=open", { token, orgId }).then(setThreads).catch(() => undefined);
    api<StoredDocument[]>("/api/v1/documents", { token, orgId }).then(setDocuments).catch(() => undefined);
  }, [token, orgId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const template = useMemo(() => {
    const candidates = templates.filter((t) => t.doc_type === docType);
    return candidates.find((t) => t.family === family(jurisdiction)) ?? candidates.find((t) => t.family === "*") ?? candidates[0];
  }, [templates, docType, jurisdiction]);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const draft = await api<Draft>("/api/v1/drafting/generate", {
        token,
        orgId,
        method: "POST",
        body: {
          doc_type: docType,
          jurisdiction,
          thread_id: threadId || null,
          document_ids: documentIds,
          facts: facts || null,
          instructions: instructions || null,
          variables: Object.fromEntries(Object.entries(variables).filter(([, v]) => v.trim())),
        },
      });
      onGenerated(draft);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="generate-title"
        onSubmit={generate}
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90dvh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-slate-900"
      >
        <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <h2 id="generate-title" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Generate a draft
          </h2>
          <p className="text-sm text-slate-500">Facts come from the case&apos;s sessions and documents. Anything unknown is left as a highlighted placeholder.</p>
        </div>

        <div className="flex flex-col gap-3 overflow-y-auto px-5 py-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Document
              <select className={field} value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Case (session context)
              <select className={field} value={threadId} onChange={(e) => setThreadId(e.target.value)}>
                <option value="">No case thread</option>
                {threads.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {template ? <p className="text-xs text-slate-500">Template: {template.name}</p> : null}

          {documents.length ? (
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-xs text-slate-500">Documents to draw on</legend>
              <div className="flex max-h-28 flex-col gap-1 overflow-y-auto rounded-lg border border-slate-200 p-2 dark:border-slate-700">
                {documents.map((d) => (
                  <label key={d.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={documentIds.includes(d.id)}
                      onChange={(e) => setDocumentIds((ids) => (e.target.checked ? [...ids, d.id] : ids.filter((x) => x !== d.id)).slice(0, 5))}
                    />
                    {d.filename}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}

          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Additional facts
            <textarea className={field} rows={3} value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="Anything not in the case file yet" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Instructions
            <input className={field} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="e.g. demand interest at 18% p.a.; firm but courteous tone" />
          </label>

          {template ? (
            <details>
              <summary className="cursor-pointer text-sm text-indigo-700 dark:text-indigo-300">Known details (override anything the AI finds)</summary>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {Object.entries(template.variables).map(([name, description]) => (
                  <label key={name} className="flex flex-col gap-1 text-xs text-slate-500">
                    {description}
                    <input className={field} value={variables[name] ?? ""} onChange={(e) => setVariables((v) => ({ ...v, [name]: e.target.value }))} />
                  </label>
                ))}
              </div>
            </details>
          ) : null}
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-sm text-slate-600 dark:text-slate-300">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60">
            {busy ? "Drafting…" : "Generate draft"}
          </button>
        </div>
      </form>
    </div>
  );
}
