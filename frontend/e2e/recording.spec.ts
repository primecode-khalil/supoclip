import { expect, test } from "@playwright/test";

const channel = { id: "demo-channel", platform: "twitch", handle: "demo_creator", url: "https://www.twitch.tv/demo_creator", name: "Demo Creator", enabled: true, quality: "best", created_at: "2026-11-16T10:00:00Z", updated_at: "2026-11-16T10:00:00Z" };
const defaults = { enabled: false, segment_seconds: 600, overlap_seconds: 60, processing_mode: "balanced", caption_template: "default", clip_length: "auto", min_score: 75, max_clips_per_window: 3, max_posts_per_day: 10, social_account_ids: [], publish_privacy: "private", archive: false, retain_days: 7 };

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: { session: { id: "session", userId: "user", expiresAt: "2099-01-01T00:00:00Z" }, user: { id: "user", name: "Studio Owner", email: "owner@example.com", emailVerified: true, is_admin: true } } }));
  await page.route("**/api/tasks/billing-summary", (route) => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/announcements**", (route) => route.fulfill({ json: { announcements: [] } }));
  await page.route("**/api/social/providers", (route) => route.fulfill({ json: { enabled: true, providers: [] } }));
  await page.route("**/api/social/connections", (route) => route.fulfill({ json: { connections: [] } }));
  await page.route("**/api/recording/home-proxy", (route) => route.fulfill({ json: { available: true, paired: false, connected: false, device_name: null, paired_at: null } }));
  await page.route("**/api/recording/channels?*", (route) => route.fulfill({ json: { channels: [channel], total: 1 } }));
  await page.route("**/api/recording/channels/*/sessions?*", (route) => route.fulfill({ json: { sessions: [], total: 0 } }));
  await page.route("**/api/recording/channels/*/windows?*", (route) => route.fulfill({ json: { windows: [], total: 0 } }));
  await page.route("**/api/recording/channels/*/automation", (route) => route.fulfill({ json: { policy: defaults, runtime: { leased: false, expires_at: null, last_heartbeat_at: null, last_error: null } } }));
});

test("enables and pauses saved automation without confusing monitoring with capture", async ({ page }) => {
  let policy = { ...defaults };
  await page.route("**/api/recording/channels/*/automation", (route) => {
    if (route.request().method() === "PUT") policy = route.request().postDataJSON();
    return route.fulfill({ json: { policy, runtime: { leased: false } } });
  });
  await page.goto("/recording");
  await page.getByRole("button", { name: "Enable automation", exact: true }).click();
  await expect(page.getByText("Waiting for recorder", { exact: true })).toBeVisible();
  expect(policy.enabled).toBe(true);
  await page.getByRole("button", { name: "Pause automation", exact: true }).click();
  await expect(page.getByText("Automation paused", { exact: true })).toBeVisible();
  expect(policy.enabled).toBe(false);
});

