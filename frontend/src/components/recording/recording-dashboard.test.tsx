import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RecordingDashboard } from "./recording-dashboard";

const session = vi.hoisted(() => ({ data: { user: { id: "owner" } }, isPending: false }));
vi.mock("@/lib/auth-client", () => ({ useSession: () => session }));

afterEach(() => vi.unstubAllGlobals());

it("shows a recoverable error for failed channel loading", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Database is unavailable" }, { status: 503 })));
  render(<RecordingDashboard />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Database is unavailable");
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
});

it("waits for the policy before showing controls and keeps connection errors separate", async () => {
  const channel = { id: "one", name: "Demo", platform: "twitch", handle: "demo", url: "https://www.twitch.tv/demo", enabled: true, quality: "best" };
  let finish!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/automation")) return new Promise<Response>((resolve) => { finish = resolve; });
    if (url.includes("/sessions")) return Response.json({ sessions: [], total: 0 });
    if (url.includes("/windows")) return Response.json({ windows: [], total: 0 });
    if (url.includes("social")) return Response.json({ detail: "Social publishing is unavailable" }, { status: 503 });
    return Response.json({ channels: [channel], total: 1 });
  }));
  render(<RecordingDashboard />);
  await screen.findByRole("button", { name: /Demo/ });
  expect(screen.queryByRole("button", { name: "Enable automation" })).not.toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Automation settings" })).not.toBeInTheDocument();
  const { DEFAULT_POLICY } = await import("./types");
  await waitFor(() => expect(finish).toBeDefined());
  finish(Response.json({ policy: DEFAULT_POLICY, runtime: { leased: false } }));
  expect(await screen.findByRole("button", { name: "Enable automation" })).toBeEnabled();
  expect(await screen.findByText(/Social publishing is unavailable/)).toBeVisible();
});

it("does not replace unsaved settings when automation is paused", async () => {
  const { DEFAULT_POLICY } = await import("./types");
  const policy = { ...DEFAULT_POLICY, enabled: true };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/automation")) return Response.json({ policy: init?.method === "PUT" ? { ...policy, enabled: false } : policy, runtime: { leased: false } });
    if (url.includes("/sessions")) return Response.json({ sessions: [], total: 0 });
    if (url.includes("/windows")) return Response.json({ windows: [], total: 0 });
    if (url.includes("social")) return Response.json({ connections: [] });
    return Response.json({ channels: [{ id: "one", name: "Demo", platform: "twitch", handle: "demo", url: "https://www.twitch.tv/demo", enabled: true, quality: "best" }], total: 1 });
  }));
  render(<RecordingDashboard />);
  await screen.findByLabelText("Minimum clip score");
  fireEvent.change(screen.getByLabelText("Minimum clip score"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "Pause automation" }));
  await screen.findByRole("button", { name: "Enable automation" });
  expect(screen.getByLabelText("Minimum clip score")).toHaveValue(90);
});

it("does not enable private automation configured for Instagram", async () => {
  const { DEFAULT_POLICY } = await import("./types");
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/automation")) return Response.json({ policy: { ...DEFAULT_POLICY, social_account_ids: ["instagram-one"] }, runtime: { leased: true } });
    if (url.includes("/sessions")) return Response.json({ sessions: [], total: 0 });
    if (url.includes("/windows")) return Response.json({ windows: [], total: 0 });
    if (url.includes("social")) return Response.json({ connections: [{ id: "instagram-one", provider: "instagram", display_name: "Demo Reels", status: "active" }] });
    return Response.json({ channels: [{ id: "one", name: "Demo", platform: "twitch", handle: "demo", url: "https://www.twitch.tv/demo", enabled: true, quality: "best" }], total: 1 });
  }));
  render(<RecordingDashboard />);
  fireEvent.click(await screen.findByRole("button", { name: "Enable automation" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Instagram requires Public visibility");
  expect(screen.getByText("Monitoring channel", { exact: true })).toBeInTheDocument();
  expect(screen.queryByText(/The recorder is capturing/)).not.toBeInTheDocument();
});
