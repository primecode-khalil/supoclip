"use client";

import { useEffect, useState } from "react";
import { recordingJSON, type AutomationState, type SessionList, type WindowList } from "./types";

export function useChannelStatus(channelId: string) {
  const [automation, setAutomation] = useState<AutomationState | null>(null);
  const [windows, setWindows] = useState<WindowList | null>(null);
  const [sessions, setSessions] = useState<SessionList | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (document.hidden) { timer = setTimeout(poll, 8_000); return; }
      const prefix = `/api/recording/channels/${encodeURIComponent(channelId)}`;
      const results = await Promise.allSettled([
        recordingJSON<AutomationState>(`${prefix}/automation`, { signal: controller.signal }),
        recordingJSON<WindowList>(`${prefix}/windows?limit=20`, { signal: controller.signal }),
        recordingJSON<SessionList>(`${prefix}/sessions?limit=5`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      const nextErrors: Record<string, string> = {};
      results.forEach((result, index) => {
        if (result.status === "rejected") nextErrors[["automation", "windows", "sessions"][index]] = result.reason instanceof Error ? result.reason.message : "Unable to refresh this section.";
      });
      if (results[0].status === "fulfilled") setAutomation(results[0].value);
      if (results[1].status === "fulfilled") setWindows(results[1].value);
      if (results[2].status === "fulfilled") setSessions(results[2].value);
      setErrors(nextErrors);
      if (!Object.keys(nextErrors).length) setUpdatedAt(new Date());
      timer = setTimeout(poll, 8_000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [channelId, revision]);
  return { automation, setAutomation, windows, sessions, errors, updatedAt, refresh: () => setRevision((value) => value + 1) };
}
