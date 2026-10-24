import { API_URL } from "./config";

/** Downloads an API file that needs the auth header (so a plain link won't do). */
export async function downloadWithAuth(path: string, token: string, orgId: string | null, fallbackName: string) {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (orgId) headers["X-Org-Id"] = orgId;
  const response = await fetch(`${API_URL}${path}`, { headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Download failed (${response.status})`);
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
