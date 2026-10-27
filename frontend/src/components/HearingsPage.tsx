"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------- API shapes (local)

type ReachWindow = {
  state: string;
  lo: string | null;
  hi: string | null;
  label: string;
  capped: boolean;
  wide: boolean;
  calls: number;
};

type BoardItem = {
  key: string;
  item_id: string | null;
  court_code: string;
  court_name: string | null;
  courtroom: string;
  complex: string | null;
  item_no: string;
  position: number | null;
  segment: string | null;
  list_type: string | null;
  bench_label: string | null;
  court_case_id: string | null;
  case_title: string | null;
  window: ReachWindow;
  reach: { text: string } | null;
  coverage: string | null;
  travel_from_previous: number | null;
};

type Candidate = {
  user_id: string;
  name: string;
  prior_appearances: number;
  on_vakalatnama: boolean | null;
  memo_of_appearance_needed: boolean;
  enrolment_no: string | null;
};

type Strip = {
  advocate_id: string;
  name: string;
  items: BoardItem[];
  clashes: { state: string; items: string[]; text: string; travel_known: boolean }[];
  amber: { courtrooms: number; pairs: number; text: string; treated_as_clash: boolean } | null;
  suggestions: { item_key: string; item_label: string; reason: string; candidates: Candidate[]; pass_over_note: string | null }[];
};

type Board = { date: string; scope: string; advocates: Strip[]; notes: string[] };

type BriefRow = {
  id: string;
  court_case_id: string;
  hearing_date: string;
  title: string | null;
  ai_status: string;
  discarded_unverified: number;
  listing: { court?: string; courtroom?: string; item_no?: string; bench?: string } | null;
};

type Direction = {
  direction: string;
  responsible: string | null;
  quote: string;
  quote_match: string;
  quote_differs: string[];
  due: { due_date: string; basis: string; runs_from: string } | null;
};

type Brief = {
  id: string;
  hearing_date: string;
  court_case_id: string;
  ai_status: string;
  discarded_unverified: number;
  generated_at: string;
  sections: {
    label: string;
    case: { title: string | null; case_number: string | null; court: string | null };
    listing: { source: string; court?: string; courtroom?: string; item_no?: string; position?: number; bench?: string; list_type?: string; note?: string };
    deadlines: { available: boolean; note?: string; items: { kind: string; title: string; due_date: string | null; masked: boolean; status: string; basis: string | null }[] };
    adjournments: Record<string, number | string>;
    prior_bench: string[] | null;
    orders: { date: string | null; url: string | null }[];
  };
  ai_section: {
    label: string;
    last_order?: string;
    order_date?: string | null;
    order_url?: string | null;
    operative?: { quote: string } | null;
    directions?: Direction[];
    discarded_unverified?: number;
  } | null;
};

type Travel = { default_same_complex: number; default_unknown: number; rows: { id: string; from_complex: string; to_complex: string; minutes: number }[] };

// ---------------------------------------------------------------------------- helpers

const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
const card = "rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900";
const linkButton = "text-xs text-indigo-700 hover:underline disabled:opacity-50 dark:text-indigo-300";

