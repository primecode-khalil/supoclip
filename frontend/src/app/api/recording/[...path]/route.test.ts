import { GET, POST, PUT } from "./route";
import { fetchBackend } from "@/server/backend-api";
import { getServerSession } from "@/server/session";

vi.mock("@/server/session", () => ({ getServerSession: vi.fn() }));
vi.mock("@/server/backend-api", async () => ({
  ...await vi.importActual<typeof import("@/server/backend-api")>("@/server/backend-api"),
  fetchBackend: vi.fn(),
}));

const context = (path: string[]) => ({ params: Promise.resolve({ path }) });

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getServerSession).mockResolvedValue({ user: { id: "owner" } } as never);
  vi.mocked(fetchBackend).mockResolvedValue(Response.json({ channels: [] }));
});

it("rejects signed-out requests before calling the backend", async () => {
  vi.mocked(getServerSession).mockResolvedValue(null);
  const response = await GET(new Request("http://localhost/api/recording/channels"), context(["channels"]));
  expect(response.status).toBe(401);
  expect(fetchBackend).not.toHaveBeenCalled();
});

it("signs the authenticated owner rather than forwarding client identity headers", async () => {
  await GET(new Request("http://localhost/api/recording/channels?limit=50", { headers: { "x-supoclip-user-id": "attacker", Authorization: "Bearer injected" } }), context(["channels"]));
  expect(fetchBackend).toHaveBeenCalledWith("/recording/channels?limit=50", expect.objectContaining({ userId: "owner", method: "GET", cache: "no-store" }));
  const forwarded = vi.mocked(fetchBackend).mock.calls[0][1]?.extraHeaders;
  expect(forwarded).not.toHaveProperty("Authorization");
  expect(forwarded).not.toHaveProperty("x-supoclip-user-id");
});

it("rejects path traversal and unrecognized recording endpoints", async () => {
  for (const path of [["..", "tasks"], ["channels", "one", "..", "tasks"], ["channels", "one", "automation", "injected"], ["admin"], []]) {
    const response = await GET(new Request("http://localhost/api/recording/channels"), context(path));
    expect(response.status).toBe(404);
  }
  expect(fetchBackend).not.toHaveBeenCalled();
});

it("forwards JSON policy updates and backend validation failures", async () => {
  vi.mocked(fetchBackend).mockResolvedValue(Response.json({ detail: "Overlap must be shorter than the segment" }, { status: 422 }));
  const body = JSON.stringify({ segment_seconds: 60, overlap_seconds: 90 });
  const response = await PUT(new Request("http://localhost/api/recording/channels/one/automation", { method: "PUT", body, headers: { "Content-Type": "application/json" } }), context(["channels", "one", "automation"]));
  expect(response.status).toBe(422);
  expect((await response.json()).detail).toMatch(/Overlap/);
  expect(fetchBackend).toHaveBeenCalledWith("/recording/channels/one/automation", expect.objectContaining({ body, userId: "owner" }));
});

it("returns a useful unavailable response when the backend cannot be reached", async () => {
  vi.mocked(fetchBackend).mockRejectedValue(new TypeError("fetch failed at internal secret URL"));
  const response = await POST(new Request("http://localhost/api/recording/channels", { method: "POST", body: "{}" }), context(["channels"]));
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain("secret URL");
});

it("forwards only the owned-window retry endpoint", async () => {
  const response = await POST(new Request("http://localhost/api/recording/channels/one/windows/window-one/retry", { method: "POST" }), context(["channels", "one", "windows", "window-one", "retry"]));
  expect(response.status).toBe(200);
  expect(fetchBackend).toHaveBeenCalledWith("/recording/channels/one/windows/window-one/retry", expect.objectContaining({ method: "POST", userId: "owner" }));
});