test("validates a handle and adds a channel without implicitly enabling it", async ({ page }) => {
  let submitted: Record<string, unknown> | undefined;
  await page.route("**/api/recording/channels", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { ...channel, ...submitted, id: "new-channel" } });
  });
  await page.goto("/recording");
  await page.getByRole("button", { name: "Add channel", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Display name").fill("New creator");
  await dialog.getByLabel("Channel handle").fill("https://twitch.tv/new_creator");
  await dialog.getByRole("button", { name: "Add channel", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("without the full URL");
  expect(submitted).toBeUndefined();
  await dialog.getByLabel("Channel handle").fill("new_creator");
  await dialog.getByRole("button", { name: "Add channel", exact: true }).click();
  await expect(page.getByRole("heading", { name: "New creator", exact: true })).toBeVisible();
  expect(submitted).toEqual({ platform: "twitch", name: "New creator", handle: "new_creator" });
  await expect(page.getByRole("button", { name: "Enable automation", exact: true })).toBeVisible();
});

test("requires public visibility before saving an Instagram destination", async ({ page }) => {
  let submitted: Record<string, unknown> | undefined;
  await page.route("**/api/social/connections", (route) => route.fulfill({ json: { connections: [{ id: "instagram-demo", provider: "instagram", display_name: "Demo Reels", username: "demo_reels", status: "active" }] } }));
  await page.route("**/api/recording/channels/*/automation", (route) => {
    if (route.request().method() === "PUT") submitted = route.request().postDataJSON();
    return route.fulfill({ json: { policy: submitted ?? defaults, runtime: { leased: false } } });
  });
  await page.goto("/recording");
  await page.getByRole("checkbox", { name: /Demo Reels/ }).check();
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Instagram requires Public visibility");
  expect(submitted).toBeUndefined();
  await page.getByLabel("Publication visibility").selectOption("public");
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByText("Settings saved", { exact: true })).toBeVisible();
  expect(submitted).toMatchObject({ publish_privacy: "public", social_account_ids: ["instagram-demo"] });
});

test("keeps form edits through polling, validates overlap, and saves preserved settings", async ({ page }) => {
  let reads = 0;
  let submitted: Record<string, unknown> | undefined;
  await page.route("**/api/recording/channels/*/automation", async (route) => {
    if (route.request().method() === "PUT") submitted = route.request().postDataJSON();
    else reads++;
    await route.fulfill({ json: { policy: submitted ?? { ...defaults, max_clips_per_window: 8 }, runtime: { leased: false } } });
  });
  await page.goto("/recording");
  await page.getByLabel("Minimum clip score").fill("90");
  const initialReads = reads;
  await expect.poll(() => reads, { timeout: 12_000 }).toBeGreaterThan(initialReads);
  await expect(page.getByLabel("Minimum clip score")).toHaveValue("90");
  await page.getByLabel("Segment length (seconds)").fill("60");
  await page.getByLabel("Overlap (seconds)").fill("90");
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Overlap must be shorter");
  expect(submitted).toBeUndefined();
  await page.getByLabel("Overlap (seconds)").fill("30");
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByText("Settings saved", { exact: true })).toBeVisible();
  expect(submitted).toMatchObject({ min_score: 90, max_clips_per_window: 8, enabled: false });
});

test("keeps a recoverable channel error separate from social connection errors", async ({ page }) => {
  let fail = true;
  await page.route("**/api/recording/channels?*", (route) => route.fulfill(fail ? { status: 503, json: { detail: "The recording service is unavailable" } } : { json: { channels: [channel], total: 1 } }));
  await page.route("**/api/social/connections", (route) => route.fulfill({ status: 503, json: { detail: "Publishing accounts are unavailable" } }));
  await page.goto("/recording");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The recording service is unavailable");
  fail = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Demo Creator", exact: true })).toBeVisible();
  await expect(page.getByRole("form", { name: "Automation settings" })).toBeVisible();
  await expect(page.getByText(/Publishing accounts are unavailable/)).toBeVisible();
});

test("is usable at a narrow mobile width and links to actual clip generations", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await page.route("**/api/recording/channels/*/windows?*", (route) => route.fulfill({ json: { total: 1, windows: [{ id: "one", session_id: "session", epoch: "epoch", sequence: 0, start_seconds: 0, end_seconds: 600, status: "blocked", task_id: "generation-one", attempts: 3, next_attempt_at: null, last_error: "Reconnect your publishing account", created_at: "2026-11-16T10:00:00Z" }] } }));
  await page.goto("/recording");
  await expect(page.getByRole("link", { name: "Open clips and generation" })).toHaveAttribute("href", "/tasks/generation-one");
  await expect(page.getByText("Needs attention", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/recording-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("retries an existing blocked window and refreshes its saved status", async ({ page }) => {
  let retries = 0;
  await page.route("**/api/recording/channels/*/windows/one/retry", (route) => {
    retries++;
    return route.fulfill({ json: { id: "one", status: "processing" } });
  });
  await page.route("**/api/recording/channels/*/windows?*", (route) => route.fulfill({ json: { total: 1, windows: [{ id: "one", session_id: "session", epoch: "epoch", sequence: 0, start_seconds: 0, end_seconds: 600, status: retries ? "processing" : "blocked", task_id: "generation-one", attempts: 3, next_attempt_at: null, last_error: retries ? null : "Reconnect your publishing account", created_at: "2026-11-16T10:00:00Z" }] } }));
  await page.goto("/recording");
  await page.getByRole("button", { name: "Retry window 1" }).click();
  await expect(page.getByText("Clipping", { exact: true })).toBeVisible();
  expect(retries).toBe(1);
  await expect(page.getByRole("link", { name: "Open clips and generation" })).toHaveAttribute("href", "/tasks/generation-one");
});

test("signed-out visitors do not request recording data", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: null }));
  await page.route("**/api/recording/**", (route) => { requests++; return route.fulfill({ status: 401 }); });
  await page.goto("/recording");
  await expect(page.getByRole("heading", { name: "Sign in to manage live channels" })).toBeVisible();
  expect(requests).toBe(0);
});

