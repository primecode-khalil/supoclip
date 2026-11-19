export class PublishingError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function publishingJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/social/${path}`, { cache: "no-store", ...options,
    headers: { ...(options?.body ? { "Content-Type": "application/json" } : {}), ...options?.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail)
      ? body.detail.map((item: { msg?: string }) => item.msg || "Invalid setting").join(". ") : "Unable to update publishing. Please try again.";
    throw new PublishingError(message, response.status);
  }
  return body as T;
}
export function publicationTime(value: string | null, timezone: string) {
  if (!value) return "Waiting for a slot";
  try { return new Intl.DateTimeFormat(undefined, { timeZone: timezone, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value)); }
  catch { return value; }
}
