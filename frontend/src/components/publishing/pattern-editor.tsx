"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PublicationPolicy, PublicationSettings } from "@/lib/social";
import { publishingJSON } from "./api";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export function PatternEditor({ accountId, settings, onSaved }: { accountId: string; settings: PublicationSettings; onSaved: (value: PublicationSettings) => void }) {
  const [draft, setDraft] = useState(settings.policy);
  const [times, setTimes] = useState(settings.policy.schedule.times.join(", "));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const field = <K extends keyof PublicationPolicy>(name: K, value: PublicationPolicy[K]) => { setDraft(old => ({ ...old, [name]: value })); setSaved(false); };
  const pattern = (value: Partial<PublicationPolicy["schedule"]>) => { setDraft(old => ({ ...old, schedule: { ...old.schedule, ...value } })); setSaved(false); };
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try {
      const value = await publishingJSON<PublicationSettings>(`accounts/${accountId}/automation`, { method: "PUT", body: JSON.stringify({ ...draft, schedule: { ...draft.schedule, times: times.split(",").map(t => t.trim()).filter(Boolean) } }) });
      onSaved(value); setDraft(value.policy); setSaved(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the pattern."); }
    finally { setBusy(false); }
  };
  return <form aria-label="Posting pattern settings" onSubmit={save} className="rounded-xl border bg-background p-4 sm:p-6">
    <h2 className="text-lg font-semibold">Posting pattern</h2>
    <p className="mt-1 text-sm text-muted-foreground">Changes apply to future approvals. Existing reservations and confirmed YouTube schedules stay in place.</p>
    <fieldset disabled={busy} className="mt-5 space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-2 text-sm font-medium">Pattern<select className="h-10 w-full rounded-md border bg-background px-3" value={draft.schedule.kind} onChange={e => pattern({ kind: e.target.value as "interval" | "weekly" })}><option value="interval">Every few hours</option><option value="weekly">Weekly posting times</option></select></label>
        <label className="space-y-2 text-sm font-medium">Timezone<Input list="publishing-timezones" value={draft.timezone} onChange={e => field("timezone", e.target.value)} /><datalist id="publishing-timezones">{["UTC", "Europe/Bucharest", "Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "Asia/Dubai", "Asia/Tokyo", "Australia/Sydney"].map(tz => <option key={tz} value={tz} />)}</datalist></label>
      </div>
      {draft.schedule.kind === "interval" ? <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-2 text-sm font-medium">Every (hours)<Input type="number" min={0.25} max={168} step={0.25} required value={draft.schedule.interval_minutes / 60} onChange={e => pattern({ interval_minutes: Math.round(Number(e.target.value) * 60) })} /></label>
        <label className="space-y-2 text-sm font-medium">First slot (your device time)<Input type="datetime-local" required value={draft.schedule.anchor_at ? deviceTime(draft.schedule.anchor_at) : ""} onChange={e => { const d = new Date(e.target.value); if (!Number.isNaN(d.getTime())) pattern({ anchor_at: d.toISOString() }); }} /></label>
      </div> : <div className="space-y-4">
        <fieldset><legend className="mb-2 text-sm font-medium">Posting days</legend><div className="flex flex-wrap gap-2">{DAYS.map((day, index) => <label key={day} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" aria-label={day} checked={draft.schedule.weekdays.includes(index)} onChange={e => pattern({ weekdays: e.target.checked ? [...draft.schedule.weekdays, index] : draft.schedule.weekdays.filter(d => d !== index) })} />{day.slice(0,3)}</label>)}</div></fieldset>
        <label className="block space-y-2 text-sm font-medium">Local times (24-hour, comma separated)<Input placeholder="09:00, 15:00, 21:00" required value={times} onChange={e => { setTimes(e.target.value); setSaved(false); }} /></label>
        <p className="text-xs text-muted-foreground">Clock changes: skipped local times are omitted; repeated times are used once.</p>
      </div>}
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="space-y-2 text-sm font-medium">Minimum live clip score<Input type="number" min={0} max={100} value={draft.min_score} onChange={e => field("min_score", Number(e.target.value))} /></label>
        <label className="space-y-2 text-sm font-medium">Category<select className="h-10 w-full rounded-md border bg-background px-3" value={draft.category_id} onChange={e => field("category_id", e.target.value)}>{[["22","People & Blogs"],["20","Gaming"],["24","Entertainment"],["27","Education"],["25","News & Politics"],["17","Sports"],["23","Comedy"],["28","Science & Technology"]].map(([id,name]) => <option value={id} key={id}>{name}</option>)}</select></label>
        <label className="space-y-2 text-sm font-medium">Synthetic media<select className="h-10 w-full rounded-md border bg-background px-3" value={draft.contains_synthetic_media == null ? "unset" : String(draft.contains_synthetic_media)} onChange={e => field("contains_synthetic_media", e.target.value === "unset" ? null : e.target.value === "true")}><option value="unset">Not specified</option><option value="false">No realistic altered content</option><option value="true">Yes, realistic altered content</option></select></label>
      </div>
      <div className="space-y-3 text-sm">
        <label className="flex items-start gap-2"><input className="mt-1" type="checkbox" checked={draft.made_for_kids} onChange={e => field("made_for_kids", e.target.checked)} />These videos are made for kids</label>
        <label className="flex items-start gap-2"><input className="mt-1" type="checkbox" checked={draft.enabled} onChange={e => field("enabled", e.target.checked)} />Add qualifying future live clips to review</label>
        <label className="flex items-start gap-2"><input className="mt-1" type="checkbox" checked={draft.uploads_paused} onChange={e => field("uploads_paused", e.target.checked)} />Pause new uploads and scheduling</label>
        <p className="text-xs text-muted-foreground">Recording continues. Already confirmed YouTube schedules keep publishing unless you cancel them individually.</p>
      </div>
      <details className="border-t pt-4 text-sm"><summary className="cursor-pointer font-medium">Advanced: automatic approval</summary>
        <label className="mt-4 flex items-start gap-2"><input className="mt-1" type="checkbox" disabled={!settings.private_test_completed || !settings.permissions_complete} checked={draft.mode === "automatic"} onChange={e => field("mode", e.target.checked ? "automatic" : "review")} />Automatically approve future live clips</label>
        <p className="mt-2 text-xs text-muted-foreground">Explicitly enables public scheduling without review for qualifying future live clips. Requires a verified private upload and current permissions. At most nine unpublished automatic approvals per channel; extra clips remain available for review.</p>
      </details>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {saved && <p role="status" className="text-sm">Pattern saved.</p>}
      <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save pattern"}</Button>
    </fieldset>
  </form>;
}
function deviceTime(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,16);
}
