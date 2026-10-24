"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { JurisdictionPicker } from "@/components/JurisdictionPicker";
import { ClauseEditor } from "@/components/studio/ClauseEditor";
import { GenerateDraftModal } from "@/components/studio/GenerateDraftModal";
import { RedlineViewer } from "@/components/studio/RedlineViewer";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";
import type { Draft, DraftSummary } from "@/lib/types";

type Tab = "redline" | "drafts";

const DOC_LABELS: Record<string, string> = {
  legal_notice: "Legal notice",
  bail_application: "Bail application",
  cease_and_desist: "Cease & desist",
  nda: "NDA",
  affidavit: "Affidavit",
  contract: "Contract",
};

/** Full-screen document studio: redline review, drafting, and the clause editor. */
export function DocumentStudio({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId, jurisdiction, setJurisdiction } = workspace;
  // Deep links from the consultation room: /studio?tab=drafts&generate=legal_notice&thread=<id>&jurisdiction=IN
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(() => (params.get("tab") === "drafts" || params.get("generate") || params.get("draft") ? "drafts" : "redline"));
  const [modal, setModal] = useState<{ threadId: string | null; docType: string | null } | null>(() =>
    params.get("generate") ? { threadId: params.get("thread"), docType: params.get("generate") } : null,
  );
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [active, setActive] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const linkedJurisdiction = params.get("jurisdiction");
  useEffect(() => {
    if (linkedJurisdiction) setJurisdiction(linkedJurisdiction);
  }, [linkedJurisdiction, setJurisdiction]);

  const loadDrafts = useCallback(() => {
    if (!orgId) return;
    api<DraftSummary[]>("/api/v1/drafting", { token, orgId }).then(setDrafts).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  useEffect(loadDrafts, [loadDrafts]);

  // /studio?draft=<id>: open a draft made elsewhere (e.g. by a workflow).
  const linkedDraft = params.get("draft");
  useEffect(() => {
    if (!linkedDraft || !orgId) return;
    api<Draft>(`/api/v1/drafting/${linkedDraft}`, { token, orgId })
      .then(setActive)
      .catch((e: Error) => setError(e.message));
  }, [linkedDraft, token, orgId]);

  async function open(id: string) {
    try {
      setActive(await api<Draft>(`/api/v1/drafting/${id}`, { token, orgId }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function opened(draft: Draft) {
    setActive(draft);
    setTab("drafts");
    setModal(null);
    loadDrafts();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Document Studio</h1>
        <select
          aria-label="Organization"
          value={orgId ?? ""}
          onChange={(e) => workspace.setOrgId(e.target.value)}
          className="min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
        >
          {workspace.orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <JurisdictionPicker value={jurisdiction} onChange={workspace.setJurisdiction} />
        <nav className="ml-auto flex items-center gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800" aria-label="Studio">
          {(["redline", "drafts"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              aria-current={tab === t ? "page" : undefined}
              className={`rounded-md px-3 py-1 text-sm ${tab === t ? "bg-white font-medium text-slate-900 shadow-sm dark:bg-slate-950 dark:text-white" : "text-slate-600 dark:text-slate-300"}`}
            >
              {t === "redline" ? "Redline" : "Drafts"}
            </button>
          ))}
        </nav>
        <button onClick={() => setModal({ threadId: null, docType: null })} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white">
          + New pleading
        </button>
        <button onClick={onSignOut} className="text-sm text-slate-500">
          Sign out
        </button>
      </header>
      {error || workspace.error ? <p className="px-4 py-2 text-sm text-red-600">{error ?? workspace.error}</p> : null}

      {tab === "redline" ? (
        <RedlineViewer token={token} orgId={orgId} jurisdiction={jurisdiction} onDraftCreated={opened} />
      ) : (
        <div className="grid min-h-0 flex-1 md:grid-cols-[240px_minmax(0,1fr)]">
          <aside className="min-h-0 overflow-y-auto border-r border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Drafts</h2>
            {drafts.length === 0 ? <p className="px-1 text-sm text-slate-400">No drafts yet.</p> : null}
            <ul className="flex flex-col gap-1">
              {drafts.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => open(d.id)}
                    className={`w-full rounded-lg px-2 py-1.5 text-left text-sm ${active?.id === d.id ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}
                  >
                    <div className="truncate font-medium">{d.title}</div>
                    <div className="text-xs text-slate-500">
                      {DOC_LABELS[d.doc_type] ?? d.doc_type}
                      {d.jurisdiction ? ` · ${d.jurisdiction}` : ""} · {d.status}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          {active ? (
            <ClauseEditor key={active.id} draft={active} token={token} orgId={orgId} onSaved={(d) => { setActive(d); loadDrafts(); }} />
          ) : (
            <div className="m-auto max-w-sm px-6 text-center text-sm text-slate-500">
              Open a draft, or generate a legal notice, bail application, cease and desist letter, NDA or affidavit from a case.
            </div>
          )}
        </div>
      )}

      {modal ? (
        <GenerateDraftModal
          token={token}
          orgId={orgId}
          jurisdiction={jurisdiction}
          initialThreadId={modal.threadId}
          initialDocType={modal.docType}
          onClose={() => setModal(null)}
          onGenerated={opened}
        />
      ) : null}
    </div>
  );
}
