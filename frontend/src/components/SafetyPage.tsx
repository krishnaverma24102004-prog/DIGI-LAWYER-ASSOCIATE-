"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";
import { downloadWithAuth } from "@/lib/download";
import type { ApprovalRequest, IntakeState, TrashItem } from "@/lib/types";

type Member = { user_id: string; role: string; email: string | null; full_name: string | null };

const ACTION_LABELS: Record<ApprovalRequest["action"], string> = {
  delete: "Delete",
  enable_intake: "Turn on public intake",
  make_owner: "Make owner",
  purge: "Erase from Trash now",
};
const KIND_LABELS: Record<string, string> = {
  transcript: "Consultation",
  document: "Document",
  draft: "Draft",
  review_grid: "Review",
  court_case: "Court case",
  case_thread: "Case thread",
  knowledge_source: "Knowledge source",
  trash_item: "Trashed record",
  organization: "Firm setting",
  organization_member: "Member",
};

const card = "rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900";
const heading = "border-b border-slate-200 px-4 py-3 font-medium text-slate-900 dark:border-slate-800 dark:text-slate-100";
const small = "rounded-lg px-2.5 py-1 text-xs font-medium";

function when(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
}

type Pending =
  | { kind: "intake_on" }
  | { kind: "intake_off" }
  | { kind: "erase"; item: TrashItem }
  | { kind: "decide"; request: ApprovalRequest; approve: boolean };

