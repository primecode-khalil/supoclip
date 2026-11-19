"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Radio, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import type { SocialConnection } from "@/lib/social";
import { ChannelCreate } from "./channel-create";
import { ChannelDetail } from "./channel-detail";
import { HomeProxyCard } from "./home-proxy-card";
import { recordingJSON, type RecordingChannel } from "./types";

export function RecordingDashboard() {
  const { data: session, isPending } = useSession();
  const [channels, setChannels] = useState<RecordingChannel[] | null>(null);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    const results = await Promise.allSettled([
      recordingJSON<{ channels: RecordingChannel[]; total: number }>("/api/recording/channels?limit=100", { signal }),
      recordingJSON<{ connections: SocialConnection[] }>("/api/social/connections", { signal }),
    ]);
    if (signal?.aborted) return;
    if (results[0].status === "fulfilled") {
      const data = results[0].value;
      setChannels(data.channels); setTotal(data.total); setError(null);
      setSelectedId((current) => data.channels.some((item) => item.id === current) ? current : data.channels[0]?.id ?? null);
    } else setError(results[0].reason instanceof Error ? results[0].reason.message : "Unable to load your channels.");
    if (results[1].status === "fulfilled") { setConnections(results[1].value.connections ?? []); setConnectionError(null); }
    else setConnectionError(results[1].reason instanceof Error ? results[1].reason.message : "Unable to load connected accounts.");
    setLoading(false);
  }, []);
  useEffect(() => {
    if (!session?.user?.id) return;
    const controller = new AbortController(); void load(controller.signal);
    return () => controller.abort();
  }, [session?.user?.id, load]);
  const admin = Boolean((session?.user as { is_admin?: boolean } | undefined)?.is_admin);
  const selected = channels?.find((item) => item.id === selectedId);
  if (isPending) return <main className="mx-auto w-full max-w-6xl p-6" aria-label="Loading live channels"><Skeleton className="h-64 w-full" /></main>;
  if (!session?.user) return <main className="mx-auto max-w-md px-4 py-24 text-center"><h1 className="font-display text-2xl font-bold">Sign in to manage live channels</h1><p className="mt-3 text-sm text-muted-foreground">Recording and publishing settings belong to your account.</p><Button asChild className="mt-5"><Link href="/sign-in">Sign in</Link></Button></main>;
  return <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-8 md:py-10">
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><p className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground"><Radio className="size-3.5" />Recording studio</p><h1 className="font-display text-3xl font-bold tracking-tight">Live channels</h1><p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">Monitor your streams, create captioned vertical clips, and publish to your connected accounts.</p></div><ChannelCreate onCreated={(channel) => { setChannels((current) => [...(current ?? []), channel]); setTotal((current) => current + 1); setSelectedId(channel.id); setError(null); }} /></div>
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-background px-4 py-3 text-xs"><p className="text-muted-foreground">Setup: connect your AI services and publishing accounts, then enable a channel.</p><div className="flex flex-wrap gap-4">{admin && <Link href="/admin" className="inline-flex items-center gap-1 font-medium hover:underline">AI and server settings<ArrowUpRight className="size-3" /></Link>}<Link href="/settings/social" className="inline-flex items-center gap-1 font-medium hover:underline">Publishing accounts<ArrowUpRight className="size-3" /></Link></div></div>
    {admin && <HomeProxyCard />}
    {error && <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm"><span className="text-destructive">{error}</span><Button size="sm" variant="outline" disabled={loading} onClick={() => void load()}>Try again</Button></div>}
    {!channels && !error ? <div className="grid gap-5 lg:grid-cols-[240px_1fr]"><Skeleton className="h-48 w-full" /><Skeleton className="h-96 w-full" /></div> : channels && !channels.length ? <div className="rounded-xl border border-dashed py-16 text-center"><Radio className="mx-auto mb-4 size-8 text-muted-foreground" /><h2 className="text-lg font-semibold">Add your first channel</h2><p className="mx-auto mt-2 max-w-sm px-4 text-sm leading-relaxed text-muted-foreground">Choose a Twitch, Kick, or YouTube channel to monitor. You can review its clipping and publishing settings before starting.</p></div> : channels && <div className="grid items-start gap-5 lg:grid-cols-[240px_1fr]">
      <aside className="min-w-0 rounded-xl border bg-background p-3"><div className="mb-2 flex items-center justify-between px-2"><h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Your channels</h2><Button variant="ghost" size="icon" className="size-7" aria-label="Refresh channels and accounts" onClick={() => void load()} disabled={loading}><RefreshCw className={cn("size-3.5", loading && "animate-spin")} /></Button></div><div className="space-y-1">{channels.map((channel) => <button key={channel.id} type="button" onClick={() => setSelectedId(channel.id)} aria-pressed={channel.id === selectedId} className={cn("w-full min-w-0 rounded-lg px-3 py-2.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring", channel.id === selectedId ? "bg-muted" : "hover:bg-muted/60")}><span className="block truncate text-sm font-medium">{channel.name}</span><span className="mt-0.5 block truncate text-xs text-muted-foreground">{channel.platform === "youtube" ? "YouTube" : channel.platform === "twitch" ? "Twitch" : "Kick"} · @{channel.handle}</span></button>)}</div>{total > channels.length && <p className="mt-3 px-2 text-xs text-muted-foreground">Showing the first {channels.length} of {total} channels.</p>}</aside>
      {selected && <ChannelDetail key={selected.id} channel={selected} connections={connections} connectionError={connectionError} />}
    </div>}
  </main>;
}
