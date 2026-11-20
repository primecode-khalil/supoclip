import { NextResponse } from 'next/server';
import { createTextProxyResponse, fetchBackend } from '@/server/backend-api';
import { getServerSession } from '@/server/session';

type Context = { params: Promise<{ path?: string[] }> };
function allowed(method: string, path: string[]) {
  if (!path.every(part => /^[A-Za-z0-9_-]{1,64}$/.test(part))) return false;
  if (!path.length) return method === 'GET';
  if (path[0] === 'order' && path.length === 1) return method === 'PUT';
  if (path[0] !== 'connections') return false;
  return (path.length === 1 && method === 'POST')
    || (path.length === 2 && ['PATCH', 'DELETE'].includes(method))
    || (path.length === 3 && path[2] === 'test' && method === 'POST');
}

async function proxy(request: Request, { params }: Context) {
  const session = await getServerSession();
  if (!session?.user?.id) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (!(session.user as { is_admin?: boolean }).is_admin) return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  const path = (await params).path || [];
  if (!allowed(request.method, path)) return NextResponse.json({ detail: 'Not found' }, { status: 404 });
  const body = ['GET', 'DELETE'].includes(request.method) ? undefined : await request.text();
  if (body && new TextEncoder().encode(body).length > 8192) return NextResponse.json({ detail: 'Proxy settings are too large' }, { status: 413 });
  try {
    const upstream = await fetchBackend(`/proxy${path.length ? '/' + path.join('/') : ''}`, {
      method: request.method, userId: session.user.id, body,
      extraHeaders: body ? { 'Content-Type': 'application/json' } : {},
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]), cache: 'no-store',
    });
    const response = await createTextProxyResponse(upstream);
    response.headers.set('Cache-Control', 'private, no-store');
    return response;
  } catch {
    return NextResponse.json({ detail: 'The proxy service is temporarily unavailable. Try again shortly.' }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
