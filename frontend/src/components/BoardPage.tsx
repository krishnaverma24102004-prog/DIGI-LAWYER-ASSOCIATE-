"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";
import { API_URL } from "@/lib/config";

// Declared here (not in lib/types.ts): the shapes of /api/v1/causelists responses.
type Warning = { kind: "order_lag" | "disposed_no_judgment"; message: string };

type Listing = {
  id: string;
  match_type: "exact" | "probable" | "possibly_ours";
  reason: string;
  state: "open" | "claimed" | "dismissed" | "confirmed";
  list_type: "daily" | "supplementary" | "advance";
  list_date: string;
  court_code: string;
  court_name: string;
  complex: string | null;
  courtroom: string | null;
  item_no: string | null;
  position: number | null;
  bench: string | null;
  segment: string | null;
  status: "listed" | "deleted" | "not_to_be_taken_up";
  case_label: string | null;
  parties: string | null;
  connected_to: string | null;
  court_case_id: string | null;
  case_title: string | null;
  appearing_advocate_id: string | null;
  appearing_advocate: string | null;
  fallback_advocate_id: string | null;
  fallback_advocate: string | null;
  confirmed_by: string | null;
  escalation_level: number;
  tone: "confirmed" | "deleted" | "expected" | "red" | "amber" | "pending";
  hearing_date_set: boolean;
  warnings: Warning[];
};

type Board = {
  date: string;
  complexes: { complex: string; courtrooms: { court_name: string; courtroom: string; items: Listing[] }[] }[];
  possibly_ours: Listing[];
  dismissed: number;
  warnings: ({ court_case_id: string; title: string; case_number: string | null } & Warning)[];
  lists: { id: string; court_code: string; list_type: string; source: string; filename: string | null; fetched_at: string; item_count: number; parse_warnings: string[] }[];
};

type Court = { code: string; name: string; automated_access_allowed: boolean; terms_note: string; polling: string };
type Member = { user_id: string; role: string; email: string | null; full_name: string | null };
type Alias = { id: string; user_id: string; alias: string; enrolment_no: string | null };
type CourtCase = { id: string; title: string; case_number: string | null };

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

