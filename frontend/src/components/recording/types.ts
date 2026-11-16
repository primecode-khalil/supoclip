import type { SocialConnection } from "@/lib/social";

export type RecordingPlatform = "twitch" | "kick" | "youtube";
export interface RecordingChannel {
  id: string; platform: RecordingPlatform; handle: string; url: string; name: string;
  enabled: boolean; quality: string; created_at: string; updated_at: string;
}
export interface AutomationPolicy {
  enabled: boolean; segment_seconds: number; overlap_seconds: number;
  processing_mode: "fast" | "balanced" | "quality"; caption_template: string;
  clip_length: "auto" | "short" | "medium" | "long"; min_score: number;
  max_clips_per_window: number; max_posts_per_day: number; social_account_ids: string[];
  publish_privacy: "private" | "public" | "unlisted"; archive: boolean; retain_days: number;
}
export const DEFAULT_POLICY: AutomationPolicy = {
  enabled: false, segment_seconds: 600, overlap_seconds: 60, processing_mode: "balanced",
  caption_template: "default", clip_length: "auto", min_score: 75, max_clips_per_window: 3,
  max_posts_per_day: 10, social_account_ids: [], publish_privacy: "private", archive: false, retain_days: 7,
};
export interface AutomationState {
  policy: AutomationPolicy;
  runtime: { leased: boolean; expires_at: string | null; last_heartbeat_at: string | null; last_error: string | null };
}
export interface RecordingSession {
  id: string; status: "created" | "recording" | "interrupted" | "completed" | "failed" | "cancelled";
  started_at: string | null; ended_at: string | null; created_at: string;
}
export interface RecordingWindow {
  id: string; session_id: string; epoch: string; sequence: number;
  start_seconds: number; end_seconds: number; status: "pending" | "submitting" | "processing" | "publishing" | "completed" | "blocked";
  task_id: string | null; attempts: number; next_attempt_at: string | null; last_error: string | null;
  publication_capped?: boolean;
  created_at: string;
}
export interface WindowList { windows: RecordingWindow[]; total: number }
export interface SessionList { sessions: RecordingSession[]; total: number }

export async function recordingJSON<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...init, signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(20_000)]) : AbortSignal.timeout(20_000) });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail :
      Array.isArray(data?.detail) ? data.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(". ") : null;
    throw new Error(detail || (response.status === 401 ? "Your session expired. Sign in again." : "Unable to load recording data. Please try again."));
  }
  return data as T;
}

export const SELECT_STYLE = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
export const CAPTION_OPTIONS = ["default", "hormozi", "mrbeast", "minimal", "tiktok", "neon", "podcast"];

export function publicationError(policy: AutomationPolicy, connections: SocialConnection[]): string | null {
  const instagram = connections.some((account) => account.provider === "instagram" && policy.social_account_ids.includes(account.id));
  return instagram && policy.publish_privacy !== "public"
    ? "Instagram requires Public visibility. Choose Public or uncheck the Instagram account."
    : null;
}

export function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}
