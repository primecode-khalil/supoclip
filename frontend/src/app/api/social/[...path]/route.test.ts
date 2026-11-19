import { PUT } from "./route";
import { getServerSession } from "@/server/session";
import { fetchBackend } from "@/server/backend-api";
vi.mock("@/server/session", () => ({ getServerSession: vi.fn() }));
vi.mock("@/server/backend-api", async () => ({ ...await vi.importActual<typeof import("@/server/backend-api")>("@/server/backend-api"), fetchBackend: vi.fn() }));
it("forwards owner-signed posting pattern updates and validation errors", async () => {
  vi.mocked(getServerSession).mockResolvedValue({ user: { id: "owner" } } as never);
  vi.mocked(fetchBackend).mockResolvedValue(Response.json({ detail: "Invalid timezone" }, { status: 422 }));
  const body = JSON.stringify({ timezone: "bad" });
  const response = await PUT(new Request("https://example/api/social/accounts/one/automation", { method: "PUT", body }), { params: Promise.resolve({ path: ["accounts", "one", "automation"] }) });
  expect(response.status).toBe(422);
  expect(fetchBackend).toHaveBeenCalledWith("/social/accounts/one/automation", expect.objectContaining({ userId: "owner", method: "PUT", body }));
});
