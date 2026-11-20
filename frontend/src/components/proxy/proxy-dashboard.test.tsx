import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ProxyManager, ProxyDashboard } from './proxy-dashboard';
import { useSession } from '@/lib/auth-client';

vi.mock('@/lib/auth-client', () => ({ useSession: vi.fn() }));
vi.mock('@/components/recording/home-proxy-card', () => ({ HomeProxyCard: () => <section>Mac setup controls</section> }));
const initial = [
  { id: 'home', name: 'My Mac', kind: 'home', revision: 'home-v1', usage: 'both', priority: 0, enabled: true, country: '', endpoint: '172.19.0.1:18888', scheme: 'http', has_credentials: false, health: { status: 'working', retry_after_seconds: 0 } },
  { id: 'backup', name: 'Backup', kind: 'url', revision: 'backup-v1', usage: 'imports', priority: 1, enabled: true, country: 'us', endpoint: 'proxy.example:8080', scheme: 'http', has_credentials: true, health: { status: 'not_checked', retry_after_seconds: 0 } },
];
afterEach(() => { vi.unstubAllGlobals(); });
function setup(fail = false) {
  let rows = structuredClone(initial);
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (!options?.method || options.method === 'GET') return Response.json({ connections: rows, max_url_connections: 10 });
    if (fail) return Response.json({ detail: 'Connection changed. Reload before editing.' }, { status: 409 });
    const body = options.body ? JSON.parse(options.body as string) : {};
    if (url.endsWith('/test')) return Response.json({ ok: true, message: 'YouTube metadata reached.' });
    if (options.method === 'POST') rows = [...rows, { ...initial[1], id: 'new', name: body.name, usage: body.usage }];
    if (options.method === 'PATCH') rows = rows.map(row => url.endsWith(row.id) ? { ...row, ...body } : row);
    if (options.method === 'DELETE') rows = rows.filter(row => !url.endsWith(row.id));
    if (options.method === 'PUT') rows = body.connection_ids.map((id: string) => rows.find(row => row.id === id));
    return Response.json({ connections: rows, max_url_connections: 10 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<ProxyManager />);
  return fetcher;
}

it('shows ordered named connections and saves a proxy for both purposes', async () => {
  const fetcher = setup();
  await screen.findByRole('heading', { name: 'My Mac' });
  expect(screen.getByText('Mac setup controls')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Add proxy' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Connection name'), { target: { value: 'Second home' } });
  fireEvent.change(within(dialog).getByLabelText('Proxy URL'), { target: { value: 'socks5h://user:private-password@proxy.example:1080' } });
  fireEvent.change(within(dialog).getByLabelText('Use for'), { target: { value: 'both' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save proxy' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  const request = fetcher.mock.calls.find(([, options]) => options?.method === 'POST')!;
  expect(JSON.parse(request[1]!.body as string)).toMatchObject({ name: 'Second home', usage: 'both', url: 'socks5h://user:private-password@proxy.example:1080' });
  expect(document.body.textContent).not.toContain('private-password');
});

it('keeps saved credentials hidden and preserves them when editing another setting', async () => {
  const fetcher = setup();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Backup' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('Proxy URL')).toHaveValue('');
  expect(within(dialog).getByText(/leave empty to keep/i)).toBeVisible();
  fireEvent.change(within(dialog).getByLabelText('Connection name'), { target: { value: 'Preferred backup' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save proxy' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  const body = JSON.parse(fetcher.mock.calls.find(([, options]) => options?.method === 'PATCH')![1]!.body as string);
  expect(body).toMatchObject({ name: 'Preferred backup', url: '', expected_revision: 'backup-v1' });
});

it('retains the form and unsaved edits when saving fails', async () => {
  setup(true);
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Backup' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Connection name'), { target: { value: 'Keep this edit' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save proxy' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Connection changed');
  expect(within(dialog).getByLabelText('Connection name')).toHaveValue('Keep this edit');
});

it('changes purpose, pauses a connection and changes priority only after acknowledgement', async () => {
  const fetcher = setup();
  const select = await screen.findByLabelText('Use My Mac for');
  fireEvent.change(select, { target: { value: 'live' } });
  await waitFor(() => expect(fetcher.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(true));
  await waitFor(() => expect(select).toBeEnabled());
  fireEvent.click(screen.getByLabelText('Enable Backup'));
  await waitFor(() => expect(screen.getByLabelText('Enable Backup')).not.toBeChecked());
  fireEvent.click(screen.getByRole('button', { name: 'Move Backup up' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true));
  const body = JSON.parse(fetcher.mock.calls.find(([, options]) => options?.method === 'PUT')![1]!.body as string);
  expect(body.connection_ids).toEqual(['backup', 'home']);
});

it('warns that removing the Mac also disconnects it', async () => {
  const fetcher = setup();
  fireEvent.click(await screen.findByRole('button', { name: 'Remove My Mac' }));
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText(/disconnects your Mac/i)).toBeVisible();
  expect(fetcher.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Remove connection' }));
  await waitFor(() => expect(screen.queryByRole('heading', { name: 'My Mac' })).not.toBeInTheDocument());
});

it('shows a metadata test result without promising verified playback', async () => {
  setup();
  fireEvent.click(await screen.findByRole('button', { name: 'Test Backup' }));
  expect(await screen.findByText('YouTube metadata reached.')).toBeVisible();
  expect(screen.queryByText('Playback verified')).not.toBeInTheDocument();
});

it('keeps non-admins outside the proxy manager', () => {
  vi.mocked(useSession).mockReturnValue({ data: { user: { id: 'regular' } }, isPending: false } as never);
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  render(<ProxyDashboard />);
  expect(screen.getByText(/administrators manage proxy/i)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it('ignores an older refresh that arrives after a saved change', async () => {
  let release!: (response: Response) => void;
  let gets = 0;
  const updated = initial.map(c => c.id === 'backup' ? { ...c, enabled: false } : c);
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'PATCH') return Response.json({ connections: updated, max_url_connections: 10 });
    gets++;
    if (gets === 2) return new Promise<Response>(resolve => { release = resolve; });
    return Response.json({ connections: gets > 2 ? updated : initial, max_url_connections: 10 });
  }));
  render(<ProxyManager />);
  await screen.findByLabelText('Enable Backup');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await waitFor(() => expect(gets).toBe(2));
  fireEvent.click(screen.getByLabelText('Enable Backup'));
  await waitFor(() => expect(screen.getByLabelText('Enable Backup')).not.toBeChecked());
  await act(async () => { release(Response.json({ connections: initial, max_url_connections: 10 })); });
  expect(screen.getByLabelText('Enable Backup')).not.toBeChecked();
});
