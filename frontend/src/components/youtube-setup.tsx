"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Circle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { YouTubeSetupStatus } from "@/lib/social";

export function YouTubeSetup() {
  const [setup, setSetup] = useState<YouTubeSetupStatus | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    setError(false);
    try {
      const response = await fetch("/api/social/youtube/setup", { cache: "no-store", signal });
      if (!response.ok) throw new Error("setup unavailable");
      const data = await response.json();
      if (!signal?.aborted) setSetup(data);
    } catch {
      if (!signal?.aborted) setError(true);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const step = (complete: boolean, label: string, detail: React.ReactNode) => (
    <li className="flex gap-3">
      {complete ? <CheckCircle2 aria-label="Complete" className="mt-0.5 size-4 shrink-0 text-green-500" /> : <Circle aria-label="Pending" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0"><p className="text-sm font-medium">{label}</p><div className="mt-1 text-sm text-muted-foreground">{detail}</div></div>
    </li>
  );

  return (
    <section aria-labelledby="youtube-setup-heading" className="mb-8 rounded-xl border p-4 sm:p-5">
      <h2 id="youtube-setup-heading" className="font-semibold">YouTube setup</h2>
      <p className="mt-1 text-sm text-muted-foreground">Connect once, choose a posting pattern, then review your clips. Public posting stays off until you approve a clip or explicitly enable automatic approval.</p>
      {error ? <div role="alert" className="mt-4 text-sm">Could not load YouTube setup. <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="size-3" />Retry</Button></div> : !setup ? <p role="status" className="mt-4 text-sm text-muted-foreground">Loading setup…</p> : (
        <ol className="mt-5 space-y-5">
          {step(setup.configured, "Add your Google app", <><a className="underline" href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">Enable YouTube Data API</a>, create a Web OAuth client, and save its client ID and secret in <Link className="underline" href="/admin">server settings</Link>. No YouTube password or cookies are needed.</>)}
          {step(setup.configured, "Register this callback URL", <Input aria-label="YouTube callback URL" readOnly value={setup.redirect_uri} className="mt-2 w-full text-xs" onFocus={(event) => event.target.select()} />)}
          {step(setup.connections.some(c => c.status === "active"), "Connect your channel", <>
            {setup.connections.map(connection => <p key={connection.id} className="break-words text-foreground">{connection.display_name || connection.username || "YouTube channel"}</p>)}
            {setup.configured && (
              // eslint-disable-next-line @next/next/no-html-link-for-pages -- The OAuth handler redirects to Google and needs full navigation.
              <a className="underline" href="/api/social/connect/youtube">{setup.refresh_access_available ? "Connect another YouTube channel" : "Connect YouTube"}</a>
            )}
            <p className="mt-1">For unattended use, move your Google consent app out of Testing. Testing access expires after seven days; revoked access still needs reconnection.</p>
          </>)}
          {step(setup.private_test_completed, "Complete a private test upload", <><Link className="underline" href="/publishing">Open the review queue</Link> and approve a clip. It uploads and processes privately before its approved public schedule is set. You can also publish a private test from your library. Check the processed video, captions and audio; automatic approval stays off.</>)}
        </ol>
      )}
    </section>
  );
}
