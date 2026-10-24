"use client";

import type { Session } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";

import { useStoredValue } from "@/lib/storage";
import { getSupabase } from "@/lib/supabase";

/** Supabase email/password session. Without Supabase configured, a pasted access token works for development. */
export function useAuth() {
  const supabase = getSupabase();
  const [session, setSession] = useState<Session | null>(null);
  // A pasted development token survives navigation between pages (this tab only).
  const [manualToken, setManualToken] = useStoredValue("dl.devToken", null, "session");
  const [ready, setReady] = useState(!supabase);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, [supabase]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (!supabase) throw new Error("Supabase is not configured (NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY)");
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
    },
    [supabase],
  );

  /** Create an account. Returns true when Supabase wants the email confirmed before signing in. */
  const signUp = useCallback(
    async (details: { fullName: string; firmName: string; email: string; password: string }) => {
      if (!supabase) throw new Error("Supabase is not configured (NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY)");
      const { data, error } = await supabase.auth.signUp({
        email: details.email,
        password: details.password,
        // The database names the new workspace after the firm (migration 009), unless the person was invited.
        options: { data: { full_name: details.fullName, firm_name: details.firmName } },
      });
      if (error) throw error;
      return !data.session;
    },
    [supabase],
  );

  const signOut = useCallback(async () => {
    setManualToken(null);
    await supabase?.auth.signOut();
  }, [supabase, setManualToken]);

  return {
    ready,
    supabaseConfigured: Boolean(supabase),
    token: session?.access_token ?? manualToken,
    email: session?.user.email ?? (manualToken ? "token session" : null),
    signIn,
    signUp,
    signOut,
    useToken: setManualToken,
  };
}
