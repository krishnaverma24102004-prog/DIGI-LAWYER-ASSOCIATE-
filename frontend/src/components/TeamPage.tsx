"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

type Member = { user_id: string; role: string; email: string | null; full_name: string | null };
type Invitation = { id: string; email: string; role: string; expires_at: string };

const ROLES = ["associate", "paralegal", "partner", "owner"] as const;
const CAN_GRANT: Record<string, readonly string[]> = {
  owner: ROLES,
  partner: ["associate", "paralegal"],
};

/** Members of the firm, and invitations for colleagues who haven't signed up yet. */
export function TeamPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const myRole = workspace.orgs.find((o) => o.id === orgId)?.role ?? "";
  const grantable = CAN_GRANT[myRole] ?? [];
  const canManage = grantable.length > 0;

  const [members, setMembers] = useState<Member[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("associate");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      setMembers(await api<Member[]>(`/api/v1/organizations/${orgId}/members`, { token }));
      setInvitations(canManage ? await api<Invitation[]>(`/api/v1/organizations/${orgId}/invitations`, { token }) : []);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, token, canManage]);

  useEffect(() => {
    // Fetching on mount and whenever the org changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!orgId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api<{ invited?: boolean }>(`/api/v1/organizations/${orgId}/members`, {
        token,
        method: "POST",
        body: { email: email.trim(), role },
      });
      setMessage(
        result.invited
          ? `Invitation saved. Ask ${email.trim()} to create an account with this email at ${window.location.origin}; they'll join as ${role}.`
          : `${email.trim()} added as ${role}.`,
      );
      setEmail("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    if (!orgId) return;
    await api(`/api/v1/organizations/${orgId}/invitations/${id}`, { token, method: "DELETE" }).catch((e: Error) => setError(e.message));
    await load();
  }

  async function remove(member: Member) {
    if (!orgId || !window.confirm(`Remove ${member.email ?? "this member"} from the firm?`)) return;
    await api(`/api/v1/organizations/${orgId}/members/${member.user_id}`, { token, method: "DELETE" }).catch((e: Error) => setError(e.message));
    await load();
  }

  const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Team</h1>
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
        {canManage ? (
          <section className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <h2 className="font-medium text-slate-900 dark:text-slate-100">Invite a colleague</h2>
            <form onSubmit={invite} className="mt-3 flex flex-wrap gap-2">
              <input
                type="email"
                required
                placeholder="colleague@firm.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={`${field} min-w-0 flex-1`}
              />
              <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value)} className={field}>
                {grantable.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button disabled={busy} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                {busy ? "Inviting…" : "Invite"}
              </button>
            </form>
            <p className="mt-2 text-xs text-slate-500">
              Colleagues with an account join right away; others join when they sign up with this email.
            </p>
          </section>
        ) : null}

        {message ? <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">{message}</p> : null}
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}

        <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <h2 className="border-b border-slate-200 px-4 py-3 font-medium text-slate-900 dark:border-slate-800 dark:text-slate-100">
            Members ({members.length})
          </h2>
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {members.map((m) => (
              <li key={m.user_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-slate-900 dark:text-slate-100">{m.full_name || m.email}</div>
                  {m.full_name ? <div className="truncate text-xs text-slate-500">{m.email}</div> : null}
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs capitalize text-slate-700 dark:bg-slate-800 dark:text-slate-300">{m.role}</span>
                {canManage && grantable.includes(m.role) ? (
                  <button onClick={() => remove(m)} className="text-xs text-red-600 hover:underline">
                    Remove
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        {canManage && invitations.length ? (
          <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <h2 className="border-b border-slate-200 px-4 py-3 font-medium text-slate-900 dark:border-slate-800 dark:text-slate-100">
              Pending invitations ({invitations.length})
            </h2>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {invitations.map((i) => (
                <li key={i.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                  <div className="min-w-0 flex-1 truncate text-slate-900 dark:text-slate-100">{i.email}</div>
                  <span className="text-xs capitalize text-slate-500">{i.role}</span>
                  <span className="text-xs text-slate-400">until {new Date(i.expires_at).toLocaleDateString()}</span>
                  <button onClick={() => revoke(i.id)} className="text-xs text-red-600 hover:underline">
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </div>
  );
}
