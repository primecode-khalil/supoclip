import { mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const demoCommand = "curl -fsSL https://demo.example/home-proxy/install.sh | sh -s -- DEMO-ONLY-NOT-A-PAIRING-TOKEN";
const unpaired = { available: true, paired: false, connected: false, device_name: null as string | null, paired_at: null as string | null };
let status = { ...unpaired };
let setups = 0;
let disconnects = 0;
let pageErrors: string[] = [];

// Record isolated demo contexts only. All APIs below use fake account and pairing data.
test.use({ viewport: { width: 1280, height: 900 }, video: { mode: "on", size: { width: 1280, height: 900 } } });

test.beforeEach(async ({ page }) => {
  status = { ...unpaired }; setups = disconnects = 0; pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => { if (["error", "warning"].includes(message.type())) pageErrors.push(message.text()); });
  // Exercise the browser copy flow without replacing the operator's system clipboard.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async (value: string) => { (window as Window & { demoCopiedCommand?: string }).demoCopiedCommand = value; } } });
  });
  await page.route("**/api/**", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/auth/get-session**", (route) => route.fulfill({ json: { session: { id: "demo-session", userId: "demo-owner", expiresAt: "2099-01-01T00:00:00Z" }, user: { id: "demo-owner", name: "Studio Owner", email: "owner@example.com", emailVerified: true, is_admin: true } } }));
  await page.route("**/api/tasks/billing-summary", (route) => route.fulfill({ json: { monetization_enabled: false } }));
  await page.route("**/api/preferences", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/announcements**", (route) => route.fulfill({ json: { announcements: [] } }));
  await page.route("**/api/social/providers", (route) => route.fulfill({ json: { enabled: true, providers: [] } }));
  await page.route("**/api/social/connections", (route) => route.fulfill({ json: { connections: [] } }));
  await page.route("**/api/recording/channels?*", (route) => route.fulfill({ json: { channels: [], total: 0 } }));
  await page.route("**/api/proxy", route => route.fulfill({ json: { connections: [], max_url_connections: 10 } }));
  await page.route("**/api/recording/home-proxy", (route) => route.fulfill({ json: status }));
  await page.route("**/api/recording/home-proxy/setup", (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ device_name: "My Mac" });
    setups++;
    return route.fulfill({ json: { setup_command: demoCommand, expires_at: new Date(Date.now() + 600_000).toISOString() } });
  });
  await page.route("**/api/recording/home-proxy/disconnect", (route) => {
    expect(route.request().method()).toBe("POST");
    disconnects++; status = { ...unpaired };
    return route.fulfill({ json: status });
  });
});

async function artifact(name: string, testInfo: TestInfo) {
  const directory = process.env.HOME_PROXY_UI_ARTIFACT_DIR || testInfo.outputPath("home-proxy");
  await mkdir(directory, { recursive: true });
  return path.join(directory, name);
}

async function showState(page: Page) {
  if (process.env.HOME_PROXY_UI_ARTIFACT_DIR) await page.waitForTimeout(700);
}

async function finishVideo(page: Page, name: string, testInfo: TestInfo) {
  const video = page.video();
  await page.close();
  if (video) await video.saveAs(await artifact(name, testInfo));
}

test("sets up a Mac, copies the command, polls pairing, and disconnects", async ({ page }, testInfo) => {
  await page.clock.install();
  await page.goto("/proxy");
  const card = page.getByRole("region", { name: "Mac home connection" });
  await expect(card.getByText("Not connected", { exact: true })).toBeVisible();
  await showState(page);
  await expect(card.getByRole("textbox", { name: "Mac setup command" })).toHaveCount(0);
  expect(setups).toBe(0);
  await card.getByRole("button", { name: "Set up my Mac" }).focus();
  await page.keyboard.press("Enter");
  await expect(card.getByRole("textbox", { name: "Mac setup command" })).toHaveValue(demoCommand);
  await expect(card.getByText(/starts at login and reconnects automatically/)).toBeVisible();
  await page.screenshot({ path: await artifact("desktop-setup.png", testInfo), fullPage: true });
  await showState(page);
  await card.getByRole("button", { name: "Copy command" }).click();
  await expect(card.getByText("Command copied.")).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { demoCopiedCommand?: string }).demoCopiedCommand)).toBe(demoCommand);
  expect(setups).toBe(1);
  await showState(page);
  status = { ...unpaired, paired: true, device_name: "Studio Mac", paired_at: "2026-11-18T10:00:00Z" };
  await page.clock.fastForward(15_000);
  await expect(card.getByText("Waiting for Mac", { exact: true })).toBeVisible();
  await showState(page);
  await expect(card.getByRole("textbox", { name: "Mac setup command" })).toHaveCount(0);
  status.connected = true;
  await page.clock.fastForward(15_000);
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  await expect(card.getByText(/Use Test YouTube/)).toBeVisible();
  await page.screenshot({ path: await artifact("desktop-connected.png", testInfo), fullPage: true });
  await showState(page);
  await card.getByRole("button", { name: "Disconnect Mac" }).click();
  await expect(card.getByText("Not connected", { exact: true })).toBeVisible();
  await expect(card.getByRole("button", { name: "Disconnect Mac" })).toHaveCount(0);
  expect(disconnects).toBe(1);
  await showState(page);
  expect(pageErrors).toEqual([]);
  await finishVideo(page, "desktop-flow.webm", testInfo);
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 320, height: 850 } });

  test("keeps setup and connected controls usable at 320 pixels", async ({ page }, testInfo) => {
  await page.goto("/proxy");
  const card = page.getByRole("region", { name: "Mac home connection" });
  await card.getByRole("button", { name: "Set up my Mac" }).click();
  const command = card.getByRole("textbox", { name: "Mac setup command" });
  await expect(command).toHaveValue(demoCommand);
  await card.getByRole("button", { name: "Copy command" }).click();
  await expect(card.getByText("Command copied.")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: await artifact("mobile-320-setup.png", testInfo), fullPage: true });
  await showState(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const bounds = await command.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320);
  status = { ...unpaired, paired: true, connected: true, device_name: "Studio Mac", paired_at: "2026-11-18T10:00:00Z" };
  await card.getByRole("button", { name: "Check connection" }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  await expect(command).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: await artifact("mobile-320-connected.png", testInfo), fullPage: true });
  await showState(page);
  await card.getByRole("button", { name: "Disconnect Mac" }).click();
  await expect(card.getByText("Not connected", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(pageErrors).toEqual([]);
  await finishVideo(page, "mobile-320-flow.webm", testInfo);
});
});