for (const width of [1280, 320]) {
  test(`clears failed and finished history while retaining active work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let windows = [
      { id: "failed", sequence: 0, status: "blocked", task_id: null, last_error: "The bound task was deleted; automatic recreation is disabled" },
      { id: "completed", sequence: 1, status: "completed", task_id: null, last_error: null },
      { id: "active", sequence: 2, status: "pending", task_id: null, last_error: null },
    ].map((item) => ({ ...item, session_id: "demo-session", epoch: "demo-epoch", start_seconds: 0, end_seconds: 600, attempts: 0, next_attempt_at: null, created_at: "2026-11-19T10:00:00Z" }));
    const scopes: string[] = [];
    await page.route("**/api/recording/channels/*/windows?*", async (route) => {
      if (route.request().method() === "DELETE") {
        const scope = new URL(route.request().url()).searchParams.get("scope")!;
        scopes.push(scope);
        const before = windows.length;
        windows = windows.filter((item) => item.status !== "blocked" && (scope !== "finished" || item.status !== "completed"));
        return route.fulfill({ json: { cleared: before - windows.length } });
      }
      return route.fulfill({ json: { windows, total: windows.length } });
    });
    await page.goto("/recording");
    const activity = page.locator('section[aria-labelledby="recording-activity"]');
    await expect(activity.getByText("3 total")).toBeVisible();
    await activity.scrollIntoViewIfNeeded();
    if (process.env.RECORDING_HISTORY_PROOF_DIR) await page.screenshot({ path: `${process.env.RECORDING_HISTORY_PROOF_DIR}/before-${width}.png` });
    await activity.getByRole("button", { name: "Clear failed", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("Captured recordings, library clips, and published posts are kept.");
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(scopes).toEqual([]);
    await activity.getByRole("button", { name: "Clear failed", exact: true }).click();
    await page.getByRole("alertdialog").evaluate((element) => Promise.all(element.getAnimations().map((animation) => animation.finished)));
    await expect(page.getByRole("alertdialog")).toBeInViewport({ ratio: 1 });
    if (process.env.RECORDING_HISTORY_PROOF_DIR) await page.screenshot({ path: `${process.env.RECORDING_HISTORY_PROOF_DIR}/confirm-${width}.png` });
    await page.getByRole("button", { name: "Clear history", exact: true }).click();
    await expect(activity.getByText("2 total")).toBeVisible();
    await expect(activity.getByText("Window 1", { exact: false })).toHaveCount(0);
    await activity.getByRole("button", { name: "Clear all finished", exact: true }).click();
    await expect(page.getByRole("alertdialog")).toContainText("Active work continues.");
    await page.getByRole("button", { name: "Clear history", exact: true }).click();
    await expect(activity.getByText("1 total")).toBeVisible();
    await expect(activity.getByText("Waiting", { exact: true })).toBeVisible();
    expect(scopes).toEqual(["failed", "finished"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (process.env.RECORDING_HISTORY_PROOF_DIR) await page.screenshot({ path: `${process.env.RECORDING_HISTORY_PROOF_DIR}/after-${width}.png` });
  });
}
