// Actual WatchMyList + useApi + CSS. Entire synthetic origin fulfilled in-browser; no server/provider/DB.
// node e2e/watch-freshness-noise.fixture.mjs <evidence-directory>
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium, expect } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })
const clock = '2026-10-24T14:00:00Z'
const base = { value: 10, as_of: '2026-10-23T19:45:00Z', source: 'data_broker.latest_quote:schwab',
  source_label: 'Stored quote · schwab', stale: true, freshness: 'STALE', reason: 'Price observation is stale.' }
const level = { value: 9, source: 'watchlist_symbol_master', source_label: 'Watch symbol master',
  as_of: null, as_of_basis: 'not exposed by source', stale: null, freshness: 'UNKNOWN', reason: 'Level observation time unavailable.' }
const broken = { value: 8, source: 'watchlist_symbol_master', source_label: 'Watch symbol master', as_of: null, relation: 'BELOW_PRICE' }
const facts = { schema: 'WatchMarketFacts@v1', price: base, support: level,
  resistance: { ...level, value: 11, source: 'ui_prefs:portfolio.reentry.resistance.v1', source_label: 'Closed-session resistance cache',
    as_of: '2026-10-23', as_of_basis: 'last closed session', broken_reference: broken,
    reason: 'Watch symbol master resistance is below the shown price. Closed-session date; level freshness is not assessed.' } }
function row(symbol, market_facts) {
  return { schema: 'WatchProspectRow@v1', symbol, security_guid: `fixture-${symbol}`, company: 'Synthetic source facts',
    lane: 'forming', stage: 'watch', conviction: 50, conviction_components: [], conviction_missing: [], stance: 'WATCH',
    why: 'Stored evidence only', summary: 'Synthetic fixture, not a recommendation', conflicts: [], whats_missing: [],
    next_trigger: { label: 'Observe' }, next_action: { kind: 'none', label: 'Observe', reason: 'Fixture only' },
    surfaces: [], mine: true, starred: true, membership: [], position_state: 'never_held', market_facts }
}
const rows = [row('AAA', facts), row('BBB', { ...facts, price: { ...base, as_of: '2026-10-22T19:45:00Z' },
  resistance: { ...level, value: null, source: null, source_label: 'No reference', broken_reference: broken, fallback_status: 'none_above_price' } }),
row('CCC', { ...facts, support: { ...level, value: null, source: null, source_label: 'No reference',
  broken_reference: { ...broken, value: 12, relation: 'ABOVE_PRICE' }, fallback_status: 'none_below_price' } })]
const payload = { ok: true, interim: false, my_watchlist: { rows, count: 3, unfiltered_count: 3, starred: 3,
  sources: {}, position_filters: {}, position_facets: {} } }
