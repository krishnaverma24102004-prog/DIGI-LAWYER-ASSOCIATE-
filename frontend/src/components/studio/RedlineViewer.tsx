"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { API_URL } from "@/lib/config";
import type { ClauseChange, ClauseRevisionResult, CompareReport, DiffOp, Draft, GoverningLaw, StoredDocument } from "@/lib/types";

type Choice = "revised" | "original" | "counter" | "custom";
type Decision = { choice: Choice; text?: string };

const IMPACT_STYLE = {
  increased: "bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-300",
  decreased: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300",
  neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
};
const DELTA_STYLE: Record<string, string> = {
  Increased: "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200",
  Decreased: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
  Neutral: "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
  "Not analyzed": "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200",
};

/** One side of a redline: the original keeps deletions (red), the revision keeps insertions (green). */
function DiffText({ ops, side }: { ops: DiffOp[]; side: "original" | "revised" }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
      {ops.map((op, i) =>
        op.op === "equal" ? (
          <span key={i}>{op.text}</span>
        ) : op.op === "delete" && side === "original" ? (
          <del key={i} className="rounded-sm bg-red-100 text-red-800 decoration-red-500 dark:bg-red-950/60 dark:text-red-200">
            {op.text}
          </del>
        ) : op.op === "insert" && side === "revised" ? (
          <ins key={i} className="rounded-sm bg-emerald-100 text-emerald-900 no-underline dark:bg-emerald-950/60 dark:text-emerald-200">
            {op.text}
          </ins>
        ) : null,
      )}
    </p>
  );
}

type DetectedLaw = NonNullable<GoverningLaw["detected"]>;

const lawKey = (d: DetectedLaw) => (d.code ?? d.law).trim().toLowerCase();

function LawLine({ label, gov }: { label: string; gov: GoverningLaw }) {
  const d = gov.detected;
  if (!d) return <li>{label}: no governing-law clause found</li>;
  return (
    <li>
      {label}: governed by{" "}
      <span title={`“${d.quote}”`} className="cursor-help font-medium underline decoration-dotted underline-offset-2">
        {d.law}
      </span>{" "}
      ({d.basis === "clause" ? "clause" : "inferred from courts clause"}){gov.mismatch ? " — differs from the selected jurisdiction" : ""}
    </li>
  );
}

function GoverningLawBanner({ report }: { report: CompareReport }) {
  const gl = report.governing_law;
  if (!gl) return null;
  const o = gl.original.detected;
  const r = gl.revised.detected;
  const change =
    o && r && lawKey(o) !== lawKey(r)
      ? `The revision changes the governing law from ${o.law} to ${r.law}.`
      : o && !r
        ? `The revision removes the governing-law clause (the original named ${o.law}).`
        : !o && r
          ? `The revision adds a governing-law clause naming ${r.law}.`
          : null;

  if (report.jurisdiction_caveat || change) {
    return (
      <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        {change ? <p className="font-semibold">{change}</p> : null}
        {report.jurisdiction_caveat ? <p className={change ? "mt-1" : "font-medium"}>{report.jurisdiction_caveat}</p> : null}
        <ul className="mt-1.5 flex flex-col gap-0.5 text-xs">
          <LawLine label="Original" gov={gl.original} />
          <LawLine label="Revised" gov={gl.revised} />
        </ul>
      </div>
    );
  }

  const d = r ?? o;
  if (!d) return <p className="mb-3 text-xs text-slate-400">No governing-law clause found.</p>;
  const selected = gl.revised.selected ?? gl.original.selected;
  return (
    <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
      Governed by{" "}
      <span title={`“${d.quote}”`} className="cursor-help underline decoration-dotted underline-offset-2">
        {d.law}
      </span>
      {selected && !gl.original.mismatch && !gl.revised.mismatch ? " — matches the selected jurisdiction" : ""}
    </p>
  );
}

// By default the counterparty's change is accepted; the lawyer changes what they disagree with.
function defaultDecision(): Decision {
  return { choice: "revised" };
}

