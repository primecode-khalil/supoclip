'use client';
import { ArrowDown, ArrowUp, Pencil, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { ProxyConnection, ProxyUsage } from './types';
import { selectStyle } from './connection-form';

function status(connection: ProxyConnection) {
  if (!connection.enabled) return 'Paused';
  const { health } = connection;
  if (health.status === 'cooldown') return `Retry in ${health.retry_after_seconds}s`;
  return ({ working: 'Working', reachable: 'Metadata reached', failed: 'Ready to retry', unavailable: 'Unavailable' } as Record<string, string>)[health.status] || 'Not checked';
}
export function ConnectionRow({ connection: c, index, count, busy, testing, onEdit, onRemove, onMove, onChange, onTest }: {
  connection: ProxyConnection; index: number; count: number; busy: boolean; testing: boolean;
  onEdit: () => void; onRemove: () => void; onMove: (direction: -1 | 1) => void;
  onChange: (values: { enabled?: boolean; usage?: ProxyUsage }) => void; onTest: () => void;
}) {
  return <article aria-label={`${c.name} proxy`} className="min-w-0 rounded-xl border bg-background p-4 sm:p-5">
    <div className="flex min-w-0 flex-wrap items-start gap-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-medium" aria-label={`Priority ${index + 1}`}>{index + 1}</span>
      <div className="min-w-0 flex-1"><h2 className="break-words font-semibold">{c.name}</h2><p className="mt-1 break-all text-xs text-muted-foreground">{c.kind === 'home' ? 'Mac home connection' : `${c.scheme?.toUpperCase() || 'Proxy'} · ${c.endpoint || 'Update endpoint'}`}{c.has_credentials ? ' · Credentials saved' : ''}</p></div>
      <Badge variant="outline" className="max-w-full whitespace-normal">{status(c)}</Badge>
    </div>
    <div className="mt-4 grid min-w-0 gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
      <label className="min-w-0 space-y-2 text-xs font-medium">Use for<select aria-label={`Use ${c.name} for`} value={c.usage} disabled={busy} onChange={e => onChange({ usage: e.target.value as ProxyUsage })} className={selectStyle}><option value="live">Live streams</option><option value="imports">Video imports</option><option value="both">Both</option></select></label>
      <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" aria-label={`Enable ${c.name}`} checked={c.enabled} disabled={busy} onChange={e => onChange({ enabled: e.target.checked })} className="size-4 accent-foreground" />Enabled</label>
    </div>
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-3">
      <Button size="sm" variant="outline" aria-label={`Test ${c.name}`} disabled={busy || !c.endpoint} onClick={onTest}>{testing ? 'Testing…' : 'Test YouTube'}</Button>
      <Button size="sm" variant="ghost" aria-label={`Edit ${c.name}`} disabled={busy} onClick={onEdit}><Pencil className="size-3.5" />Edit</Button>
      <Button size="sm" variant="ghost" aria-label={`Remove ${c.name}`} disabled={busy} onClick={onRemove}><Trash2 className="size-3.5" />Remove</Button>
      <div className="ml-auto flex gap-1"><Button variant="ghost" size="icon" aria-label={`Move ${c.name} up`} disabled={busy || index === 0} onClick={() => onMove(-1)}><ArrowUp className="size-4" /></Button><Button variant="ghost" size="icon" aria-label={`Move ${c.name} down`} disabled={busy || index === count - 1} onClick={() => onMove(1)}><ArrowDown className="size-4" /></Button></div>
    </div>
  </article>;
}
