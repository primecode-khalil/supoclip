import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { YouTubeSetup } from "./youtube-setup";

afterEach(() => vi.unstubAllGlobals());

function setup(overrides = {}) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    configured: false,
    redirect_uri: "https://studio.example/api/social/callback/youtube",
    connections: [], refresh_access_available: false, private_test_completed: false,
    ...overrides,
  }))));
}

it("guides setup with the exact callback and no enabled publishing", async () => {
  setup();
  render(<YouTubeSetup />);
  expect(await screen.findByLabelText("YouTube callback URL")).toHaveValue("https://studio.example/api/social/callback/youtube");
  expect(screen.getByRole("link", { name: /server settings/i })).toHaveAttribute("href", "/admin");
  expect(screen.getByText(/seven days/i)).toBeVisible();
  expect(screen.queryByRole("link", { name: /connect youtube/i })).not.toBeInTheDocument();
  expect(screen.getByText(/public posting stays off/i)).toBeVisible();
});

it("shows a configured connection and the remaining private test", async () => {
  setup({ configured: true, connections: [{ id: "one", display_name: "Demo Channel", status: "active" }], refresh_access_available: true });
  render(<YouTubeSetup />);
  expect(await screen.findByText("Demo Channel")).toBeVisible();
  expect(screen.getByText(/private test upload/i)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("recovers from a setup load failure without changing account settings", async () => {
  const request = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ configured: true, redirect_uri: "https://studio.example/callback", connections: [], refresh_access_available: false, private_test_completed: false })));
  vi.stubGlobal("fetch", request);
  render(<YouTubeSetup />);
  fireEvent.click(await screen.findByRole("button", { name: /retry/i }));
  expect(await screen.findByRole("link", { name: /connect youtube/i })).toHaveAttribute("href", "/api/social/connect/youtube");
  expect(request.mock.calls.every(([, options]) => !options.method || options.method === "GET")).toBe(true);
});
