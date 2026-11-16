"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, ExternalLink, Loader2, Pause, Play, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { SocialConnection } from "@/lib/social";
import { PolicyForm } from "./policy-form";
import { useChannelStatus } from "./use-channel-status";
import { WindowActivity } from "./window-activity";
import { dateTime, publicationError, recordingJSON, type AutomationPolicy, type AutomationState, type RecordingChannel } from "./types";

export function ChannelDetail({ channel, connections, connectionError }: { channel: RecordingChannel; connections: SocialConnection[]; connectionError: string | null }) {
  const { automation, setAutomation, windows, sessions, errors, updatedAt, refresh } = useChannelStatus(channel.id);
  const [toggling, setToggling] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);
  async function save(policy: AutomationPolicy) {
    const visibilityError = publicationError(policy, connections);
    if (policy.enabled && visibilityError) throw new Error(visibilityError);
    const response = await recordingJSON<AutomationState>(`/api/recording/channels/${encodeURIComponent(channel.id)}/automation`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(policy),
    });
    setAutomation(response);
  }
  async function toggle() {
    if (!automation) return;
    setToggling(true); setToggleError(null);
    try { await save({ ...automation.policy, enabled: !automation.policy.enabled }); }
    catch (reason) { setToggleError(reason instanceof Error ? reason.message : "Unable to change automation."); }
    finally { setToggling(false); }
  }
  async function retry(windowId: string) {
    await recordingJSON(`/api/recording/channels/${encodeURIComponent(channel.id)}/windows/${encodeURIComponent(windowId)}/retry`, { method: "POST" });
    refresh();
  }
  const enabled = automation?.policy.enabled && channel.enabled;
  // Lease validity is computed with the database clock by the API.
  const alive = automation?.runtime.leased;
  const latestSession = sessions?.sessions[0];
  const stale = Boolean(errors.automation);
  const capturing = enabled && alive && !errors.sessions && latestSession?.status === "recording";
  return <section className="min-w-0 rounded-xl border bg-background" aria-label={`${channel.name} details`}>
    <div className="space-y-4 border-b p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 className="break-words font-display text-xl font-bold">{channel.name}</h2><Link href={channel.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex max-w-full items-center gap-1 text-xs text-muted-foreground hover:underline"><span className="truncate">{channel.platform === "youtube" ? "YouTube" : channel.platform === "twitch" ? "Twitch" : "Kick"} · @{channel.handle}</span><ExternalLink className="size-3 shrink-0" /></Link></div><Button size="icon" variant="ghost" aria-label="Refresh channel status" onClick={refresh}><RefreshCw className="size-4" /></Button></div>
      {automation ? <>
        <div className="flex flex-wrap items-center gap-2"><Badge variant={enabled ? "secondary" : "outline"}>{enabled ? "Automation enabled" : "Automation paused"}</Badge><span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><Activity className="size-3.5" />{stale ? "Recorder status unavailable" : capturing ? "Recording now" : alive ? "Monitoring channel" : enabled ? "Waiting for recorder" : "Recorder inactive"}</span></div>
        <p className="text-xs leading-relaxed text-muted-foreground">{stale ? "The latest status could not be loaded. Saved settings are shown below." : !channel.enabled ? "This source is disabled. Enable the channel before starting automation." : !enabled ? "Enable automation to monitor this channel whenever it goes live." : !alive ? "Automation is enabled, but no recorder is holding this channel. Check that the recorder service is running." : capturing ? "The recorder is capturing this channel. Finished windows feed the clipping pipeline." : "The recorder is monitoring this channel and will capture it when it goes live."}</p>
        <div className="flex flex-wrap items-center gap-3"><Button size="sm" variant={automation.policy.enabled ? "outline" : "default"} disabled={toggling || stale || !channel.enabled} onClick={() => void toggle()}>{toggling ? <Loader2 className="size-4 animate-spin" /> : automation.policy.enabled ? <Pause className="size-4" /> : <Play className="size-4" />}{automation.policy.enabled ? "Pause automation" : "Enable automation"}</Button><span className="text-xs text-muted-foreground">{automation.runtime.last_heartbeat_at ? `Last heartbeat: ${dateTime(automation.runtime.last_heartbeat_at)}` : "No heartbeat yet"}</span></div>
        {automation.runtime.last_error && <p role="status" className="break-words rounded-lg border border-destructive/30 p-3 text-xs text-destructive">{automation.runtime.last_error}</p>}
      </> : <Skeleton className="h-20 w-full" />}
      {(toggleError || errors.automation) && <p role="alert" className="text-sm text-destructive">{toggleError || errors.automation}<button type="button" className="ml-2 underline underline-offset-4" onClick={refresh}>Retry</button></p>}
    </div>
    <div className="space-y-6 p-4 sm:p-6">
      {automation && <PolicyForm policy={automation.policy} connections={connections} connectionError={connectionError} onSave={save} />}
      <WindowActivity data={windows} error={errors.windows} onRetry={retry} />
      <section className="border-t pt-6"><h3 className="mb-3 text-sm font-semibold">Recent recording sessions</h3>{errors.sessions && <p role="status" className="mb-2 text-xs text-destructive">{errors.sessions}</p>}{!sessions ? <Skeleton className="h-12 w-full" /> : !sessions.sessions.length ? <p className="text-xs text-muted-foreground">No recording sessions yet.</p> : <ul className="space-y-2">{sessions.sessions.map((session) => <li key={session.id} className="flex flex-wrap items-center justify-between gap-2 text-xs"><span className="text-muted-foreground">{dateTime(session.started_at || session.created_at)}</span><Badge variant="outline">{session.status}</Badge></li>)}</ul>}</section>
      <p className="text-xs text-muted-foreground">{updatedAt ? `Last refreshed ${updatedAt.toLocaleTimeString()}. Updates every 8 seconds while this tab is visible.` : "Waiting for a complete status update."}</p>
    </div>
  </section>;
}
