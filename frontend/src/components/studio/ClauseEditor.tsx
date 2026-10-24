"use client";

import { useMemo, useState } from "react";

import { ExportChecklist, type ExportFormat, type UnresolvedChoice } from "@/components/studio/ExportChecklist";
import { api } from "@/lib/api";
import { downloadWithAuth } from "@/lib/download";
import type { ClauseRevisionResult, DiffOp, Draft, DraftChecklist, DraftContent } from "@/lib/types";

const PLACEHOLDER = /\[●[^●\]]*●\]/;
const APPROVAL_HINT = "Approval records that you reviewed this version. Saving any change to the title or a clause withdraws it.";

function jwtSub(token: string): string | null {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).sub ?? null;
  } catch {
    return null;
  }
}

function Suggestion({ ops }: { ops: DiffOp[] }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {ops.map((op, i) =>
        op.op === "equal" ? (
          <span key={i}>{op.text}</span>
        ) : op.op === "delete" ? (
          <del key={i} className="bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-200">
            {op.text}
          </del>
        ) : (
          <ins key={i} className="bg-emerald-100 text-emerald-900 no-underline dark:bg-emerald-950/60 dark:text-emerald-200">
            {op.text}
          </ins>
        ),
      )}
    </p>
  );
}

type Pending = { key: string; instruction: string; busy: boolean; result?: ClauseRevisionResult; error?: string };

/**
 * Clause-by-clause editor: edit text directly, or ask the AI to revise a clause and accept or
 * reject its proposal (shown as a redline). Placeholders still to fill are flagged.
 */
