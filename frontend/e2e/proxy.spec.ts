import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 1000 }, video: { mode: 'on', size: { width: 1440, height: 1000 } } });

for (const width of [1440, 320]) {
  test(`manages connections and failover at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    let failNextEdit = false;
    let rows = [
      { id: 'home', name: 'Studio Mac', kind: 'home', revision: 'home-v1', usage: 'both', priority: 0, enabled: true, country: '', endpoint: '172.19.0.1:18888', scheme: 'http', has_credentials: false, health: { status: 'working', retry_after_seconds: 0 } },
      { id: 'backup', name: 'Backup connection', kind: 'url', revision: 'backup-v1', usage: 'both', priority: 1, enabled: true, country: '', endpoint: 'backup.example:8080', scheme: 'http', has_credentials: true, health: { status: 'cooldown', retry_after_seconds: 30 } },
    ];
    await page.route('**/api/**', route => route.fulfill({ json: {} }));
    await page.route('**/api/auth/get-session**', route => route.fulfill({ json: { session: { id: 'demo-session', userId: 'demo-owner', expiresAt: '2099-01-01T00:00:00Z' }, user: { id: 'demo-owner', name: 'Studio Owner', email: 'owner@example.com', emailVerified: true, is_admin: true } } }));
    await page.route('**/api/tasks/billing-summary', route => route.fulfill({ json: { monetization_enabled: false } }));
    await page.route('**/api/announcements**', route => route.fulfill({ json: { announcements: [] } }));
    await page.route('**/api/social/providers', route => route.fulfill({ json: { enabled: true, providers: [] } }));
    await page.route('**/api/recording/home-proxy', route => route.fulfill({ json: { available: true, paired: true, connected: true, device_name: 'Studio Mac', paired_at: '2026-11-20T10:00:00Z' } }));
    await page.route('**/api/proxy{,/**}', async route => {
      const request = route.request(), method = request.method();
      const url = new URL(request.url()).pathname;
      const body = request.postDataJSON() || {};
      if (method === 'PATCH' && failNextEdit) {
        failNextEdit = false;
        return route.fulfill({ status: 409, json: { detail: 'Connection changed. Reload before editing.' } });
      }
      if (url.endsWith('/test')) {
        rows = rows.map(row => row.id === 'backup' ? { ...row, health: { status: 'reachable', retry_after_seconds: 0 } } : row);
        return route.fulfill({ json: { ok: true, message: 'YouTube metadata reached. Playback is checked during an import or recording.' } });
      }
      if (method === 'POST') rows.push({ ...rows[1], id: 'new', name: body.name, usage: body.usage, endpoint: 'second.example:1080', health: { status: 'not_checked', retry_after_seconds: 0 } });
      if (method === 'PATCH') rows = rows.map(row => url.endsWith(row.id) ? { ...row, ...body } : row);
      if (method === 'DELETE') rows = rows.filter(row => !url.endsWith(row.id));
      if (method === 'PUT') rows = body.connection_ids.map((id: string) => rows.find(row => row.id === id)!);
      return route.fulfill({ json: { connections: rows, max_url_connections: 10 } });
    });
    const artifactDir = process.env.PROXY_UI_ARTIFACT_DIR || testInfo.outputPath('proxy');
    await mkdir(artifactDir, { recursive: true });
    await page.goto('/proxy');
    await expect(page.getByRole('article', { name: 'Studio Mac proxy' })).toBeVisible();
    await expect(page.getByText('Retry in 30s')).toBeVisible();
    await page.screenshot({ path: path.join(artifactDir, `proxy-${width}.png`), fullPage: true });
    await page.getByLabel('Use Studio Mac for').selectOption('live');
    await expect(page.getByLabel('Use Studio Mac for')).toBeEnabled();
    await page.getByRole('button', { name: 'Test Backup connection' }).click();
    await expect(page.getByText('Metadata reached', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Move Backup connection up' }).click();
    await expect(page.getByRole('article').first()).toHaveAccessibleName('Backup connection proxy');
    await page.getByRole('button', { name: 'Edit Backup connection' }).click();
    const edit = page.getByRole('dialog');
    await expect(edit.getByLabel('Proxy URL')).toHaveValue('');
    await edit.getByLabel('Connection name').fill('Backup for imports');
    failNextEdit = true;
    await edit.getByRole('button', { name: 'Save proxy' }).click();
    await expect(edit.getByRole('alert')).toContainText('Connection changed');
    await expect(edit.getByLabel('Connection name')).toHaveValue('Backup for imports');
    await edit.getByRole('button', { name: 'Save proxy' }).click();
    await expect(edit).toHaveCount(0);
    await page.getByRole('button', { name: 'Add proxy', exact: true }).click();
    const add = page.getByRole('dialog');
    await add.getByLabel('Connection name').fill('Second connection');
    await add.getByLabel('Proxy URL').fill('socks5h://demo:DEMO-ONLY-PASSWORD@second.example:1080');
    await add.getByLabel('Use for').selectOption('imports');
    await add.getByRole('button', { name: 'Save proxy' }).click();
    await expect(add).toHaveCount(0);
    await expect(page.getByRole('article', { name: 'Second connection proxy' })).toBeVisible();
    expect(await page.locator('body').innerText()).not.toContain('DEMO-ONLY-PASSWORD');
    await page.getByLabel('Enable Second connection').click();
    await expect(page.getByLabel('Enable Second connection')).not.toBeChecked();
    await expect(page.getByText('Paused', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Remove Second connection' }).click();
    const remove = page.getByRole('alertdialog');
    await remove.getByRole('button', { name: 'Remove connection' }).click();
    await expect(remove).toHaveCount(0);
    await expect(page.getByRole('article', { name: 'Second connection proxy' })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    const video = page.video();
    await page.close();
    if (video) await video.saveAs(path.join(artifactDir, `proxy-${width}.webm`));
  });
}
