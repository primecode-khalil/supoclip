"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Youtube } from "lucide-react";
import { useSession } from "@/lib/auth-client";
import type { YouTubeSetupStatus } from "@/lib/social";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { YouTubeSetup } from "@/components/youtube-setup";
import { ReviewStudio } from "./review-studio";
import { publishingJSON } from "./api";

export function PublishingDashboard() {
  const { data: session, isPending } = useSession();
  const [setup, setSetup] = useState<YouTubeSetupStatus | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!session?.user?.id) return;
    const controller = new AbortController(); setError(null);
    void publishingJSON<YouTubeSetupStatus>("youtube/setup", { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      setSetup(data); setSelected(old => data.connections.some(c => c.id === old) ? old : data.connections[0]?.id || "");
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [session?.user?.id, reload]);
  if (isPending) return <div className="p-6"><Skeleton className="h-64" /></div>;
  if (!session?.user) return <div className="mx-auto max-w-xl px-4 py-16 text-center"><h1 className="font-display text-2xl">Sign in to review and publish clips</h1><Button asChild className="mt-5"><Link href="/sign-in">Sign in</Link></Button></div>;
  const account = setup?.connections.find(c => c.id === selected);
  return <div className="mx-auto w-full max-w-6xl min-w-0 px-4 py-6 sm:px-6 sm:py-10">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div><p className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground"><Youtube className="size-4" />YouTube Shorts</p><h1 className="font-display text-3xl font-semibold tracking-tight">Publishing</h1><p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">Watch a clip. Make the call. We’ll upload your approved Shorts and keep your posting rhythm.</p></div><Link className="text-sm underline underline-offset-4" href="/settings/social">Manage accounts</Link></header>
    {error ? <div role="alert" className="rounded-lg border p-4 text-sm">{error}<Button variant="outline" className="ml-2" onClick={() => setReload(value => value+1)}>Try again</Button></div> : !setup ? <Skeleton aria-label="Loading publishing" className="h-96" /> : !account ? <YouTubeSetup /> : <>
      <label className="mb-5 block max-w-md space-y-2 text-sm font-medium">Destination channel<select className="h-10 w-full min-w-0 rounded-md border bg-background px-3" value={selected} onChange={event => setSelected(event.target.value)}>{setup.connections.map(c => <option value={c.id} key={c.id}>{c.display_name || c.username || "YouTube channel"}</option>)}</select></label>
      <ReviewStudio key={account.id} account={account} />
    </>}
  </div>;
}
