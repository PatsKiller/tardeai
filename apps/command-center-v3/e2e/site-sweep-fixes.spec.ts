/** Site sweep 2026-10-25 fixes (batch 32), phone proof at 412 and 390. Every request is intercepted:
 * no server, no live data, no writes. Two harnesses:
 *   1. the built app (dist/, `npm run build` first) served from a fake origin with every /api/ GET stubbed —
 *      the shared 44px tap-target rule, the header Deep option, the Journal tabs (no sideways scroll,
 *      readable freshness chips / calendar / replay times);
 *   2. esbuild bundles of the actual components — DeskPage source clocks (readable <time>, no
 *      "Updated update time …") and the analyst-report button (labelled, asks before any POST).
 *
 *   npm run build && npx playwright test e2e/site-sweep-fixes.spec.ts --project=chromium --workers=1
 */
import { expect, test, type Locator, type Page } from '@playwright/test'
import { build } from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(app, 'dist')
const tiv = JSON.parse(fs.readFileSync(path.join(app, 'e2e/fixtures/tradeinviewRedesign.fixture.json'), 'utf8'))
const ORIGIN = 'http://site-sweep-fixes.invalid'
const RAW_ISO = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/
const VIEWPORTS = [{ width: 412, height: 915 }, { width: 390, height: 844 }]

// Journeys with the captured long ledger receipt (the chip that pushed the page 5px sideways) and the
// captured raw sync stamps; a calendar week whose total is the captured "-$14,402.36" (19px spill).
const journeys = structuredClone(tiv.journeys.fresh)
journeys.freshness_chips = journeys.freshness_chips.map((c: any) => c.key === 'ledger_sync'
  ? { ...c, value: '2026-10-23T22:15:02+00:00 · ledger row write', at: '2026-10-23T22:15:02+00:00', source_label: 'run receipt' }
  : c.key === 'holdings_sync' ? { ...c, value: '2026-10-25T11:30:02.571711+00:00', at: '2026-10-25T11:30:02.571711+00:00' } : c)
const calendar = structuredClone(tiv.calendar.populated)
calendar.weeks = calendar.weeks.map((w: any, i: number) => i === 1 ? { ...w, realized_pl: -14402.36 } : i === 2 ? { ...w, realized_pl: -3061.5 } : w)
calendar.events = calendar.events.map((e: any) => ({ ...e, as_of: '2026-10-01T09:45:11.982480-04:00', source: 'benzinga_rss' }))
calendar.gaps = [...calendar.gaps, { source: 'market_ohlcv_bars', reason: 'latest stored bar observed 2026-10-20T00:00:00-04:00' }]
calendar.as_of = '2026-10-25T13:52:42.031827+00:00'
const exitRows = { ok: true, data: { value: { rows: [
  { symbol: 'SPCX', trade_date: '2026-10-20', trade_time: '15:59:21', shares: 10, price: 120, event_key: 'SPCX:2026-10-20' },
  { symbol: 'TSTA', trade_date: '2026-10-21', trade_time: '10:00:00', shares: 5, price: 40, event_key: 'TSTA:2026-10-21' },
] } } }

async function serveApp(page: Page) {
  const writes: string[] = []
  await page.routeWebSocket('**/*', ws => { writes.push('WS ' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (u.origin !== ORIGIN || req.method() !== 'GET') { writes.push(`${req.method()} ${u.origin}${u.pathname}`); return route.abort() }
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname === '/api/v3/data-broker/trade-journeys') return json(journeys)
    if (u.pathname === '/api/v3/data-broker/trade-calendar') return json(calendar)
    if (u.pathname === '/api/v2/trade-chart') return json(Object.values(tiv.replay as Record<string, any>).find(r => r.trade_id === u.searchParams.get('trade_id')) ?? { ok: false })
    if (u.pathname === '/api/v2/ui/prefs/get' && u.searchParams.get('key') === 'portfolio.reentry.exit-universe.v1') return json(exitRows)
    if (u.pathname.startsWith('/api/')) return json({ ok: false, error: 'fixture_unavailable' }, 503)
    const rel = u.pathname.replace(/^\/v3\/?/, ''), file = path.join(dist, rel)
    if (rel && file.startsWith(dist + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file })
    return route.fulfill({ path: path.join(dist, 'index.html') })
  })
  return writes
}

