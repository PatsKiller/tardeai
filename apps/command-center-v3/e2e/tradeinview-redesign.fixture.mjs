/** Actual B components + A pure-builder responses. Every request is intercepted; never a live server. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium, expect } from '@playwright/test'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const input = process.argv[2] || path.join(app, 'e2e/fixtures/tradeinviewRedesign.fixture.json')
const out = process.argv[3]
assert(out, 'Explicit screenshot/receipt directory required')
assert(fs.existsSync(input), 'Actual A pure-builder fixture export required; no sample-data fallback')
const f = JSON.parse(fs.readFileSync(input, 'utf8'))
assert(f.clock && f.journeys && f.calendar && f.replay, 'A fixture export must identify clock and all three endpoint groups')
const scopes = (process.env.TIV_FIXTURE_SCREENS || 'journeys,calendar,replay').split(',')
assert(scopes.every(s => ['journeys','calendar','replay'].includes(s)), 'Unknown fixture screen selection')
const first = object => Object.values(object)[0]
const fresh = f.journeys.fresh || first(f.journeys), stale = f.journeys.stale
if (scopes.includes('journeys') || scopes.includes('replay')) assert(fresh?.schema === 'TradeJourneys@v1', 'Actual Journey fixture required')
if (scopes.includes('journeys')) assert(stale, 'Actual stale receipt variant required')
const populated = f.calendar.populated || Object.values(f.calendar).find(x => x.summary?.known_trade_count > 0)
const empty = f.calendar.empty
const bars = f.replay.bars || Object.values(f.replay).find(x => x.kind === 'candles' && x.bars?.length)
const closes = f.replay.closes, missing = f.replay.missing
if (scopes.includes('calendar')) assert(populated && empty, 'Actual populated/empty Calendar outputs required')
if (scopes.includes('replay')) assert(bars && closes && missing, 'Actual candles/closes/missing Replay outputs required')
const cases = []
if (scopes.includes('journeys')) for (const [state, test] of [['awaiting-fill', j => j.exit_cause.kind === 'stop_likely_filled'], ['open', j => j.status === 'open' && j.exit_cause.kind !== 'stop_likely_filled'], ['closed', j => j.status === 'closed']]) {
  const row = fresh.journeys.find(test); assert(row, `Actual ${state} Journey fixture required`)
  cases.push({ screen: 'journeys', state, response: fresh, url: `tab=journeys&trade=${encodeURIComponent(row.trade_id)}` })
}
if (scopes.includes('journeys')) cases.push({ screen: 'journeys', state: 'chips-fresh', response: fresh, url: 'tab=journeys' }, { screen: 'journeys', state: 'chips-stale', response: stale, url: 'tab=journeys' })
if (scopes.includes('calendar')) cases.push({ screen: 'calendar', state: 'month-data', response: populated, url: `tab=calendar&month=${populated.month}` }, { screen: 'calendar', state: 'empty-month', response: empty, url: `tab=calendar&month=${empty.month}` }, { screen: 'calendar', state: 'day-drawer', response: populated, url: `tab=calendar&month=${populated.month}` })
if (scopes.includes('calendar') && f.calendar.missing) cases.push({ screen: 'calendar', state: 'missing-source', response: f.calendar.missing, url: `tab=calendar&month=${f.calendar.missing.month}` })
if (scopes.includes('replay')) for (const [state, response] of [['with-bars', bars], ['closes-only', closes], ['missing-bars', missing], ['compare', bars]]) cases.push({ screen: 'replay', state, response, url: `tab=replay&trade=${encodeURIComponent(response.trade_id)}` })
const bundle = await build({ metafile: true, stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import {BrowserRouter} from 'react-router-dom';import TradeInViewPage from './src/pages/TradeInViewPage';import './src/styles/tokens.css';import './src/index.css';createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><TradeInViewPage onDrill={()=>{}} /></BrowserRouter>);`, loader: 'tsx', sourcefile: 'tradeinview-fixture.tsx', resolveDir: app }, bundle: true, write: false, outfile: 'fixture.js', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const sourceFiles = [...Object.keys(bundle.metafile.inputs).map(name => path.resolve(app,name)).filter(file => file.startsWith(path.join(app,'src') + path.sep) && fs.existsSync(file)), path.join(app,'package.json'),path.join(app,'package-lock.json'),fileURLToPath(import.meta.url)]
const sourceHashes = Object.fromEntries(sourceFiles.map(file => [file,sha(file)]))
const testedSource = {head:execFileSync('git',['rev-parse','HEAD'],{cwd:app,encoding:'utf8'}).trim(),working_patch_sha256:crypto.createHash('sha256').update(execFileSync('git',['diff','HEAD'],{cwd:app})).digest('hex'),file_sha256:sourceHashes}
const js = bundle.outputFiles.find(x => x.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(x => x.path.endsWith('.css'))?.text || ''
fs.mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ headless: true })
const receipts = []
const replayHref = id => `/v3/journal?${new URLSearchParams({tab:'replay',trade:id})}`
const dollars = n => n == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', signDisplay: 'exceptZero', maximumFractionDigits: 2 }).format(n)
try {
  for (const width of [1440, 412]) for (const c of cases) {
    const context = await browser.newContext({ viewport: { width, height: 1100 } })
    const page = await context.newPage(), traffic = { reads: [], mutations: [], unexpected: [], external: [], errors: [] }
    await page.clock.setFixedTime(new Date(f.clock))
    page.on('pageerror', e => traffic.errors.push(String(e)))
    await page.routeWebSocket('**/*', ws => { traffic.external.push(ws.url()); ws.close() })
    await page.route('**/*', async route => {
      const req = route.request(), u = new URL(req.url())
      if (u.origin !== 'http://tradeinview-fixture.test') { traffic.external.push(u.origin + u.pathname); return route.abort() }
      if (req.method() !== 'GET') { traffic.mutations.push(req.method() + ' ' + u.pathname); return route.abort() }
      if (u.pathname.startsWith('/v3/')) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{margin:0;background:var(--bg-0)}#root{padding:24px 28px;box-sizing:border-box}@media(max-width:820px){#root{padding:16px}}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      traffic.reads.push(u.pathname + u.search)
      const journeys = c.screen === 'journeys' ? c.response : fresh
      let payload
      if (u.pathname === '/api/v3/data-broker/trade-journeys') payload = journeys
      else if (u.pathname.startsWith('/api/v3/data-broker/trade-journeys/')) {
        const id = decodeURIComponent(u.pathname.slice('/api/v3/data-broker/trade-journeys/'.length)), journey = journeys.journeys.find(j => j.trade_id === id)
        if (journey) payload = { ...journeys, journeys: undefined, journey }
      } else if (u.pathname === '/api/v3/data-broker/trade-calendar') {
        payload = c.screen === 'calendar' && c.response.month === u.searchParams.get('month') ? c.response : Object.values(f.calendar).find(x => x.month === u.searchParams.get('month'))
      } else if (u.pathname === '/api/v2/trade-chart') {
        assert.equal(u.searchParams.get('stored_only'), '1', 'new Replay must never fall through to providers')
        const id = u.searchParams.get('trade_id')
        payload = c.screen === 'replay' && id === c.response.trade_id ? c.response : Object.values(f.replay).find(x => x.trade_id === id)
      }
      if (!payload) { traffic.unexpected.push(u.pathname + u.search); return route.abort() }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) })
    })
    await page.goto(`http://tradeinview-fixture.test/v3/journal?${c.url}`)
    await expect(page.getByRole('heading', { level: 1, name: 'TradeInView', exact: true })).toBeVisible()
    if (c.screen === 'journeys') {
      await expect(page.getByTestId('trade-journey')).toBeVisible()
      for (const chip of c.response.freshness_chips) await expect(page.getByTestId(`tj-chip-${chip.key}`)).toContainText(chip.value ?? chip.missing_reason ?? 'Sync evidence unavailable')
      await expect(page.getByTestId('tj-row')).toHaveCount(c.response.journeys.length)
      if (c.state === 'awaiting-fill') {
        await expect(page.getByTestId('tj-awaiting-fill')).toContainText('Awaiting fill confirmation')
        assert(!(await page.getByTestId('tj-row').allTextContents()).some(text => text.includes('⚠')))
        await expect(page.locator('.tradeinview-reconciliation > div')).toHaveCount(3)
      }
      const selected = c.response.journeys.find(j => j.trade_id === new URLSearchParams(c.url).get('trade'))
      if (selected) { await expect(page.getByTestId('tj-detail')).toContainText(selected.account_label); await expect(page.getByTestId('tj-replay')).toHaveAttribute('href', replayHref(selected.trade_id)) }
    } else if (c.screen === 'calendar') {
      await expect(page.getByTestId('calendar-month-total')).toHaveText(dollars(c.response.summary.realized_pl))
      if (c.state === 'empty-month') await expect(page.getByTestId('calendar-empty')).toBeVisible()
      if (c.state === 'day-drawer') {
        const day = c.response.days.find(d => d.trades.length); assert(day)
        const button = page.locator(`[data-testid="calendar-day"][data-date="${day.date}"]`)
        if (await button.count()) await button.click(); else await page.getByRole('button', { name: new RegExp(day.date) }).click()
        const drawer = page.getByTestId('calendar-day-drawer'); await expect(drawer).toBeVisible()
        for (const trade of day.trades) await expect(drawer.locator(`a[href*="${encodeURIComponent(trade.trade_id)}"]`)).toHaveAttribute('href', replayHref(trade.trade_id))
      }
      if (c.state === 'missing-source') { await expect(page.getByTestId('calendar-month-total')).toHaveText('—'); await expect(page.getByTestId('calendar-empty')).toHaveCount(0) }
    } else {
      await expect(page.getByTestId('trade-replay-page')).toBeVisible()
      if (c.response.bars.length) await expect(page.getByTestId('trade-replay-chart').locator('canvas').first()).toBeVisible()
      else await expect(page.getByText('No stored bars available for this trade and interval.', { exact: true })).toBeVisible()
      const intervals = c.response.available_intervals.filter(i => ['1D', '15m', '5m'].includes(i))
      for (const i of ['1D', '15m', '5m']) await expect(page.getByRole('button', { name: i, exact: true })).toHaveCount(intervals.includes(i) ? 1 : 0)
      if (c.state === 'compare') {
        await page.getByRole('button', { name: '⇄ Compare with a win', exact: true }).click()
        await expect(page.getByRole('dialog', { name: 'Compare recorded trades' })).toBeVisible()
        await expect(page.getByRole('button', { name: 'Close comparison' })).toBeFocused()
        await expect(page.getByRole('dialog').getByTestId('trade-replay-chart')).toHaveCount(2)
        for (const chart of await page.getByRole('dialog').getByTestId('trade-replay-chart').all()) await expect(chart.locator('canvas').first()).toBeVisible()
      } else if (c.response.bars.length) {
        const chart = page.getByTestId('trade-replay-chart'); await chart.getByRole('button', { name: 'Step back', exact: true }).click()
        await expect(chart).not.toHaveAttribute('data-replay-position', '0')
        await chart.getByRole('slider', { name: 'Replay position' }).press('Home')
        await chart.getByRole('button', { name: 'Play', exact: true }).click()
        await expect(chart.getByRole('button', { name: 'Pause', exact: true })).toBeVisible()
        await chart.getByRole('button', { name: 'Pause', exact: true }).click()
      }
    }
    if (width === 412) {
      const targets = await page.locator('button:visible').evaluateAll(els => els.map(el => ({ h: el.getBoundingClientRect().height, w: el.getBoundingClientRect().width, label: el.getAttribute('aria-label') || el.textContent })))
      assert(targets.every(t => t.h >= 44 && t.w >= 44), JSON.stringify(targets.filter(t => t.h < 44 || t.w < 44)))
    }
    const contrast = await page.getByTestId('tradeinview-page').evaluate(root => {
      const rgba = value => { const n = value.match(/[\d.]+/g)?.map(Number) || [0, 0, 0]; const factor = value.startsWith('color(srgb') ? 255 : 1; return [n[0]*factor, n[1]*factor, n[2]*factor, n[3] ?? 1] }
      const blend = (f, b) => f.slice(0, 3).map((v, i) => v * f[3] + b[i] * (1 - f[3]))
      const luminance = rgb => rgb.map(v => { const c = v / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4 }).reduce((a, v, i) => a + v * [.2126, .7152, .0722][i], 0)
      const rows = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        const text = walker.currentNode, el = text.parentElement
        if (!text.textContent.trim() || !el || el.closest('[hidden],[aria-hidden="true"],button:disabled,option') || !el.getBoundingClientRect().height || getComputedStyle(el).display === 'none') continue
        let parent = el, stack = []
        while (parent) { stack.unshift(rgba(getComputedStyle(parent).backgroundColor)); parent = parent.parentElement }
        const bg = stack.reduce((b, f) => blend(f, b), [255,255,255])
        const style = getComputedStyle(el), colour = el instanceof SVGElement && style.fill !== 'none' ? style.fill : style.color
        const fg = blend(rgba(colour), bg), l = [luminance(bg),luminance(fg)].sort((a,b)=>b-a)
        rows.push({text:text.textContent.trim(),ratio:(l[0]+.05)/(l[1]+.05)})
      }
      return rows
    })
    assert(contrast.every(x => x.ratio >= 4.5), JSON.stringify(contrast.filter(x => x.ratio < 4.5)))
    await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
    const geometry = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }))
    assert(geometry.document <= geometry.width + 1, JSON.stringify(geometry))
    assert.deepEqual({ ...traffic, reads: [] }, { reads: [], mutations: [], unexpected: [], external: [], errors: [] })
    const name = `impl-${c.screen}-${c.state}-${width}.png`
    await page.screenshot({ path: path.join(out, name), fullPage: true, animations: 'disabled' })
    if (c.state === 'compare') { await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0) }
    receipts.push({ screen: c.screen, state: c.state, width, file: name, geometry, contrast, traffic })
    await context.close()
  }
} finally { await browser.close() }
for(const [file,digest] of Object.entries(sourceHashes)) assert.equal(sha(file),digest,`Source changed during fixture proof: ${file}`)
fs.writeFileSync(path.join(out, 'impl-tradeinview-receipts.json'), JSON.stringify({ fixture: true, scope: scopes, tested_source: testedSource, clock: f.clock, input, input_sha256: crypto.createHash('sha256').update(fs.readFileSync(input)).digest('hex'), cases: receipts }, null, 2) + '\n')
console.log(`TradeInView actual-component fixture:${receipts.length} cases passed; ${out}`)
