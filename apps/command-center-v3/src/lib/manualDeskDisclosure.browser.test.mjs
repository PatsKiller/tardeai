// Hermetic desk-disclosure integration: only fetch is fake; no server, no live API.
//
// codex P1 at f5586fdd1 (PR 2599): manualSetupScope.test.mjs's `/onToggle=\{/` check accepts a
// nonfunctional callback such as `onToggle={() => {}}`, and its render assertions supply their own
// `expanded` prop. Neither proves that clicking "Show details" wires the desk's own state. This file
// renders the REAL ManualTosDesk, clicks the disclosure, and asserts what the operator sees:
//   - wide screen: the inline ticket (sizing/actions) opens and closes;
//   - phone (<= 820 px): the full-screen sheet opens, and pressing the control on the open sheet closes it;
//   - phone, collapsed: the row is ONE column even though W9Mobile.css forces two with !important
//     (codex P2 at f5586fdd1) — a collapsed row has one grid child, so its summary must fill the row.
//
// The rules are the real files: the component tree is bundled from src/, and W9Mobile.css is read from
// disk and injected untouched, so deleting the exemption rule fails this suite.
// Run: node src/lib/manualDeskDisclosure.browser.test.mjs [repo-root] [result.json]
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), '../../../..'))
const app = join(root, 'apps/command-center-v3')
const require = createRequire(join(app, 'package.json'))
const { build } = require('esbuild')
const { chromium } = require('@playwright/test')