const bundled = await build({ stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
  import {MemoryRouter} from 'react-router-dom'; import WatchMyList from './src/pages/WatchMyList';
  import './src/index.css'; import './src/pages/WatchLayout.css';
  createRoot(document.getElementById('root')).render(<MemoryRouter><main className="cc-terminal-ui"
    style={{padding:12,background:'var(--bg0)',color:'var(--text0)',minHeight:'100vh'}}>
    <h1>SYNTHETIC Watch freshness fixture</h1><WatchMyList /></main></MemoryRouter>);`, resolveDir: app,
  loader: 'tsx', sourcefile: 'watch-freshness-fixture.tsx' }, bundle: true, write: false, outfile: 'fixture.js',
  jsx: 'automatic', platform: 'browser', define: { 'process.env.NODE_ENV': '"production"' } })
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css')).text
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body>
  <div id="root"></div><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`
const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  for (const width of [1440, 412]) for (const status of [200, 503, 403]) {
    const context = await browser.newContext({ viewport: { width, height: 1050 }, serviceWorkers: 'block' })
    const page = await context.newPage()
    await page.clock.install({ time: new Date(clock) })
    const traffic = { reads: [], unexpected: [], mutations: [], external: [], errors: [] }
    let curation = 0
    page.on('pageerror', e => traffic.errors.push(e.message))
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url())
      if (url.origin !== 'http://watch-freshness-fixture.test') { traffic.external.push(req.url()); return route.abort() }
      if (req.method() !== 'GET') { traffic.mutations.push(req.method() + ' ' + url.pathname); return route.abort() }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      traffic.reads.push(url.pathname)
      if (url.pathname === '/api/v3/data-broker/watch-curation') {
        curation++
        return route.fulfill({ status: curation > 1 ? status : 200, contentType: 'application/json',
          body: JSON.stringify(curation > 1 && status !== 200 ? { error: 'Synthetic unavailable' } : payload) })
      }
      if (url.pathname === '/api/v2/watch/alerts/list') return route.fulfill({ contentType: 'application/json', body: '{"alerts":[]}' })
      traffic.unexpected.push(url.pathname); return route.abort()
    })
    await page.goto('http://watch-freshness-fixture.test/')
    const first = page.locator('[data-testid="mine-row"][data-symbol="AAA"]')
    const price = first.getByTestId('watch-market-price')
    await expect(price.locator('[data-state]')).toHaveText('Closed session · 2026-10-23')
    await expect(price).toContainText('Intraday observation')
    await expect(price).toContainText('03:45:00 PM EDT')
    await expect(price).not.toContainText('2026-10-23 close')
    await expect(first.getByTestId('watch-market-resistance')).toContainText('$8.00 broken — nearest valid level: $11.00')
    await expect(first.getByTestId('watch-market-resistance').locator('.watch-market-source')).toHaveText('Closed session')
    await expect(first.getByTestId('watch-market-resistance').locator('[title]')).toHaveAttribute('title', /ui_prefs:portfolio\.reentry\.resistance\.v1/)
    await expect(first.getByTestId('watch-market-time-unknown')).toHaveCount(1)
    assert.equal((await first.innerText()).match(/time unknown/g)?.length, 1)
    await expect(page.locator('[data-symbol="BBB"][data-testid="mine-row"]').getByTestId('watch-market-price').locator('[data-state]')).toHaveText('Stale')
    await expect(page.locator('[data-symbol="BBB"][data-testid="mine-row"]').getByTestId('watch-market-resistance')).toContainText('none above price')
    await expect(page.locator('[data-symbol="CCC"][data-testid="mine-row"]').getByTestId('watch-market-support')).toContainText('none below price')
    const source = await price.locator('.watch-market-source').getAttribute('title')
    const observed = await price.locator('time').getAttribute('datetime')
    if (status !== 200) {
      await page.clock.runFor(120001)
      await expect(page.getByTestId('watch-market-refresh-warning')).toContainText('last successful snapshot')
      await expect(price.locator('[data-state]')).toHaveText('Last snapshot')
      await expect(price).toContainText('$10.00')
      assert.equal(await price.locator('.watch-market-source').getAttribute('title'), source)
      assert.equal(await price.locator('time').getAttribute('datetime'), observed)
      assert.equal(curation, 2)
      if (status === 403) { await page.clock.runFor(120001); assert.equal(curation, 2, 'denial stops automatic polling') }
    }
    const geometry = await page.evaluate(() => ({ document: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth, panels: Array.from(document.querySelectorAll('[data-testid="watch-market-facts"]'))
        .map(el => ({ client: el.clientWidth, scroll: el.scrollWidth })) }))
    assert(geometry.scroll <= geometry.document + 1, JSON.stringify(geometry))
    assert(geometry.panels.every(p => p.scroll <= p.client + 1), JSON.stringify(geometry))
    assert.deepEqual({ ...traffic, reads: [] }, { reads: [], unexpected: [], mutations: [], external: [], errors: [] })
    // Keyboard access reveals the original observations and both selected/broken sources.
    const summary = first.locator('summary'); await summary.focus(); await page.keyboard.press('Enter')
    await expect(first.locator('details')).toHaveAttribute('open', '')
    await expect(first.locator('details')).toContainText('Broken reference: Watch symbol master')
    await page.keyboard.press('Enter')
    const name = `watch-freshness-${width}-${status}`
    await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true, animations: 'disabled' })
    results.push({ name, fixture: true, clock, width, status, geometry, curation, source, observed,
      displayed: await first.innerText(), traffic })
    await context.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ fixture: true, cases: results }, null, 2) + '\n')
console.log(`Watch freshness actual MyList fixture: ${results.length} cases passed; ${out}`)
