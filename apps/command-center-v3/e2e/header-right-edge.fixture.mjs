// Actual MetricStrip + actual bundled CSS, synthetic APIs, no server or credentials.
// node e2e/header-right-edge.fixture.mjs <output-directory> [before]
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })
const before = process.argv[3] === 'before'
const baseSha = '68994d0c20b49c913d9fa7f7f2f3ef778d370fe0'
const clock = '2026-10-23T15:00:00Z'
const fixtures = {
  '/api/v2/overview': {
    portfolio_value: 1266531, today_change: 1998, today_pct: 0.16, pending_approvals: 125,
    as_of: clock, data_as_of: clock, cached_at: clock,
    today_pnl: { session_date: '2026-10-23', funded_account_count: 2, represented_account_count: 2 },
    portfolio_aggregate: { portfolio_scope: 'ALL_ACCOUNTS', position_observation_newest: clock,
      position_observation_oldest: clock, position_observation_oldest_age_hours: 0,
      valuation_time: clock, quote_observation_time: clock, included_account_count: 2 },
    journal: { win_rate: 49.3, trade_count: 223, total_pnl: 39970, realized_pnl: 154529,
      realized_count: 229, basis: 'schwab', account_scope: 'all_time', last_close_date: '2026-10-23' },
    pricing: { last_repriced: clock, reprice_source: 'finviz' },
  },
  '/api/v2/paper-trade-readiness': { closed_usable: 152, win_rate: 0.49 },
  '/api/v2/risk-regime/latest': { regime_label: 'risk on trend', confidence: 0.33,
    trend_state: 'bearish', breadth_state: 'broad', volatility_state: 'high_vol' },
  '/api/v2/trade-ai/summary': { run_date: '2026-10-23', run_label: '0900', cached_at: clock,
    run_finished_at: clock, stale: false, vix: 14.8, vix_source: 'fixture-run-summary', vix_observation_time: clock,
    setup_run_summary: { run_id: '2026-10-23::0900', run_label: '0900', run_date: '2026-10-23',
      run_timestamp: clock, scanned_count: 17, classified_count: 8, go_count: 2, wait_count: 0,
      nogo_count: 6, review_count: 9, excluded_count: 0, error_count: 0, unclassified_count: 0,
      count_integrity: 'RECONCILED', freshness_status: 'RUN_UNDERFILLED' } },
  '/api/v2/live-trading-gate': { operator_live_via_2fa_allowed: true },
  '/api/v2/health': { findings: [...Array.from({ length: 12 }, () => ({ severity: 'critical' })),
    ...Array.from({ length: 113 }, () => ({ severity: 'warning' }))] },
  '/api/v2/design-features': { header: {} },
}
const bundled = await build({
  stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
    import {MemoryRouter} from 'react-router-dom'; import MetricStrip from './src/components/MetricStrip';
    import './src/index.css'; createRoot(document.getElementById('root')).render(
      <MemoryRouter><div className="app-shell cc-terminal-ui" style={{display:'flex',flexDirection:'column',
        height:'100vh',background:'var(--bg0)',color:'var(--text0)'}}>
        <div style={{height:24,flexShrink:0,fontSize:12}}>SYNTHETIC HEADER FIXTURE — no live data</div>
        <MetricStrip onDrill={() => {}} /></div></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'header-fixture.tsx' },
  bundle: true, write: false, outfile: 'fixture.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: before ? [{ name: 'exact-base-header', setup(builder) {
    builder.onLoad({ filter: /src\/(?:components\/MetricStrip\.tsx|index\.css)$/ }, args => ({
      contents: execFileSync('git', ['show', `${baseSha}:apps/command-center-v3/${path.relative(app, args.path)}`],
        { cwd: app, encoding: 'utf8' }),
      loader: args.path.endsWith('.css') ? 'css' : 'tsx', resolveDir: path.dirname(args.path),
    }))
  } }] : [],
})
const js = bundled.outputFiles.find(file => file.path.endsWith('.js')).text
const css = bundled.outputFiles.find(file => file.path.endsWith('.css')).text
const html = `<html><head><style>${css}</style></head><body><main id="root"></main>
  <script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`
