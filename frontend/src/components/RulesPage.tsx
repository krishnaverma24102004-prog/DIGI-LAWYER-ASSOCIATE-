"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useWorkspace } from "@/hooks/useWorkspace";
import { api } from "@/lib/api";

type Signature = { verified_by: string; verified_at: string; note: string | null };
type Rule = {
  rule_id: string;
  version: number;
  title: string | null;
  basis: string | null;
  signatures: Signature[];
  active: boolean;
  signed_by_me: boolean;
};
type Member = { user_id: string; email: string | null; full_name: string | null };

const REGISTRIES = [
  { key: "limitation", label: "Limitation periods", used: "the limitation calculator" },
  { key: "offence_punishments", label: "Punishments (default bail, s.479 BNSS)", used: "the custody board" },
] as const;

/** The firm's two-signature check of the statutory rule tables before they are relied on. */
export function RulesPage({ token, onSignOut }: { token: string; onSignOut: () => void }) {
  const workspace = useWorkspace(token);
  const { orgId } = workspace;
  const myRole = workspace.orgs.find((o) => o.id === orgId)?.role ?? "";
  const canSign = myRole !== "paralegal";

  const [registry, setRegistry] = useState<(typeof REGISTRIES)[number]["key"]>("limitation");
  const [rules, setRules] = useState<Rule[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [filter, setFilter] = useState<"all" | "pending" | "active">("pending");
  const [signing, setSigning] = useState<Rule | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    try {
      const [r, m] = await Promise.all([
        api<Rule[]>(`/api/v1/rules/${registry}`, { token, orgId }),
        api<Member[]>(`/api/v1/organizations/${orgId}/members`, { token }),
      ]);
      setRules(r);
      setMembers(m);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [orgId, token, registry]);

  useEffect(() => {
    // Fetching on mount and whenever the org or registry changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const name = (id: string) => {
    const m = members.find((x) => x.user_id === id);
    return m?.full_name || m?.email || "a former member";
  };

  async function sign() {
    if (!signing) return;
    setBusy(true);
    setDialogError(null);
    try {
      await api(`/api/v1/rules/${registry}/${encodeURIComponent(signing.rule_id)}/sign`, {
        token,
        orgId,
        method: "POST",
        body: { version: signing.version, confirm: true, note: note || null },
      });
      setSigning(null);
      setNote("");
      await load();
    } catch (e) {
      setDialogError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const shown = rules.filter((r) => filter === "all" || (filter === "active" ? r.active : !r.active));
  const activeCount = rules.filter((r) => r.active).length;
  const field = "rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  const used = REGISTRIES.find((r) => r.key === registry)?.used;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          ← Consultations
        </Link>
        <h1 className="font-semibold text-slate-900 dark:text-slate-100">Rule sign-off</h1>
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

      <main className="mx-auto flex w-full max-w-4xl flex-col gap-4 overflow-y-auto p-4">
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          These tables were written from the statutes by the software team. A rule is used by {used} in your firm only after two of
          your advocates have checked it against the bare act and signed it. A new version needs signing again.
        </p>
        {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p> : null}

        <div className="flex flex-wrap items-center gap-2">
          {REGISTRIES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRegistry(r.key)}
              className={`rounded-lg px-3 py-1.5 text-sm ${registry === r.key ? "bg-indigo-600 text-white" : "bg-white text-slate-700 dark:bg-slate-900 dark:text-slate-200"}`}
            >
              {r.label}
            </button>
          ))}
          <span className="ml-auto text-sm text-slate-500">
            {activeCount} of {rules.length} in use
          </span>
          <select aria-label="Show" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className={field}>
            <option value="pending">Needs signatures</option>
            <option value="active">In use</option>
            <option value="all">All</option>
          </select>
        </div>

        <ul className="flex flex-col gap-2">
          {shown.map((r) => (
            <li key={r.rule_id} className="rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-slate-900 dark:text-slate-100">
                    {r.title ?? r.rule_id} <span className="text-xs font-normal text-slate-400">v{r.version}</span>
                  </div>
                  {r.basis ? <p className="mt-1 text-slate-600 dark:text-slate-400">{r.basis}</p> : null}
                  <p className="mt-1 text-xs text-slate-500">
                    {r.signatures.length
                      ? `Signed by ${r.signatures.map((s) => `${name(s.verified_by)} (${new Date(s.verified_at).toLocaleDateString()})`).join(", ")}`
                      : "No signatures yet"}
                  </p>
                </div>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    r.active ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300" : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                  }`}
                >
                  {r.active ? "In use" : `${r.signatures.length}/2 signatures`}
                </span>
                {canSign && !r.signed_by_me ? (
                  <button onClick={() => setSigning(r)} className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700">
                    Check and sign…
                  </button>
                ) : r.signed_by_me ? (
                  <span className="text-xs text-slate-400">You signed</span>
                ) : null}
              </div>
            </li>
          ))}
          {shown.length === 0 ? <li className="py-6 text-center text-sm text-slate-500">Nothing to show.</li> : null}
        </ul>
      </main>

      {signing ? (
        <ConfirmDialog
          title={`Sign “${signing.title ?? signing.rule_id}” (v${signing.version})?`}
          confirmLabel="I checked it: sign"
          busy={busy}
          error={dialogError}
          onCancel={() => setSigning(null)}
          onConfirm={sign}
          facts={[
            { label: "You confirm", value: "You checked this rule against the statute and it is correct as written." },
            { label: "What happens", value: "With a second advocate's signature, the rule is used in your firm's computations." },
            { label: "Recorded", value: "Your name, the time and your note, in the audit log." },
          ]}
        >
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional), e.g. checked against the 1963 Act" className={`${field} w-full`} />
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
