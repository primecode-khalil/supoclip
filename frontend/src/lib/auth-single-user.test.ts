import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ count: vi.fn() }));
vi.mock("better-auth", () => ({ betterAuth: (options: unknown) => options }));
vi.mock("better-auth/api", () => ({
  APIError: class APIError extends Error { constructor(public status: string, options: { message: string }) { super(options.message); } },
  createAuthMiddleware: (callback: unknown) => callback,
}));
vi.mock("better-auth/adapters/prisma", () => ({ prismaAdapter: () => ({}) }));
vi.mock("better-auth/next-js", () => ({ nextCookies: () => ({}) }));
vi.mock("@/lib/prisma", () => ({ default: { user: { count: state.count } } }));
vi.mock("@/server/account-deletion", () => ({ prepareAccountDeletion: vi.fn() }));
vi.mock("@/server/backend-api", () => ({ fetchBackend: vi.fn() }));

type Hook = (context: { path: string; headers: Headers }) => Promise<void>;

async function signupHook(): Promise<Hook> {
  const { auth } = await import("./auth");
  return (auth as unknown as { hooks: { before: Hook } }).hooks.before;
}

describe("first-owner signup middleware", () => {
  const token = "a".repeat(64);
  beforeEach(() => {
    vi.resetModules();
    state.count.mockReset().mockResolvedValue(0);
    vi.stubEnv("SELF_HOST_SINGLE_USER", "true");
    vi.stubEnv("NEXT_PUBLIC_SELF_HOST", "true");
    vi.stubEnv("INITIAL_SETUP_TOKEN", token);
  });
  afterEach(() => vi.unstubAllEnvs());
  it("rejects an unclaimed public signup without the setup token", async () => {
    const hook = await signupHook();
    await expect(hook({ path: "/sign-up/email", headers: new Headers() })).rejects.toMatchObject({ status: "FORBIDDEN" });
    expect(state.count).not.toHaveBeenCalled();
  });
  it("permits the exact token only before an owner exists", async () => {
    const hook = await signupHook();
    await expect(hook({ path: "/sign-up/email", headers: new Headers({ "x-supoclip-setup-token": token }) })).resolves.toBeUndefined();
    expect(state.count).toHaveBeenCalledOnce();
    state.count.mockResolvedValue(1);
    await expect(hook({ path: "/sign-up/email", headers: new Headers({ "x-supoclip-setup-token": token }) })).rejects.toMatchObject({ status: "FORBIDDEN" });
  });
  it("does not block normal sign-in or change hosted signup behavior", async () => {
    const hook = await signupHook();
    await expect(hook({ path: "/sign-in/email", headers: new Headers() })).resolves.toBeUndefined();
    vi.stubEnv("SELF_HOST_SINGLE_USER", "false");
    await expect(hook({ path: "/sign-up/email", headers: new Headers() })).resolves.toBeUndefined();
    expect(state.count).not.toHaveBeenCalled();
  });
});