async function box(locator: Locator) {
  await locator.scrollIntoViewIfNeeded()
  const b = await locator.boundingBox()
  expect(b, 'control is laid out').not.toBeNull()
  return b!
}
async function expectTapTarget(locator: Locator, what: string) {
  const b = await box(locator)
  expect(b.height, `${what} height`).toBeGreaterThanOrEqual(44)
  expect(b.width, `${what} width`).toBeGreaterThanOrEqual(44)
}
/** Every visible button / select / non-checkbox input in the page body is at least 44x44. */
async function expectAllControlsTappable(page: Page, where: string) {
  const small = await page.evaluate(() => [...document.querySelectorAll('main.app-main button, main.app-main select, main.app-main [role="button"], main.app-main input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="hidden"])')]
    .map(el => ({ el, r: el.getBoundingClientRect() }))
    .filter(({ el, r }) => r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden')
    .filter(({ r }) => r.width < 44 || r.height < 44)
    .map(({ el, r }) => `${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)}`))
  expect(small, `controls under 44px on ${where}`).toEqual([])
}
async function mainOverflow(page: Page) {
  return page.evaluate(() => { const m = document.querySelector('main.app-main') as HTMLElement; return { main: m.scrollWidth - m.clientWidth, doc: document.documentElement.scrollWidth - innerWidth } })
}
async function rawIsoTexts(locator: Locator) {
  return locator.evaluate((root, src) => {
    const re = new RegExp(src), out: string[] = []
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let n: Node | null
    while ((n = walker.nextNode())) if (re.test(n.textContent || '') && (n.parentElement?.getClientRects().length ?? 0) > 0) out.push((n.textContent || '').trim().slice(0, 90))
    return out
  }, RAW_ISO.source)
}

test.describe('phone: built app, every API stubbed', () => {
  test.use({ hasTouch: true, isMobile: true })
  test.beforeAll(() => { expect(fs.existsSync(path.join(dist, 'index.html')), 'run `npm run build` first (dist/ is served)').toBe(true) })
  for (const viewport of VIEWPORTS) {
    test(`44px tap targets on Portfolio, Watch, CIO questions + header Deep at ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const writes = await serveApp(page)
      await page.goto(ORIGIN + '/v3/portfolio')
      await expectTapTarget(page.getByRole('button', { name: /Sync SnapTrade/ }), 'Sync SnapTrade')
      await expectTapTarget(page.getByRole('button', { name: /Sync Schwab/ }), 'Sync Schwab')
      await expectAllControlsTappable(page, '/v3/portfolio')
      // Deep: a 13px checkbox became a label-wrapped 44px hit area; tapping the label toggles it.
      const deep = page.getByTestId('ask-cio-deep'), deepLabel = page.getByTestId('ask-cio-deep-label')
      await expectTapTarget(deepLabel, 'Deep option label')
      const deepBox = await box(deep); expect(deepBox.width).toBeGreaterThanOrEqual(20)
      await expect(deep).not.toBeChecked(); await deepLabel.tap(); await expect(deep).toBeChecked()

      await page.goto(ORIGIN + '/v3/watch')
      await expect(page.getByTestId('watch-tab-my-watchlist')).toBeVisible()
      await expectTapTarget(page.getByTestId('watch-tab-my-watchlist'), 'Watch tab')
      // Re-Entry context bridge: Show context / Open re-entry.
      const show = page.getByRole('button', { name: /show context/i })
      await expectTapTarget(show, 'Show context')
      await expectTapTarget(page.getByRole('button', { name: /open re-entry/i }), 'Open re-entry')
      await show.tap()
      await expectAllControlsTappable(page, '/v3/watch (context open)')

      await page.goto(ORIGIN + '/v3/cio/questions')
      for (const g of ['security', 'sector', 'theme', 'date', 'none']) await expectTapTarget(page.getByTestId(`mq-group-${g}`), `question group ${g}`)
      await expectAllControlsTappable(page, '/v3/cio/questions')
      expect(writes).toEqual([])
    })

    test(`/v3/journal: no sideways scroll, readable times on every tab at ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const writes = await serveApp(page)
      const main = page.locator('main.app-main')
      for (const tab of ['journeys', 'calendar', 'replay', 'history', 'journal']) {
        const extra = tab === 'calendar' ? '&month=2026-11' : tab === 'replay' ? `&trade=${encodeURIComponent(tiv.replay.bars.trade_id)}` : ''
        await page.goto(`${ORIGIN}/v3/journal?tab=${tab}${extra}`)
        await expect(page.getByTestId('tradeinview-page')).toBeVisible()
        if (tab === 'journeys') {
          const ledger = page.getByTestId('tj-chip-ledger_sync')
          await expect(ledger).toContainText('Ledger synced Oct 23 18:15 ET · ledger row write')
          await expect(ledger).toHaveAttribute('title', /2026-10-23T22:15:02\+00:00/)   // raw stamp kept in the tooltip
          await expect(page.getByTestId('tj-chip-holdings_sync')).toContainText('Oct 25 07:30 ET')
        }
        if (tab === 'calendar') {
          await expect(page.getByTestId('calendar-week-total').filter({ hasText: '-$14,402.36' })).toBeVisible()
          await expect(page.getByTestId('calendar-event').first()).toContainText('benzinga_rss · Oct 1 09:45 ET')
          await expect(page.getByTestId('trade-calendar')).toContainText('latest stored bar observed Oct 20 00:00 ET')
        }
        if (tab === 'replay') await expect(page.getByTestId('tradeinview-page')).toContainText(/observed Nov 3 \(date only\)|observed Nov 2/)
        await page.waitForTimeout(300)
        expect(await mainOverflow(page), `sideways scroll on ${tab}`).toEqual({ main: 0, doc: 0 })
        expect(await rawIsoTexts(main), `raw ISO text on ${tab}`).toEqual([])
      }
      expect(writes).toEqual([])
    })
  }
})

