"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useStoredValue } from "@/lib/storage";
import type { Organization } from "@/lib/types";

/** The organization and jurisdiction the user is working in, remembered across pages. */
export function useWorkspace(token: string) {
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [savedOrgId, setOrgId] = useStoredValue("dl.org", null);
  const [jurisdiction, setJurisdictionValue] = useStoredValue("dl.jurisdiction", "IN");

  useEffect(() => {
    api<Organization[]>("/api/v1/organizations", { token })
      .then(setOrgs)
      .catch((e: Error) => setError(e.message));
  }, [token]);

  // The remembered org if the user still belongs to it, else their active org.
  const orgId = (orgs.find((o) => o.id === savedOrgId) ?? orgs.find((o) => o.is_active) ?? orgs[0])?.id ?? null;

  return {
    orgs,
    orgId,
    setOrgId: useCallback((id: string) => setOrgId(id), [setOrgId]),
    jurisdiction: jurisdiction ?? "IN",
    setJurisdiction: useCallback((code: string) => setJurisdictionValue(code), [setJurisdictionValue]),
    error,
  };
}
