"use client";
import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SocialPost } from "@/lib/social";
import { publicationTime, publishingJSON } from "./api";

export function publicationLabel(post: SocialPost) {
  if (post.stage === "deleted") return "Deleted from YouTube";
  if ((post.provider_options?.delete_remote || post.stage === "deleting" || (post.provider_options?.native_schedule && post.clip_id === null && !["published","cancelled"].includes(post.status))) && post.status !== "cancelled") return "Deletion pending · YouTube copy may still be live";
  if (post.status === "cancelled") return "Cancelled · kept private";
  if (post.provider_options?.cancel_requested && post.status !== "published") return "Cancellation pending · check YouTube until confirmed";
  if (post.status === "failed") return "Needs attention";
  if (post.status === "published") return post.actual_visibility === "private" ? "Ready · private" : "Published";
  if (post.stage === "youtube_scheduled") return "Scheduled on YouTube";
  if (post.stage === "scheduling") return "Confirming YouTube schedule";
  if (post.stage === "waiting_for_quota") return "Waiting for YouTube quota";
  if (post.stage === "paused") return "Uploads paused";
  if (post.stage === "processing") return "YouTube is processing";
  if (post.stage === "uploading") return "Uploading privately";
  return "Queued for private upload";
}
export function PublicationQueue({ posts, timezone, onRefresh, history = false }: { posts: SocialPost[]; timezone: string; onRefresh: () => void; history?: boolean }) {
  if (!posts.length) return <div className="rounded-xl border p-8 text-center text-sm text-muted-foreground">{history ? "No publication history yet." : "No approved clips waiting. Approve a clip in Review to reserve its next slot."}</div>;
  return <div className="divide-y rounded-xl border bg-background">{posts.map(post => <QueueRow key={post.id} post={post} timezone={timezone} onRefresh={onRefresh} />)}</div>;
}
function QueueRow({ post, timezone, onRefresh }: { post: SocialPost; timezone: string; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [when, setWhen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = async (action: string) => {
    if (busy) return; setBusy(true); setError(null);
    try { await publishingJSON(`posts/${post.id}/${action}`, { method: "POST", ...(action === "reschedule" ? { body: JSON.stringify({ custom_local: when }) } : {}) }); setEditing(false); onRefresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not update this publication."); }
    finally { setBusy(false); }
  };
  const cancel = !["published", "cancelled"].includes(post.status) && !post.provider_options?.cancel_requested;
  const progress = post.total_bytes ? Math.min(100, Math.round((post.confirmed_bytes || 0) / post.total_bytes * 100)) : null;
  return <article className="min-w-0 p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1"><h3 className="break-words font-medium">{post.title || "Untitled Short"}</h3><p className="mt-1 text-sm text-muted-foreground">{publicationLabel(post)}</p><p className="mt-2 text-sm">{publicationTime(post.scheduled_for, timezone)} · {timezone}</p></div>
      {post.external_url && post.stage !== "deleted" && <a href={post.external_url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-sm underline underline-offset-4">View on YouTube<ExternalLink className="size-3" /></a>}
    </div>
    {post.stage === "uploading" && progress !== null && <div className="mt-3 flex items-center gap-3"><progress aria-label="Upload progress" max={100} value={progress} className="h-2 w-full" /><span className="text-xs tabular-nums">{progress}%</span></div>}
    {post.error_message && <p className="mt-3 break-words text-sm text-destructive">{post.error_message}</p>}
    {post.next_attempt_at && post.stage === "waiting_for_quota" && <p className="mt-2 text-xs text-muted-foreground">Next check: {publicationTime(post.next_attempt_at, timezone)}</p>}
    {post.provider_options?.cancel_requested && post.status !== "cancelled" && post.status !== "published" && <p className="mt-2 text-xs text-muted-foreground">If reconnection is needed, the existing schedule may still publish. <a className="underline" href="https://studio.youtube.com" target="_blank" rel="noreferrer">Check YouTube Studio</a>.</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      {cancel && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act("cancel")}>Cancel schedule</Button>}
      {cancel && post.provider_options?.native_schedule && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(!editing)}>Reschedule</Button>}
      {post.status === "failed" && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act("retry")}>Retry saved work</Button>}
    </div>
    {editing && <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void act("reschedule"); }}><label className="min-w-0 space-y-2 text-sm">New time ({timezone})<Input aria-label="New publication time" type="datetime-local" required value={when} onChange={e => setWhen(e.target.value)} /></label><Button size="sm" disabled={busy} type="submit">Update time</Button></form>}
    {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
  </article>;
}