const bundle = await build({
  stdin: {
    contents: `
      import React, { act } from 'react'
      import { createRoot } from 'react-dom/client'
      import Desk from './src/pages/ManualTosDesk'
      window.IS_REACT_ACT_ENVIRONMENT = true
      const root = createRoot(document.getElementById('root'))
      // Wrap in the same container class TradingHub's Path A uses, so W9Mobile.css selects it.
      window.mountDesk = () => act(async () => root.render(<div className="w9-entry-desk"><Desk /></div>))
      window.unmountDesk = () => act(async () => root.unmount())
    `,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  jsx: 'automatic',
  platform: 'browser',
  define: { 'process.env.NODE_ENV': '"test"' },
})
const w9mobileCss = readFileSync(join(app, 'src/pages/W9Mobile.css'), 'utf8')

// One curated proposal is enough to render a row. Every other endpoint gets an empty, well-formed body.
const fixtures = {
  '/api/v2/paper-proposals': {
    proposals: [{
      proposal_id: 'P-1', symbol: 'AAA', company: 'Fixture Corp', entry_price: 10, stop_price: 9,
      target_price: 12, decision: 'GO', score: 80, thesis: 'fixture thesis',
    }],
  },
  '/api/v2/broker-orders/drafts': { drafts: [] },
  '/api/v2/broker-orders/activity': { activity: [] },
  '/api/v2/watchlist/items': { items: [] },
  '/api/v2/symbol-cards': { cards: {} },
  '/api/v2/schwab/accounts-live': { accounts: [] },
  '/api/v2/watchlist/summary': {},
  '/api/v2/execution/current-state': {},
  '/api/v2/entry-desk/automation': {},
  '/api/v2/pro-analyst/pills': { map: {} },
  '/api/v2/entry-desk/technical-grades': { ok: false },
}

async function openDesk(browser, { viewport, withMobileCss }) {
  const page = await browser.newPage({ viewport })
  const pageErrors = []
  const externalRequests = []
  page.on('pageerror', error => pageErrors.push(error.message))
  // Any accidental network request is refused and also fails the test.
  await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
  await page.setContent('<div id="root"></div>')
  if (withMobileCss) await page.addStyleTag({ content: w9mobileCss })
  await page.evaluate(fixtures => {
    window.fixtures = fixtures
    window.fetch = async url => {
      const target = String(url)
      const key = Object.keys(window.fixtures).find(k => target.includes(k))
      const body = key ? window.fixtures[key] : {}
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
  }, fixtures)
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.evaluate(() => window.mountDesk())
  await page.waitForSelector('[data-testid="entry-desk-row"]', { timeout: 15_000 })
  return { page, pageErrors, externalRequests }
}

const results = []
const browser = await chromium.launch({ headless: true })
try {
  // ── wide screen: the inline ticket opens and closes ────────────────────────────────────────────────
  {
    const scenario = 'desktop inline disclosure'
    const { page, pageErrors, externalRequests } = await openDesk(browser, { viewport: { width: 1280, height: 900 }, withMobileCss: false })
    try {
      const toggle = page.getByTestId('entry-desk-details-toggle').first()
      assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'the desk starts with the ticket folded')
      assert.equal(await page.getByRole('button', { name: 'Copy setup', exact: true }).count(), 0, 'the inline ticket renders while folded')
      await toggle.click()
      await page.waitForFunction(() =>
        document.querySelector('[data-testid="entry-desk-details-toggle"]')?.getAttribute('aria-expanded') === 'true',
        null, { timeout: 5_000 })
      assert.equal(await page.getByRole('button', { name: 'Copy setup', exact: true }).count(), 1,
        'clicking Show details did not open the inline ticket (the page onToggle is not wired to its state)')
      assert.match(await page.locator('body').innerText(), /Sizing is read-only/, 'the opened ticket lost its sizing column')
      assert.equal(await page.getByText('Hide details ▴', { exact: true }).count(), 1, 'the control did not flip to Hide details')
      await page.getByTestId('entry-desk-details-toggle').first().click()
      await page.waitForFunction(() =>
        document.querySelector('[data-testid="entry-desk-details-toggle"]')?.getAttribute('aria-expanded') === 'false',
        null, { timeout: 5_000 })
      assert.equal(await page.getByRole('button', { name: 'Copy setup', exact: true }).count(), 0, 'Hide details left the ticket open')
      assert.deepEqual(pageErrors, [], 'the desk must not throw in the browser')
      assert.deepEqual(externalRequests, [], 'all fetches must stay in the fake boundary')
      await page.evaluate(() => window.unmountDesk())
      results.push({ scenario, passed: true })
    } catch (error) {
      results.push({ scenario, passed: false, error: error.name, assertion: error.message, text: await page.locator('body').innerText() })
    } finally {
      await page.close()
    }
  }

  // ── phone: collapsed row is one column, the control opens the sheet, the sheet control closes it ───
  {
    const scenario = 'phone sheet disclosure + collapsed grid'
    const { page, pageErrors, externalRequests } = await openDesk(browser, { viewport: { width: 390, height: 844 }, withMobileCss: true })
    try {
      const rowGrid = page.getByTestId('entry-desk-row-grid').first()
      assert.equal(await rowGrid.getAttribute('data-desk-collapsed'), 'true', 'the collapsed row does not mark itself for the stylesheet')
      const ratio = await rowGrid.evaluate(el => {
        const child = el.firstElementChild
        return child.getBoundingClientRect().width / el.getBoundingClientRect().width
      })
      assert.ok(ratio > 0.9,
        `a collapsed phone row leaves its summary in ${Math.round(ratio * 100)}% of the row — W9Mobile.css's two-column override still applies`)
      assert.equal(await page.getByTestId('manual-desk-detail-sheet').count(), 0, 'the phone sheet rendered before it was asked for')

      await page.getByTestId('entry-desk-details-toggle').first().click()
      const sheet = page.getByTestId('manual-desk-detail-sheet').first()
      await sheet.waitFor({ state: 'visible', timeout: 5_000 })
      assert.equal(await sheet.getAttribute('role'), 'dialog', 'the phone detail sheet is not a dialog')
      assert.equal(await sheet.getAttribute('aria-label'), 'AAA ticket', 'the sheet is not the clicked row')
      assert.equal(await page.getByRole('button', { name: 'Copy setup', exact: true }).count(), 1,
        'the opened phone sheet does not contain the full ticket')

      // codex B2: the control on the OPEN sheet must close it, not re-set the same key.
      await page.getByText('Hide details ▴', { exact: true }).click()
      await sheet.waitFor({ state: 'detached', timeout: 5_000 })
      assert.equal(await page.getByTestId('entry-desk-row').count(), 1, 'closing the sheet lost the shortlist row')
      assert.deepEqual(pageErrors, [], 'the desk must not throw in the browser')
      assert.deepEqual(externalRequests, [], 'all fetches must stay in the fake boundary')
      await page.evaluate(() => window.unmountDesk())
      results.push({ scenario, passed: true })
    } catch (error) {
      results.push({ scenario, passed: false, error: error.name, assertion: error.message, text: await page.locator('body').innerText() })
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}

const result = { source_root: root, actual_desk: true, live_requests: false, results,
  passed: results.filter(row => row.passed).length, failed: results.filter(row => !row.passed).length }
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(result, null, 2) + '\n')
console.log(JSON.stringify(result, null, 2))
process.exitCode = result.failed ? 1 : 0
