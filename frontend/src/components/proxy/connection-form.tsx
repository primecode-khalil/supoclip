'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { ProxyConnection, ProxyUsage } from './types';

export const selectStyle = 'h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring';
export function ConnectionForm({ connection, busy, error, onClose, onSave }: {
  connection: ProxyConnection | null; busy: boolean; error: string | null; onClose: () => void;
  onSave: (body: { name: string; url?: string; usage: ProxyUsage; enabled: boolean; country?: string; expected_revision?: string }) => Promise<boolean>;
}) {
  const [name, setName] = useState(connection?.name || '');
  const [url, setUrl] = useState('');
  const [usage, setUsage] = useState<ProxyUsage>(connection?.usage || 'both');
  const [enabled, setEnabled] = useState(connection?.enabled ?? true);
  const [country, setCountry] = useState(connection?.country || '');
  const home = connection?.kind === 'home';
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
      <DialogHeader><DialogTitle>{connection ? 'Edit connection' : 'Add proxy'}</DialogTitle><DialogDescription>Save this connection once, then choose where to use it.</DialogDescription></DialogHeader>
      <form className="min-w-0 space-y-4" onSubmit={async event => {
        event.preventDefault();
        const saved = await onSave({ name, usage, enabled, ...(home ? {} : { url, country }), ...(connection ? { expected_revision: connection.revision } : {}) });
        if (saved) onClose();
      }}>
        <div className="space-y-2"><Label htmlFor="proxy-name">Connection name</Label><Input id="proxy-name" required maxLength={80} value={name} onChange={e => setName(e.target.value)} disabled={busy} placeholder="Home or backup" /></div>
        {!home && <div className="space-y-2"><Label htmlFor="proxy-url">Proxy URL</Label><Input id="proxy-url" type="password" autoComplete="off" spellCheck={false} required={!connection || !connection.endpoint} maxLength={2048} value={url} onChange={e => setUrl(e.target.value)} disabled={busy} placeholder="http://user:password@proxy.example:8080" />
          <p className="text-xs leading-relaxed text-muted-foreground">{connection ? 'Leave empty to keep the saved endpoint and credentials. ' : ''}HTTP, HTTPS, SOCKS5 and SOCKS5h are supported. Credentials stay hidden after saving.</p></div>}
        <div className="space-y-2"><Label htmlFor="proxy-usage">Use for</Label><select id="proxy-usage" className={selectStyle} value={usage} onChange={e => setUsage(e.target.value as ProxyUsage)} disabled={busy}><option value="live">Live streams</option><option value="imports">Video imports</option><option value="both">Both</option></select></div>
        {!home && <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Proxy country template</summary><div className="mt-3 space-y-2"><Label htmlFor="proxy-country">Country code (optional)</Label><Input id="proxy-country" maxLength={2} value={country} onChange={e => setCountry(e.target.value)} disabled={busy} placeholder="US" /><p className="text-xs text-muted-foreground">For endpoints using {'{country}'}. A {'{session}'} token keeps each source on a stable session.</p></div></details>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} disabled={busy} className="size-4 accent-foreground" />Enable this connection</label>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2 pt-2"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save proxy'}</Button></div>
      </form>
    </DialogContent>
  </Dialog>;
}