const TONE: Record<Listing["tone"], { row: string; badge: string; label: string }> = {
  confirmed: { row: "", badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300", label: "Confirmed" },
  pending: { row: "", badge: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300", label: "Awaiting confirmation" },
  amber: { row: "bg-amber-50 dark:bg-amber-950/30", badge: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300", label: "Unconfirmed: fallback told" },
  red: { row: "bg-red-50 dark:bg-red-950/30", badge: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300", label: "Unconfirmed: partners told" },
  expected: { row: "", badge: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300", label: "Expected (advance list)" },
  deleted: { row: "opacity-70", badge: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300", label: "Deleted from the list" },
};

function listTypeLabel(l: Pick<Listing, "list_type" | "segment">) {
  if (l.list_type === "advance") return "Advance";
  return l.list_type === "supplementary" ? "Supplementary" : "Daily";
}

function tomorrow() {
  const d = new Date();
  if (d.getHours() >= 12) d.setDate(d.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function longDate(day: string) {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

function WarningChips({ warnings }: { warnings: Warning[] }) {
  if (!warnings.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {warnings.map((w) => (
        <span key={w.kind} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
          {w.message}
        </span>
      ))}
    </div>
  );
}

function AdvocateSelect({
  value,
  empty,
  members,
  disabled,
  onChange,
}: {
  value: string | null;
  empty: string;
  members: Member[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <select
      disabled={disabled}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      className="max-w-40 rounded border border-slate-200 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700"
    >
      <option value="">{empty}</option>
      {members.map((m) => (
        <option key={m.user_id} value={m.user_id}>
          {m.full_name || m.email}
        </option>
      ))}
    </select>
  );
}

/** Tonight's board: the firm's matters in tonight's cause lists, who appears, and who has confirmed. */
export function BoardPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const [day, setDay] = useState(tomorrow);
  const [board, setBoard] = useState<Board | null>(null);
  const [courts, setCourts] = useState<Court[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [aliases, setAliases] = useState<Alias[]>([]);
  const [cases, setCases] = useState<CourtCase[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [panel, setPanel] = useState<"upload" | "aliases" | null>(null);
  const [upload, setUpload] = useState({ court_code: "", list_date: "", list_type: "" });
  const [file, setFile] = useState<File | null>(null);
  const [aliasForm, setAliasForm] = useState({ user_id: "", alias: "", enrolment_no: "" });
  const [claimCase, setClaimCase] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    if (!orgId) return;
    api<Board>(`/api/v1/causelists/board?date=${day}`, { token, orgId }).then(setBoard).catch((e: Error) => setError(e.message));
  }, [token, orgId, day]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!orgId) return;
    api<Court[]>("/api/v1/causelists/courts", { token, orgId }).then(setCourts).catch(() => undefined);
    api<Member[]>(`/api/v1/organizations/${orgId}/members`, { token }).then(setMembers).catch(() => undefined);
    api<Alias[]>("/api/v1/causelists/aliases", { token, orgId }).then(setAliases).catch(() => undefined);
    api<CourtCase[]>("/api/v1/cases", { token, orgId }).then(setCases).catch(() => undefined);
  }, [token, orgId]);

  const memberName = (id: string) => {
    const m = members.find((x) => x.user_id === id);
    return m?.full_name || m?.email || "Member";
  };

  async function act(id: string, run: () => Promise<unknown>, done?: string) {
    setBusy(id);
    setError(null);
    setNotice(null);
    try {
      await run();
      if (done) setNotice(done);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const post = (path: string, body?: unknown) => api(path, { token, orgId, method: "POST", body });

  function assign(l: Listing, key: "appearing_advocate_id" | "fallback_advocate_id", value: string) {
    return act(l.id, () =>
      api(`/api/v1/causelists/matches/${l.id}/advocates`, {
        token,
        orgId,
        method: "PUT",
        body: { [key]: value || null, remember_fallback: key === "fallback_advocate_id" && Boolean(l.court_case_id) },
      }),
    );
  }

  async function sendUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !upload.court_code || !orgId) return;
    setBusy("upload");
    setError(null);
    setNotice(null);
    const form = new FormData();
    form.append("file", file);
    form.append("court_code", upload.court_code);
    if (upload.list_date) form.append("list_date", upload.list_date);
    if (upload.list_type) form.append("list_type", upload.list_type);
    try {
      const res = await fetch(`${API_URL}/api/v1/causelists/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "X-Org-Id": orgId },
        body: form,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed");
      setNotice(
        body.status === "unchanged"
          ? "That list was already added."
          : `Added the ${body.list_type} list for ${longDate(body.list_date)}: ${body.items} items, ${body.exact} of your matters, ${
              body.probable + body.possibly_ours
            } to check.`,
      );
      setFile(null);
      if (body.list_date) setDay(body.list_date);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function addAlias(e: React.FormEvent) {
    e.preventDefault();
    await act("alias", async () => {
      const body = { user_id: aliasForm.user_id, alias: aliasForm.alias, ...(aliasForm.enrolment_no ? { enrolment_no: aliasForm.enrolment_no } : {}) };
      const saved = await api<Alias>("/api/v1/causelists/aliases", { token, orgId, method: "POST", body });
      setAliases((xs) => [...xs, saved]);
      setAliasForm({ user_id: aliasForm.user_id, alias: "", enrolment_no: "" });
    });
  }

  function removeAlias(a: Alias) {
    return act(a.id, async () => {
      await api(`/api/v1/causelists/aliases/${a.id}`, { token, orgId, method: "DELETE" });
      setAliases((xs) => xs.filter((x) => x.id !== a.id));
    });
  }

  const listed = board?.complexes.reduce((n, c) => n + c.courtrooms.reduce((m, r) => m + r.items.length, 0), 0) ?? 0;
  const unconfirmed =
    board?.complexes.flatMap((c) => c.courtrooms.flatMap((r) => r.items)).filter((l) => l.tone === "amber" || l.tone === "red").length ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/cases" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Cases
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Tonight&apos;s board</h1>
        <input type="date" aria-label="List date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} className={field} />
        <button
          onClick={() => setPanel((p) => (p === "upload" ? null : "upload"))}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Add a cause list
        </button>
        <button onClick={() => setPanel((p) => (p === "aliases" ? null : "aliases"))} className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
          Advocate names ({aliases.length})
        </button>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 overflow-y-auto p-4">
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p> : null}

        {panel === "upload" ? (
          <form onSubmit={sendUpload} className="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 dark:border-slate-800 dark:bg-slate-900">
            <input type="file" accept="application/pdf" aria-label="Cause list PDF" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
            <select required value={upload.court_code} onChange={(e) => setUpload({ ...upload, court_code: e.target.value })} className={field}>
              <option value="">Court…</option>
              {courts.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              List date (if the PDF doesn&apos;t say)
              <input type="date" value={upload.list_date} onChange={(e) => setUpload({ ...upload, list_date: e.target.value })} className={field} />
            </label>
            <select value={upload.list_type} onChange={(e) => setUpload({ ...upload, list_type: e.target.value })} className={field}>
              <option value="">List type: as printed</option>
              <option value="daily">Daily</option>
              <option value="supplementary">Supplementary</option>
              <option value="advance">Advance</option>
            </select>
            <button disabled={!file || !upload.court_code || busy === "upload"} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {busy === "upload" ? "Reading the list…" : "Add list"}
            </button>
            <div className="text-xs text-slate-500 sm:col-span-2">
              For lists we can&apos;t fetch: those behind a captcha (district courts on eCourts) and courts whose terms don&apos;t allow automated
              downloads. The list is kept for your firm only and read by fixed rules, no AI.
              {courts.length ? (
                <ul className="mt-1 list-disc pl-4">
                  {courts.map((c) => (
                    <li key={c.code}>
                      {c.name}: {c.automated_access_allowed ? `fetched automatically (${c.polling})` : "forward its lists here"}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </form>
        ) : null}

        {panel === "aliases" ? (
          <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">How lists print your advocates</h2>
            <p className="mt-1 text-xs text-slate-500">
              Members&apos; names are matched already. Add the variants lists use (initials, chamber names) and AOR codes or enrolment
              numbers, so items under your advocates that match no tracked matter appear under &lsquo;Possibly ours&rsquo;.
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm">
              {aliases.map((a) => (
                <li key={a.id} className="flex items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-slate-100">{a.alias}</span>
                  {a.enrolment_no ? <span className="text-xs text-slate-500">#{a.enrolment_no}</span> : null}
                  <span className="text-xs text-slate-500">{memberName(a.user_id)}</span>
                  <button disabled={busy === a.id} onClick={() => removeAlias(a)} className="text-xs text-red-600 hover:underline">
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <form onSubmit={addAlias} className="mt-3 flex flex-wrap gap-2">
              <select required value={aliasForm.user_id} onChange={(e) => setAliasForm({ ...aliasForm, user_id: e.target.value })} className={field}>
                <option value="">Advocate…</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.full_name || m.email}
                  </option>
                ))}
              </select>
              <input required placeholder="As printed, e.g. D. Abhinav Rao" value={aliasForm.alias} onChange={(e) => setAliasForm({ ...aliasForm, alias: e.target.value })} className={field} />
              <input placeholder="AOR code / enrolment no." value={aliasForm.enrolment_no} onChange={(e) => setAliasForm({ ...aliasForm, enrolment_no: e.target.value })} className={field} />
              <button disabled={busy === "alias"} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                Add
              </button>
            </form>
          </section>
        ) : null}

        <section className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{longDate(day)}</h2>
          <span className="text-sm text-slate-500">
            {listed} listed · {unconfirmed} unconfirmed · {board?.possibly_ours.length ?? 0} possibly ours
          </span>
          {board?.lists.length ? (
            <span className="text-xs text-slate-500">
              Lists read:{" "}
              {board.lists
                .map((l) => `${l.court_code} ${l.list_type}${l.source === "forwarded" ? " (forwarded)" : ""}`)
                .join(", ")}
            </span>
          ) : (
            <span className="text-xs text-slate-500">No list for this date yet. Supplementary lists often arrive late; the board fills in as they do.</span>
          )}
        </section>
        {board?.lists.some((l) => l.parse_warnings?.length) ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
            Some lists may not have been read completely: {board.lists.flatMap((l) => l.parse_warnings ?? []).slice(0, 3).join("; ")}. Check the court&apos;s
            PDF for your matters.
          </p>
        ) : null}

        {board?.complexes.map((c) => (
          <section key={c.complex} className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <h2 className="border-b border-slate-100 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500 dark:border-slate-800">{c.complex}</h2>
            {c.courtrooms.map((r) => (
              <div key={`${r.court_name}-${r.courtroom}`} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                <h3 className="px-4 pt-2 text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {r.court_name} · {/^\d+$/.test(r.courtroom) ? `Court ${r.courtroom}` : r.courtroom}
                  {r.items[0]?.bench ? <span className="ml-2 font-normal text-slate-500">{r.items[0].bench}</span> : null}
                </h3>
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {r.items.map((l) => {
                    const tone = TONE[l.tone];
                    return (
                      <li key={l.id} className={`flex flex-wrap items-start gap-3 px-4 py-2 text-sm ${tone.row}`}>
                        <div className="w-16 shrink-0 font-mono text-base font-semibold text-slate-900 dark:text-slate-100">
                          {l.item_no ?? "–"}
                          {l.connected_to ? <div className="font-sans text-xs font-normal text-slate-500">with {l.connected_to}</div> : null}
                        </div>
                        <div className="min-w-56 flex-1">
                          <div className="font-medium text-slate-900 dark:text-slate-100">
                            {l.case_label}
                            {l.case_title ? <span className="ml-2 font-normal text-slate-600 dark:text-slate-300">{l.case_title}</span> : null}
                          </div>
                          <div className="text-xs text-slate-500">
                            {listTypeLabel(l)}
                            {l.segment && l.segment !== "other" && l.segment !== l.list_type ? ` · ${l.segment.replace("_", " ")}` : ""}
                            {l.match_type !== "exact" ? ` · claimed (${l.match_type.replace("_", " ")})` : ""}
                            {l.hearing_date_set ? " · next hearing date updated" : ""}
                          </div>
                          <WarningChips warnings={l.warnings} />
                        </div>
                        <div className="flex flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
                          <label className="flex items-center gap-1">
                            Appears
                            <AdvocateSelect
                              value={l.appearing_advocate_id}
                              empty="Not assigned"
                              members={members}
                              disabled={busy === l.id || l.state === "confirmed"}
                              onChange={(v) => assign(l, "appearing_advocate_id", v)}
                            />
                          </label>
                          <label className="flex items-center gap-1">
                            Fallback
                            <AdvocateSelect
                              value={l.fallback_advocate_id}
                              empty="No fallback"
                              members={members}
                              disabled={busy === l.id || l.state === "confirmed"}
                              onChange={(v) => assign(l, "fallback_advocate_id", v)}
                            />
                          </label>
                        </div>
                        <div className="flex w-44 flex-col items-end gap-1">
                          <span className={`rounded-full px-2 py-0.5 text-xs ${tone.badge}`}>
                            {l.tone === "confirmed" && l.confirmed_by ? `Confirmed by ${l.confirmed_by}` : tone.label}
                          </span>
                          {l.tone !== "confirmed" && l.tone !== "deleted" ? (
                            <button
                              disabled={busy === l.id}
                              onClick={() => act(l.id, () => post(`/api/v1/causelists/matches/${l.id}/confirm`), `Appearance confirmed: ${l.case_label}, item ${l.item_no}.`)}
                              className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                            >
                              {l.tone === "expected" ? "Confirm (expected)" : "Confirm appearance"}
                            </button>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        ))}
        {board && !board.complexes.length ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            None of the firm&apos;s tracked matters is in the lists read for this date.
          </p>
        ) : null}

        <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Possibly ours ({board?.possibly_ours.length ?? 0})</h2>
          <p className="mt-1 text-xs text-slate-500">
            Items naming one of the firm&apos;s advocates that match no tracked matter, and items that match a matter on parties but not on
            number. Claim one to put it on the board (and update the matter&apos;s hearing date), or dismiss it.
          </p>
          <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
            {board?.possibly_ours.map((l) => (
              <li key={l.id} className="flex flex-wrap items-start gap-3 py-2 text-sm">
                <div className="w-40 shrink-0 text-xs text-slate-500">
                  {l.court_name}
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-200">
                    {l.courtroom ? (/^\d+$/.test(l.courtroom) ? `Court ${l.courtroom}` : l.courtroom) : "Not allotted"} · item {l.item_no}
                  </div>
                  {listTypeLabel(l)}
                </div>
                <div className="min-w-56 flex-1">
                  <div className="font-medium text-slate-900 dark:text-slate-100">
                    {l.case_label}{" "}
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-normal text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                      {l.match_type === "probable" ? "Probable" : "Names our advocate"}
                    </span>
                  </div>
                  {l.parties ? <div className="text-xs text-slate-600 dark:text-slate-300">{l.parties}</div> : null}
                  <div className="text-xs text-slate-500">{l.reason}</div>
                  {l.case_title ? <div className="text-xs text-slate-500">Matter: {l.case_title}</div> : null}
                </div>
                <div className="flex items-center gap-2">
                  {!l.court_case_id ? (
                    <select
                      aria-label="Link to a matter"
                      value={claimCase[l.id] ?? ""}
                      onChange={(e) => setClaimCase({ ...claimCase, [l.id]: e.target.value })}
                      className="max-w-48 rounded border border-slate-200 bg-transparent px-1 py-0.5 text-xs dark:border-slate-700"
                    >
                      <option value="">Not a tracked matter</option>
                      {cases.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.case_number ? `${c.case_number} · ` : ""}
                          {c.title}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <button
                    disabled={busy === l.id}
                    onClick={() =>
                      act(l.id, () => post(`/api/v1/causelists/matches/${l.id}/claim`, claimCase[l.id] ? { court_case_id: claimCase[l.id] } : {}), "Claimed: it is on the board now.")
                    }
                    className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    Ours
                  </button>
                  <button
                    disabled={busy === l.id}
                    onClick={() => act(l.id, () => post(`/api/v1/causelists/matches/${l.id}/dismiss`))}
                    className="text-xs text-slate-600 hover:underline dark:text-slate-300"
                  >
                    Not ours
                  </button>
                </div>
              </li>
            ))}
            {board && !board.possibly_ours.length ? <li className="py-2 text-sm text-slate-500">Nothing to check.</li> : null}
          </ul>
          {board?.dismissed ? <p className="mt-1 text-xs text-slate-400">{board.dismissed} dismissed.</p> : null}
        </section>

        {board?.warnings.length ? (
          <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Matters to check ({board.warnings.length})</h2>
            <ul className="mt-2 flex flex-col gap-1 text-sm">
              {board.warnings.map((w) => (
                <li key={`${w.court_case_id}-${w.kind}`} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-slate-100">{w.title}</span>
                  {w.case_number ? <span className="text-xs text-slate-500">{w.case_number}</span> : null}
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">{w.message}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <p className="text-xs text-slate-400">
          Unconfirmed listings turn amber (the fallback advocate is told) at 20:00 the evening before or an hour after the list arrives, whichever is
          later, and red (partners are told) an hour after that; everyone is told again at 07:30. Only exact matches in daily and supplementary
          lists change a matter&apos;s next hearing date.
        </p>
      </main>
    </div>
  );
}