/** Requests waiting for a partner or owner, the Trash (restore within 30 days), and public intake. */
export function SafetyPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const myRole = workspace.orgs.find((o) => o.id === orgId)?.role ?? "";
  const senior = myRole === "owner" || myRole === "partner";

  const [me, setMe] = useState<string | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [showClosed, setShowClosed] = useState(false);
  const [intake, setIntake] = useState<IntakeState | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const [m, a, t, i] = await Promise.all([
        api<Member[]>(`/api/v1/organizations/${orgId}/members`, { token }),
        api<ApprovalRequest[]>("/api/v1/approvals", { token, orgId }),
        api<TrashItem[]>(`/api/v1/trash?include_closed=${showClosed}`, { token, orgId }),
        api<IntakeState>("/api/v1/intake", { token, orgId }),
      ]);
      setMembers(m);
      setApprovals(a);
      setTrash(t);
      setIntake(i);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, token, showClosed]);

  useEffect(() => {
    // Fetching on mount and whenever the org or the trash filter changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    // The signed-in user's id, to tell their own requests apart (the JWT's subject).
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMe(JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).sub ?? null);
    } catch {
      setMe(null);
    }
  }, [token]);

  const name = (id: string | null) => {
    if (!id) return "someone";
    if (id === me) return "you";
    const m = members.find((x) => x.user_id === id);
    return m?.full_name || m?.email || "a former member";
  };

  async function run(action: () => Promise<{ message?: string; status?: string } | void>, done?: string) {
    setBusy(true);
    setDialogError(null);
    try {
      const result = await action();
      setPending(null);
      setNote("");
      setMessage((result && "message" in result && result.message) || done || null);
      await load();
    } catch (e) {
      setDialogError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const waiting = approvals.filter((a) => a.status === "pending");
  const decided = approvals.filter((a) => a.status !== "pending").slice(0, 20);
  const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Approvals &amp; Trash</h1>
        <select aria-label="Organization" value={orgId ?? ""} onChange={(e) => workspace.setOrgId(e.target.value)} className={`${field} min-w-0`}>
          {workspace.orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} ({o.role})
            </option>
          ))}
        </select>
        <button onClick={onSignOut} className="ml-auto text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          Sign out
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 overflow-y-auto p-4">
        {message ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{message}</p> : null}
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}

        {/* Requests */}
        <section className={card}>
          <h2 className={heading}>Waiting for approval ({waiting.length})</h2>
          {waiting.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500">Nothing is waiting.</p>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {waiting.map((a) => {
                const mine = a.requested_by === me;
                const canDecide = senior && !mine && (a.action !== "make_owner" || myRole === "owner");
                return (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-slate-900 dark:text-slate-100">
                        {ACTION_LABELS[a.action]}: {a.target_label || KIND_LABELS[a.target_kind] || a.target_kind}
                      </div>
                      <div className="text-xs text-slate-500">
                        {KIND_LABELS[a.target_kind] ?? a.target_kind} · asked by {name(a.requested_by)} · {when(a.requested_at)} · expires{" "}
                        {when(a.expires_at)}
                      </div>
                      {a.reason ? <div className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">Reason: {a.reason}</div> : null}
                    </div>
                    {canDecide ? (
                      <>
                        <button onClick={() => setPending({ kind: "decide", request: a, approve: true })} className={`${small} bg-emerald-600 text-white hover:bg-emerald-700`}>
                          Approve
                        </button>
                        <button onClick={() => setPending({ kind: "decide", request: a, approve: false })} className={`${small} bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200`}>
                          Reject
                        </button>
                      </>
                    ) : mine ? (
                      <button
                        onClick={() => run(() => api(`/api/v1/approvals/${a.id}/cancel`, { token, orgId, method: "POST" }), "Request withdrawn.")}
                        className={`${small} text-slate-600 hover:underline dark:text-slate-300`}
                      >
                        Withdraw
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400">Waiting for {a.action === "make_owner" ? "another owner" : "a partner or owner"}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {decided.length ? (
            <details className="border-t border-slate-200 px-4 py-2 text-sm dark:border-slate-800">
              <summary className="cursor-pointer text-slate-500">Recent decisions</summary>
              <ul className="mt-2 flex flex-col gap-1.5">
                {decided.map((a) => (
                  <li key={a.id} className="text-xs text-slate-600 dark:text-slate-400">
                    <span className="font-medium capitalize">{a.status}</span>: {ACTION_LABELS[a.action]} {a.target_label ? `“${a.target_label}”` : ""} ·
                    asked by {name(a.requested_by)}
                    {a.decided_by ? `, decided by ${name(a.decided_by)} ${when(a.decided_at)}` : ""}
                    {a.decision_note ? ` · “${a.decision_note}”` : ""}
                    {a.error ? ` · ${a.error}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>

        {/* Trash */}
        <section className={card}>
          <div className={`${heading} flex items-center gap-3`}>
            <h2 className="flex-1">Trash</h2>
            <label className="flex items-center gap-1.5 text-xs font-normal text-slate-500">
              <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} className="accent-indigo-600" />
              Show restored and erased
            </label>
          </div>
          <p className="px-4 pt-3 text-xs text-slate-500">
            Deleted records stay here for 30 days and can be restored. After that they are erased, and an erasure record is kept.
          </p>
          {trash.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500">The Trash is empty.</p>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {trash.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-900 dark:text-slate-100">{t.title || "(untitled)"}</div>
                    <div className="text-xs text-slate-500">
                      {KIND_LABELS[t.kind] ?? t.kind} · deleted by {name(t.deleted_by)} {when(t.deleted_at)}
                      {t.requested_by && t.requested_by !== t.deleted_by ? ` at ${name(t.requested_by)}'s request` : ""}
                      {t.reason ? ` · “${t.reason}”` : ""}
                    </div>
                    <div className="text-xs text-slate-400">
                      {t.restored_at
                        ? `Restored by ${name(t.restored_by ?? null)} ${when(t.restored_at)}`
                        : t.purged_at
                          ? `Erased ${when(t.purged_at)}${t.purged_by ? ` by ${name(t.purged_by)}` : " (30-day retention)"}`
                          : `Erased automatically after ${when(t.purge_after)}`}
                    </div>
                  </div>
                  {!t.restored_at && !t.purged_at ? (
                    <>
                      <button
                        onClick={() => run(() => api(`/api/v1/trash/${t.id}/restore`, { token, orgId, method: "POST" }), `Restored “${t.title ?? "the record"}”.`)}
                        className={`${small} bg-indigo-600 text-white hover:bg-indigo-700`}
                      >
                        Restore
                      </button>
                      {myRole === "owner" ? (
                        <button onClick={() => setPending({ kind: "erase", item: t })} className={`${small} text-red-600 hover:underline`}>
                          Erase now…
                        </button>
                      ) : null}
                    </>
                  ) : t.purged_at ? (
                    <button
                      onClick={() =>
                        downloadWithAuth(`/api/v1/trash/${t.id}/certificate`, token, orgId, "erasure-certificate.pdf").catch((e: Error) => setError(e.message))
                      }
                      className={`${small} text-indigo-700 hover:underline dark:text-indigo-300`}
                    >
                      Erasure certificate
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Public intake */}
        {intake ? (
          <section className={`${card} p-4`}>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="font-medium text-slate-900 dark:text-slate-100">Public intake (WhatsApp and phone)</h2>
                <p className="mt-0.5 text-sm text-slate-600 dark:text-slate-400">
                  {intake.enabled
                    ? "On: the AI answers the firm's numbers. It only asks intake questions; replies with legal substance wait for a lawyer."
                    : "Off: messages go to the lawyer's inbox and calls hear that the line isn't answered by the assistant."}
                </p>
                {intake.changed_at ? (
                  <p className="text-xs text-slate-400">
                    Last changed by {name(intake.changed_by)} {when(intake.changed_at)}
                  </p>
                ) : null}
                {intake.pending_request ? (
                  <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                    Turning it on is waiting for approval (asked by {name(intake.pending_request.requested_by)}).
                  </p>
                ) : null}
              </div>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  intake.enabled ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                }`}
              >
                {intake.enabled ? "On" : "Off"}
              </span>
              {senior ? (
                <button
                  onClick={() => setPending({ kind: intake.enabled ? "intake_off" : "intake_on" })}
                  disabled={!intake.enabled && !!intake.pending_request}
                  className={`${small} ${intake.enabled ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" : "bg-indigo-600 text-white hover:bg-indigo-700"} disabled:opacity-50`}
                >
                  {intake.enabled ? "Turn off" : "Turn on…"}
                </button>
              ) : null}
            </div>
          </section>
        ) : null}
      </main>

      {pending?.kind === "intake_on" ? (
        <ConfirmDialog
          title="Turn on public intake?"
          confirmLabel="Turn on"
          busy={busy}
          error={dialogError}
          onCancel={() => setPending(null)}
          onConfirm={() => run(() => api("/api/v1/intake", { token, orgId, method: "PUT", body: { enabled: true, confirm: true, reason: note || null } }))}
          facts={[
            { label: "What happens", value: "The AI replies to anyone who messages or calls the firm's WhatsApp and phone numbers, asking intake questions." },
            { label: "Never sent alone", value: "Anything about the law, deadlines, amounts or what to do waits for a lawyer's approval." },
            { label: "Who sees it", value: "The public on those numbers; chats and calls are saved for the number's lawyer, partners and owners." },
            { label: "Cost", value: "Phone minutes are billed per started minute; AI and WhatsApp usage counts toward your plan." },
            { label: "Approval", value: "Another partner or owner must approve, unless you are the firm's only one." },
          ]}
        >
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why (optional, shown to the approver)" className={`${field} w-full`} />
        </ConfirmDialog>
      ) : null}
      {pending?.kind === "intake_off" ? (
        <ConfirmDialog
          title="Turn off public intake?"
          confirmLabel="Turn off"
          busy={busy}
          error={dialogError}
          onCancel={() => setPending(null)}
          onConfirm={() => run(() => api("/api/v1/intake", { token, orgId, method: "PUT", body: { enabled: false } }), "Public intake is off.")}
          facts={[{ label: "What happens", value: "The AI stops answering at once. New messages wait in the inbox; callers hear that the line isn't answered by the assistant." }]}
        />
      ) : null}
      {pending?.kind === "erase" ? (
        <ConfirmDialog
          title={`Erase “${pending.item.title ?? "this record"}” now?`}
          confirmLabel="Erase"
          danger
          typed="ERASE"
          busy={busy}
          error={dialogError}
          onCancel={() => setPending(null)}
          onConfirm={() =>
            run(() => api(`/api/v1/trash/${pending.item.id}/erase`, { token, orgId, method: "POST", body: { confirm: "ERASE", reason: note || null } }), "Erased. The erasure certificate is available below.")
          }
          facts={[
            { label: "What happens", value: "The record is permanently erased before its 30 days are up. This can't be undone." },
            { label: "Kept", value: "An erasure record: who deleted and erased it, when, and a fingerprint of what was erased." },
            { label: "Approval", value: "Another partner or owner must approve, unless you are the firm's only one." },
          ]}
        >
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (e.g. client's erasure request)" className={`${field} w-full`} />
        </ConfirmDialog>
      ) : null}
      {pending?.kind === "decide" ? (
        <ConfirmDialog
          title={`${pending.approve ? "Approve" : "Reject"}: ${ACTION_LABELS[pending.request.action]}`}
          confirmLabel={pending.approve ? "Approve and carry out" : "Reject"}
          danger={pending.approve && pending.request.action === "purge"}
          busy={busy}
          error={dialogError}
          onCancel={() => setPending(null)}
          onConfirm={() =>
            run(
              () =>
                api(`/api/v1/approvals/${pending.request.id}/${pending.approve ? "approve" : "reject"}`, {
                  token,
                  orgId,
                  method: "POST",
                  body: { note: note || null },
                }),
              pending.approve ? "Approved and done." : "Rejected.",
            )
          }
          facts={[
            { label: "Record", value: pending.request.target_label || KIND_LABELS[pending.request.target_kind] || pending.request.target_kind },
            { label: "Asked by", value: name(pending.request.requested_by) },
            ...(pending.approve
              ? [
                  {
                    label: "What happens",
                    value:
                      pending.request.action === "delete"
                        ? "It moves to the Trash (restorable for 30 days)."
                        : pending.request.action === "purge"
                          ? "It is permanently erased now."
                          : pending.request.action === "make_owner"
                            ? "They become an owner: billing, members and erasure."
                            : "The AI starts answering the firm's WhatsApp and phone numbers.",
                  },
                ]
              : []),
          ]}
        >
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note to the requester (optional)" className={`${field} w-full`} />
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
