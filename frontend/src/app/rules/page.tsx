"use client";

import { SignIn } from "@/components/SignIn";
import { RulesPage } from "@/components/RulesPage";
import { useAuth } from "@/hooks/useAuth";

export default function Rules() {
  const auth = useAuth();

  if (!auth.ready) return <div className="flex-1 bg-slate-50 dark:bg-slate-950" />;
  if (!auth.token) {
    return <SignIn supabaseConfigured={auth.supabaseConfigured} onSignIn={auth.signIn} onSignUp={auth.signUp} onToken={auth.useToken} />;
  }
  return <RulesPage token={auth.token} onSignOut={auth.signOut} />;
}
