export type ProxyUsage = 'live' | 'imports' | 'both';
export interface ProxyConnection {
  id: string; name: string; revision: string; kind: 'url' | 'home'; usage: ProxyUsage;
  priority: number; enabled: boolean; country: string; endpoint: string | null;
  scheme: string | null; has_credentials: boolean;
  health: { status: string; retry_after_seconds: number; last_checked_at?: string | null; last_purpose?: string | null };
}
export interface ProxyList { connections: ProxyConnection[]; max_url_connections: number }
export function readProxyList(value: unknown): ProxyList {
  const data = value as ProxyList | null;
  if (!data || !Array.isArray(data.connections) || data.connections.length > 11
      || !Number.isInteger(data.max_url_connections) || data.max_url_connections < 1) throw new Error('Unable to read saved proxy connections. Try again.');
  for (const c of data.connections) {
    if (!c || typeof c.id !== 'string' || !c.id || typeof c.revision !== 'string' || typeof c.name !== 'string'
        || !['home', 'url'].includes(c.kind) || !['live', 'imports', 'both'].includes(c.usage)
        || typeof c.enabled !== 'boolean' || !Number.isFinite(c.priority) || typeof c.country !== 'string'
        || !(c.endpoint === null || typeof c.endpoint === 'string') || !c.health || typeof c.health.status !== 'string') {
      throw new Error('Unable to read saved proxy connections. Try again.');
    }
  }
  return data;
}

export async function proxyJSON(path: string, options: RequestInit = {}) {
  const response = await fetch('/api/proxy' + path, { ...options, cache: 'no-store' });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not update proxy connections. Try again.');
  return data;
}
