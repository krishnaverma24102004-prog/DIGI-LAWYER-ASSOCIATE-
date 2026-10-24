"use client";

import { Suspense } from "react";

import { DocumentStudio } from "@/components/DocumentStudio";
import { SignIn } from "@/components/SignIn";
import { useAuth } from "@/hooks/useAuth";

export default function StudioPage() {
  const auth = useAuth();

  if (!auth.ready) return <div className="flex-1 bg-slate-50 dark:bg-slate-950" />;
  if (!auth.token) {
    return <SignIn supabaseConfigured={auth.supabaseConfigured} onSignIn={auth.signIn} onSignUp={auth.signUp} onToken={auth.useToken} />;
  }
  return (
    // useSearchParams (deep links) needs a Suspense boundary.
    <Suspense fallback={<div className="flex-1 bg-slate-50 dark:bg-slate-950" />}>
      <DocumentStudio token={auth.token} onSignOut={auth.signOut} />
    </Suspense>
  );
}
