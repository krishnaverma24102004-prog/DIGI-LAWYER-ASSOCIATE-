import { API_URL } from "./config";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    // Machine-readable reason when the API gives one ("legal_hold", "confirmation_required", ...).
    public code: string | null = null,
  ) {
    super(message);
  }
}

/** The API's `detail`: a message, a {code, message} object, or FastAPI's validation list. */
function errorDetail(detail: unknown, fallback: string): { message: string; code: string | null } {
  if (typeof detail === "string") return { message: detail, code: null };
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { message: string; code?: string };
    return { message: d.message, code: d.code ?? null };
  }
  if (Array.isArray(detail) && detail[0]?.msg) return { message: String(detail[0].msg), code: null };
  return { message: fallback, code: null };
}

/** Calls the Digi Lawyer API as the signed-in user, in the selected organization. */
export async function api<T>(
  path: string,
  { token, orgId, method = "GET", body }: { token: string; orgId?: string | null; method?: string; body?: unknown },
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (orgId) headers["X-Org-Id"] = orgId;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const { message, code } = errorDetail(data?.detail, `${response.status} ${response.statusText}`);
    throw new ApiError(message, response.status, code);
  }
  return data as T;
}

/** What a Delete button gets back: moved to the Trash, or sent to a partner/owner for approval. */
export type DeleteOutcome = {
  status: "trashed" | "approval_requested";
  message: string;
  trash_id?: string;
  restorable_until?: string;
};
