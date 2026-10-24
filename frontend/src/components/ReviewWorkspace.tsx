"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ConfirmDialog, deleteFacts, type ConfirmFact } from "@/components/ConfirmDialog";
import { JurisdictionPicker } from "@/components/JurisdictionPicker";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api, type DeleteOutcome } from "@/lib/api";
import { API_URL } from "@/lib/config";
import { downloadWithAuth } from "@/lib/download";
import type { GoverningLaw, StoredDocument } from "@/lib/types";

type Question = { id: string; question: string; kind: string };
type NewQuestion = { question: string; kind: string };
type Cell = {
  document_id: string;
  question_id: string;
  status: "pending" | "done" | "error";
  answer: string | null;
  quote: string | null;
  verified: boolean | null;
  quote_match?: "exact" | "close" | null;
  quote_differs?: string[];
  jurisdiction_caveat?: string;
  confidence: "high" | "medium" | "low" | null;
  error: string | null;
};
type GridDocument = { id: string; filename: string; governing_law?: GoverningLaw };
type Grid = {
  id: string;
  title: string;
  questions: Question[];
  documents: GridDocument[];
  cells: Cell[];
  progress: { total: number; done: number; errors: number; verified: number };
};
type GridSummary = { id: string; title: string; document_ids: string[]; questions: Question[]; created_at: string };
type Preset = { name: string; questions: NewQuestion[] };
type Pending = { kind: "delete" } | { kind: "questions"; questions: NewQuestion[] } | { kind: "retry"; documents: number; questions: number };

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const button = "rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function aiFacts(documents: number, questions: number): ConfirmFact[] {
  return [
    { label: "What happens", value: `${plural(documents, "document")} × ${plural(questions, "question")} answered by AI.` },
    { label: "Cost", value: `One AI call per document (${documents} calls), counted toward your plan.` },
    { label: "Who sees it", value: "The documents are sent to the AI with identity numbers masked." },
  ];
}

