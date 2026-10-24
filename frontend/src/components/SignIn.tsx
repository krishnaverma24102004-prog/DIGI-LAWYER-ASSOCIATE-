"use client";

import { useState } from "react";

type SignUpDetails = { fullName: string; firmName: string; email: string; password: string };

export function SignIn({
  supabaseConfigured,
  onSignIn,
  onSignUp,
  onToken,
}: {
  supabaseConfigured: boolean;
  onSignIn: (email: string, password: string) => Promise<void>;
  onSignUp: (details: SignUpDetails) => Promise<boolean>;
  onToken: (token: string) => void;
}) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [fullName, setFullName] = useState("");
  const [firmName, setFirmName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const signingUp = mode === "signup";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (signingUp) {
        const needsConfirmation = await onSignUp({ fullName: fullName.trim(), firmName: firmName.trim(), email, password });
        if (needsConfirmation) {
          setNotice("Account created. Check your email to confirm it, then sign in.");
          setMode("signin");
        }
      } else {
        await onSignIn(email, password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  function switchMode() {
    setMode(signingUp ? "signin" : "signup");
    setError(null);
    setNotice(null);
  }

  const input =
    "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

  return (
    <main className="flex min-h-full flex-1 items-center justify-center bg-slate-50 px-4 py-12 dark:bg-slate-950">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Digi Lawyer</h1>
        <p className="mt-1 text-sm text-slate-500">
          {signingUp ? "Create your firm's workspace." : "Sign in to your firm's workspace."}
        </p>

        {supabaseConfigured ? (
          <form onSubmit={submit} className="mt-6 flex flex-col gap-3">
            {signingUp ? (
              <>
                <input className={input} placeholder="Your name" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
                <input
                  className={input}
                  placeholder="Firm name (e.g. Sharma & Associates)"
                  autoComplete="organization"
                  value={firmName}
                  onChange={(e) => setFirmName(e.target.value)}
                />
              </>
            ) : null}
            <input className={input} type="email" placeholder="Email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <input
              className={input}
              type="password"
              placeholder={signingUp ? "Password (at least 8 characters)" : "Password"}
              autoComplete={signingUp ? "new-password" : "current-password"}
              minLength={signingUp ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {busy ? (signingUp ? "Creating…" : "Signing in…") : signingUp ? "Create account" : "Sign in"}
            </button>
            {signingUp ? (
              <p className="text-xs text-slate-500">Invited by your firm? Use the email the invitation was sent to and you&apos;ll join it.</p>
            ) : null}
            <button type="button" onClick={switchMode} className="text-sm text-indigo-700 hover:underline dark:text-indigo-300">
              {signingUp ? "Already have an account? Sign in" : "New here? Create an account"}
            </button>
          </form>
        ) : (
          <div className="mt-6 flex flex-col gap-3">
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Supabase isn&apos;t configured in <code>.env.local</code>. For development, paste an access token.
            </p>
            <input className={input} placeholder="Supabase access token" value={token} onChange={(e) => setToken(e.target.value)} />
            <button
              onClick={() => token.trim() && onToken(token.trim())}
              className="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700"
            >
              Continue
            </button>
          </div>
        )}
        {notice ? <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">{notice}</p> : null}
        <a href="/about" className="mt-4 block text-center text-xs text-slate-400 hover:text-slate-600">
          About, data handling and sources
        </a>
        {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
      </div>
    </main>
  );
}
