import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReviewStudio } from "./review-studio";

const account = { id: "account", display_name: "Demo channel", provider: "youtube", status: "active" } as const;
const policy = { mode: "review", enabled: true, uploads_paused: false, timezone: "UTC", min_score: 75, category_id: "22", made_for_kids: false, schedule: { kind: "interval", interval_minutes: 360, anchor_at: "2026-12-01T12:00:00Z", weekdays: [0,1,2,3,4,5,6], times: ["09:00"] } };
const settings = { policy, next_slot: "2026-12-01T12:00:00Z", permissions_complete: true, private_test_completed: false, legacy: false, pending_review: 2 };
const clips = ["one", "two"].map(id => ({ id, account_id: "account", title: `Clip ${id}`, caption: `Description ${id}`, source_title: "Demo source", score: 91, version: "a".repeat(64), video_url: `/demo-${id}.mp4`, status: "pending" }));

afterEach(() => { vi.unstubAllGlobals(); });
function setup(fail = false, delayed = false) {
  let items = [...clips];
  let saved = settings;
  let complete: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "PUT") { saved = { ...saved, policy: JSON.parse(options.body as string) }; return Response.json(saved); }
    if (url.includes("/posts?")) return Response.json({ posts: [] });
    if (url.includes("/approve") || url.includes("/reject")) {
      if (delayed) await new Promise<void>(resolve => { complete = resolve; });
      if (fail) return Response.json({ detail: "YouTube needs reconnection" }, { status: 409 });
      const item = items[0]; items = items.slice(1);
      return Response.json({ item: { ...item, status: url.includes("approve") ? "approved" : "rejected" }, settings: saved });
    }
    if (url.includes("/undo")) { items = [...clips]; return Response.json({ item: clips[0] }); }
    if (url.includes("status=rejected")) return Response.json({ items: [], settings: saved });
    return Response.json({ items, settings: saved });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ReviewStudio account={account} />);
  return { fetcher, finish: () => complete?.() };
}

it("shows one vertical preview and advances only after approval acknowledgement", async () => {
  const { fetcher, finish } = setup(false, true);
  const button = await screen.findByRole("button", { name: /approve & schedule/i });
  expect(screen.getByLabelText("Clip preview")).toHaveAttribute("src", "/demo-one.mp4");
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "My approved title" } });
  fireEvent.click(button); fireEvent.click(button);
  expect(screen.getByLabelText("Title")).toHaveValue("My approved title");
  expect(fetcher.mock.calls.filter(([url]) => url.includes("/approve"))).toHaveLength(1);
  finish();
  await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Clip two"));
  const request = fetcher.mock.calls.find(([url]) => url.includes("/approve"))![1];
  expect(JSON.parse(request!.body as string)).toMatchObject({ expected_version: "a".repeat(64), title: "My approved title" });
});

it("ignores shortcuts while editing, then rejects with R and restores with Undo", async () => {
  const { fetcher } = setup();
  const title = await screen.findByLabelText("Title");
  fireEvent.keyDown(title, { key: "r" });
  fireEvent.keyDown(document.body, { key: "a", repeat: true });
  expect(fetcher.mock.calls.some(([url]) => url.includes("/reject") || url.includes("/approve"))).toBe(false);
  fireEvent.keyDown(document.body, { key: "r" });
  await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Clip two"));
  fireEvent.click(screen.getByRole("button", { name: /undo rejection/i }));
  await waitFor(() => expect(screen.getByLabelText("Title")).toHaveValue("Clip one"));
});

it("keeps the current clip and edits when the server rejects a decision", async () => {
  setup(true);
  const title = await screen.findByLabelText("Title");
  fireEvent.change(title, { target: { value: "Keep my edit" } });
  fireEvent.click(screen.getByRole("button", { name: /approve & schedule/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("YouTube needs reconnection");
  expect(screen.getByLabelText("Title")).toHaveValue("Keep my edit");
});

it("Later rotates locally without making a decision", async () => {
  const { fetcher } = setup();
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  expect(screen.getByLabelText("Title")).toHaveValue("Clip two");
  expect(fetcher.mock.calls.every(([, opts]) => !opts?.method)).toBe(true);
});

it("saves a six-hour pattern and selected timezone without enabling automatic approval", async () => {
  const { fetcher } = setup();
  fireEvent.click(await screen.findByRole("button", { name: /posting pattern/i }));
  expect(screen.getByLabelText("Every (hours)")).toHaveValue(6);
  fireEvent.change(screen.getByLabelText("Every (hours)"), { target: { value: "12" } });
  fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "Europe/Bucharest" } });
  fireEvent.click(screen.getByRole("button", { name: "Save pattern" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([, opts]) => opts?.method === "PUT")).toBe(true));
  const body = JSON.parse(fetcher.mock.calls.find(([, opts]) => opts?.method === "PUT")![1]!.body as string);
  expect(body).toMatchObject({ mode: "review", timezone: "Europe/Bucharest", schedule: { interval_minutes: 720 } });
  expect(screen.getByLabelText("Automatically approve future live clips")).toBeDisabled();
});

it("saves weekly local times and selected days", async () => {
  const { fetcher } = setup();
  fireEvent.click(await screen.findByRole("button", { name: /posting pattern/i }));
  fireEvent.change(screen.getByLabelText("Pattern"), { target: { value: "weekly" } });
  fireEvent.click(screen.getByLabelText("Sunday"));
  fireEvent.change(screen.getByLabelText("Local times (24-hour, comma separated)"), { target: { value: "09:00, 15:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Save pattern" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([, opts]) => opts?.method === "PUT")).toBe(true));
  const body = JSON.parse(fetcher.mock.calls.find(([, opts]) => opts?.method === "PUT")![1]!.body as string);
  expect(body.schedule).toMatchObject({ kind: "weekly", times: ["09:00", "15:00"], weekdays: [0,1,2,3,4,5] });
});