/** Bulk review: many documents x the same questions; every answer with its source passage, checked. */
export function ReviewWorkspace({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId, jurisdiction } = workspace;
  const [grids, setGrids] = useState<GridSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadGrids = useCallback(() => {
    if (!orgId) return;
    api<GridSummary[]>("/api/v1/reviews", { token, orgId }).then(setGrids).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  useEffect(() => {
    loadGrids();
  }, [loadGrids]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Bulk Review</h1>
        <select aria-label="Organization" value={orgId ?? ""} onChange={(e) => workspace.setOrgId(e.target.value)} className={`${field} min-w-0`}>
          {workspace.orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <JurisdictionPicker value={jurisdiction} onChange={workspace.setJurisdiction} />
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside className="border-b border-slate-200 bg-white p-3 lg:w-64 lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-r dark:border-slate-800 dark:bg-slate-900">
          <button onClick={() => setSelected(null)} className={`${button} w-full`}>
            + New review
          </button>
          <ul className="mt-3 flex flex-col gap-1">
            {grids.map((g) => (
              <li key={g.id}>
                <button
                  onClick={() => setSelected(g.id)}
                  className={`w-full rounded-lg px-2.5 py-2 text-left text-sm ${
                    selected === g.id ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200" : "hover:bg-slate-100 dark:hover:bg-slate-800"
                  }`}
                >
                  <div className="truncate font-medium">{g.title}</div>
                  <div className="text-xs text-slate-500">
                    {g.document_ids.length} documents · {g.questions.length} questions
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="min-h-0 min-w-0 flex-1 overflow-auto p-4">
          {error ? <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
          {notice ? (
            <div className="mb-3 flex items-start gap-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
              <span className="flex-1">
                {notice}{" "}
                <Link href="/safety" className="font-medium underline">
                  Open Trash
                </Link>
              </span>
              <button onClick={() => setNotice(null)} aria-label="Dismiss" className="text-emerald-700 hover:text-emerald-900 dark:text-emerald-300">
                ✕
              </button>
            </div>
          ) : null}
          {selected && orgId ? (
            <GridView
              key={selected}
              token={token}
              orgId={orgId}
              gridId={selected}
              onDeleted={(message) => (setSelected(null), setNotice(message), loadGrids())}
            />
          ) : orgId ? (
            <NewReview token={token} orgId={orgId} jurisdiction={jurisdiction} onCreated={(id) => (loadGrids(), setNotice(null), setSelected(id))} />
          ) : null}
        </main>
      </div>
    </div>
  );
}

function NewReview({ token, orgId, jurisdiction, onCreated }: { token: string; orgId: string; jurisdiction: string; onCreated: (id: string) => void }) {
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [questions, setQuestions] = useState<NewQuestion[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<StoredDocument[]>("/api/v1/documents", { token, orgId }).then(setDocuments).catch((e: Error) => setError(e.message));
    api<Preset[]>("/api/v1/reviews/presets", { token, orgId }).then(setPresets).catch(() => undefined);
  }, [token, orgId]);

  async function upload(files: FileList) {
    setBusy(true);
    setError(null);
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_URL}/api/v1/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "X-Org-Id": orgId },
        body: form,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(`${file.name}: ${body.detail ?? "upload failed"}`);
        continue;
      }
      setDocuments((docs) => [body, ...docs]);
      setChosen((set) => new Set(set).add(body.id));
    }
    setBusy(false);
  }

  function toggle(id: string) {
    setChosen((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function addDraft() {
    const lines = draft.split("\n").map((l) => l.trim()).filter((l) => l.length >= 3);
    setQuestions((qs) => [...qs, ...lines.map((question) => ({ question, kind: "text" }))].slice(0, 15));
    setDraft("");
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const grid = await api<{ id: string }>("/api/v1/reviews", {
        token,
        orgId,
        method: "POST",
        body: { title: title.trim() || "Untitled review", document_ids: [...chosen], questions, jurisdiction },
      });
      onCreated(grid.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">New review</h2>
        <p className="text-sm text-slate-500">
          Ask the same questions of up to 50 documents. Every answer comes with the passage it rests on, checked against the document.
        </p>
      </div>
      {error && !confirming ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
      <input className={field} placeholder="Title, e.g. Pune leases due for renewal" value={title} onChange={(e) => setTitle(e.target.value)} />

      <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium text-slate-900 dark:text-slate-100">Documents ({chosen.size} selected)</h3>
          <label className="ml-auto cursor-pointer text-sm text-indigo-700 hover:underline dark:text-indigo-300">
            Upload PDFs
            <input type="file" multiple accept=".pdf,.txt,image/*" className="hidden" onChange={(e) => e.target.files && upload(e.target.files)} />
          </label>
        </div>
        <ul className="mt-2 max-h-56 overflow-y-auto">
          {documents.map((d) => (
            <li key={d.id}>
              <label className="flex items-center gap-2 py-1 text-sm">
                <input type="checkbox" checked={chosen.has(d.id)} onChange={() => toggle(d.id)} className="accent-indigo-600" />
                <span className="truncate">{d.filename}</span>
                <span className="ml-auto text-xs text-slate-400">{d.page_count ? `${d.page_count} pages` : ""}</span>
              </label>
            </li>
          ))}
          {documents.length === 0 ? <li className="py-2 text-sm text-slate-500">No documents yet: upload some.</li> : null}
        </ul>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium text-slate-900 dark:text-slate-100">Questions ({questions.length}/15)</h3>
          <select
            aria-label="Question set"
            className={`${field} ml-auto`}
            value=""
            onChange={(e) => {
              const preset = presets.find((p) => p.name === e.target.value);
              if (preset) setQuestions(preset.questions);
            }}
          >
            <option value="">Use a question set…</option>
            {presets.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-sm">
          {questions.map((q, i) => (
            <li key={`${q.question}-${i}`}>
              {q.question}{" "}
              <button onClick={() => setQuestions((qs) => qs.filter((_, j) => j !== i))} className="text-xs text-red-600 hover:underline">
                remove
              </button>
            </li>
          ))}
        </ol>
        <div className="mt-2 flex gap-2">
          <textarea
            className={`${field} min-h-16 flex-1`}
            placeholder="Add questions, one per line (e.g. What is the lock-in period?)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button onClick={addDraft} className="self-start rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700">
            Add
          </button>
        </div>
      </section>

      <button
        onClick={() => (chosen.size > 1 ? (setError(null), setConfirming(true)) : void start())}
        disabled={busy || chosen.size === 0 || questions.length === 0}
        className={`${button} self-start`}
      >
        {busy ? "Working…" : `Review ${plural(chosen.size, "document")}`}
      </button>
      {confirming ? (
        <ConfirmDialog
          title={`Review ${plural(chosen.size, "document")}?`}
          facts={aiFacts(chosen.size, questions.length)}
          confirmLabel="Start review"
          busy={busy}
          error={error}
          onConfirm={() => void start()}
          onCancel={() => (setConfirming(false), setError(null))}
        />
      ) : null}
    </div>
  );
}

// Built at runtime: the TS target (ES2017) rejects Unicode property escapes in regex literals.
const WORD = new RegExp("([\\p{L}\\p{M}\\p{N}]+(?:['’][\\p{L}\\p{M}\\p{N}]+)*)", "u");

/** The quote, with the words that differ from the document passage marked. */
function HighlightedQuote({ quote, differs }: { quote: string; differs: string[] | undefined }) {
  if (!differs?.length) return <>{quote}</>;
  const marked = new Set(differs.map((w) => w.toLowerCase()));
  return (
    <>
      {quote.split(WORD).map((part, i) =>
        i % 2 === 1 && marked.has(part.toLowerCase()) ? (
          <mark key={i} className="rounded bg-amber-200 px-0.5 text-inherit dark:bg-amber-500/30" title="Not in the document's wording">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function QuoteStatus({ cell, compact = false }: { cell: Cell; compact?: boolean }) {
  const pill = "rounded px-1.5 py-0.5 text-xs font-medium";
  if (cell.verified === false)
    return (
      <span className={`${pill} bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300`} title="The quoted passage was not found in the document: read it before relying on this">
        Not found in document
      </span>
    );
  if (cell.verified !== true) return null;
  if (cell.quote_match === "close")
    return (
      <span className={`${pill} bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300`} title="Close to the document's wording but not identical: check the marked words">
        {compact ? "Close – check" : "Close match – check"}
      </span>
    );
  return (
    <span className={`${pill} bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300`} title="The source passage was found word for word in the document">
      {compact ? "✓ Exact" : "Exact quote"}
    </span>
  );
}

function CaveatTag({ caveat }: { caveat: string | undefined }) {
  if (!caveat) return null;
  return (
    <span className="rounded border border-amber-300 px-1.5 py-0.5 text-xs text-amber-700 dark:border-amber-700 dark:text-amber-300" title={caveat}>
      Depends on governing law
    </span>
  );
}

function GoverningLawNote({ law }: { law: GoverningLaw | undefined }) {
  if (!law || (!law.detected && !law.mismatch)) return null;
  const tooltip = law.detected ? `${law.detected.basis === "clause" ? "Governing law clause" : "Courts clause"}: “${law.detected.quote}”` : undefined;
  if (law.mismatch)
    return (
      <div className="mt-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-normal text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200" title={tooltip}>
        ⚠ {law.caveat ?? `Governed by ${law.detected?.law ?? "a different law"}, not the review's jurisdiction.`}
      </div>
    );
  return (
    <div className="mt-1 text-xs font-normal text-slate-500" title={tooltip}>
      Governed by {law.detected?.law}
    </div>
  );
}

function CellView({ cell, onOpen }: { cell: Cell | undefined; onOpen: () => void }) {
  if (!cell || cell.status === "pending") return <span className="text-xs text-slate-400">Reviewing…</span>;
  if (cell.status === "error") return <span className="text-xs text-red-600">{cell.error ?? "Failed"}</span>;
  return (
    <button onClick={onOpen} className="block w-full text-left">
      <span className="text-sm text-slate-900 dark:text-slate-100">{cell.answer}</span>
      <span className="mt-1 flex flex-wrap gap-1">
        <QuoteStatus cell={cell} compact />
        <CaveatTag caveat={cell.jurisdiction_caveat} />
      </span>
    </button>
  );
}

function GridView({ token, orgId, gridId, onDeleted }: { token: string; orgId: string; gridId: string; onDeleted: (message: string) => void }) {
  const [grid, setGrid] = useState<Grid | null>(null);
  const [open, setOpen] = useState<Cell | null>(null);
  const [more, setMore] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Grid>(`/api/v1/reviews/${gridId}`, { token, orgId }).then(setGrid).catch((e: Error) => setError(e.message));
  }, [token, orgId, gridId]);

  const running = grid ? grid.progress.done + grid.progress.errors < grid.progress.total : true;
  useEffect(() => {
    load();
    if (!running) return;
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [load, running]);

  const cells = useMemo(() => new Map((grid?.cells ?? []).map((c) => [`${c.document_id}:${c.question_id}`, c])), [grid]);
  if (!grid) return <p className="text-sm text-slate-500">{error ?? "Loading…"}</p>;
  const questionText = (id: string) => grid.questions.find((q) => q.id === id)?.question;

  const failedCells = grid.cells.filter((c) => c.status === "error");
  const failedDocs = new Set(failedCells.map((c) => c.document_id)).size;
  const failedQuestions = new Set(failedCells.map((c) => c.question_id)).size;

  async function submitQuestions(questions: NewQuestion[]) {
    await api(`/api/v1/reviews/${gridId}/questions`, { token, orgId, method: "POST", body: { questions } });
    setMore("");
    load();
  }

  async function retryFailed() {
    await api(`/api/v1/reviews/${gridId}/retry`, { token, orgId, method: "POST" });
    load();
  }

  async function trash() {
    const outcome = await api<DeleteOutcome>(`/api/v1/reviews/${gridId}`, { token, orgId, method: "DELETE" });
    if (outcome.status === "trashed") onDeleted(outcome.message);
    else setNotice(outcome.message);
  }

  function addQuestions() {
    const questions = more.split("\n").map((l) => l.trim()).filter((l) => l.length >= 3).map((question) => ({ question, kind: "text" }));
    if (!questions.length) return;
    if (grid && grid.documents.length > 1) setPending({ kind: "questions", questions });
    else submitQuestions(questions).catch((e: Error) => setError(e.message));
  }

  function retry() {
    if (failedDocs > 1) setPending({ kind: "retry", documents: failedDocs, questions: failedQuestions });
    else retryFailed().catch((e: Error) => setError(e.message));
  }

  async function confirmPending() {
    if (!pending) return;
    setBusy(true);
    setDialogError(null);
    try {
      if (pending.kind === "delete") await trash();
      else if (pending.kind === "questions") await submitQuestions(pending.questions);
      else await retryFailed();
      setPending(null);
    } catch (e) {
      setDialogError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const dialog =
    pending?.kind === "delete"
      ? { title: "Delete this review?", facts: deleteFacts("review", false), confirmLabel: "Move to Trash" }
      : pending?.kind === "questions"
        ? {
            title: `Ask ${plural(pending.questions.length, "question")} of every document?`,
            facts: aiFacts(grid.documents.length, pending.questions.length),
            confirmLabel: "Add and run",
          }
        : pending?.kind === "retry"
          ? { title: "Retry the failed answers?", facts: aiFacts(pending.documents, pending.questions), confirmLabel: "Retry" }
          : null;

  const { progress } = grid;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{grid.title}</h2>
        <span className="text-sm text-slate-500">
          {progress.done}/{progress.total} answered · {progress.verified} with verified sources
          {progress.errors ? ` · ${progress.errors} failed` : ""}
        </span>
        <div className="ml-auto flex gap-2">
          {progress.errors ? (
            <button
              onClick={retry}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700"
            >
              Retry failed
            </button>
          ) : null}
          <button
            onClick={() => downloadWithAuth(`/api/v1/reviews/${gridId}/export`, token, orgId, "review.csv").catch((e: Error) => setError(e.message))}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700"
          >
            Export CSV
          </button>
          <button onClick={() => (setDialogError(null), setPending({ kind: "delete" }))} className="text-sm text-red-600 hover:underline">
            Delete
          </button>
        </div>
      </div>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {notice ? <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">{notice}</p> : null}

      <div className="overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="min-w-full border-collapse text-left text-sm">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-800/60">
              <th className="sticky left-0 z-10 min-w-48 border-b border-r border-slate-200 bg-slate-50 px-3 py-2 font-medium dark:border-slate-700 dark:bg-slate-800">
                Document
              </th>
              {grid.questions.map((q) => (
                <th key={q.id} className="min-w-56 border-b border-slate-200 px-3 py-2 font-medium dark:border-slate-700">
                  {q.question}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.documents.map((d) => (
              <tr key={d.id} className="align-top">
                <td className="sticky left-0 max-w-64 border-b border-r border-slate-200 bg-white px-3 py-2 font-medium dark:border-slate-700 dark:bg-slate-900">
                  {d.filename}
                  <GoverningLawNote law={d.governing_law} />
                </td>
                {grid.questions.map((q) => (
                  <td key={q.id} className="border-b border-slate-100 px-3 py-2 dark:border-slate-800">
                    <CellView cell={cells.get(`${d.id}:${q.id}`)} onOpen={() => setOpen(cells.get(`${d.id}:${q.id}`) ?? null)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{questionText(open.question_id)}</div>
              <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">{open.answer}</div>
              {open.quote ? (
                <blockquote
                  className={`mt-2 border-l-4 pl-3 text-slate-600 dark:text-slate-300 ${
                    open.verified === false ? "border-red-300 dark:border-red-700" : "border-slate-300 dark:border-slate-600"
                  }`}
                >
                  “<HighlightedQuote quote={open.quote} differs={open.verified === false ? undefined : open.quote_differs} />”
                </blockquote>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-1">
                <QuoteStatus cell={open} />
                <CaveatTag caveat={open.jurisdiction_caveat} />
              </div>
              {open.jurisdiction_caveat ? <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">{open.jurisdiction_caveat}</p> : null}
              <div className="mt-2 text-xs text-slate-500">
                {open.verified === true
                  ? open.quote_match === "close"
                    ? "A close match to the document's wording was found; the marked words differ, so check the passage."
                    : "Source passage found word for word in the document."
                  : open.verified === false
                    ? "The quoted passage was not found in the document: read the document before relying on this."
                    : "The document doesn't address this."}
                {open.confidence ? ` Confidence: ${open.confidence}.` : ""}
              </div>
            </div>
            <button onClick={() => setOpen(null)} className="text-slate-400 hover:text-slate-700">
              ✕
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex gap-2">
        <textarea
          className={`${field} min-h-12 flex-1`}
          placeholder="Ask another question of every document (one per line)"
          value={more}
          onChange={(e) => setMore(e.target.value)}
        />
        <button onClick={addQuestions} className={`${button} self-start`}>
          Add column
        </button>
      </div>

      {pending && dialog ? (
        <ConfirmDialog
          title={dialog.title}
          facts={dialog.facts}
          confirmLabel={dialog.confirmLabel}
          danger={pending.kind === "delete"}
          busy={busy}
          error={dialogError}
          onConfirm={() => void confirmPending()}
          onCancel={() => (setPending(null), setDialogError(null))}
        />
      ) : null}
    </div>
  );
}
