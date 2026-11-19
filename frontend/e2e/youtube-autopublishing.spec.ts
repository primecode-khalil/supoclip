import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test.use({ video: "on" });
let media: Buffer;
test.beforeAll(async ({ browser }) => {
  const dir = mkdtempSync(join(tmpdir(), "supoclip-review-demo-"));
  try {
    const path = join(dir, "demo.mp4");
    const frame = await browser.newPage({ viewport: { width: 360, height: 640 } });
    const image = join(dir, "frame.png");
    await frame.setContent(`<body style="margin:0;background:#202824;color:white;font-family:Arial;height:640px;display:flex;flex-direction:column;align-items:center;justify-content:space-between"><p style="margin-top:80px;font-size:14px;letter-spacing:3px">DEMO PREVIEW</p><div style="width:180px;height:180px;border-radius:50%;border:2px solid #779186;display:grid;place-items:center;font-size:48px">▶</div><p style="font-weight:700;font-size:30px;text-align:center;margin-bottom:110px;line-height:1.4">Small steps.<br>Great stories.</p></body>`);
    await frame.screenshot({ path: image });
    await frame.close();
    execFileSync("ffmpeg", ["-v","error","-loop","1","-i",image,"-f","lavfi","-i","sine=frequency=330:duration=4","-t","4","-r","24","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",path]);
    media = readFileSync(path);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

for (const width of [1440, 320]) {
  test(`reviews captioned videos sequentially and manages native schedules at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const account = { id: "demo-channel", provider: "youtube", display_name: "Demo Creator", status: "active" };
    let settings = { policy: { mode: "review", enabled: true, uploads_paused: false, timezone: "UTC", min_score: 75, category_id: "22", made_for_kids: false, contains_synthetic_media: null,
      schedule: { kind: "interval", interval_minutes: 360, anchor_at: "2026-12-01T12:00:00Z", weekdays: [0,1,2,3,4,5,6], times: ["09:00", "15:00"] } }, next_slot: "2026-12-01T12:00:00Z", pending_review: 2, permissions_complete: true, private_test_completed: false, legacy: false };
    const clips = ["one", "two"].map((id, i) => ({ id, account_id: account.id, task_id: "demo-source", clip_id: id, version: "a".repeat(64), status: "pending", title: i ? "A moment worth keeping" : "Small steps make great stories", caption: "A complete thought, ready for the next story. #Shorts", score: 91-i, duration: 4, source_title: "Demo recording · captioned vertical clip", video_url: `/api/demo-video/${id}` }));
    let pending = [...clips];
    let rejected: typeof clips = [];
    let posts: Record<string, unknown>[] = [];
    let approvals = 0;
    await page.route("**/api/**", route => route.fulfill({ json: {} }));
    await page.route("**/api/auth/get-session**", route => route.fulfill({ json: { session: { id: "demo-session", userId: "demo-owner", expiresAt: "2099-01-01T00:00:00Z" }, user: { id: "demo-owner", name: "Studio Owner", email: "owner@example.com", emailVerified: true, is_admin: true } } }));
    await page.route("**/api/tasks/billing-summary", route => route.fulfill({ json: { monetization_enabled: false } }));
    await page.route("**/api/announcements**", route => route.fulfill({ json: { announcements: [] } }));
    await page.route("**/api/social/providers", route => route.fulfill({ json: { enabled: true, providers: [] } }));
    await page.route("**/api/social/youtube/setup", route => route.fulfill({ json: { configured: true, connections: [account], private_test_completed: false } }));
    await page.route("**/api/demo-video/*", route => route.fulfill({ body: media, contentType: "video/mp4" }));
    await page.route("**/api/social/posts?*", route => route.fulfill({ json: { posts } }));
    await page.route("**/api/social/review?*", route => route.fulfill({ json: { items: route.request().url().includes("status=rejected") ? rejected : pending, settings } }));
    await page.route("**/api/social/review/*/approve", async route => {
      approvals++;
      const body = route.request().postDataJSON();
      expect(body.expected_version).toBe("a".repeat(64));
      const item = pending.shift()!;
      const post = { id: "demo-post", title: body.title, caption: body.caption, social_account_id: account.id, provider: "youtube", status: "scheduled", stage: "youtube_scheduled", scheduled_for: settings.next_slot, actual_visibility: "private", external_url: "https://www.youtube.com/shorts/demo", provider_options: { native_schedule: true }, account: { display_name: account.display_name } };
      posts = [post]; settings = { ...settings, next_slot: "2026-12-01T18:00:00Z" };
      await route.fulfill({ json: { item: { ...item, status: "approved" }, post, settings } });
    });
    await page.route("**/api/social/review/*/reject", route => { const item = pending.shift()!; rejected = [item]; return route.fulfill({ json: { item: { ...item, status: "rejected" } } }); });
    await page.route("**/api/social/review/*/undo", route => { pending = [...rejected, ...pending]; rejected = []; return route.fulfill({ json: { item: pending[0] } }); });
    await page.route("**/api/social/accounts/*/automation", route => { settings = { ...settings, policy: route.request().postDataJSON() }; return route.fulfill({ json: settings }); });
    await page.route("**/api/social/posts/*/cancel", route => { posts = posts.map(post => ({ ...post, status: "publishing", provider_options: { native_schedule: true, cancel_requested: true } })); return route.fulfill({ json: { post: posts[0] } }); });
    await page.goto("/publishing");
    const title = page.getByLabel("Title", { exact: true });
    await expect(title).toHaveValue(clips[0].title);
    await page.getByLabel("Clip preview").evaluate(async element => { await (element as HTMLVideoElement).play(); });
    await expect.poll(() => page.getByLabel("Clip preview").evaluate(element => (element as HTMLVideoElement).currentTime)).toBeGreaterThan(0.2);
    await page.screenshot({ path: `test-results/shorts-review-${width}.png`, fullPage: true });
    await title.fill("Small steps, great stories");
    await title.press("r");
    expect(rejected).toHaveLength(0);
    await page.getByRole("button", { name: "Approve & schedule", exact: true }).click();
    await expect(title).toHaveValue(clips[1].title);
    expect(approvals).toBe(1);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByText("You’re caught up")).toBeVisible();
    await page.getByRole("button", { name: "Undo rejection" }).click();
    await expect(title).toHaveValue(clips[1].title);
    await page.getByRole("button", { name: /posting pattern/i }).click();
    await page.getByLabel("Every (hours)").fill("12");
    await page.getByLabel("Timezone", { exact: true }).fill("Europe/Bucharest");
    await page.getByRole("button", { name: "Save pattern", exact: true }).click();
    await expect(page.getByText("Pattern saved.", { exact: true })).toBeVisible();
    expect(settings.policy.schedule.interval_minutes).toBe(720);
    expect(settings.policy.mode).toBe("review");
    await page.getByRole("button", { name: /posting pattern/i }).click();
    await page.getByRole("button", { name: /^Queue/ }).click();
    await expect(page.getByText("Scheduled on YouTube", { exact: true })).toBeVisible();
    await page.screenshot({ path: `test-results/shorts-queue-${width}.png`, fullPage: true });
    await page.getByRole("button", { name: "Cancel schedule", exact: true }).click();
    await expect(page.getByText(/Cancellation pending/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
