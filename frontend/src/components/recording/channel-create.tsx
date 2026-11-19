"use client";

import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SELECT_STYLE, recordingJSON, type RecordingChannel, type RecordingPlatform } from "./types";

export function ChannelCreate({ onCreated }: { onCreated: (channel: RecordingChannel) => void }) {
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState<RecordingPlatform>("twitch");
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError(null);
    if (/[:/\\]/.test(handle)) { setError("Enter the channel handle, such as creator_name, without the full URL."); return; }
    setSaving(true);
    try {
      const channel = await recordingJSON<RecordingChannel>("/api/recording/channels", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform, name: name.trim(), handle: handle.trim() }),
      });
      onCreated(channel); setOpen(false); setName(""); setHandle("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to add this channel."); }
    finally { setSaving(false); }
  }
  return <Dialog open={open} onOpenChange={(value) => { if (!saving) { setOpen(value); setError(null); } }}>
    <DialogTrigger asChild><Button><Plus className="size-4" />Add channel</Button></DialogTrigger>
    <DialogContent className="sm:max-w-md">
      <DialogHeader><DialogTitle>Add a live channel</DialogTitle><DialogDescription>Choose a stream you own or have permission to clip. Automation starts after you enable it.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-4">
        <fieldset disabled={saving} className="space-y-4">
          <div className="space-y-1.5"><Label htmlFor="channel-platform">Platform</Label><select id="channel-platform" value={platform} onChange={(event) => setPlatform(event.target.value as RecordingPlatform)} className={SELECT_STYLE}><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="youtube">YouTube</option></select></div>
          <div className="space-y-1.5"><Label htmlFor="channel-name">Display name</Label><Input id="channel-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="My live channel" required maxLength={120} /></div>
          <div className="space-y-1.5"><Label htmlFor="channel-handle">Channel handle</Label><Input id="channel-handle" value={handle} onChange={(event) => setHandle(event.target.value)} placeholder={platform === "youtube" ? "@creator" : "creator_name"} autoComplete="off" required maxLength={255} /><p className="text-xs text-muted-foreground">Use the handle only. YouTube handles may begin with @.</p></div>
        </fieldset>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={saving}>Cancel</Button><Button type="submit" disabled={saving}>{saving && <Loader2 className="size-4 animate-spin" />}Add channel</Button></div>
      </form>
    </DialogContent>
  </Dialog>;
}
