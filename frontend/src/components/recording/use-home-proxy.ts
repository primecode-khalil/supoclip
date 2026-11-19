"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { recordingJSON } from "./types";

interface HomeProxyStatus {
  available: boolean;
  paired: boolean;
  connected: boolean;
  device_name: string | null;
  paired_at: string | null;
}
interface HomeProxySetup { setup_command: string; expires_at: string; previousPairing: string | null }
const ENDPOINT = "/api/recording/home-proxy";

function readStatus(value: unknown): HomeProxyStatus {
  const data = value as Partial<HomeProxyStatus> | null;
  if (!data || typeof data.available !== "boolean" || typeof data.paired !== "boolean" || typeof data.connected !== "boolean"
    || !(data.device_name === null || typeof data.device_name === "string")
    || !(data.paired_at === null || (typeof data.paired_at === "string" && Number.isFinite(Date.parse(data.paired_at))))) {
    throw new Error("Unable to read the home connection status. Try again.");
  }
  return data as HomeProxyStatus;
}
const message = (error: unknown) => error instanceof Error ? error.message : "Unable to update the home connection. Try again.";

export function useHomeProxy() {
  const [status, setStatus] = useState<HomeProxyStatus | null>(null);
  const [setup, setSetup] = useState<HomeProxySetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [action, setAction] = useState<"setup" | "disconnect" | null>(null);
  const controller = useRef<AbortController | null>(null);
  const version = useRef(0);
  const busy = useRef(false);
  const pendingCheck = useRef<number | null>(null);

  const check = useCallback(async () => {
    if (busy.current || !controller.current || controller.current.signal.aborted || pendingCheck.current === version.current) return;
    const requestVersion = ++version.current;
    pendingCheck.current = requestVersion;
    const signal = controller.current.signal;
    setChecking(true);
    try {
      const next = readStatus(await recordingJSON<unknown>(ENDPOINT, { signal }));
      if (signal.aborted || requestVersion !== version.current) return;
      setStatus(next); setError(null);
      setSetup((current) => current && next.paired && next.paired_at !== current.previousPairing ? null : current);
    } catch (reason) {
      if (signal.aborted || requestVersion !== version.current) return;
      setStatus(null); setError(message(reason));
    } finally {
      if (pendingCheck.current === requestVersion) pendingCheck.current = null;
      if (!signal.aborted && requestVersion === version.current) setChecking(false);
    }
  }, []);

  useEffect(() => {
    controller.current = new AbortController();
    ++version.current;
    void check();
    const interval = window.setInterval(() => void check(), 15_000);
    return () => { controller.current?.abort(); window.clearInterval(interval); };
  }, [check]);

  useEffect(() => {
    if (!setup) return;
    const expiry = window.setTimeout(() => {
      setSetup(null);
      setNotice("Setup command expired. Create a new one to connect your Mac.");
    }, Math.max(0, Date.parse(setup.expires_at) - Date.now()));
    return () => window.clearTimeout(expiry);
  }, [setup]);

  const mutate = async (kind: "setup" | "disconnect") => {
    if (busy.current || !controller.current || controller.current.signal.aborted) return;
    busy.current = true; ++version.current;
    const signal = controller.current.signal;
    setAction(kind); setSetup(null); setError(null); setNotice(null); setChecking(false);
    try {
      const data = await recordingJSON<unknown>(`${ENDPOINT}/${kind}`, {
        method: "POST", signal,
        ...(kind === "setup" ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ device_name: "My Mac" }) } : {}),
      });
      if (signal.aborted) return;
      if (kind === "disconnect") {
        setStatus(readStatus(data));
        setNotice("Mac disconnected. Its access and unused setup commands have been revoked.");
      } else {
        const result = data as { setup_command?: unknown; expires_at?: unknown } | null;
        if (!result || typeof result.setup_command !== "string" || !result.setup_command.trim()
          || typeof result.expires_at !== "string" || !(Date.parse(result.expires_at) > Date.now())) {
          throw new Error("Unable to create a valid setup command. Try again.");
        }
        setSetup({ setup_command: result.setup_command, expires_at: result.expires_at, previousPairing: status?.paired_at ?? null });
      }
    } catch (reason) {
      if (!signal.aborted) setError(message(reason));
    } finally {
      busy.current = false;
      if (!signal.aborted) setAction(null);
    }
  };

  return { status, setup, error, notice, checking, action, check, createSetup: () => mutate("setup"), disconnect: () => mutate("disconnect") };
}