/** The clause text that goes into the negotiated version, or null if the clause is dropped. */
function finalText(c: ClauseChange, d: Decision): string | null {
  switch (d.choice) {
    case "revised":
      return c.revised_text;
    case "original":
      return c.original_text;
    case "counter":
      return c.analysis?.recommended_counter_clause ?? c.revised_text;
    case "custom":
      return d.text ?? c.revised_text;
  }
}

function ClauseCard({
  change,
  decision,
  onDecide,
  token,
  orgId,
  jurisdiction,
}: {
  change: ClauseChange;
  decision: Decision;
  onDecide: (d: Decision) => void;
  token: string;
  orgId: string | null;
  jurisdiction: string;
}) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestion, setSuggestion] = useState<ClauseRevisionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCaveat, setShowCaveat] = useState(false);
  const a = change.analysis;

  async function askAI(e: React.FormEvent) {
    e.preventDefault();
    if (!instruction.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setSuggestion(
        await api<ClauseRevisionResult>("/api/v1/drafting/revise-clause", {
          token,
          orgId,
          method: "POST",
          body: { text: finalText(change, decision) ?? change.original_text ?? "", instruction, jurisdiction },
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const options: { choice: Choice; label: string }[] =
    change.status === "deleted"
      ? [
          { choice: "revised", label: "Accept deletion" },
          { choice: "original", label: "Restore clause" },
        ]
      : [
          { choice: "revised", label: change.status === "added" ? "Accept addition" : "Accept revision" },
          { choice: "original", label: change.status === "added" ? "Reject addition" : "Keep original" },
          ...(a?.recommended_counter_clause ? [{ choice: "counter" as Choice, label: "Use counter-clause" }] : []),
        ];

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
      {a ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase ${IMPACT_STYLE[a.risk_impact]}`}>
              Risk {a.risk_impact}
            </span>
            <span className="text-[11px] uppercase text-slate-500">{a.severity}</span>
            {a.categories.map((cat) => (
              <span key={cat} className="rounded border border-slate-200 px-1 text-[11px] text-slate-500 dark:border-slate-700">
                {cat.replaceAll("_", " ")}
              </span>
            ))}
            {change.jurisdiction_caveat ? (
              <button
                type="button"
                title={change.jurisdiction_caveat}
                aria-expanded={showCaveat}
                onClick={() => setShowCaveat((v) => !v)}
                className="rounded border border-amber-300 bg-amber-50 px-1.5 text-[11px] font-medium text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
              >
                Depends on governing law
              </button>
            ) : null}
          </div>
          <p className="font-medium text-slate-900 dark:text-slate-100">{a.change_summary}</p>
          <p className="text-slate-600 dark:text-slate-300">{a.explanation}</p>
          {change.jurisdiction_caveat && showCaveat ? (
            <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">{change.jurisdiction_caveat}</p>
          ) : null}
          {a.recommended_counter_clause ? (
            <details className="rounded-lg bg-indigo-50 p-2 dark:bg-indigo-950/40">
              <summary className="cursor-pointer text-xs font-medium text-indigo-700 dark:text-indigo-300">Suggested counter-clause</summary>
              <p className="mt-1 whitespace-pre-wrap text-slate-700 dark:text-slate-200">{a.recommended_counter_clause}</p>
            </details>
          ) : null}
        </>
      ) : (
        <p className="text-slate-500">No AI analysis for this clause.</p>
      )}

      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Decision">
        {options.map((o) => (
          <button
            key={o.choice}
            role="radio"
            aria-checked={decision.choice === o.choice}
            onClick={() => onDecide({ choice: o.choice })}
            className={`rounded-full border px-2.5 py-1 text-xs ${
              decision.choice === o.choice
                ? "border-indigo-600 bg-indigo-600 text-white"
                : "border-slate-300 text-slate-600 hover:border-slate-400 dark:border-slate-600 dark:text-slate-300"
            }`}
          >
            {o.label}
          </button>
        ))}
        {decision.choice === "custom" ? <span className="rounded-full bg-violet-600 px-2.5 py-1 text-xs text-white">AI revision</span> : null}
      </div>

      {change.status !== "deleted" ? (
        <form onSubmit={askAI} className="flex gap-1.5">
          <input
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="Ask AI to revise, e.g. “cap liability at fees paid”"
            className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-transparent px-2 py-1 text-xs dark:border-slate-600"
          />
          <button disabled={busy || !instruction.trim()} className="rounded-lg bg-violet-600 px-2.5 py-1 text-xs text-white disabled:opacity-50">
            {busy ? "…" : "Revise"}
          </button>
        </form>
      ) : null}
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
      {suggestion ? (
        <div className="rounded-lg border border-violet-200 bg-violet-50 p-2 dark:border-violet-900 dark:bg-violet-950/40">
          <DiffText ops={suggestion.inline_diff} side="revised" />
          <p className="mt-1 text-xs text-slate-500">{suggestion.explanation}</p>
          <div className="mt-1.5 flex gap-1.5">
            <button
              onClick={() => {
                onDecide({ choice: "custom", text: suggestion.revised_text });
                setSuggestion(null);
                setInstruction("");
              }}
              className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white"
            >
              Accept
            </button>
            <button onClick={() => setSuggestion(null)} className="rounded border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-600">
              Discard
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function RedlineViewer({
  token,
  orgId,
  jurisdiction,
  onDraftCreated,
}: {
  token: string;
  orgId: string | null;
  jurisdiction: string;
  onDraftCreated: (draft: Draft) => void;
}) {
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [originalId, setOriginalId] = useState("");
  const [revisedId, setRevisedId] = useState("");
  const [ourSide, setOurSide] = useState("");
  const [report, setReport] = useState<CompareReport | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [showUnchanged, setShowUnchanged] = useState(false);
  const [busy, setBusy] = useState<"compare" | "save" | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!orgId) return;
    api<StoredDocument[]>("/api/v1/documents", { token, orgId }).then(setDocuments).catch((e: Error) => setError(e.message));
  }, [token, orgId]);

  async function upload(file: File) {
    setBusy("upload");
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
      if (orgId) headers["X-Org-Id"] = orgId;
      const res = await fetch(`${API_URL}/api/v1/documents/upload`, { method: "POST", headers, body: form });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? "Upload failed");
      setDocuments((docs) => [body, ...docs]);
      if (!originalId) setOriginalId(body.id);
      else setRevisedId(body.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function compare() {
    setBusy("compare");
    setError(null);
    try {
      const result = await api<CompareReport>("/api/v1/documents/compare", {
        token,
        orgId,
        method: "POST",
        body: { original_document_id: originalId, revised_document_id: revisedId, jurisdiction, our_side: ourSide || undefined },
      });
      setReport(result);
      setDecisions(Object.fromEntries(result.clauses.map((c) => [c.id, defaultDecision()])));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const visible = useMemo(
    () => report?.clauses.filter((c) => showUnchanged || (c.status !== "unchanged" && c.status !== "renumbered")) ?? [],
    [report, showUnchanged],
  );

  async function saveNegotiated() {
    if (!report) return;
    setBusy("save");
    try {
      const paragraphs = report.clauses
        .map((c) => (c.status === "unchanged" || c.status === "renumbered" ? c.revised_text : finalText(c, decisions[c.id] ?? defaultDecision())))
        .filter((t): t is string => Boolean(t && t.trim()));
      const draft = await api<Draft>("/api/v1/drafting", {
        token,
        orgId,
        method: "POST",
        body: {
          title: `Negotiated – ${report.revised.filename}`,
          doc_type: "contract",
          jurisdiction,
          content: { sections: [{ heading: null, paragraphs }], signature_block: [] },
        },
      });
      onDraftCreated(draft);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  const field = "min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-end gap-2 border-b border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
        <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-xs text-slate-500">
          Original (our draft)
          <select className={field} value={originalId} onChange={(e) => setOriginalId(e.target.value)}>
            <option value="">Choose a document…</option>
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-xs text-slate-500">
          Revised (their markup)
          <select className={field} value={revisedId} onChange={(e) => setRevisedId(e.target.value)}>
            <option value="">Choose a document…</option>
            {documents.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-[140px] flex-col gap-1 text-xs text-slate-500">
          We act for
          <input className={field} value={ourSide} onChange={(e) => setOurSide(e.target.value)} placeholder="e.g. the Tenant" />
        </label>
        <input ref={fileRef} type="file" hidden accept=".pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <button onClick={() => fileRef.current?.click()} disabled={busy !== null} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-600">
          {busy === "upload" ? "Uploading…" : "Upload"}
        </button>
        <button
          onClick={compare}
          disabled={!originalId || !revisedId || originalId === revisedId || busy !== null}
          className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy === "compare" ? "Analysing…" : "Compare"}
        </button>
      </div>

      {error ? <p className="px-4 py-2 text-sm text-red-600">{error}</p> : null}

      {!report ? (
        <div className="m-auto max-w-md px-6 text-center text-sm text-slate-500">
          Choose your draft and the counterparty&apos;s revision. Each changed clause is shown side by side with the AI&apos;s risk
          assessment, and you decide clause by clause what goes into the negotiated version.
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <GoverningLawBanner report={report} />
          <div className={`mb-4 rounded-xl border p-4 ${DELTA_STYLE[report.risk_delta]}`}>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-lg font-semibold">Risk {report.risk_delta.toLowerCase()}</span>
              <span className="text-sm opacity-80">
                score {report.risk_score > 0 ? "+" : ""}
                {report.risk_score} · {report.stats.modified} modified · {report.stats.added} added · {report.stats.deleted} deleted
              </span>
              <div className="ml-auto flex items-center gap-2">
                <label className="flex items-center gap-1 text-sm">
                  <input type="checkbox" checked={showUnchanged} onChange={(e) => setShowUnchanged(e.target.checked)} />
                  Show unchanged
                </label>
                <button onClick={saveNegotiated} disabled={busy !== null} className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm text-white dark:bg-white dark:text-slate-900">
                  {busy === "save" ? "Saving…" : "Save negotiated version"}
                </button>
              </div>
            </div>
            {report.summary ? <p className="mt-2 text-sm">{report.summary}</p> : null}
            {report.key_concerns.length ? (
              <ul className="mt-2 list-disc pl-5 text-sm">
                {report.key_concerns.map((k) => (
                  <li key={k}>{k}</li>
                ))}
              </ul>
            ) : null}
          </div>

          <div className="mb-2 hidden grid-cols-[1fr_1fr_minmax(260px,0.8fr)] gap-3 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500 xl:grid">
            <span>{report.original.filename}</span>
            <span>{report.revised.filename}</span>
            <span>AI commentary &amp; decision</span>
          </div>
          <div className="flex flex-col gap-3">
            {visible.map((c) => (
              <div key={c.id} className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 xl:grid-cols-[1fr_1fr_minmax(260px,0.8fr)] dark:border-slate-800 dark:bg-slate-950">
                <div className="min-w-0">
                  <div className="mb-1 text-[11px] font-semibold uppercase text-slate-400 xl:hidden">Original</div>
                  {c.original_text ? <DiffText ops={c.status === "unchanged" ? [{ op: "equal", text: c.original_text }] : c.inline_diff} side="original" /> : <span className="text-sm italic text-slate-400">— not in original —</span>}
                </div>
                <div className="min-w-0">
                  <div className="mb-1 text-[11px] font-semibold uppercase text-slate-400 xl:hidden">Revised</div>
                  {c.revised_text ? <DiffText ops={c.status === "unchanged" ? [{ op: "equal", text: c.revised_text }] : c.inline_diff} side="revised" /> : <span className="text-sm italic text-slate-400">— deleted —</span>}
                </div>
                {c.status === "unchanged" || c.status === "renumbered" ? (
                  <p className="text-xs text-slate-400">{c.status === "renumbered" ? "Renumbered only" : "Unchanged"}</p>
                ) : (
                  <ClauseCard
                    change={c}
                    decision={decisions[c.id] ?? defaultDecision()}
                    onDecide={(d) => setDecisions((all) => ({ ...all, [c.id]: d }))}
                    token={token}
                    orgId={orgId}
                    jurisdiction={jurisdiction}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
