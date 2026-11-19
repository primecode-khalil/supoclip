"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { connectionLabel, PROVIDER_LABELS, type SocialConnection } from "@/lib/social";
import { CAPTION_OPTIONS, SELECT_STYLE, publicationError, type AutomationPolicy } from "./types";

interface Props {
  policy: AutomationPolicy; connections: SocialConnection[]; connectionError: string | null;
  onSave: (policy: AutomationPolicy) => Promise<void>;
}

export function PolicyForm({ policy, connections, connectionError, onSave }: Props) {
  const [draft, setDraft] = useState(policy);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (!dirty) setDraft(policy); }, [policy, dirty]);
  function edit<K extends keyof AutomationPolicy>(key: K, value: AutomationPolicy[K]) {
    setDraft((current) => ({ ...current, [key]: value })); setDirty(true); setSaved(false);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError(null); setSaved(false);
    if (draft.overlap_seconds >= draft.segment_seconds) { setError("Overlap must be shorter than the segment."); return; }
    const visibilityError = publicationError(draft, connections);
    if (visibilityError) { setError(visibilityError); return; }
    setSaving(true);
    try { await onSave({ ...draft, enabled: policy.enabled }); setDirty(false); setSaved(true); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to save settings."); }
    finally { setSaving(false); }
  }
  const number = (key: "segment_seconds" | "overlap_seconds" | "min_score" | "max_posts_per_day" | "retain_days" | "max_clips_per_window", label: string, min: number, max: number) => (
    <div className="space-y-1.5"><Label htmlFor={`recording-${key}`}>{label}</Label><Input id={`recording-${key}`} type="number" min={min} max={max} step={key === "min_score" ? "any" : 1} value={draft[key]} onChange={(event) => edit(key, Number(event.target.value))} required /></div>
  );
  return (
    <form onSubmit={submit} className="space-y-6" aria-label="Automation settings">
      <fieldset disabled={saving} className="space-y-6">
        <legend className="mb-4 text-sm font-semibold">Clip settings</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {number("segment_seconds", "Segment length (seconds)", 60, 1800)}
          {number("overlap_seconds", "Overlap (seconds)", 0, 120)}
          {number("min_score", "Minimum clip score", 0, 100)}
          <div className="space-y-1.5"><Label htmlFor="recording-template">Caption style</Label><select id="recording-template" className={SELECT_STYLE} value={draft.caption_template} onChange={(event) => edit("caption_template", event.target.value)}>{CAPTION_OPTIONS.map((name) => <option key={name} value={name}>{name === "default" ? "Default" : name[0].toUpperCase() + name.slice(1)}</option>)}</select></div>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">Each finished window becomes a vertical video generation with captions. Overlap keeps moments that cross a recording boundary together.</p>
        <div className="space-y-3 border-t pt-5">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">Publishing destinations</h3><Link href="/settings/social" className="text-xs font-medium underline underline-offset-4">Manage connected accounts</Link></div>
          <p className="text-xs text-muted-foreground">Choose where qualifying clips go. YouTube destinations with a review policy wait for approval in Publishing. Existing source rules remain until you save a destination policy. Leave all accounts unchecked to keep clips in your library.</p>
          {connectionError ? <p role="status" className="text-xs text-destructive">{connectionError} Your saved destinations will be preserved.</p> : connections.length === 0 ? <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">No connected accounts. Connect YouTube or Instagram to enable publishing.</p> : (
            <div className="space-y-2">{connections.map((account) => {
              const eligible = account.status === "active" && account.provider !== "tiktok";
              return <label key={account.id} className="flex items-start gap-3 rounded-lg border p-3 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-current" checked={draft.social_account_ids.includes(account.id)} disabled={!eligible && !draft.social_account_ids.includes(account.id)} onChange={(event) => edit("social_account_ids", event.target.checked ? [...draft.social_account_ids, account.id] : draft.social_account_ids.filter((id) => id !== account.id))} /><span className="min-w-0"><span className="block break-words font-medium">{connectionLabel(account)}</span><span className="block text-xs text-muted-foreground">{PROVIDER_LABELS[account.provider]}{account.provider === "tiktok" ? " · Automated posting requires a supported consent flow" : account.status !== "active" ? " · Reconnect required" : ""}</span></span></label>;
            })}</div>
          )}
          {!connectionError && draft.social_account_ids.filter((id) => !connections.some((account) => account.id === id)).map((id) => <label key={id} className="flex items-center gap-3 rounded-lg border p-3 text-sm"><input type="checkbox" className="size-4 accent-current" checked onChange={() => edit("social_account_ids", draft.social_account_ids.filter((value) => value !== id))} /><span>Unavailable saved account<span className="block text-xs text-muted-foreground">Uncheck to remove this destination.</span></span></label>)}
          <div className="grid gap-4 sm:grid-cols-2">
            {number("max_posts_per_day", "Maximum posts per day", 1, 100)}
            <div className="space-y-1.5"><Label htmlFor="recording-privacy">Publication visibility</Label><select id="recording-privacy" value={draft.publish_privacy} className={SELECT_STYLE} onChange={(event) => edit("publish_privacy", event.target.value as AutomationPolicy["publish_privacy"])}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></div>
          </div>
          <p className="text-xs text-muted-foreground">Instagram requires Public visibility. Keep Instagram unchecked to publish privately to YouTube.</p>
        </div>
        <details className="border-t pt-4"><summary className="cursor-pointer text-sm font-medium">More settings</summary><div className="mt-4 space-y-4"><div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="recording-mode">Processing quality</Label><select id="recording-mode" value={draft.processing_mode} className={SELECT_STYLE} onChange={(event) => edit("processing_mode", event.target.value as AutomationPolicy["processing_mode"])}><option value="fast">Fast</option><option value="balanced">Balanced</option><option value="quality">Quality</option></select></div>
          <div className="space-y-1.5"><Label htmlFor="recording-length">Clip length</Label><select id="recording-length" value={draft.clip_length} className={SELECT_STYLE} onChange={(event) => edit("clip_length", event.target.value as AutomationPolicy["clip_length"])}><option value="auto">Auto</option><option value="short">15–30 seconds</option><option value="medium">30–60 seconds</option><option value="long">60–120 seconds</option></select></div>
          {number("max_clips_per_window", "Maximum clips per window", 1, 10)}
          {number("retain_days", "Originals retention (days)", 1, 365)}
        </div><label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-current" checked={draft.archive} onChange={(event) => edit("archive", event.target.checked)} /><span>Keep an offsite copy of originals<span className="mt-1 block text-xs text-muted-foreground">Requires an archive destination in server setup. Unfinished work is retained until it completes.</span></span></label></div></details>
      </fieldset>
      {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
      <div className="flex items-center gap-3 border-t pt-4"><Button disabled={saving || !dirty} type="submit">{saving && <Loader2 className="size-4 animate-spin" />}Save settings</Button><span role="status" className="text-xs text-muted-foreground">{saved ? <span className="inline-flex items-center gap-1"><Check className="size-3.5" />Settings saved</span> : dirty ? "Unsaved changes" : ""}</span></div>
    </form>
  );
}
