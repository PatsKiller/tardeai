// LQ-20261113-3062 (review 3051 A3): the real ReEntryRotationWorkspace, mounted in Chromium, shows a watchlist
// 503 build_deferred as UNKNOWN with its retry hint, never as an empty watch row, and retries on the hint.
// Hermetic: only fetch is fake (synthetic bodies); every real network request is refused and fails the test.
// Run: node src/components/reentry/reentryWatchUnknown.browser.test.mjs [repo-root] [result.json]
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), '../../../../..'))
const app = join(root, 'apps/command-center-v3')
const require = createRequire(join(app, 'package.json'))
const { build } = require('esbuild')
const { chromium } = require('@playwright/test')
const bundle = await build({
  stdin: {
    contents: `
      import React from 'react'
      import { createRoot } from 'react-dom/client'
      import { MemoryRouter } from 'react-router-dom'
      import View from './src/components/reentry/ReEntryRotationWorkspace'
      window.mountWorkspace = () => createRoot(document.getElementById('root')).render(<MemoryRouter><View mode="full" /></MemoryRouter>)
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

const LINK = {
  id: 'L1', sourceEventId: 1, sourceSymbol: 'AAA', destinationSymbol: 'BBB', account: 'fixture', amountMoved: 1000,
  sourceShares: 100, sourceExitDate: '2026-11-01', sourceExitPrice: 10, destinationPurchaseDate: '2026-11-02',
  destinationCost: 20, destinationShares: 50, reason: 'volatility_reduction', intendedDurationDays: null, switchType: 'temporary',
  targetSourceAllocationPct: null, returnMode: 'full', tranches: [], thesis: '', invalidation: '', confirmed: true,
  suggested: false, rsThresholdPct: 0, taxClear: true, accountClear: true, settlementClear: true,
  createdAt: '2026-11-02T00:00:00Z', updatedAt: '2026-11-02T00:00:00Z',
}

const browser = await chromium.launch({ headless: true })
const results = []
try {
  for (const scenario of ['503 then 200', '200 first']) {
    const page = await browser.newPage({ serviceWorkers: 'block' })
    const pageErrors = []
    const externalRequests = []
    page.on('pageerror', error => pageErrors.push(error.message))
    await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
    try {
      await page.setContent('<div id="root"></div>')
      await page.evaluate(({ scenario, link }) => {
        window.watchCalls = []
        window.watchStatus = scenario === '503 then 200' ? 503 : 200   // the test flips 503 -> 200
        const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
        window.fetch = async (url) => {
          url = String(url)
          if (url.startsWith('/api/v2/watchlist/items')) {
            const status = window.watchStatus
            window.watchCalls.push(status)
            if (status === 503) return json(503, { ok: false, status: 'UNKNOWN', state: 'UNKNOWN', error: 'build_deferred', reason: 'REFUSED_CAP', retry_after_sec: 1 })
            return json(200, { ok: true, items: [{ symbol: 'AAA', last_price: 11 }, { symbol: 'BBB', last_price: 21 }] })
          }
          if (url.startsWith('/api/v2/redeploy/book')) return json(200, { ok: true, data: { rows: [{ event_id: 1, symbol: 'AAA', sold_at: '2026-11-01', account: 'fixture', sell_price: 10, proceeds_usd: 1000, shares_sold: 100 }] } })
          if (url.includes('portfolio.reentry.rotation-links')) return json(200, { ok: true, data: { value: { L1: link } } })
          if (url.startsWith('/api/v2/symbol-cards')) return json(200, { ok: true, data: { cards: {} } })
          return json(200, { ok: true, data: {} })
        }
      }, { scenario, link: LINK })
      await page.addScriptTag({ content: bundle.outputFiles[0].text })
      await page.evaluate(() => window.mountWorkspace())
      await page.waitForFunction(() => window.watchCalls.length >= 1)
      await page.getByText('▸ intelligence').click()
      const banner = page.getByTestId('reentry-watch-unknown')
      if (scenario === '503 then 200') {
        await banner.waitFor({ state: 'visible', timeout: 5000 })
        await page.waitForFunction(() => /for 2 symbols/.test(document.querySelector('[data-testid="reentry-watch-unknown"]')?.textContent ?? ''), null, { timeout: 5000 })
        const text = await banner.innerText()
        assert.match(text, /WATCHLIST DATA UNKNOWN/)
        assert.match(text, /UNKNOWN for 2 symbols: HTTP 503 build_deferred \(REFUSED_CAP\)/)
        assert.match(text, /retrying in 1 s \(retry \d+ of \d+\)/)
        assert.match(text, /not known, not empty/)
        assert.equal(await page.getByTestId('reentry-watch-unknown-pill').count(), 2, 'both rotation sides marked UNKNOWN')
        assert.equal(await page.getByText('$11.00').count(), 0, 'no price while UNKNOWN')
        // the server's retry hint (1 s) is honoured: the page asks again on its own
        const before = await page.evaluate(() => window.watchCalls.length)
        await page.waitForFunction(n => window.watchCalls.length > n, before, { timeout: 5000 })
        // the build finishes: the next retry is a 200 and the UNKNOWN clears
        await page.evaluate(() => { window.watchStatus = 200 })
        await banner.waitFor({ state: 'detached', timeout: 5000 })
        assert.equal(await page.getByTestId('reentry-watch-unknown-pill').count(), 0)
        await page.getByText('$11.00').first().waitFor({ timeout: 5000 })
      } else {
        await page.getByText('$11.00').first().waitFor({ timeout: 5000 })
        assert.equal(await banner.count(), 0, 'a good read shows no UNKNOWN banner')
        assert.equal(await page.getByTestId('reentry-watch-unknown-pill').count(), 0)
      }
      const watchCalls = await page.evaluate(() => window.watchCalls)
      assert.deepEqual(pageErrors, [])
      assert.deepEqual(externalRequests, [])
      results.push({ scenario, ok: true, watchCalls })
      console.log(`  [PASS] ${scenario} (watchlist answers ${watchCalls.join(', ')})`)
    } catch (error) {
      const body = await page.evaluate(() => document.body.innerText.slice(0, 600)).catch(() => '')
      results.push({ scenario, ok: false, error: String(error?.message || error), pageErrors, externalRequests, body })
      console.log(`  [FAIL] ${scenario}: ${String(error?.message || error).split('\n')[0]}`)
      console.log(`         pageErrors=${JSON.stringify(pageErrors)} body=${JSON.stringify(body.slice(0, 300))}`)
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(results, null, 2))
const failed = results.filter(r => !r.ok).length
console.log(`\n${results.length - failed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
