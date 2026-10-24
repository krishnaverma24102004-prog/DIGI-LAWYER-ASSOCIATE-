import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./config";

let client: SupabaseClient | null = null;

/** The browser Supabase client (auth only; all data goes through the API). Null if not configured. */
export function getSupabase(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return null;
  client ??= createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return client;
}
