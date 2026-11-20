'use client';
import Link from 'next/link';
import { useState } from 'react';
import { Network, Plus, RefreshCw } from 'lucide-react';
import { useSession } from '@/lib/auth-client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { HomeProxyCard } from '@/components/recording/home-proxy-card';
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { ConnectionForm } from './connection-form';
import { ConnectionRow } from './connection-row';
import { useProxyRegistry } from './use-proxy-registry';
import type { ProxyConnection } from './types';

export function ProxyDashboard() {
  const { data: session, isPending } = useSession();
  if (isPending) return <main className="p-8 text-sm text-muted-foreground">Loading proxy settings…</main>;
  if (!session?.user) return <main className="mx-auto max-w-md px-4 py-24 text-center"><h1 className="font-display text-2xl font-bold">Sign in to manage proxies</h1><Button asChild className="mt-5"><Link href="/sign-in">Sign in</Link></Button></main>;
  if (!(session.user as { is_admin?: boolean }).is_admin) return <main className="mx-auto max-w-md px-4 py-24"><h1 className="font-display text-2xl font-bold">Proxy</h1><p className="mt-3 text-sm text-muted-foreground">Administrators manage proxy connections for this server.</p></main>;
  return <ProxyManager />;
}

export function ProxyManager() {
  const registry = useProxyRegistry();
  const [form, setForm] = useState<{ connection: ProxyConnection | null } | null>(null);
  const [removing, setRemoving] = useState<ProxyConnection | null>(null);
  const [testURL, setTestURL] = useState('');
  const connections = registry.data?.connections || [];
  const busy = registry.action !== null;
  const openForm = (connection: ProxyConnection | null) => { registry.clearActionError(); setForm({ connection }); };
  const route = (purpose: 'live' | 'imports') => !registry.data ? (registry.loadError ? 'Routing unavailable' : 'Loading…') : connections.filter(c => c.enabled && (c.usage === purpose || c.usage === 'both')).map(c => c.name).join(' → ') || 'Normal server connection';
  async function move(connection: ProxyConnection, direction: -1 | 1) {
    const ids = connections.map(c => c.id);
    const index = ids.indexOf(connection.id), target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await registry.run('order', '/order', 'PUT', { connection_ids: ids });
  }
  return <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 sm:py-10">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4"><div className="min-w-0"><p className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground"><Network className="size-4" />Connections</p><h1 className="font-display text-3xl font-bold tracking-tight">Proxy</h1><p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">Configure your YouTube connections once. Choose live streams, video imports, or both, with another proxy ready if one fails.</p></div>
      <Button onClick={() => openForm(null)} disabled={busy || !registry.data || connections.filter(c => c.kind === 'url').length >= (registry.data?.max_url_connections || 10)}><Plus className="size-4" />Add proxy</Button></header>
    <HomeProxyCard />
    {registry.loadError && <div className="mb-5 space-y-3 rounded-lg border p-4"><p role="alert" className="text-sm text-destructive">{registry.loadError}</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void registry.refresh()}>Try again</Button></div>}
    <section aria-labelledby="proxy-routing" className="mb-6 rounded-xl border bg-background p-4 sm:p-5"><h2 id="proxy-routing" className="text-sm font-semibold">Routing and failover</h2>
      <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2"><div className="min-w-0"><p className="text-xs font-medium text-muted-foreground">Live streams</p><p className="mt-1 break-words text-sm">{route('live')}</p></div><div className="min-w-0"><p className="text-xs font-medium text-muted-foreground">Video imports</p><p className="mt-1 break-words text-sm">{route('imports')}</p></div></div>
      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">Connections are tried in priority order. Failed proxies cool down before retrying. When a path has assigned proxies, it waits if all are unavailable.</p>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Video imports are YouTube source URLs. Local file uploads and social publishing use their normal connections. New jobs use updated settings; a running recording keeps its connection until it reconnects.</p>
    </section>
    <section aria-labelledby="saved-proxies"><div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h2 id="saved-proxies" className="font-semibold">Saved connections</h2><Button size="sm" variant="ghost" onClick={() => void registry.refresh()} disabled={busy}><RefreshCw className="size-4" />Refresh</Button></div>
      {!registry.data && !registry.loadError && <p className="py-8 text-sm text-muted-foreground">Loading connections…</p>}
      {registry.data && !connections.length && <div className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">Set up your Mac above or add a proxy endpoint. Paths without assigned proxies use the normal server connection.</div>}
      <div className="grid min-w-0 gap-4">{connections.map((connection, index) => <ConnectionRow key={connection.id} connection={connection} index={index} count={connections.length} busy={busy} testing={registry.action === `test:${connection.id}`}
        onEdit={() => openForm(connection)} onRemove={() => { registry.clearActionError(); setRemoving(connection); }} onMove={direction => void move(connection, direction)}
        onChange={values => void registry.run(`edit:${connection.id}`, `/connections/${connection.id}`, 'PATCH', { ...values, expected_revision: connection.revision })}
        onTest={() => void registry.run(`test:${connection.id}`, `/connections/${connection.id}/test`, 'POST', testURL.trim() ? { video_url: testURL.trim() } : {})} />)}</div>
      {registry.actionError && !form && !removing && <p role="alert" className="mt-4 text-sm text-destructive">{registry.actionError}</p>}
      {registry.notice && <p role={registry.notice.ok ? 'status' : 'alert'} className={`mt-4 text-sm ${registry.notice.ok ? 'text-muted-foreground' : 'text-destructive'}`}>{registry.notice.text}</p>}
      <details className="mt-5 text-sm"><summary className="cursor-pointer text-muted-foreground">Choose a YouTube video for connection tests</summary><label className="mt-3 block space-y-2 text-xs">Test video URL (optional)<Input value={testURL} maxLength={2048} onChange={e => setTestURL(e.target.value)} disabled={busy} placeholder="https://www.youtube.com/watch?v=…" /></label><p className="mt-2 text-xs leading-relaxed text-muted-foreground">Tests read metadata using this connection. Leave empty to use the sample video. Playback is checked during an import or recording.</p></details>
    </section>
    {form && <ConnectionForm connection={form.connection} busy={busy} error={registry.actionError} onClose={() => setForm(null)} onSave={body => registry.run('save', form.connection ? `/connections/${form.connection.id}` : '/connections', form.connection ? 'PATCH' : 'POST', body)} />}
    <AlertDialog open={!!removing} onOpenChange={open => { if (!open && !busy) setRemoving(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Remove {removing?.name}?</AlertDialogTitle><AlertDialogDescription>New requests will use another eligible connection. Active work may need to reconnect.{removing?.kind === 'home' ? ' Removing this connection also disconnects your Mac.' : ''}</AlertDialogDescription></AlertDialogHeader>
      {registry.actionError && <p role="alert" className="text-sm text-destructive">{registry.actionError}</p>}
      <AlertDialogFooter><Button variant="outline" disabled={busy} onClick={() => setRemoving(null)}>Cancel</Button><Button variant="destructive" disabled={busy} onClick={async () => { if (removing && await registry.run('remove', `/connections/${removing.id}`, 'DELETE')) setRemoving(null); }}>Remove connection</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </main>;
}
