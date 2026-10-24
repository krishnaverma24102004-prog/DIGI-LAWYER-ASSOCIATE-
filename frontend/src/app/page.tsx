"use client";

import { ChatRoom } from "@/components/ChatRoom";
import { SignIn } from "@/components/SignIn";
import { useAuth } from "@/hooks/useAuth";

export default function Home() {
  const auth = useAuth();

  if (!auth.ready) return <div className="flex-1 bg-slate-50 dark:bg-slate-950" />;
  if (!auth.token) {
    return <SignIn supabaseConfigured={auth.supabaseConfigured} onSignIn={auth.signIn} onSignUp={auth.signUp} onToken={auth.useToken} />;
  }
  return <ChatRoom token={auth.token} email={auth.email} onSignOut={auth.signOut} />;
}
