"use client";

import { SignIn } from "@/components/SignIn";
import { WorkflowsPage } from "@/components/WorkflowsPage";
import { useAuth } from "@/hooks/useAuth";

export default function Workflows() {
  const auth = useAuth();

  if (!auth.ready) return <div className="flex-1 bg-slate-50 dark:bg-slate-950" />;
  if (!auth.token) {
    return <SignIn supabaseConfigured={auth.supabaseConfigured} onSignIn={auth.signIn} onSignUp={auth.signUp} onToken={auth.useToken} />;
  }
  return <WorkflowsPage token={auth.token} onSignOut={auth.signOut} />;
}
