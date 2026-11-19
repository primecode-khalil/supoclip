import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RecordingDashboard } from "./recording-dashboard";

const session = vi.hoisted(() => ({ data: { user: { id: "owner", is_admin: true } }, isPending: false }));
vi.mock("@/lib/auth-client", () => ({ useSession: () => session }));
const unpaired = { available: true, paired: false, connected: false, device_name: null as string | null, paired_at: null as string | null };
const paired = { ...unpaired, paired: true, device_name: "Studio Mac", paired_at: "2026-11-18T10:00:00Z" };
const command = "curl https://demo.example/home-proxy/install | sh -s -- setup-secret";
let status = { ...unpaired };
let setupExpiresAt: string;
let statusError = false;
let setupError = false;
let disconnectError = false;
let statusResponse: unknown;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  session.data.user.is_admin = true;
  status = { ...unpaired };
  setupExpiresAt = new Date(Date.now() + 300_000).toISOString();
  statusError = setupError = disconnectError = false;
  statusResponse = undefined;
  fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("home-proxy/setup")) return setupError
      ? Response.json({ detail: "Setup is temporarily unavailable" }, { status: 503 })
      : Response.json({ setup_command: command, expires_at: setupExpiresAt });
    if (url.endsWith("home-proxy/disconnect")) {
      if (disconnectError) return Response.json({ detail: "Unable to disconnect the Mac" }, { status: 503 });
      status = { ...unpaired, available: status.available };
      return Response.json(status);
    }
    if (url.endsWith("home-proxy")) return statusError
      ? Response.json({ detail: "Unable to check the connection" }, { status: 503 })
      : Response.json(statusResponse ?? status);
    if (url.includes("social")) return Response.json({ connections: [] });
    return Response.json({ channels: [], total: 0 });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
async function renderCard() {
  render(<RecordingDashboard />);
  const card = await screen.findByRole("region", { name: "Home connection" });
  await waitFor(() => expect(within(card).queryByText("Checking connection…")).not.toBeInTheDocument());
  return within(card);
}

