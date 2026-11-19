"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Clock, SkipForward, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ReviewItem } from "@/lib/social";
import { publicationTime } from "./api";

export type ApprovalEdit = { expected_version: string; title: string; caption: string; youtube_tags: string[]; custom_local?: string };
export function ReviewCard({ item, timezone, nextSlot, destination, busy, disabled, onDecision, onLater }: {
  item: ReviewItem; timezone: string; nextSlot: string; destination: string; busy: boolean; disabled: boolean;
  onDecision: (action: "approve" | "reject", body: ApprovalEdit) => void; onLater: () => void;
}) {
  const [title, setTitle] = useState(item.title);
  const [caption, setCaption] = useState(item.caption);
  const [tagsInput, setTagsInput] = useState((item.youtube_tags || []).join(", "));
  const youtubeTags = useMemo(() => [...new Map(tagsInput.split(",").map(value => value.normalize("NFKC").trim().replace(/^#+/, "").trim())
    .filter(Boolean).map(tag => [tag.toLowerCase(), tag])).values()], [tagsInput]);
  const tagsError = youtubeTags.length > 8 ? "Use at most 8 tags." : youtubeTags.some(tag => [...tag].length > 60) ? "Keep each tag within 60 characters." : "";
  const [custom, setCustom] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);
  const decide = useCallback((action: "approve" | "reject") => {
    if (busy || (action === "approve" && (disabled || tagsError))) return;
    onDecision(action, { expected_version: item.version, title, caption, youtube_tags: youtubeTags, ...(custom ? { custom_local: custom } : {}) });
  }, [busy, disabled, tagsError, onDecision, item.version, title, caption, youtubeTags, custom]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.repeat || event.metaKey || event.ctrlKey || event.altKey || target?.closest("input,textarea,select,[contenteditable],[role=dialog]") || busy) return;
      if (["a", "r"].includes(event.key.toLowerCase())) {
        event.preventDefault(); decide(event.key.toLowerCase() === "a" ? "approve" : "reject");
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [decide, busy]);
  return <div className="grid min-w-0 overflow-hidden rounded-xl border bg-background lg:grid-cols-2">
    <div className="flex min-w-0 justify-center bg-muted/40 p-3 sm:p-6">
      <video key={item.video_url} aria-label="Clip preview" controls playsInline preload="metadata" src={item.video_url || undefined}
        className="aspect-[9/16] max-h-[65vh] w-auto max-w-full rounded-lg bg-black object-contain lg:max-h-[70vh]" />
    </div>
    <div className="flex min-w-0 flex-col gap-5 p-4 sm:p-6">
      <div><p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Review this clip</p>
        <h2 ref={heading} tabIndex={-1} className="mt-2 break-words text-xl font-semibold outline-none">{item.title}</h2>
        <p className="mt-1 break-words text-sm text-muted-foreground">{item.source_title || "From your library"}{item.score != null ? ` · Score ${Math.round(item.score)}` : ""}{item.duration != null ? ` · ${Math.round(item.duration)}s` : ""}</p>
      </div>
      <label className="space-y-2 text-sm font-medium">Title<Input maxLength={100} value={title} disabled={busy} onChange={e => setTitle(e.target.value)} /></label>
      <label className="space-y-2 text-sm font-medium">Description<Textarea maxLength={2200} rows={4} value={caption} disabled={busy} onChange={e => setCaption(e.target.value)} className="resize-y" /></label>
      <div className="space-y-2">
        <label htmlFor="youtube-tags" className="text-sm font-medium">YouTube tags</label>
        <Input id="youtube-tags" value={tagsInput} disabled={busy} onChange={e => setTagsInput(e.target.value)} aria-invalid={!!tagsError} aria-describedby="youtube-tags-help youtube-tags-error" />
        <p id="youtube-tags-help" className="text-xs text-muted-foreground">Suggested from this clip. Separate with commas; keep only accurate topics or names. Up to 8 tags, 60 characters each. Leave empty for none.</p>
        {tagsError && <p id="youtube-tags-error" role="alert" className="text-sm text-destructive">{tagsError}</p>}
      </div>
      <div className="rounded-lg border bg-muted/30 p-3 text-sm">
        <p className="font-medium break-words">{destination} · YouTube Shorts</p>
        <p className="mt-1 flex items-start gap-2 text-muted-foreground"><Clock className="mt-0.5 size-4 shrink-0" /><span>{custom ? `${custom.replace("T", " ")} · ${timezone}` : `${publicationTime(nextSlot, timezone)} · ${timezone}`}</span></p>
        <p className="mt-2 text-xs text-muted-foreground">Uploads privately now. Publishes at the confirmed time on YouTube. A late upload moves to the next free slot.</p>
      </div>
      <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Choose a different time for this clip</summary>
        <label className="mt-3 block space-y-2">Publication time ({timezone})<Input aria-label="Custom publication time" type="datetime-local" value={custom} onChange={e => setCustom(e.target.value)} disabled={busy} /></label>
        <p className="mt-2 text-xs text-muted-foreground">Leave empty to use the next slot. Allow at least 15 minutes for uploading and processing.</p>
      </details>
      <div className="mt-auto space-y-3 pt-2">
        <Button className="h-auto min-h-11 w-full whitespace-normal" disabled={busy || disabled || !!tagsError || !item.video_url} onClick={() => decide("approve")}><Check className="size-4 shrink-0" />{busy ? "Saving decision…" : "Approve & schedule"}</Button>
        <div className="grid grid-cols-2 gap-3"><Button variant="outline" disabled={busy} onClick={() => decide("reject")}><X className="size-4" />Reject</Button><Button variant="ghost" disabled={busy} onClick={onLater}><SkipForward className="size-4" />Later</Button></div>
        <p className="text-xs text-muted-foreground">A approve · R reject · Rejected clips stay in your library.</p>
      </div>
    </div>
  </div>;
}
