import { GET, POST, PATCH, PUT, DELETE } from './route';
import { getServerSession } from '@/server/session';
import { fetchBackend } from '@/server/backend-api';

vi.mock('@/server/session', () => ({ getServerSession: vi.fn() }));
vi.mock('@/server/backend-api', async () => ({ ...await vi.importActual<typeof import('@/server/backend-api')>('@/server/backend-api'), fetchBackend: vi.fn() }));
const context = (path?: string[]) => ({ params: Promise.resolve({ path }) });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getServerSession).mockResolvedValue({ user: { id: 'owner', is_admin: true } } as never);
  vi.mocked(fetchBackend).mockResolvedValue(Response.json({ connections: [] }));
});

it('requires an administrator before forwarding any saved proxy data', async () => {
  vi.mocked(getServerSession).mockResolvedValue(null);
  expect((await GET(new Request('http://localhost/api/proxy'), context())).status).toBe(401);
  vi.mocked(getServerSession).mockResolvedValue({ user: { id: 'regular' } } as never);
  expect((await GET(new Request('http://localhost/api/proxy'), context())).status).toBe(403);
  expect(fetchBackend).not.toHaveBeenCalled();
});

it.each([
  [GET, 'GET', [], '/proxy'], [POST, 'POST', ['connections'], '/proxy/connections'],
  [PATCH, 'PATCH', ['connections', 'one'], '/proxy/connections/one'],
  [DELETE, 'DELETE', ['connections', 'one'], '/proxy/connections/one'],
  [PUT, 'PUT', ['order'], '/proxy/order'],
  [POST, 'POST', ['connections', 'one', 'test'], '/proxy/connections/one/test'],
])('forwards only an approved admin action %s', async (handler, method, path, endpoint) => {
  const body = ['POST', 'PUT', 'PATCH'].includes(method) ? '{}' : undefined;
  const response = await handler(new Request('http://localhost/api/proxy', { method, body }), context(path));
  expect(response.status).toBe(200);
  expect(response.headers.get('cache-control')).toBe('private, no-store');
  expect(fetchBackend).toHaveBeenCalledWith(endpoint, expect.objectContaining({ userId: 'owner', method, body, cache: 'no-store' }));
});

it('does not forward arbitrary paths, oversized secrets or internal diagnostics', async () => {
  expect((await GET(new Request('http://localhost/api/proxy'), context(['..', 'admin']))).status).toBe(404);
  expect((await POST(new Request('http://localhost/api/proxy', { method: 'POST', body: 'x'.repeat(8193) }), context(['connections']))).status).toBe(413);
  expect(fetchBackend).not.toHaveBeenCalled();
  vi.mocked(fetchBackend).mockRejectedValue(new Error('internal private-password endpoint'));
  const response = await GET(new Request('http://localhost/api/proxy'), context());
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain('private-password');
});
