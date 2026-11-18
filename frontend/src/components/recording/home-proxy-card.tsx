"use client";

import { useId, useRef, useState } from "react";
import { Copy, House, RefreshCw, Unplug } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { dateTime } from "./types";
import { useHomeProxy } from "./use-home-proxy";

export function HomeProxyCard() {
  const { status, setup, error, notice, checking, action, check, createSetup, disconnect } = useHomeProxy();
  const titleId = useId();
  const commandId = useId();
  const commandRef = useRef<HTMLTextAreaElement>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const label = !status ? (checking && !error ? "Checking connection…" : "Connection status unavailable")
    : !status.available ? "Server setup needed" : status.paired ? (status.connected ? "Connected" : "Waiting for Mac") : "Not connected";
  const disabled = Boolean(action);

  const copy = async () => {
    const target = commandRef.current;
    if (!setup || !target || Date.parse(setup.expires_at) <= Date.now()) return;
    let copied = false;
    try { await navigator.clipboard.writeText(setup.setup_command); copied = true; } catch { /* Select the visible field below. */ }
    if (!target.isConnected || target !== commandRef.current || target.value !== setup.setup_command || Date.parse(setup.expires_at) <= Date.now()) return;
    if (!copied) { target.focus(); target.select(); }
    setCopyMessage(copied ? "Command copied." : "Copy the selected command manually, then paste it into Terminal.");
  };

  return <section aria-labelledby={titleId} className="mb-6 min-w-0 rounded-xl border bg-background p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h2 id={titleId} className="flex items-center gap-2 text-sm font-semibold"><House className="size-4 text-muted-foreground" aria-hidden="true" />Home connection</h2><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Use your Mac’s internet connection for YouTube recording.</p></div>
      <Badge role="status" variant="outline" className="max-w-full whitespace-normal text-xs">{label}</Badge>
    </div>
    <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
      {!status ? <p>{checking && !error ? "Checking your Mac connection." : "Check again to see whether your Mac is connected."}</p>
        : !status.available ? <p>The home connection is not configured on this server. Finish the server setup, then check again.</p>
          : status.paired ? <p>{status.connected ? `Tunnel connected to ${status.device_name || "your Mac"}. YouTube access has not been verified.` : `${status.device_name || "Your Mac"} is offline. Waiting for its tunnel to reconnect.`}</p>
            : <p>Connect a Mac once to send recording traffic through your home internet.</p>}
      <p>Keep your Mac awake and connected to the internet. No VPN or router changes are needed.</p>
      <p>Files are not stored on your Mac. Recording, clipping, and publishing run on your server.</p>
    </div>
    {error && <p role="alert" className="mt-3 text-xs text-destructive">{error}</p>}
    {notice && <p role="status" className="mt-3 text-xs text-muted-foreground">{notice}</p>}
    <div className="mt-4 flex flex-wrap gap-2">
      {status?.available && !setup && <Button size="sm" onClick={() => { setCopyMessage(null); void createSetup(); }} disabled={disabled}>{action === "setup" ? "Creating command…" : status.paired ? "Set up a different Mac" : "Set up my Mac"}</Button>}
      {status?.paired && <Button size="sm" variant="outline" onClick={() => void disconnect()} disabled={disabled}><Unplug className="size-3.5" aria-hidden="true" />{action === "disconnect" ? "Disconnecting…" : "Disconnect Mac"}</Button>}
      <Button size="sm" variant="ghost" onClick={() => void check()} disabled={checking || disabled}><RefreshCw className="size-3.5" aria-hidden="true" />{error && !status ? "Check again" : "Check connection"}</Button>
    </div>
    {setup && <div className="mt-4 min-w-0 space-y-3 border-t pt-4">
      <div className="space-y-1 text-xs leading-relaxed"><p>Paste this command into Terminal on your Mac.</p><p className="text-muted-foreground">The installer starts at login and reconnects automatically. This setup does not copy your YouTube login or cookies.</p>{status?.paired && <p className="text-muted-foreground">Pairing a different Mac replaces the current connection.</p>}</div>
      <div className="space-y-2"><label htmlFor={commandId} className="text-xs font-medium">Mac setup command</label><textarea id={commandId} ref={commandRef} readOnly rows={3} value={setup.setup_command} spellCheck={false} className="block w-full min-w-0 resize-y rounded-md border border-input bg-muted/40 p-3 font-mono text-xs leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>
      <div className="flex flex-wrap items-center gap-3"><Button size="sm" variant="outline" onClick={() => void copy()}><Copy className="size-3.5" aria-hidden="true" />Copy command</Button><p className="text-xs text-muted-foreground">Private command · expires {dateTime(setup.expires_at)}. Keep it to yourself.</p></div>
      {copyMessage && <p role="status" className="text-xs text-muted-foreground">{copyMessage}</p>}
    </div>}
  </section>;
}