export function ClauseEditor({
  draft,
  token,
  orgId,
  onSaved,
}: {
  draft: Draft;
  token: string;
  orgId: string | null;
  onSaved: (draft: Draft) => void;
}) {
  const [title, setTitle] = useState(draft.title);
  const [content, setContent] = useState<DraftContent>(draft.content);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [approving, setApproving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<{ list: DraftChecklist; format: ExportFormat | null } | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const me = useMemo(() => jwtSub(token), [token]);
  const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

  function update(next: DraftContent) {
    setContent(next);
    setDirty(true);
  }

  function setParagraph(s: number, p: number, text: string) {
    update({
      ...content,
      sections: content.sections.map((sec, i) => (i === s ? { ...sec, paragraphs: sec.paragraphs.map((t, j) => (j === p ? text : t)) } : sec)),
    });
  }

  function removeParagraph(s: number, p: number) {
    update({
      ...content,
      sections: content.sections.map((sec, i) => (i === s ? { ...sec, paragraphs: sec.paragraphs.filter((_, j) => j !== p) } : sec)),
    });
  }

  function addParagraph(s: number, p: number) {
    update({
      ...content,
      sections: content.sections.map((sec, i) =>
        i === s ? { ...sec, paragraphs: [...sec.paragraphs.slice(0, p + 1), "", ...sec.paragraphs.slice(p + 1)] } : sec,
      ),
    });
  }

  async function revise(s: number, p: number) {
    if (!pending?.instruction.trim()) return;
    setPending({ ...pending, busy: true, error: undefined });
    try {
      const neighbours = content.sections[s].paragraphs.filter((_, j) => j !== p).join("\n").slice(0, 4000);
      const result = await api<ClauseRevisionResult>("/api/v1/drafting/revise-clause", {
        token,
        orgId,
        method: "POST",
        body: { text: content.sections[s].paragraphs[p], instruction: pending.instruction, jurisdiction: draft.jurisdiction, context: neighbours },
      });
      setPending({ ...pending, busy: false, result });
    } catch (e) {
      setPending({ ...pending, busy: false, error: e instanceof Error ? e.message : String(e) });
    }
  }

  const reload = () => api<Draft>(`/api/v1/drafting/${draft.id}`, { token, orgId });

  async function save(status?: "draft" | "final"): Promise<boolean> {
    setSaving(true);
    setMessage(null);
    try {
      await api<Draft>(`/api/v1/drafting/${draft.id}`, {
        token,
        orgId,
        method: "PATCH",
        body: { title, content, ...(status ? { status } : {}) },
      });
      // The server withdraws approval when content changes; reload so the pill shows it.
      const fresh = await reload();
      setDirty(false);
      onSaved(fresh);
      setMessage(draft.approved_at && !fresh.approved_at ? "Saved · approval withdrawn" : "Saved");
      return true;
    } catch (e) {
      setMessage(errorText(e));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function changeApproval(approve: boolean): Promise<boolean> {
    if (approve && dirty && !(await save())) return false;
    await api(`/api/v1/drafting/${draft.id}/approve`, { token, orgId, method: approve ? "POST" : "DELETE" });
    onSaved(await reload());
    return true;
  }

  async function toggleApproval(approve: boolean) {
    setApproving(true);
    setMessage(null);
    try {
      if (await changeApproval(approve)) setMessage(approve ? "Approved" : "Approval withdrawn");
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setApproving(false);
    }
  }

  function download(format: ExportFormat, unresolved: UnresolvedChoice) {
    return downloadWithAuth(`/api/v1/drafting/${draft.id}/export?format=${format}&unresolved=${unresolved}`, token, orgId, `draft.${format}`);
  }

  /** Fetches the checklist first; exports straight away only when approved and nothing is open. */
  async function openChecklist(format: ExportFormat | null) {
    setChecking(true);
    setMessage(null);
    try {
      if (dirty && !(await save())) return;
      const list = await api<DraftChecklist>(`/api/v1/drafting/${draft.id}/checklist`, { token, orgId });
      if (format && list.clear && list.approved) {
        await download(format, "keep");
      } else {
        setCheckError(null);
        setCheck({ list, format });
      }
    } catch (e) {
      setMessage(errorText(e));
    } finally {
      setChecking(false);
    }
  }

  async function exportChecked(format: ExportFormat, unresolved: UnresolvedChoice, approveFirst: boolean) {
    setCheckBusy(true);
    setCheckError(null);
    try {
      if (approveFirst && !(await changeApproval(true))) return;
      await download(format, unresolved);
      setCheck(null);
    } catch (e) {
      setCheckError(errorText(e));
    } finally {
      setCheckBusy(false);
    }
  }

  async function approveChecked() {
    setCheckBusy(true);
    setCheckError(null);
    try {
      if (await changeApproval(true)) setCheck((c) => c && { ...c, list: { ...c.list, approved: true } });
    } catch (e) {
      setCheckError(errorText(e));
    } finally {
      setCheckBusy(false);
    }
  }

  const approvedAt = draft.approved_at ? new Date(draft.approved_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : null;
  const approver = draft.approved_by && draft.approved_by === me ? "you" : (draft.approved_by?.slice(0, 8) ?? "a lawyer");

  const missing = draft.missing;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <input
          aria-label="Title"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setDirty(true);
          }}
          className="min-w-0 flex-1 rounded-md bg-transparent px-1 text-base font-semibold text-slate-900 outline-none focus:ring-2 focus:ring-indigo-500/30 dark:text-slate-100"
        />
        <span className={`rounded-full px-2 py-0.5 text-[11px] ${draft.status === "final" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
          {draft.status}
        </span>
        {approvedAt ? (
          <span title={APPROVAL_HINT} className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200">
            ✓ Approved by {approver} on {approvedAt}
            {dirty ? " · saving edits withdraws it" : ""}
          </span>
        ) : (
          <span title={APPROVAL_HINT} className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
            AI draft · unreviewed
          </span>
        )}
        {message ? <span className="text-xs text-slate-500">{message}</span> : null}
        {approvedAt ? (
          <button onClick={() => toggleApproval(false)} disabled={approving} title={APPROVAL_HINT} className="px-1 text-sm text-slate-500 hover:text-slate-800 disabled:opacity-40 dark:hover:text-slate-200">
            Withdraw approval
          </button>
        ) : (
          <button
            onClick={() => toggleApproval(true)}
            disabled={approving || saving}
            title={APPROVAL_HINT}
            className="rounded-lg border border-emerald-500 px-3 py-1.5 text-sm text-emerald-700 disabled:opacity-40 dark:text-emerald-300"
          >
            {approving ? "Approving…" : "Approve"}
          </button>
        )}
        <button onClick={() => save()} disabled={!dirty || saving} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-slate-600">
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={() => openChecklist(null)} disabled={checking} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-slate-600">
          Check draft
        </button>
        <button onClick={() => openChecklist("docx")} disabled={checking} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          Export .docx
        </button>
        <button onClick={() => openChecklist("pdf")} disabled={checking} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-slate-600">
          PDF
        </button>
      </div>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-h-0 overflow-y-auto px-4 py-5">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            {content.sections.map((section, s) => (
              <section key={s} className="flex flex-col gap-2">
                {section.heading ? <h3 className="font-semibold text-slate-900 dark:text-slate-100">{section.heading}</h3> : null}
                {section.paragraphs.map((text, p) => {
                  const key = `${s}-${p}`;
                  const open = pending?.key === key;
                  const needsInput = PLACEHOLDER.test(text);
                  return (
                    <div key={key} className={`group rounded-lg border-l-4 pl-2 ${needsInput ? "border-amber-400" : "border-transparent hover:border-slate-200 dark:hover:border-slate-700"}`}>
                      <textarea
                        aria-label={`Clause ${s + 1}.${p + 1}`}
                        value={text}
                        onChange={(e) => setParagraph(s, p, e.target.value)}
                        className="field-sizing-content w-full resize-none rounded-md bg-transparent p-1 text-[15px] leading-relaxed text-slate-800 outline-none focus:bg-slate-50 dark:text-slate-200 dark:focus:bg-slate-800/50"
                      />
                      <div className="flex gap-3 pb-1 text-xs text-slate-400 opacity-100 group-focus-within:opacity-100 md:opacity-0 md:group-hover:opacity-100">
                        {needsInput ? <span className="text-amber-600">Needs input</span> : null}
                        <button onClick={() => setPending(open ? null : { key, instruction: "", busy: false })} className="hover:text-violet-600">
                          Revise with AI
                        </button>
                        <button onClick={() => addParagraph(s, p)} className="hover:text-slate-700">
                          Add paragraph
                        </button>
                        <button onClick={() => removeParagraph(s, p)} className="hover:text-red-600">
                          Delete
                        </button>
                      </div>
                      {open && pending ? (
                        <div className="mb-2 rounded-lg border border-violet-200 bg-violet-50 p-2 dark:border-violet-900 dark:bg-violet-950/40">
                          {pending.result ? (
                            <>
                              <Suggestion ops={pending.result.inline_diff} />
                              <p className="mt-1 text-xs text-slate-500">{pending.result.explanation}</p>
                              <div className="mt-2 flex gap-2">
                                <button
                                  onClick={() => {
                                    setParagraph(s, p, pending.result!.revised_text);
                                    setPending(null);
                                  }}
                                  className="rounded bg-violet-600 px-2.5 py-1 text-xs text-white"
                                >
                                  Accept
                                </button>
                                <button onClick={() => setPending(null)} className="rounded border border-slate-300 px-2.5 py-1 text-xs dark:border-slate-600">
                                  Reject
                                </button>
                              </div>
                            </>
                          ) : (
                            <form
                              onSubmit={(e) => {
                                e.preventDefault();
                                revise(s, p);
                              }}
                              className="flex gap-2"
                            >
                              <input
                                autoFocus
                                value={pending.instruction}
                                onChange={(e) => setPending({ ...pending, instruction: e.target.value })}
                                placeholder="e.g. make the demand firmer, add interest at 12% p.a."
                                className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900"
                              />
                              <button disabled={pending.busy || !pending.instruction.trim()} className="rounded-md bg-violet-600 px-3 py-1 text-sm text-white disabled:opacity-50">
                                {pending.busy ? "Revising…" : "Revise"}
                              </button>
                            </form>
                          )}
                          {pending.error ? <p className="mt-1 text-xs text-red-600">{pending.error}</p> : null}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </section>
            ))}
            {content.signature_block.length ? (
              <div className="mt-6 text-right text-sm text-slate-700 dark:text-slate-300">
                {content.signature_block.map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <aside className="hidden min-h-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4 lg:block dark:border-slate-800 dark:bg-slate-950">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Still needed</h4>
          {missing.length ? (
            <ul className="flex flex-col gap-1.5 text-sm text-slate-700 dark:text-slate-300">
              {missing.map((m) => (
                <li key={m} className="rounded-md border-l-4 border-amber-400 bg-white px-2 py-1 dark:bg-slate-900">
                  {m}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-emerald-600">Nothing missing.</p>
          )}
          <button onClick={() => save("final")} disabled={saving} className="mt-4 w-full rounded-lg border border-emerald-500 px-3 py-1.5 text-sm text-emerald-700 dark:text-emerald-300">
            Mark as final
          </button>
          <p className="mt-3 text-xs text-slate-500">AI drafts must be reviewed by a licensed lawyer before they are sent or filed.</p>
        </aside>
      </div>

      {check ? (
        <ExportChecklist
          checklist={check.list}
          format={check.format}
          busy={checkBusy}
          error={checkError}
          onApprove={approveChecked}
          onExport={exportChecked}
          onClose={() => setCheck(null)}
        />
      ) : null}
    </div>
  );
}
