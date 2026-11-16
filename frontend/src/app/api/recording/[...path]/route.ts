import { NextResponse } from "next/server";
import { createTextProxyResponse, fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

type Context = { params: Promise<{ path: string[] }> };
const SEGMENT = /^[A-Za-z0-9_-]+$/;

function allowed(method: string, path: string[]) {
  if (!path.length || !path.every((part) => SEGMENT.test(part))) return false;
  if (path[0] === "channels") {
    if (path.length === 1) return method === "GET" || method === "POST";
    if (path.length === 2) return method === "GET" || method === "PATCH";
    if (path.length === 3 && path[2] === "automation") return method === "GET" || method === "PUT";
    if (path.length === 3 && ["sessions", "windows"].includes(path[2])) return method === "GET";
    if (path.length === 5 && path[2] === "windows" && path[4] === "retry") return method === "POST";
  }
  return path[0] === "sessions" && path.length === 2 && method === "GET";
}

async function proxy(request: Request, { params }: Context) {
  const session = await getServerSession();
  if (!session?.user?.id) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { path } = await params;
  if (!allowed(request.method, path)) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const body = request.method === "GET" ? undefined : await request.text();
  if (body && body.length > 32_768) return NextResponse.json({ detail: "Recording settings are too large" }, { status: 413 });
  try {
    const upstream = await fetchBackend(`/recording/${path.join("/")}${new URL(request.url).search}`, {
      method: request.method, userId: session.user.id, body,
      extraHeaders: body ? { "Content-Type": "application/json" } : {},
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]), cache: "no-store",
    });
    const response = await createTextProxyResponse(upstream);
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  } catch {
    return NextResponse.json({ detail: "The recording service is temporarily unavailable. Try again shortly." }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
