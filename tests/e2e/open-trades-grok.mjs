#!/usr/bin/env node
/**
 * E2E: Open Trades → per-holding ▶ Grok stop advisory (PositionDecisionCard).
 *
 * Requires portfolio-server on :7777 and Grok OAuth ready.
 *
 * From repo root:
 *   npm run test:e2e:open-trades-grok
 *   CC_SYMBOL=ANET npm run test:e2e:open-trades-grok
 *
 * From anywhere (no cd):
 *   ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/e2e-open-trades-grok.sh
 *   e2e-open-trades-grok   # if ~/.local/bin symlink installed
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const RUNTIME = path.join(ROOT, 'data', 'runtime');

const BASE = (process.env.CC_BASE || 'http://127.0.0.1:7777').replace(/\/$/, '');
const SYMBOL = (process.env.CC_SYMBOL || 'NEE').trim().toUpperCase();
const URL = `${BASE}/v3/trading?tab=Open+Trades&symbol=${encodeURIComponent(SYMBOL)}`;

const results = { symbol: SYMBOL, base: BASE, steps: [], errors: [] };

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
    const intelP = page.waitForResponse(
      r => r.url().includes('/api/v2/open-trades/intelligence') && r.status() === 200,
      { timeout: 120_000 },
    );
    const covP = page.waitForResponse(
      r => r.url().includes('/api/v2/portfolio/llm-coverage') && r.status() === 200,
      { timeout: 120_000 },
    );
    const oauthP = page.waitForResponse(
      r => r.url().includes('/api/v2/llm/oauth-lanes') && r.status() === 200,
      { timeout: 120_000 },
    );

    await step('navigate', async () => {
      await page.goto(URL, { waitUntil: 'domcontentloaded' });
      return page.url();
    });

    await step('wait intelligence', async () => {
      await Promise.all([intelP, covP, oauthP]);
      return 'loaded';
    });

    await step('focused symbol banner', async () => {
      const banner = page.getByText(new RegExp(`Focused on.*${SYMBOL}`, 'i'));
      await banner.waitFor({ state: 'visible', timeout: 30_000 });
      return (await banner.textContent())?.trim().slice(0, 80);
    });

    await step('find protection advisory', async () => {
      const txt = page.getByText('Protection advisory', { exact: false }).first();
      await txt.waitFor({ state: 'visible', timeout: 30_000 });
      return 'visible';
    });

    await step('find grok button', async () => {
      const btn = page.getByRole('button', { name: /▶ Grok/i }).first();
      await btn.waitFor({ state: 'visible', timeout: 15_000 });
      const disabled = await btn.isDisabled();
      return disabled ? 'visible-but-disabled' : 'visible-enabled';
    });

    const apiPromise = page.waitForResponse(
      r => r.url().includes('/api/v2/consumption/stop-advisory') && r.request().method() === 'POST',
      { timeout: 120_000 },
    );

    await step('click grok', async () => {
      const btn = page.getByRole('button', { name: /▶ Grok/i }).first();
      await btn.click();
      return 'clicked';
    });

    const apiRes = await step('stop-advisory API', async () => {
      const res = await apiPromise;
      const json = await res.json();
      const data = json?.data ?? json;
      return {
        status: res.status(),
        ok: data?.ok,
        stop: data?.protection?.stop_price,
        symbol: data?.symbol,
      };
    });

    if (!apiRes?.ok) {
      throw new Error(`stop-advisory failed: ${JSON.stringify(apiRes)}`);
    }

    await step('ui success message', async () => {
      const msg = page.getByText(/✓ Grok stop/i).first();
      await msg.waitFor({ state: 'visible', timeout: 120_000 });
      return (await msg.textContent())?.trim();
    });

    const stopText = await step('inline stop price visible', async () => {
      const el = page.locator('text=/stop.*\\$[0-9]+\\.[0-9]{2}/i').first();
      await el.waitFor({ state: 'visible', timeout: 10_000 });
      return (await el.textContent())?.trim();
    });

    results.pass = true;
    results.api = apiRes;
    results.stopText = stopText;
  } catch (e) {
    results.pass = false;
    results.finalError = String(e?.message || e);
    try {
      const shot = path.join(RUNTIME, 'e2e-open-trades-grok-fail.png');
      await page.screenshot({ path: shot, fullPage: true });
      results.screenshot = shot;
      const body = await page.locator('body').innerText();
      results.pageSnippet = body.slice(0, 1500);
    } catch { /* best effort */ }
  } finally {
    await browser.close();
    const out = path.join(RUNTIME, 'e2e-open-trades-grok.json');
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