it("offers admin setup without creating or exposing a setup command", async () => {
  const card = await renderCard();
  expect(card.getByText("Not connected", { exact: true })).toBeVisible();
  expect(card.getByRole("button", { name: "Set up my Mac" })).toBeEnabled();
  expect(card.queryByRole("textbox", { name: "Mac setup command" })).not.toBeInTheDocument();
  expect(card.getByText(/No VPN or router changes/)).toBeVisible();
  expect(card.getByText(/Files are not stored on your Mac/)).toBeVisible();
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/setup"))).toBe(false);
});
it("does not show or request home connection for non-admins", async () => {
  session.data.user.is_admin = false;
  render(<RecordingDashboard />);
  await screen.findByText("Add your first channel");
  expect(screen.queryByRole("region", { name: "Home connection" })).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => url.includes("home-proxy"))).toBe(false);
});
it("explains an unconfigured server without offering setup", async () => {
  status.available = false;
  const card = await renderCard();
  expect(card.getByText("Server setup needed", { exact: true })).toBeVisible();
  expect(card.getByText(/home connection is not configured on this server/i)).toBeVisible();
  expect(card.queryByRole("button", { name: "Set up my Mac" })).not.toBeInTheDocument();
});
it.each([{ response: [] }, { response: {} }, { response: { ...paired, connected: "yes" } }])("handles malformed status safely: $response", async ({ response }) => {
  statusResponse = response;
  const card = await renderCard();
  expect(card.getByText("Connection status unavailable", { exact: true })).toBeVisible();
  expect(card.getByRole("alert")).toHaveTextContent(/Unable to read the home connection status/);
  expect(card.getByRole("button", { name: "Check again" })).toBeEnabled();
  expect(card.queryByRole("button", { name: "Set up my Mac" })).not.toBeInTheDocument();
});
it("replaces stale connected status when a 15-second poll fails", async () => {
  vi.useFakeTimers();
  status = { ...paired, connected: true };
  await act(async () => { render(<RecordingDashboard />); });
  const card = within(screen.getByRole("region", { name: "Home connection" }));
  expect(card.getByText("Connected", { exact: true })).toBeVisible();
  expect(card.getByText(/Tunnel connected.*YouTube access has not been verified/)).toBeVisible();
  statusError = true;
  await act(async () => { vi.advanceTimersByTime(15_000); });
  expect(card.getByText("Connection status unavailable", { exact: true })).toBeVisible();
  expect(card.queryByText("Connected", { exact: true })).not.toBeInTheDocument();
  expect(card.getByRole("alert")).toHaveTextContent("Unable to check the connection");
});
it("shows a paired offline Mac as waiting", async () => {
  status = { ...paired };
  const card = await renderCard();
  expect(card.getByText("Waiting for Mac", { exact: true })).toBeVisible();
  expect(card.getByText(/Studio Mac.*offline/)).toBeVisible();
  expect(card.getByText(/awake and connected to the internet/)).toBeVisible();
});
it("creates a command on click, copies it, and explains installation", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const card = await renderCard();
  fireEvent.click(card.getByRole("button", { name: "Set up my Mac" }));
  expect(await card.findByRole("textbox", { name: "Mac setup command" })).toHaveValue(command);
  expect(fetchMock).toHaveBeenCalledWith("/api/recording/home-proxy/setup", expect.objectContaining({ method: "POST", body: JSON.stringify({ device_name: "My Mac" }) }));
  expect(card.getByText(/paste.*Terminal on your Mac/i)).toBeVisible();
  expect(card.getByText(/starts at login and reconnects automatically/i)).toBeVisible();
  fireEvent.click(card.getByRole("button", { name: "Copy command" }));
  expect(await card.findByText("Command copied.")).toBeVisible();
  expect(writeText).toHaveBeenCalledWith(command);
});
it("selects the command for manual copying when clipboard access fails", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("Denied")) } });
  const card = await renderCard();
  fireEvent.click(card.getByRole("button", { name: "Set up my Mac" }));
  const field = await card.findByRole("textbox", { name: "Mac setup command" });
  fireEvent.click(card.getByRole("button", { name: "Copy command" }));
  expect(await card.findByText(/Copy the selected command manually/)).toBeVisible();
  expect(field).toHaveFocus();
});
it("shows setup failures without exposing a command", async () => {
  setupError = true;
  const card = await renderCard();
  fireEvent.click(card.getByRole("button", { name: "Set up my Mac" }));
  expect(await card.findByRole("alert")).toHaveTextContent("Setup is temporarily unavailable");
  expect(card.queryByRole("textbox", { name: "Mac setup command" })).not.toBeInTheDocument();
  expect(card.getByRole("button", { name: "Set up my Mac" })).toBeEnabled();
});
it("clears the secret when its command expires", async () => {
  const card = await renderCard();
  vi.useFakeTimers();
  setupExpiresAt = new Date(Date.now() + 1_000).toISOString();
  await act(async () => { fireEvent.click(card.getByRole("button", { name: "Set up my Mac" })); });
  expect(card.getByRole("textbox", { name: "Mac setup command" })).toHaveValue(command);
  await act(async () => { vi.advanceTimersByTime(1_001); });
  expect(card.queryByRole("textbox", { name: "Mac setup command" })).not.toBeInTheDocument();
  expect(card.getByText(/Setup command expired/)).toBeVisible();
  expect(card.getByRole("button", { name: "Set up my Mac" })).toBeEnabled();
});
it("polls every 15 seconds and clears the command once pairing completes", async () => {
  vi.useFakeTimers();
  await act(async () => { render(<RecordingDashboard />); });
  const card = within(screen.getByRole("region", { name: "Home connection" }));
  await act(async () => { fireEvent.click(card.getByRole("button", { name: "Set up my Mac" })); });
  status = { ...paired, connected: true };
  await act(async () => { vi.advanceTimersByTime(15_000); });
  expect(card.getByText("Connected", { exact: true })).toBeVisible();
  expect(card.queryByRole("textbox", { name: "Mac setup command" })).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([url]) => url === "/api/recording/home-proxy")).toHaveLength(2);
});
it("disconnects the paired Mac and clears a replacement setup command", async () => {
  status = { ...paired, connected: true };
  const card = await renderCard();
  fireEvent.click(card.getByRole("button", { name: "Set up a different Mac" }));
  expect(await card.findByRole("textbox", { name: "Mac setup command" })).toHaveValue(command);
  fireEvent.click(card.getByRole("button", { name: "Disconnect Mac" }));
  await card.findByText("Not connected", { exact: true });
  expect(card.queryByRole("textbox", { name: "Mac setup command" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/recording/home-proxy/disconnect", expect.objectContaining({ method: "POST" }));
});
it("reports disconnect failure without claiming the Mac was disconnected", async () => {
  status = { ...paired, connected: true };
  disconnectError = true;
  const card = await renderCard();
  fireEvent.click(card.getByRole("button", { name: "Disconnect Mac" }));
  expect(await card.findByRole("alert")).toHaveTextContent("Unable to disconnect the Mac");
  expect(card.getByText("Connected", { exact: true })).toBeVisible();
});

it("does not overlap slow status polls and clears connected when the pending check fails", async () => {
  vi.useFakeTimers();
  status = { ...paired, connected: true };
  await act(async () => { render(<RecordingDashboard />); });
  const card = within(screen.getByRole("region", { name: "Home connection" }));
  const rejectChecks: Array<(error: Error) => void> = [];
  fetchMock.mockImplementation(() => new Promise<Response>((_resolve, reject) => { rejectChecks.push(reject); }));
  await act(async () => { vi.advanceTimersByTime(30_000); });
  const pendingCount = rejectChecks.length;
  await act(async () => { rejectChecks.forEach((reject) => reject(new Error("Network connection lost"))); });
  expect(pendingCount).toBe(1);
  expect(card.getByText("Connection status unavailable", { exact: true })).toBeVisible();
  expect(card.queryByText("Connected", { exact: true })).not.toBeInTheDocument();
});


it("checks immediately when React remounts effects in development", async () => {
  vi.useFakeTimers();
  status = { ...paired, connected: true };
  await act(async () => { render(<RecordingDashboard />, { reactStrictMode: true }); });
  const card = within(screen.getByRole("region", { name: "Home connection" }));
  expect(card.getByText("Connected", { exact: true })).toBeVisible();
});

it("does not reveal an expired secret after delayed clipboard permission is denied", async () => {
  let denyCopy!: (error: Error) => void;
  vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(() => new Promise<void>((_resolve, reject) => { denyCopy = reject; })) } });
  const card = await renderCard();
  vi.useFakeTimers();
  setupExpiresAt = new Date(Date.now() + 1_000).toISOString();
  await act(async () => { fireEvent.click(card.getByRole("button", { name: "Set up my Mac" })); });
  fireEvent.click(card.getByRole("button", { name: "Copy command" }));
  await act(async () => { vi.advanceTimersByTime(1_001); });
  await act(async () => { denyCopy(new Error("Permission denied")); });
  expect(screen.queryByDisplayValue(command)).not.toBeInTheDocument();
});

it("allows revoking a paired Mac even when server configuration becomes unavailable", async () => {
  status = { ...paired, available: false };
  const card = await renderCard();
  expect(card.getByText("Server setup needed", { exact: true })).toBeVisible();
  fireEvent.click(card.getByRole("button", { name: "Disconnect Mac" }));
  await card.findByText("Mac disconnected. Its access and unused setup commands have been revoked.");
  expect(card.getByText("Server setup needed", { exact: true })).toBeVisible();
  expect(card.queryByRole("button", { name: "Disconnect Mac" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/recording/home-proxy/disconnect", expect.objectContaining({ method: "POST" }));
});
