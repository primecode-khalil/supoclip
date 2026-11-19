"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, RefreshCw, Settings2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { PublicationSettings, ReviewItem, SocialPost } from "@/lib/social";
import { PublishingError, publishingJSON } from "./api";
import { ReviewCard, type ApprovalEdit } from "./review-card";
import { PatternEditor } from "./pattern-editor";
import { PublicationQueue } from "./publication-queue";

type ReviewResponse = { items: ReviewItem[]; settings: PublicationSettings };
type Account = { id: string; display_name: string | null; status: string };
export function ReviewStudio({ account }: { account: Account }) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [posts, setPosts] = useState<SocialPost[]>([]);
  const [historyPosts, setHistoryPosts] = useState<SocialPost[]>([]);
  const [queueCursor, setQueueCursor] = useState<number | null>(null);
  const [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const [rejected, setRejected] = useState<ReviewItem[]>([]);
  const [settings, setSettings] = useState<PublicationSettings | null>(null);
  const [tab, setTab] = useState<"review" | "queue" | "history">("review");
  const [pattern, setPattern] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [undo, setUndo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const loadPosts = useCallback(async (signal?: AbortSignal, offset = 0) => {
    const result = await publishingJSON<{ posts: SocialPost[]; next_offset?: number | null }>(`posts?account_id=${account.id}&status_group=active&limit=100&offset=${offset}`, { signal });
    if (!signal?.aborted) { setPosts(old => offset ? [...old, ...result.posts.filter(p => !old.some(existing => existing.id === p.id))] : result.posts); setQueueCursor(result.next_offset ?? null); }
  }, [account.id]);
  const loadHistory = useCallback(async (signal?: AbortSignal, offset = 0) => {
    const result = await publishingJSON<{ posts: SocialPost[]; next_offset?: number | null }>(`posts?account_id=${account.id}&status_group=history&limit=50&offset=${offset}`, { signal });
    if (!signal?.aborted) { setHistoryPosts(old => offset ? [...old, ...result.posts] : result.posts); setHistoryCursor(result.next_offset ?? null); }
  }, [account.id]);
  const load = useCallback(async (signal?: AbortSignal) => {
    const data = await publishingJSON<ReviewResponse>(`review?account_id=${account.id}&limit=200`, { signal });
    if (!signal?.aborted) { setItems(data.items); setSettings(data.settings); }
  }, [account.id]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([load(controller.signal), loadPosts(controller.signal)]).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load publishing."); });
    return () => controller.abort();
  }, [load, loadPosts]);
  useEffect(() => {
    if (tab !== "queue") return;
    const controller = new AbortController();
    const timer = window.setInterval(() => { void loadPosts(controller.signal).catch(() => { if (!controller.signal.aborted) setError("Queue refresh failed. Your last confirmed state is shown."); }); }, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [tab, loadPosts]);
  useEffect(() => {
    if (tab !== "history") return;
    const controller = new AbortController();
    void loadHistory(controller.signal).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    void publishingJSON<ReviewResponse>(`review?account_id=${account.id}&status=rejected&limit=200`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setRejected(data.items); }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [tab, account.id, loadHistory]);
  const decide = async (action: "approve" | "reject", body: ApprovalEdit) => {
    if (inFlight.current || !items[0]) return;
    const item = items[0]; inFlight.current = true; setBusy(true); setError(null); setNotice(null);
    try {
      const result = await publishingJSON<{ item: ReviewItem; post?: SocialPost; settings?: PublicationSettings }>(`review/${item.id}/${action}`, { method: "POST", body: JSON.stringify(body) });
      setItems(old => old.filter(i => i.id !== item.id));
      if (result.settings) setSettings(result.settings);
      if (result.post) setPosts(old => [result.post!, ...old.filter(p => p.id !== result.post!.id)]);
      setUndo(action === "reject" ? item.id : null);
      setNotice(action === "reject" ? "Rejected. The video stays in your library." : "Approved. Uploading privately before confirming the YouTube schedule.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your decision. Try again.");
      if (err instanceof PublishingError && err.status === 409 && /video changed|render|review it again/i.test(err.message)) await load().catch(() => {});
    } finally { inFlight.current = false; setBusy(false); }
  };
  const restore = async (id: string) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try { await publishingJSON(`review/${id}/undo`, { method: "POST" }); await load(); setRejected(old => old.filter(item => item.id !== id)); setUndo(null); setNotice("Restored to review."); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not undo the rejection."); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const importClips = async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try { const result = await publishingJSON<ReviewResponse & { added: number }>("review/import", { method: "POST", body: JSON.stringify({ account_id: account.id, limit: 20 }) }); setItems(result.items); setSettings(result.settings); setNotice(`Added ${result.added} clips to review. No uploads started.`); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not import clips."); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const refreshPosts = () => { void loadPosts().catch(err => setError(err.message)); };
  const queued = posts.filter(p => !["published", "cancelled"].includes(p.status));

  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <nav aria-label="Publishing views" className="flex gap-1 rounded-lg border p-1">{(["review","queue","history"] as const).map(value => <Button key={value} size="sm" variant={tab === value ? "secondary" : "ghost"} aria-current={tab === value ? "page" : undefined} onClick={() => setTab(value)}>{value[0].toUpperCase()+value.slice(1)}{value === "review" ? ` (${items.length})` : value === "queue" ? ` (${queued.length})` : ""}</Button>)}</nav>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busy} onClick={() => void importClips()}>Import latest library clips</Button><Button variant="outline" size="sm" aria-expanded={pattern} onClick={() => setPattern(!pattern)}><Settings2 className="size-4" />Posting pattern</Button></div>
    </div>
    {error && <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{error}<Button className="ml-2" variant="ghost" size="sm" disabled={busy} onClick={() => { setError(null); void Promise.all([load(), loadPosts()]).catch(err => setError(err.message)); }}><RefreshCw className="size-3" />Refresh</Button></div>}
    {notice && <div role="status" className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"><CheckCircle2 className="size-4 shrink-0" /><span>{notice}</span>{undo && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void restore(undo)}><Undo2 className="size-3" />Undo rejection</Button>}</div>}
    {!settings ? !error && <Skeleton aria-label="Loading review" className="h-96 w-full" /> : <>
      {pattern && <PatternEditor key={account.id} accountId={account.id} settings={settings} onSaved={value => { setSettings(value); setNotice("Posting pattern saved. Existing schedules are unchanged."); }} />}
      {account.status !== "active" || !settings.permissions_complete ? <p className="rounded-lg border p-3 text-sm">
        Reconnect YouTube to grant schedule management access.{" "}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- OAuth requires full navigation. */}
        <a href="/api/social/connect/youtube" className="underline">Reconnect channel</a>
      </p> : null}
      {settings.policy.uploads_paused && <p className="rounded-lg border p-3 text-sm">Uploads are paused. Review and rejection remain available. Confirmed YouTube schedules keep publishing.</p>}
      {settings.policy.mode === "automatic" && <p className="rounded-lg border p-3 text-sm">Automatic approval is enabled for qualifying future live clips. Turn it off in Posting pattern to review every clip.</p>}
      {tab === "review" && (items[0] ? <ReviewCard key={`${items[0].id}:${items[0].version}`} item={items[0]} timezone={settings.policy.timezone} nextSlot={settings.next_slot} destination={account.display_name || "Your connected channel"} busy={busy} disabled={settings.policy.uploads_paused || !settings.permissions_complete || account.status !== "active"} onDecision={(action, body) => void decide(action, body)} onLater={() => setItems(old => old.length > 1 ? [...old.slice(1),old[0]] : old)} /> : <div className="rounded-xl border bg-background p-8 text-center"><CheckCircle2 className="mx-auto mb-3 size-6 text-muted-foreground" /><h2 className="font-semibold">You’re caught up</h2><p className="mt-2 text-sm text-muted-foreground">Import library clips, or connect this destination to a <Link className="underline" href="/recording">live channel</Link>. Clips wait here until you decide.</p></div>)}
      {tab === "queue" && <div className="space-y-3"><PublicationQueue posts={[...queued].sort((a,b) => (a.scheduled_for || "").localeCompare(b.scheduled_for || ""))} timezone={settings.policy.timezone} onRefresh={refreshPosts} />{queueCursor != null && <Button variant="outline" onClick={() => void loadPosts(undefined, queueCursor).catch(err => setError(err.message))}>Load more queued clips</Button>}</div>}
      {tab === "history" && <div className="space-y-5"><PublicationQueue posts={historyPosts} timezone={settings.policy.timezone} onRefresh={() => { refreshPosts(); void loadHistory().catch(err => setError(err.message)); }} history />{historyCursor != null && <Button variant="outline" onClick={() => void loadHistory(undefined, historyCursor).catch(err => setError(err.message))}>Load more history</Button>}{rejected.length > 0 && <section><h2 className="mb-3 font-semibold">Rejected · kept in your library</h2><ul className="divide-y rounded-xl border">{rejected.map(item => <li key={item.id} className="flex items-center justify-between gap-3 p-4"><span className="min-w-0 break-words text-sm">{item.title}</span><Button size="sm" variant="outline" disabled={busy} onClick={() => void restore(item.id)}>Restore to review</Button></li>)}</ul></section>}</div>}
    </>}
  </div>;
}
