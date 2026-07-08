#!/usr/bin/env node
/**
 * E2E: Portfolio → Stop Management → ⟳ Sync Fidelity GTC stops
 *
 *   node tests/e2e/stop-management-fidelity-sync.mjs
 *   e2e-stop-mgmt-fidelity-sync   # ~/.local/bin symlink
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const RUNTIME = path.join(ROOT, 'data', 'runtime');

const BASE = (process.env.CC_BASE || 'http://127.0.0.1:7777').replace(/\/$/, '');
const URL = `${BASE}/v3/portfolio`;

const results = { base: BASE, steps: [], errors: [] };

async function step(name, fn) {
  try {
    const v = await fn();
    results.steps.push({ name, ok: true, detail: v });
    console.log('OK', name, v ?? '');
    return v;
  } catch (e) {
    results.steps.push({ name, ok: false, detail: String(e?.message || e) });
    results.errors.push(String(e?.message || e));
    console.error('FAIL', name, e?.message || e);
    throw e;
  }
}

async function main() {
  fs.mkdirSync(RUNTIME, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(120_000);

  try {
    const mgmtP = page.waitForResponse(
      r => r.url().includes('/api/v2/stops/management') && r.status() === 200,
      { timeout: 120_000 },
    );

    await step('navigate portfolio', async () => {
      await page.goto(URL, { waitUntil: 'domcontentloaded' });
      return page.url();
    });

    await step('open Stop Management tab', async () => {
      const tab = page.getByRole('button', { name: 'Stop Management', exact: true });
      await tab.waitFor({ state: 'visible', timeout: 30_000 });
      await tab.click();
      return 'clicked';
    });

    await step('wait stops management', async () => {
      await mgmtP;
      return 'loaded';
    });

    const stopMgmtBtn = () => page.locator('button[title*="manual_broker_stops"]');

    await step('find fidelity sync button', async () => {
      const btn = stopMgmtBtn();
      await btn.waitFor({ state: 'visible', timeout: 30_000 });
      const disabled = await btn.isDisabled();
      return disabled ? 'visible-disabled' : 'visible-enabled';
    });

    const apiPromise = page.waitForResponse(
      r => r.url().includes('/api/v2/fidelity-stops/sync') && r.request().method() === 'POST',
      { timeout: 60_000 },
    );
    const refreshP = page.waitForResponse(
      r => r.url().includes('/api/v2/stops/management') && r.request().method() === 'GET',
      { timeout: 60_000 },
    ).catch(() => null);

    await step('click fidelity sync', async () => {
      await stopMgmtBtn().click();
      return 'clicked';
    });

    const apiRes = await step('fidelity-stops/sync API', async () => {
      const res = await apiPromise;
      const json = await res.json();
      const data = json?.data ?? json;
      return {
        status: res.status(),
        ok: json?.ok !== false && !(data?.errors?.length),
        upserted: Array.isArray(data?.upserted) ? data.upserted.length : 0,
        errors: data?.errors?.length ?? 0,
      };
    });

    if (!apiRes?.ok) {
      throw new Error(`fidelity-stops/sync failed: ${JSON.stringify(apiRes)}`);
    }

    await step('ui success message', async () => {
      const msg = page.getByText(/✓ Fidelity GTC/i).first();
      await msg.waitFor({ state: 'visible', timeout: 30_000 });
      return (await msg.textContent())?.trim();
    });

    await step('refresh after sync', async () => {
      const res = await refreshP;
      return res ? `HTTP ${res.status()}` : 'no explicit refresh (ok if cached)';
    });

    const fidRows = await step('fidelity rows protected', async () => {
      await page.getByText('SCHG', { exact: true }).first().waitFor({ state: 'visible', timeout: 20_000 });
      const body = await page.locator('body').innerText();
      const syms = ['SCHG', 'ARKX', 'XAR', 'ANET', 'DXCM', 'DIVI'];
      const found = syms.filter(s => body.includes(s));
      return { found, count: found.length };
    });

    results.pass = true;
    results.api = apiRes;
    results.fidRows = fidRows;
  } catch (e) {
    results.pass = false;
    results.finalError = String(e?.message || e);
    try {
      const shot = path.join(RUNTIME, 'e2e-stop-mgmt-fidelity-sync-fail.png');
      await page.screenshot({ path: shot, fullPage: true });
      results.screenshot = shot;
      results.pageSnippet = (await page.locator('body').innerText()).slice(0, 2000);
    } catch { /* best effort */ }
  } finally {
    await browser.close();
    const out = path.join(RUNTIME, 'e2e-stop-mgmt-fidelity-sync.json');
    fs.writeFileSync(out, JSON.stringify(results, null, 2));
    console.log('\n=== RESULT ===');
    console.log(JSON.stringify(results, null, 2));
    console.log('wrote', out);
    process.exit(results.pass ? 0 : 1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});