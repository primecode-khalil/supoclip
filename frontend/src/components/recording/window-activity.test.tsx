import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WindowActivity } from "./window-activity";
import type { WindowList } from "./types";

const data: WindowList = { total: 1, windows: [{ id: "one", session_id: "session", epoch: "epoch", sequence: 0, start_seconds: 0, end_seconds: 600, status: "blocked", task_id: "generation", attempts: 3, next_attempt_at: null, last_error: "Reconnect your account", created_at: "2026-11-16T10:00:00Z" }] };

it("retries the saved window and surfaces a rejected recovery request", async () => {
  const retry = vi.fn().mockRejectedValue(new Error("Check the publishing account before retrying"));
  render(<WindowActivity data={data} onRetry={retry} />);
  fireEvent.click(screen.getByRole("button", { name: "Retry window 1" }));
  await waitFor(() => expect(retry).toHaveBeenCalledWith("one"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Check the publishing account before retrying");
  expect(screen.getByRole("button", { name: "Retry window 1" })).toBeEnabled();
});

it("explains that the daily limit keeps extra clips in the library", () => {
  const capped: WindowList = { total: 1, windows: [{ ...data.windows[0], status: "completed", last_error: null, publication_capped: true }] };
  render(<WindowActivity data={capped} onRetry={vi.fn()} />);
  expect(screen.getByText("Daily publishing limit reached. Remaining clips are saved in your library.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open clips and generation" })).toHaveAttribute("href", "/tasks/generation");
});
