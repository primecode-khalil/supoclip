'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { proxyJSON, readProxyList, type ProxyList } from './types';

export function useProxyRegistry() {
  const [data, setData] = useState<ProxyList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const version = useRef(0);
  const busy = useRef(false);

  const load = useCallback(async () => {
    if (busy.current || !controller.current || controller.current.signal.aborted) return;
    const signal = controller.current.signal;
    const request = ++version.current;
    try {
      const next = readProxyList(await proxyJSON('', { signal }));
      if (signal.aborted || request !== version.current) return;
      setData(next); setLoadError(null);
    } catch (error) {
      if (!signal.aborted && request === version.current) setLoadError(error instanceof Error ? error.message : 'Could not load proxy connections.');
    }
  }, []);
  useEffect(() => {
    controller.current = new AbortController();
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => { controller.current?.abort(); window.clearInterval(timer); };
  }, [load]);

  async function run(key: string, path: string, method: string, body?: unknown): Promise<boolean> {
    if (busy.current || !controller.current || controller.current.signal.aborted) return false;
    busy.current = true; ++version.current;
    const signal = controller.current.signal;
    setAction(key); setActionError(null); setNotice(null);
    try {
      const next = await proxyJSON(path, { method, signal, ...(body !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
      if (signal.aborted) return false;
      if (Array.isArray(next?.connections)) setData(readProxyList(next));
      else if (typeof next?.ok === 'boolean' && typeof next.message === 'string') setNotice({ text: next.message, ok: next.ok });
      else throw new Error('The proxy service returned an invalid response. Refresh and try again.');
      return true;
    } catch (error) {
      if (!signal.aborted) setActionError(error instanceof Error ? error.message : 'Could not update the connection.');
      return false;
    } finally {
      busy.current = false;
      if (!signal.aborted) { setAction(null); void load(); }
    }
  }
  return { data, loadError, actionError, notice, action, refresh: load, run, clearActionError: () => setActionError(null) };
}