function isoDay(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function ordinal(n: number) {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}

function roomLabel(item: BoardItem) {
  return /^\d+$/.test(item.courtroom) ? `Court ${item.courtroom}` : item.courtroom;
}

function windowTone(w: ReachWindow) {
  if (w.state === "estimated" || w.state === "pooled") return "text-slate-700 dark:text-slate-200";
  if (w.state === "beyond_rising") return "text-slate-500";
  return "text-amber-700 dark:text-amber-300";
}

const STATUS_TEXT: Record<string, string> = {
  done: "Order read",
  not_configured: "AI not configured",
  no_order: "No order",
  unreliable_text: "Order text unreliable",
  failed: "AI reading failed",
};

// ---------------------------------------------------------------------------- page

/** Hearing operations: each advocate's morning (reach windows, clashes, reassignment) and hearing briefs. */
export function HearingsPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const { orgId } = useWorkspace(token);
  const [tab, setTab] = useState<"board" | "briefs">("board");
  const [day, setDay] = useState(isoDay(1));
  const [board, setBoard] = useState<Board | null>(null);
  const [briefs, setBriefs] = useState<BriefRow[]>([]);
  const [open, setOpen] = useState<Brief | null>(null);
  const [travel, setTravel] = useState<Travel | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!orgId) return;
    api<Board>(`/api/v1/hearings/board?date=${day}`, { token, orgId }).then(setBoard).catch((e: Error) => setError(e.message));
    api<BriefRow[]>(`/api/v1/hearings/briefs?date=${day}&days=2`, { token, orgId }).then(setBriefs).catch((e: Error) => setError(e.message));
    api<Travel>("/api/v1/hearings/travel-times", { token, orgId }).then(setTravel).catch(() => setTravel(null));
  }, [token, orgId, day]);

  useEffect(load, [load]);

  async function act(key: string, run: () => Promise<unknown>, done?: string) {
    setBusy(key);
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

  function tap(kind: "assembled" | "called" | "rose", item: BoardItem) {
    const body =
      kind === "assembled"
        ? { kind, court_code: item.court_code, courtroom: item.courtroom, list_date: day }
        : { kind, item_id: item.item_id, court_case_id: kind === "called" ? item.court_case_id : undefined };
    const what = kind === "assembled" ? "Bench assembled" : kind === "called" ? `Item ${item.item_no} called` : `Court rose at item ${item.item_no}`;
    return act(`${kind}:${item.key}`, () => api("/api/v1/hearings/taps", { token, orgId, method: "POST", body }), `${what}: logged.`);
  }

  function treatAsClash() {
    return act("prefs", () => api("/api/v1/hearings/prefs", { token, orgId, method: "PUT", body: { amber_as_clash_dates: [day] } }));
  }

  async function openBrief(id: string) {
    setError(null);
    try {
      setOpen(await api<Brief>(`/api/v1/hearings/briefs/${id}`, { token, orgId }));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/cases" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Cases
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Hearings</h1>
        <div className="flex rounded-lg border border-slate-200 text-sm dark:border-slate-700">
          {(["board", "briefs"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 ${tab === t ? "bg-indigo-600 text-white" : "text-slate-600 dark:text-slate-300"} first:rounded-l-lg last:rounded-r-lg`}
            >
              {t === "board" ? "Clash board" : `Briefs (${briefs.length})`}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          Date
          <input type="date" className={field} value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        </label>
        <button onClick={() => setDay(isoDay(0))} className={linkButton}>
          Today
        </button>
        <button onClick={() => setDay(isoDay(1))} className={linkButton}>
          Tomorrow
        </button>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 overflow-y-auto p-4">
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}
        {notice ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{notice}</p> : null}

        {tab === "board" ? (
          <>
            {board === null ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : board.advocates.length === 0 ? (
              <p className={`${card} text-sm text-slate-500`}>No listed matters on this date{board.scope !== "firm" ? " among the matters you can see" : ""}.</p>
            ) : (
              board.advocates.map((strip) => (
                <AdvocateStrip key={strip.advocate_id} strip={strip} busy={busy} onTap={tap} onTreatAsClash={treatAsClash} />
              ))
            )}
            {board ? (
              <p className="text-xs text-slate-500">
                {board.notes.join(" ")} Showing {board.scope}. A clash is never a ground for adjournment: fixes are a colleague first, then asking for
                the matter to be passed over. Client messages about the hearing are not sent from here.
              </p>
            ) : null}
            <TravelTimes travel={travel} busy={busy === "travel"} onSave={(body) => act("travel", () => api("/api/v1/hearings/travel-times", { token, orgId, method: "PUT", body }), "Travel time saved.")} />
          </>
        ) : (
          <div className="grid gap-4 md:grid-cols-[18rem_1fr]">
            <section className={card}>
              <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Hearings in the next 2 days</h2>
              {briefs.length ? (
                <ul className="mt-2 flex flex-col gap-1">
                  {briefs.map((b) => (
                    <li key={b.id}>
                      <button
                        onClick={() => openBrief(b.id)}
                        className={`w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${open?.id === b.id ? "bg-slate-100 dark:bg-slate-800" : ""}`}
                      >
                        <div className="font-medium text-slate-900 dark:text-slate-100">{b.title ?? "Matter"}</div>
                        <div className="text-xs text-slate-500">
                          {b.hearing_date} · {STATUS_TEXT[b.ai_status] ?? b.ai_status}
                          {b.listing?.item_no ? ` · item ${b.listing.item_no}` : ""}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No briefs yet. They are prepared each evening for matters listed within two days.</p>
              )}
            </section>
            {open ? (
              <BriefView
                brief={open}
                busy={busy === "regenerate"}
                onRegenerate={(orderText, orderDate) =>
                  act(
                    "regenerate",
                    async () => {
                      const body: Record<string, string> = { court_case_id: open.court_case_id, hearing_date: open.hearing_date };
                      if (orderText.trim()) body.order_text = orderText;
                      if (orderDate) body.order_date = orderDate;
                      setOpen(await api<Brief>("/api/v1/hearings/briefs/regenerate", { token, orgId, method: "POST", body }));
                    },
                    "Brief regenerated.",
                  )
                }
              />
            ) : (
              <p className={`${card} text-sm text-slate-500`}>Choose a hearing to read its brief.</p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------- board

function AdvocateStrip({
  strip,
  busy,
  onTap,
  onTreatAsClash,
}: {
  strip: Strip;
  busy: string | null;
  onTap: (kind: "assembled" | "called" | "rose", item: BoardItem) => void;
  onTreatAsClash: () => void;
}) {
  const [showAmber, setShowAmber] = useState(false);
  const clashed = new Set(strip.clashes.flatMap((c) => c.items));
  return (
    <section className={card}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{strip.name}</h2>
        {strip.clashes.length ? (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/40 dark:text-red-300">
            {strip.clashes.length} overlap{strip.clashes.length > 1 ? "s" : ""}
          </span>
        ) : null}
        {strip.amber ? (
          <button
            onClick={() => setShowAmber((v) => !v)}
            className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
          >
            Possible clash, no data: {strip.amber.text}
          </button>
        ) : null}
      </div>

      {strip.clashes.map((c) => (
        <p key={c.items.join("-")} className="mt-2 rounded-lg bg-red-50 px-3 py-1.5 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          {c.text}
        </p>
      ))}
      {strip.amber && showAmber ? (
        <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          At least one courtroom has no reach estimate yet, so these items may or may not clash.{" "}
          {strip.amber.treated_as_clash ? (
            "Treated as a clash today."
          ) : (
            <button disabled={busy === "prefs"} onClick={onTreatAsClash} className="font-medium underline disabled:opacity-50">
              Treat as clash today
            </button>
          )}
        </div>
      ) : null}

      <ol className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
        {strip.items.map((item) => (
          <li key={item.key} className={`flex flex-wrap items-start gap-x-4 gap-y-1 py-2 text-sm ${clashed.has(item.key) ? "border-l-2 border-red-400 pl-2" : ""}`}>
            <div className="min-w-48">
              <div className="font-medium text-slate-900 dark:text-slate-100">
                {roomLabel(item)} · item {item.item_no}
                {item.position ? <span className="font-normal text-slate-500"> ({ordinal(item.position)} call)</span> : null}
              </div>
              <div className="text-xs text-slate-500">
                {[item.court_name ?? item.court_code, item.bench_label, item.segment?.replace("_", " ")].filter(Boolean).join(" · ")}
              </div>
              {item.case_title ? <div className="text-xs text-slate-600 dark:text-slate-300">{item.case_title}</div> : null}
            </div>
            <div className={`flex-1 ${windowTone(item.window)}`}>
              {item.window.label}
              {item.window.wide ? <span className="ml-1 text-xs text-amber-700 dark:text-amber-300">(wide window: plan loosely)</span> : null}
              {item.reach ? <div className="text-xs text-slate-500">{item.reach.text}</div> : null}
              {item.travel_from_previous !== null ? <div className="text-xs text-slate-500">{item.travel_from_previous} min from the previous courtroom</div> : null}
              {item.coverage === "manual_or_ecourtsindia_api" ? <div className="text-xs text-slate-500">Listings for this court are entered by hand or come from the eCourtsIndia API.</div> : null}
            </div>
            {item.courtroom !== "not allotted" ? (
              <div className="flex gap-3 whitespace-nowrap">
                <button disabled={busy !== null} onClick={() => onTap("assembled", item)} className={linkButton}>
                  Bench assembled
                </button>
                <button disabled={busy !== null || !item.item_id} onClick={() => onTap("called", item)} className={linkButton}>
                  Called
                </button>
                <button disabled={busy !== null || !item.item_id} onClick={() => onTap("rose", item)} className={linkButton}>
                  Rose here
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ol>

      {strip.suggestions.length ? (
        <div className="mt-3 flex flex-col gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Suggested fixes</h3>
          {strip.suggestions.map((s) => (
            <div key={s.item_key} className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
              <div className="font-medium text-slate-800 dark:text-slate-200">{s.item_label}</div>
              {s.candidates.length ? (
                <ul className="mt-1 flex flex-col gap-0.5">
                  {s.candidates.slice(0, 4).map((c) => (
                    <li key={c.user_id} className="text-slate-700 dark:text-slate-300">
                      Reassign to <span className="font-medium">{c.name}</span>
                      <span className="text-xs text-slate-500">
                        {" "}
                        · appeared {c.prior_appearances}× in this matter · on vakalatnama: {c.on_vakalatnama ? "yes" : "no"}
                        {c.memo_of_appearance_needed ? " (needs a memo of appearance)" : ""}
                        {c.enrolment_no ? ` · ${c.enrolment_no}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-slate-700 dark:text-slate-300">{s.pass_over_note}</p>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function TravelTimes({ travel, busy, onSave }: { travel: Travel | null; busy: boolean; onSave: (body: { from_complex: string; to_complex: string; minutes: number }) => void }) {
  const [form, setForm] = useState({ from_complex: "", to_complex: "", minutes: "" });
  return (
    <details className={card}>
      <summary className="cursor-pointer text-xs font-bold uppercase tracking-wide text-slate-500">Travel times between court complexes</summary>
      <p className="mt-2 text-xs text-slate-500">
        Courtrooms in one complex count {travel?.default_same_complex ?? 5} minutes apart; complexes without an entry count {travel?.default_unknown ?? 30}.
      </p>
      {travel?.rows.length ? (
        <ul className="mt-2 text-sm text-slate-700 dark:text-slate-300">
          {travel.rows.map((r) => (
            <li key={r.id}>
              {r.from_complex} ↔ {r.to_complex}: {r.minutes} min
            </li>
          ))}
        </ul>
      ) : null}
      <form
        className="mt-2 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const minutes = Number(form.minutes);
          if (!form.from_complex.trim() || !form.to_complex.trim() || !Number.isFinite(minutes)) return;
          onSave({ from_complex: form.from_complex, to_complex: form.to_complex, minutes });
          setForm({ from_complex: "", to_complex: "", minutes: "" });
        }}
      >
        <input className={field} placeholder="Complex" value={form.from_complex} onChange={(e) => setForm({ ...form, from_complex: e.target.value })} />
        <input className={field} placeholder="Other complex" value={form.to_complex} onChange={(e) => setForm({ ...form, to_complex: e.target.value })} />
        <input className={`${field} w-24`} type="number" min={0} max={600} placeholder="Minutes" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} />
        <button disabled={busy} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
          Save
        </button>
      </form>
    </details>
  );
}

// ---------------------------------------------------------------------------- briefs

function BriefView({ brief, busy, onRegenerate }: { brief: Brief; busy: boolean; onRegenerate: (orderText: string, orderDate: string) => void }) {
  const [orderText, setOrderText] = useState("");
  const [orderDate, setOrderDate] = useState("");
  const s = brief.sections;
  const ai = brief.ai_section;
  const adj = s.adjournments;
  return (
    <article className={`${card} flex flex-col gap-4 text-sm`}>
      <div>
        <p className="rounded-lg bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300">{s.label}</p>
        <h2 className="mt-2 text-base font-semibold text-slate-900 dark:text-slate-100">{s.case.title}</h2>
        <p className="text-xs text-slate-500">{[s.case.case_number, s.case.court, `hearing ${brief.hearing_date}`].filter(Boolean).join(" · ")}</p>
      </div>

      <section>
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Listing</h3>
        {s.listing.source === "cause_list" ? (
          <p className="text-slate-700 dark:text-slate-300">
            {[s.listing.court, s.listing.courtroom && `Court ${s.listing.courtroom}`, s.listing.item_no && `item ${s.listing.item_no}`, s.listing.bench, s.listing.list_type]
              .filter(Boolean)
              .join(" · ")}
          </p>
        ) : (
          <p className="text-slate-700 dark:text-slate-300">
            {s.listing.court ?? "Court not recorded"} · {s.listing.note}
          </p>
        )}
        {s.prior_bench?.length ? <p className="text-xs text-slate-500">Bench in the case record: {s.prior_bench.join(", ")}</p> : null}
      </section>

      <section>
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Last order</h3>
        {ai?.last_order ? (
          <p className="text-slate-700 dark:text-slate-300">{ai.last_order}</p>
        ) : (
          <>
            <p className="text-xs text-slate-500">
              Order of {ai?.order_date ?? "unknown date"}
              {ai?.order_url ? (
                <>
                  {" · "}
                  <a href={ai.order_url} target="_blank" rel="noreferrer" className="text-indigo-700 underline dark:text-indigo-300">
                    open the order
                  </a>
                </>
              ) : null}
            </p>
            {ai?.operative ? <blockquote className="mt-1 border-l-2 border-slate-300 pl-3 text-slate-700 italic dark:text-slate-300">{ai.operative.quote}</blockquote> : null}
            <ul className="mt-2 flex flex-col gap-2">
              {(ai?.directions ?? []).map((d, i) => (
                <li key={i} className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
                  <div className="text-slate-900 dark:text-slate-100">{d.direction}</div>
                  <blockquote className="mt-1 text-xs text-slate-600 italic dark:text-slate-400">“{d.quote}”</blockquote>
                  {d.quote_match === "close" ? (
                    <div className="text-xs text-amber-700 dark:text-amber-300">Close match to the order; check: {d.quote_differs.join(", ")}</div>
                  ) : null}
                  {d.due ? (
                    <div className="mt-1 text-xs text-slate-700 dark:text-slate-300">
                      Due {d.due.due_date} · {d.due.basis}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
            {brief.discarded_unverified ? (
              <p className="mt-1 text-xs text-slate-500">{brief.discarded_unverified} AI line(s) left out: their quotes were not found in the order.</p>
            ) : null}
          </>
        )}
      </section>

      <section>
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Deadlines (docket)</h3>
        {!s.deadlines.available ? (
          <p className="text-slate-500">{s.deadlines.note}</p>
        ) : s.deadlines.items.length ? (
          <ul className="flex flex-col gap-0.5">
            {s.deadlines.items.map((d, i) => (
              <li key={i} className="text-slate-700 dark:text-slate-300">
                {d.title} · {d.masked ? <span className="text-slate-500">date hidden until checked</span> : d.due_date} · {d.status}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-slate-500">No open deadlines.</p>
        )}
      </section>

      <section>
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Adjournments</h3>
        <p className="text-slate-700 dark:text-slate-300">
          {adj.total} so far · petitioner {adj.petitioner} · respondent {adj.respondent} · both {adj.both} · court {adj.court}
        </p>
        <p className="text-xs text-slate-500">{String(adj.note)}</p>
      </section>

      {s.orders.length ? (
        <section>
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Orders</h3>
          <ul className="flex flex-col gap-0.5">
            {s.orders.map((o, i) => (
              <li key={i}>
                {o.url ? (
                  <a href={o.url} target="_blank" rel="noreferrer" className="text-indigo-700 underline dark:text-indigo-300">
                    {o.date ?? "Order"}
                  </a>
                ) : (
                  o.date
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <form
        className="flex flex-col gap-2 border-t border-slate-200 pt-3 dark:border-slate-800"
        onSubmit={(e) => {
          e.preventDefault();
          onRegenerate(orderText, orderDate);
        }}
      >
        <label className="text-xs text-slate-500">
          Paste the latest order if it isn&apos;t in the case data (optional)
          <textarea className={`${field} mt-1 h-24 w-full`} value={orderText} onChange={(e) => setOrderText(e.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-500">
            Order date
            <input type="date" className={field} value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
          </label>
          <button disabled={busy} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "Preparing…" : "Regenerate brief"}
          </button>
          <span className="text-xs text-slate-500">Generated {new Date(brief.generated_at).toLocaleString("en-IN")}</span>
        </div>
      </form>
    </article>
  );
}
