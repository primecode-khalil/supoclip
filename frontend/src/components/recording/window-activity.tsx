"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Loader2, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { dateTime, recordingJSON, type WindowList } from "./types";

const LABELS = { pending: "Waiting", submitting: "Uploading", processing: "Clipping", publishing: "Publishing", completed: "Completed", blocked: "Needs attention" };
export type ClearHistoryScope = "failed" | "finished";

export function WindowActivity({ data, error, onRetry, onClear }: { data: WindowList | null; error?: string; onRetry: (windowId: string) => Promise<void>; onClear?: (scope: ClearHistoryScope) => Promise<number> }) {
  const [progress, setProgress] = useState<Record<string, { progress?: number; progress_message?: string; status?: string }>>({});
  const [retrying, setRetrying] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [clearScope, setClearScope] = useState<ClearHistoryScope | null>(null);
  const [clearing, setClearing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  async function clearHistory() {
    if (!clearScope || !onClear) return;
    setClearing(true); setRetryError(null); setNotice(null);
    try {
      const count = await onClear(clearScope);
      setNotice(`${count} window${count === 1 ? "" : "s"} cleared. Captured recordings are kept.`);
    } catch (reason) {
      setRetryError(reason instanceof Error ? reason.message : "Unable to clear history.");
    } finally { setClearing(false); setClearScope(null); }
  }
  async function retry(windowId: string) {
    setRetrying(windowId); setRetryError(null);
    try { await onRetry(windowId); }
    catch (reason) { setRetryError(reason instanceof Error ? reason.message : "Unable to retry this window."); }
    finally { setRetrying(null); }
  }
  const activeIds = [...new Set((data?.windows ?? []).filter((item) => item.task_id && item.status === "processing").map((item) => item.task_id!))].slice(0, 3).join(",");
  useEffect(() => {
    if (!activeIds) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (!document.hidden) {
        const ids = activeIds.split(",");
        const results = await Promise.allSettled(ids.map((id) => recordingJSON<{ progress?: number; progress_message?: string; status?: string }>(`/api/tasks/${encodeURIComponent(id)}`, { signal: controller.signal })));
        if (controller.signal.aborted) return;
        const next: typeof progress = {};
        results.forEach((result, index) => { if (result.status === "fulfilled") next[ids[index]] = result.value; });
        setProgress(next);
      }
      timer = setTimeout(poll, 8_000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeIds]);
  return <section className="border-t pt-6" aria-labelledby="recording-activity">
    <div className="mb-3 flex items-center justify-between gap-3"><h3 id="recording-activity" className="text-sm font-semibold">Recent clip windows</h3>{data && <span className="text-xs tabular-nums text-muted-foreground">{data.total} total</span>}</div>
    {onClear && <div className="mb-3 flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={!data?.total || clearing || retrying !== null} onClick={() => setClearScope("failed")}>Clear failed</Button><Button size="sm" variant="outline" disabled={!data?.total || clearing || retrying !== null} onClick={() => setClearScope("finished")}>Clear all finished</Button></div>}
    <AlertDialog open={clearScope !== null} onOpenChange={(open) => { if (!open && !clearing) setClearScope(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{clearScope === "failed" ? "Clear failed windows?" : "Clear all finished windows?"}</AlertDialogTitle><AlertDialogDescription>{clearScope === "failed" ? "Removes failed entries from this channel’s history." : "Removes completed and failed entries from this channel’s history."} Active work continues. Captured recordings, library clips, and published posts are kept.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel disabled={clearing}>Cancel</AlertDialogCancel><AlertDialogAction disabled={clearing} onClick={(event) => { event.preventDefault(); void clearHistory(); }}>{clearing && <Loader2 className="mr-2 size-4 animate-spin" />}Clear history</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
    {notice && <p role="status" className="mb-3 text-xs text-muted-foreground">{notice}</p>}
    {error && <p role="status" className="mb-3 text-xs text-destructive">{error} Showing the last available activity.</p>}
    {retryError && <p role="alert" className="mb-3 text-xs text-destructive">{retryError}</p>}
    {!data ? <Skeleton className="h-20 w-full" /> : !data.windows.length ? <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">No finished recording windows yet. Clips appear after the first live segment is captured and processed.</p> : <div className="divide-y rounded-lg border">{data.windows.map((item) => {
      const task = item.task_id ? progress[item.task_id] : undefined;
      return <div key={item.id} className="space-y-2 p-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="text-sm font-medium">Window {item.sequence + 1}<span className="ml-2 font-normal text-muted-foreground">{Math.round((item.end_seconds - item.start_seconds) / 60)} min of source</span></p><p className="mt-0.5 text-xs text-muted-foreground">{dateTime(item.created_at)}</p></div><Badge variant={item.status === "blocked" ? "destructive" : "secondary"}>{LABELS[item.status]}</Badge></div>
        {task && <div className="space-y-1"><p className="text-xs text-muted-foreground">{task.progress_message || task.status || "Processing clips"}{typeof task.progress === "number" ? ` · ${Math.round(task.progress)}%` : ""}</p>{typeof task.progress === "number" && <Progress aria-label={`Window ${item.sequence + 1} progress`} value={task.progress} className="h-1" />}</div>}
        {item.last_error && <p className="break-words text-xs text-destructive">{item.last_error}</p>}
        {item.publication_capped && <p className="text-xs text-muted-foreground">Daily publishing limit reached. Remaining clips are saved in your library.</p>}
        {item.status === "blocked" && <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" aria-label={`Retry window ${item.sequence + 1}`} disabled={retrying !== null || clearing} onClick={() => void retry(item.id)}>{retrying === item.id ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}Retry window</Button><p className="text-xs text-muted-foreground">Resumes saved work and checks previous uploads.</p></div>}
        {item.next_attempt_at && item.status !== "blocked" && <p className="text-xs text-muted-foreground">Next attempt: {dateTime(item.next_attempt_at)}</p>}
        {item.task_id && <Link href={`/tasks/${encodeURIComponent(item.task_id)}`} className="inline-flex items-center gap-1 text-xs font-medium underline underline-offset-4">Open clips and generation<ArrowUpRight className="size-3" /></Link>}
      </div>;
    })}</div>}
  </section>;
}
