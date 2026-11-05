import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Batch 34 (perf 2026-10-25): page-load checks for Watch and Portfolio at phone widths against the BUILT app
// (dist/) with every API answered from fixtures after a fixed delay. Pins what made the phone pages slow:
//   * page reads must not queue behind app-chrome polls (useApi priority 'background');
//   * Portfolio asks for symbol cards / Finviz strips of its holdings only (?symbols=), never the universe maps;
//   * the Watch re-entry banner asks for its exit symbols' slice of the 9.4 MB shared context (?symbols=);
//   * with 250 ms per API answer the page settles in well under 3 s.
// Run: npm run build && npx playwright test e2e/perf-pages.spec.ts --project=chromium
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(app, 'dist')
const ORIGIN = 'http://perf-pages-fixture.test'
const LATENCY_MS = 250
const CHROME = ['/api/v2/overview', '/api/v2/paper-trade-readiness', '/api/v2/risk-regime/latest', '/api/v2/trade-ai/summary',
  '/api/v2/live-trading-gate', '/api/v2/health', '/api/v2/design-features', '/api/v2/cio/asks/tracked']

const HOLDINGS = ['AAA', 'BBB', 'CCC'].map((symbol, i) => ({ symbol, account: 'ROTH', shares: 10 + i, price: 20 + i,
  market_value: 200 + i, cost_basis: 150, name: `${symbol} Corp` }))
const EXIT_ROWS = [{ symbol: 'XYZ', trade_date: '2026-10-20', account: 'ROTH', shares: 5, price: 10 }, { symbol: 'QQQ1', trade_date: '2026-10-21' }]

function fixture(pathname: string, url: URL): unknown {
  if (pathname === '/api/v2/portfolio/holdings') return { holdings: HOLDINGS, as_of: '2026-10-25T12:00:00Z' }
  if (pathname === '/api/v2/symbol-cards') return { cards: Object.fromEntries((url.searchParams.get('symbols') ?? '').split(',').filter(Boolean).map(s => [s, { description: `${s} card` }])) }
  if (pathname === '/api/v2/finviz-strip-map') return { ok: true, map: {} }
  if (pathname === '/api/v2/ui/prefs/get') {
    const key = url.searchParams.get('key')
    if (key === 'portfolio.reentry.exit-universe.v1') return { ok: true, key, value: { rows: EXIT_ROWS } }
    if (key === 'portfolio.shared-symbol-context.v1') return { ok: true, key, value: { generated_at: '2026-10-25T12:00:00Z', symbols: {} } }
    return { ok: true, key, value: null }
  }
  return { ok: true }
}

const contentType = (file: string) => file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'application/octet-stream'

async function load(page: Page, route: string) {
  const reads: { path: string; search: string; at: number }[] = []
  let inflight = 0, last = 0
  const t0 = Date.now()
  await page.route('**/*', async r => {
    const req = r.request(), url = new URL(req.url())
    if (url.origin !== ORIGIN) return r.abort()
    if (req.isNavigationRequest()) return r.fulfill({ contentType: 'text/html', body: fs.readFileSync(path.join(dist, 'index.html'), 'utf8') })
    if (url.pathname.startsWith('/v3/') && !url.pathname.startsWith('/v3/api')) {
      const file = path.join(dist, url.pathname.slice('/v3/'.length))
      return fs.existsSync(file) ? r.fulfill({ contentType: contentType(file), body: fs.readFileSync(file) }) : r.fulfill({ status: 404, body: '' })
    }
    if (!url.pathname.startsWith('/api/')) return r.fulfill({ status: 404, body: '' })
    if (req.method() !== 'GET') return r.abort()
    reads.push({ path: url.pathname, search: url.search, at: Date.now() - t0 })
    inflight++
    await new Promise(res => setTimeout(res, LATENCY_MS))
    inflight--; last = Date.now()
    return r.fulfill({ json: fixture(url.pathname, url) })
  })
  await page.goto(`${ORIGIN}/v3${route}`)
  // settled = no API request in flight for 1 s
  await expect.poll(() => inflight === 0 && last > 0 && Date.now() - last > 1000, { timeout: 20_000, intervals: [100] }).toBe(true)
  return { reads, settleMs: last - t0 }
}

test.skip(!fs.existsSync(path.join(dist, 'index.html')), 'needs a built app: npm run build')

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test(`portfolio loads its holdings' cards first and fast at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    const { reads, settleMs } = await load(page, '/portfolio')
    const cards = reads.filter(r => r.path === '/api/v2/symbol-cards')
    const strips = reads.filter(r => r.path === '/api/v2/finviz-strip-map')
    expect(cards.length).toBeGreaterThan(0)
    expect(strips.length).toBeGreaterThan(0)
    for (const r of [...cards, ...strips]) expect(new URLSearchParams(r.search).get('symbols')).toBe('AAA,BBB,CCC')
    const holdingsAt = reads.find(r => r.path === '/api/v2/portfolio/holdings')!.at
    // the app chrome mounts first and may take up to two slots (never the third); the rest of it waits for the page
    const chromeBefore = reads.filter(r => CHROME.includes(r.path) && r.path !== '/api/v2/overview' && r.at < holdingsAt)
    expect(chromeBefore.length).toBeLessThanOrEqual(2)
    expect(settleMs).toBeLessThan(3000)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
  })

  test(`watch asks for its own data before app chrome and a slice of the shared context at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    const { reads, settleMs } = await load(page, '/watch')
    const shared = reads.filter(r => r.path === '/api/v2/ui/prefs/get' && r.search.includes('shared-symbol-context'))
    expect(shared.length).toBeGreaterThan(0)
    for (const r of shared) expect(new URLSearchParams(r.search).get('symbols')).toBe('QQQ1,XYZ')
    const pageRead = reads.find(r => r.path.startsWith('/api/v3/data-broker/watch-'))
    expect(pageRead).toBeTruthy()
    const lateChrome = reads.filter(r => ['/api/v2/trade-ai/summary', '/api/v2/live-trading-gate', '/api/v2/health', '/api/v2/design-features'].includes(r.path))
    for (const r of lateChrome) expect(r.at).toBeGreaterThanOrEqual(pageRead!.at)
    expect(settleMs).toBeLessThan(3000)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
