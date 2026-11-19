"use client";
import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { publishingJSON } from "./api";

type Impact = { affected: {id: string; title: string | null; destination?: string | null; external_post_id?: string | null}[]; published_retained: number };
export function SourceDeletionWarning({ taskIds, clipId, onReady, onAffected }: { taskIds: string[]; clipId?: string | null; onReady: (ready: boolean) => void; onAffected?: (ids: string[]) => void }) {
  const [impact, setImpact] = useState<Impact | null>(null);
  const [ack, setAck] = useState(false);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const sourceKey = JSON.stringify(taskIds);
  useEffect(() => {
    const controller = new AbortController(); setImpact(null); setAck(false); setError(false); onReady(false); onAffected?.([]);
    void publishingJSON<Impact>("deletion-impact", { method: "POST", body: JSON.stringify({ task_ids: JSON.parse(sourceKey), ...(clipId ? {clip_id:clipId} : {}) }), signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.affected)) throw new Error("Invalid impact response");
        setImpact(data); onAffected?.(data.affected.map(upload => upload.id)); onReady(data.affected.length === 0);
      }).catch(() => { if (!controller.signal.aborted) { setError(true); onReady(false); } });
    return () => controller.abort();
  }, [sourceKey, clipId, onReady, onAffected, retry]);
  if (error) return <div role="alert" className="space-y-2 rounded-md border border-destructive/40 p-3 text-sm"><p>Could not check linked YouTube uploads. Check again before deleting.</p><Button size="sm" variant="outline" onClick={() => setRetry(value => value+1)}>Retry check</Button></div>;
  if (!impact) return <p role="status" className="text-sm text-muted-foreground">Checking linked uploads…</p>;
  return <div className="space-y-3 text-sm">
    {impact.affected.length > 0 && <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-3">
      <p className="flex items-start gap-2 font-medium"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{impact.affected.length} linked pending YouTube {impact.affected.length === 1 ? "upload" : "uploads"} will be permanently removed from YouTube.</p>
      <ul className="max-h-36 space-y-1 overflow-auto text-muted-foreground">{impact.affected.map(upload => <li key={upload.id} className="break-words">{upload.title || "Untitled Short"}{upload.destination ? ` · ${upload.destination}` : ""}</li>)}</ul>
      <p className="text-xs text-muted-foreground">This also stops the attached jobs. Removal may take time if YouTube is unavailable or needs reconnection; a video may publish before removal finishes. Track confirmation in Publishing. Deleted uploads cannot be restored.</p>
      <label className="flex items-start gap-2 font-medium"><input className="mt-1" type="checkbox" checked={ack} onChange={event => { setAck(event.target.checked); onReady(event.target.checked); }} />Delete the linked YouTube uploads too</label>
    </div>}
    {impact.published_retained > 0 && <p className="text-xs text-muted-foreground">{impact.published_retained} already published {impact.published_retained === 1 ? "video stays" : "videos stay"} on YouTube.</p>}
  </div>;
}
