import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PublicationQueue } from "./publication-queue";
import type { SocialPost } from "@/lib/social";
afterEach(() => vi.unstubAllGlobals());
const post = { id: "one", title: "Demo Short", provider: "youtube", status: "scheduled", stage: "youtube_scheduled", scheduled_for: "2026-12-01T12:00:00Z", external_url: "https://www.youtube.com/shorts/demo", provider_options: { native_schedule: true } } as SocialPost;
it("shows native confirmation and requests cancellation without prematurely labelling it cancelled", async () => {
  const refresh = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ post: { ...post, status: "publishing", provider_options: { cancel_requested: true } } })));
  const { rerender } = render(<PublicationQueue posts={[post]} timezone="UTC" onRefresh={refresh} />);
  expect(screen.getByText("Scheduled on YouTube")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Cancel schedule" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  rerender(<PublicationQueue posts={[{ ...post, status: "publishing", provider_options: { cancel_requested: true } }]} timezone="UTC" onRefresh={refresh} />);
  expect(screen.getByText(/Cancellation pending/)).toBeVisible();
  expect(screen.queryByText("Cancelled · kept private")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View on YouTube" })).toHaveAttribute("href", post.external_url);
});
it("keeps a failed cancellation visible with retry and Studio access", () => {
  render(<PublicationQueue posts={[{ ...post, status: "failed", error_message: "Reconnect YouTube", provider_options: { cancel_requested: true } }]} timezone="UTC" onRefresh={vi.fn()} />);
  expect(screen.getByText("Reconnect YouTube")).toBeVisible();
  expect(screen.getByRole("button", { name: "Retry saved work" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Check YouTube Studio" })).toHaveAttribute("href", "https://studio.youtube.com");
});