const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  const cases = [...[1280, 1440, 1920, 2560, 412, 821].map(width => ({ width, stress: false })),
    ...[821, 1280].map(width => ({ width, stress: true })),
    ...['AUTO BLOCKED', 'AUTO LIVE'].map(badge => ({ width: 821, stress: true, badge }))]
  for (const { width, stress, badge = '2FA LIVE' } of cases) {
    const approvals = stress ? 125 : 3
    const critical = stress ? 12 : 4
    const warnings = stress ? 113 : 20
    const health = critical + warnings
    const context = await browser.newContext({ viewport: { width, height: 450 }, serviceWorkers: 'block' })
    const page = await context.newPage()
    await page.clock.setFixedTime(new Date(clock))
    const traffic = { api: [], external: [], mutations: [], unexpected: [], errors: [] }
    page.on('pageerror', error => traffic.errors.push(error.message))
    await page.route('**/*', async route => {
      const req = route.request(); const url = new URL(req.url())
      if (url.origin !== 'http://header-fixture.test') {
        traffic.external.push(req.url()); return route.abort()
      }
      if (req.method() !== 'GET') {
        traffic.mutations.push(req.method() + ' ' + url.pathname); return route.abort()
      }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      if (Object.hasOwn(fixtures, url.pathname)) {
        traffic.api.push(url.pathname)
        const payload = url.pathname === '/api/v2/overview' ? { ...fixtures[url.pathname], pending_approvals: approvals }
          : url.pathname === '/api/v2/live-trading-gate' ? {
            operator_live_via_2fa_allowed: badge === '2FA LIVE', status: badge === 'AUTO LIVE' ? 'AUTHORIZED' : 'BLOCKED' }
          : url.pathname === '/api/v2/health' ? { findings: [
            ...Array.from({ length: critical }, () => ({ severity: 'critical' })),
            ...Array.from({ length: warnings }, () => ({ severity: 'warning' }))] } : fixtures[url.pathname]
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) })
      }
      traffic.unexpected.push(url.pathname)
      return route.abort()
    })
    await page.goto('http://header-fixture.test/')
    await page.waitForFunction(({ approvals, health, critical, badge }) => {
      const text = document.querySelector('.metric-strip-row')?.textContent || ''
      return text.includes(`${approvals} APPROVALS`) && text.includes(`${health} HEALTH (${critical} crit)`) && text.includes(badge)
    }, { approvals, health, critical, badge })
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    const measure = () => page.evaluate(() => {
      const row = document.querySelector('.metric-strip-row')
      const compact = document.querySelector('.ms-compact')
      const rect = el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom } }
      const actions = document.querySelector('.ms-actions')
      const metrics = document.querySelector('.ms-metrics')
      const controls = actions ? [...actions.children] : [...row.children].slice(-4)
      return { width: innerWidth, pageScrollWidth: document.documentElement.scrollWidth,
        row: rect(row), rowCssHeight: getComputedStyle(row).height,
        compact: rect(compact), actions: actions ? rect(actions) : null,
        controls: controls.map(el => {
          const range = document.createRange(); range.selectNodeContents(el)
          const text = range.getBoundingClientRect()
          return { text: el.textContent.trim(), ...rect(el), textBox: { x: text.x, right: text.right, y: text.y, bottom: text.bottom },
            clipped: el.scrollWidth > el.clientWidth + 1 }
        }),
        tileLines: [...document.querySelectorAll('.ms-metrics .ms-label, .ms-metrics .ms-value, .ms-metrics .ms-meta')]
          .map(el => ({ text: el.textContent.slice(0, 24), ...rect(el) })),
        metrics: metrics ? { ...rect(metrics), scrollWidth: metrics.scrollWidth,
          clientWidth: metrics.clientWidth, scrollLeft: metrics.scrollLeft,
          overflow: getComputedStyle(metrics).overflowX,
          scrollbar: getComputedStyle(metrics, '::-webkit-scrollbar').height } : null,
        cueVisible: !!document.querySelector('.ms-scroll-cue') &&
          getComputedStyle(document.querySelector('.ms-scroll-cue')).display !== 'none',
      }
    })
    const initial = await measure()
    const receipt = { fixture: true, clock, before, baseSha, width, stress, badge, initial, traffic }
    results.push(receipt)
    if (!before && width > 820) {
      assert.equal(initial.rowCssHeight, '62px', 'declared content row remains62px')
      assert.equal(initial.row.height, 62, 'actual desktop row including padding remains62px')
      assert(initial.actions && initial.metrics, 'separate action and metric groups')
      assert(initial.controls.length === 4 && initial.controls.every(c => c.width > 0 &&
        c.x >= initial.actions.x - 1 && c.right <= Math.min(width, initial.row.right, initial.actions.right) &&
        c.y >= initial.row.y && c.bottom <= initial.row.bottom && !c.clipped &&
        c.textBox.x >= c.x && c.textBox.right <= c.right + 1 &&
        c.textBox.y >= c.y && c.textBox.bottom <= c.bottom + 1), 'all four controls fully visible: ' + JSON.stringify(initial))
      for (let i = 1; i < initial.controls.length; i++) {
        assert(initial.controls[i].x >= initial.controls[i - 1].right, 'controls never overlap')
      }
      assert(initial.tileLines.every(line => line.y >= initial.row.y && line.bottom <= initial.row.bottom),
        'metric label/value/meta vertical bounds remain inside62px row')
      assert(initial.metrics.right <= initial.actions.x + 1, 'metrics cannot paint behind fixed controls')
      assert.equal(initial.pageScrollWidth, width, 'no page sideways overflow')
      if ([821, 1280].includes(width)) assert(initial.metrics.scrollWidth > initial.metrics.clientWidth + 1,
        'narrow-desktop overflow precondition must hold for scroll/cue proof')
      if (initial.metrics.scrollWidth > initial.metrics.clientWidth + 1) {
        assert(initial.cueVisible, 'overflow has visible directional cue')
        assert.equal(initial.metrics.overflow, 'auto')
        await page.locator('.ms-metrics').evaluate(el => { el.scrollLeft = el.scrollWidth })
        const scrolled = await measure()
        receipt.scrolled = scrolled
        assert(scrolled.metrics.scrollLeft > 0, 'all metrics reachable by horizontal scroll')
        assert.deepEqual(scrolled.actions, initial.actions, 'right controls stay fixed while metrics scroll')
        assert.deepEqual(scrolled.controls, initial.controls, 'right controls never enter scroll viewport')
        await page.locator('.ms-metrics').evaluate(el => { el.scrollLeft = 0 })
        await page.locator('.ms-metrics').focus()
        await page.keyboard.press('ArrowRight')
        await page.waitForFunction(() => document.querySelector('.ms-metrics').scrollLeft > 0)
        receipt.keyboard = await measure()
        assert.deepEqual(receipt.keyboard.actions, initial.actions, 'controls fixed after keyboard scroll')
        await page.locator('.ms-metrics').evaluate(el => { el.scrollLeft = 0 })
        await page.locator('.ms-metrics').hover()
        await page.mouse.wheel(300, 0)
        await page.waitForFunction(() => document.querySelector('.ms-metrics').scrollLeft > 0)
        receipt.mouse = await measure()
        assert.deepEqual(receipt.mouse.actions, initial.actions, 'controls fixed after mouse scroll')
        await page.waitForTimeout(250) // let native wheel momentum finish before the evidence reset
        await page.locator('.ms-metrics').evaluate(el => { el.scrollLeft = 0 })
        await page.locator('.ms-metrics').evaluate(el => el.blur())
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      }
    }
    if (!before && width <= 820) {
      assert(initial.compact.height >= 44 && initial.row.height === 0, 'mobile stays collapsed and compact')
      assert.equal(initial.pageScrollWidth, width)
    }
    assert.deepEqual(traffic.external, []); assert.deepEqual(traffic.mutations, [])
    assert.deepEqual(traffic.unexpected, []); assert.deepEqual(traffic.errors, [])
    assert.equal(new Set(traffic.api).size, 7, 'every header API fulfilled synthetically')
    const suffix = badge !== '2FA LIVE' ? '-' + badge.toLowerCase().replaceAll(' ', '-') : stress ? '-stress' : ''
    await page.screenshot({ path: path.join(out, `header-${width}${suffix}.png`), animations: 'disabled' })
    if (width === 412) {
      await page.locator('.ms-compact__toggle').click()
      receipt.expanded = await measure()
      assert(receipt.expanded.row.height > 0, 'mobile expansion remains available')
      if (!before) assert.equal(receipt.expanded.pageScrollWidth, width)
      await page.screenshot({ path: path.join(out, 'header-412-expanded.png'), animations: 'disabled' })
    }
    await context.close()
  }
} finally {
  await browser.close()
  fs.writeFileSync(path.join(out, 'geometry.json'), JSON.stringify(results, null, 2) + '\n')
}
console.log(`PASS ${before ? 'baseline capture' : 'fixed geometry'}: ${results.length} cases, zero real HTTP/server requests`)