// ── Actual components bundled with esbuild ───────────────────────────────────────────────────────────
let js = '', css = ''
const NOW = '2026-10-25T14:00:00Z'
test.describe('phone: DeskPage clocks + analyst report confirm', () => {
  test.use({ hasTouch: true, isMobile: true })
  test.beforeAll(async () => {
    const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';
      import DeskPage from'./src/components/DeskPage';import HoldingReportLinks from'./src/components/HoldingReportLinks';import'./src/styles/tokens.css';import'./src/index.css';
      const sources=[
        {id:'cio',label:'CIO record',asOf:'2026-10-25T14:00:30.123456+00:00',laneIds:['cio']},
        {id:'holdings',label:'Holdings',asOf:'2026-10-23T09:45:02-04:00',laneIds:['holdings']},
        {id:'stops',label:'Stops',asOf:'2026-04-19T00:00:00+00:00'},
        {id:'future',label:'Unverified clock',asOf:'2026-10-26T00:00:00Z'}];
      createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><main className="app-main">
        <section aria-label="Report buttons"><HoldingReportLinks symbol="tsla" compact /> <HoldingReportLinks symbol="nvda" /></section>
        <DeskPage title="Home" purpose="Fixture" sources={sources}>{() => null}</DeskPage></main></BrowserRouter>);`,
      resolveDir: app, loader: 'tsx', sourcefile: 'site-sweep-fixes.tsx' },
      bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
    js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script'); css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
  })
  async function serveBundle(page: Page) {
    const posts: string[] = [], other: string[] = []
    await page.clock.install({ time: new Date(NOW) })
    await page.route('**/*', async route => {
      const req = route.request(), u = new URL(req.url())
      if (u.origin !== ORIGIN) { other.push(req.method() + ' ' + req.url()); return route.abort() }
      if (req.method() !== 'GET') { posts.push(`${req.method()} ${u.pathname}`); return route.abort() }   // recorded, never reaches a server
      if (u.pathname.startsWith('/v3')) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
      if (u.pathname === '/api/v2/desk-sources') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { observed_at: NOW, writers: [
        { lane_id: 'cio', state: 'ACTIVE', last_success_at: '2026-10-25T13:53:48.866966+00:00', evidence_as_of: NOW, reason: null },
        { lane_id: 'holdings', state: 'ACTIVE', last_success_at: '2026-10-25T11:30:01+00:00', evidence_as_of: NOW, reason: null }] } }) })
      other.push('unlisted ' + u.pathname); return route.abort()
    })
    return { posts, other }
  }
  for (const viewport of VIEWPORTS) {
    test(`source clocks read as ET, never raw ISO or "Updated update time" at ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const { posts, other } = await serveBundle(page)
      await page.goto(ORIGIN + '/v3/home')
      const clocks = page.getByRole('region', { name: 'Source clocks' })
      await expect(clocks.getByText('Writer ACTIVE').first()).toBeVisible()
      expect(await rawIsoTexts(clocks)).toEqual([])
      await expect(clocks).not.toContainText(/Updated update/i)
      const cio = clocks.locator('article', { hasText: 'CIO record' })
      // 30s after the minute tick is clock skew, not a future time.
      await expect(cio.getByTestId('desk-source-age')).toHaveText('Updated just now')
      await expect(cio.getByTestId('desk-source-as-of')).toHaveText('Oct 25 10:00 ET')
      await expect(cio.getByTestId('desk-source-as-of')).toHaveAttribute('datetime', '2026-10-25T14:00:30.123456+00:00')
      await expect(cio.getByTestId('desk-source-as-of')).toHaveAttribute('title', '2026-10-25T14:00:30.123456+00:00')
      await expect(cio).toContainText('At Oct 25 09:53 ET')
      await expect(clocks.locator('article', { hasText: 'Holdings' })).toContainText('As of Oct 23 09:45 ET')
      await expect(clocks.locator('article', { hasText: 'Stops' })).toContainText('As of Apr 19 (date only)')
      const future = clocks.locator('article', { hasText: 'Unverified clock' })
      await expect(future.getByTestId('desk-source-age')).toHaveText('Update time needs review')
      await expect(future).toContainText('The source update time is in the future.')
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBe(0)
      expect(posts).toEqual([]); expect(other).toEqual([])
    })

    test(`📄 is labelled, 44px, and asks before generating at ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const { posts } = await serveBundle(page)
      await page.goto(ORIGIN + '/v3/home')
      const compact = page.getByTestId('report-generate').first()
      await expect(compact).toHaveAttribute('aria-label', /Analyst report for TSLA/)
      await expect(compact).toContainText('Analyst report')          // visible text on a phone, not emoji only
      await expect(compact.locator('.hrl-generate-label')).toBeVisible()
      await expectTapTarget(compact, '📄 Analyst report')
      await compact.tap()
      const sheet = page.getByRole('alertdialog', { name: 'Generate analyst report for TSLA?' })
      await expect(sheet).toBeVisible()
      expect(posts, 'nothing sent before confirming').toEqual([])
      const sheetBox = await sheet.boundingBox()
      expect(sheetBox!.width).toBe(viewport.width)                   // bottom sheet, full width
      expect(Math.round(sheetBox!.y + sheetBox!.height)).toBe(viewport.height)
      await expectTapTarget(page.getByTestId('report-generate-cancel'), 'Cancel')
      await expectTapTarget(page.getByTestId('report-generate-confirm-go'), 'Generate report')
      await page.getByTestId('report-generate-cancel').tap()
      await expect(sheet).toBeHidden()
      await page.waitForTimeout(300)
      expect(posts, 'Cancel sends nothing').toEqual([])
      // Backdrop tap also cancels.
      await compact.tap(); await expect(sheet).toBeVisible()
      await page.mouse.click(viewport.width / 2, 20); await expect(sheet).toBeHidden()
      expect(posts).toEqual([])
      // Confirm sends exactly one POST (aborted here: it never reaches a server).
      await compact.tap(); await page.getByTestId('report-generate-confirm-go').tap()
      await expect.poll(() => posts).toEqual(['POST /api/v2/reports/analyst/generate'])
    })
  }
})
