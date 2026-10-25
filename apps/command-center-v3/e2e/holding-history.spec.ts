/** Actual HoldingHistory + real URL hooks; every request fulfilled to an isolated origin.
 * Financial fixture fields come from the backend producer COPY fixture, never the approved mockup.
 */
import { expect, test, type Page } from '@playwright/test'
import { build } from 'esbuild'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
const capture = JSON.parse(readFileSync(new URL('./fixtures/holdingHistory.fixture.json', import.meta.url), 'utf8'))
const origin = 'http://history-fixture.invalid'
let js = '', css = ''
test.beforeAll(async () => {
  const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter,useSearchParams}from'react-router-dom';
    import HoldingHistory from'./src/components/tradeinview/HoldingHistory';import'./src/index.css';
    function Harness(){const[q,setQ]=useSearchParams();return q.has('fixture_replay')?<section data-testid="fixture-replay"><h2>Replay callback received</h2><p>{q.get('fixture_replay')}</p></section>:<HoldingHistory onReplay={id=>{window.__replayed=id;if(q.has('fixture_mobile_flow')){const n=new URLSearchParams(q);n.set('fixture_replay',id);setQ(n)}}}/>}
    createRoot(document.getElementById('root')).render(<BrowserRouter><main className="cc-terminal-ui" style={{padding:20,minHeight:'100vh',background:'var(--bg-0)',color:'var(--text-0)'}}>
    <h1 style={{fontSize:24,fontWeight:600}}>TradeInView</h1><nav style={{padding:'8px 0 16px'}}>Journeys · Calendar · Replay · <b>Holding history</b> · Journal (classic tabs)</nav>
    <Harness/></main></BrowserRouter>);`, resolveDir: process.cwd(), loader: 'tsx', sourcefile: 'history-fixture.tsx' },
    bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } })
  js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text; css = b.outputFiles.find(f => f.path.endsWith('.css'))!.text
})
const nilStats = { times_held: null, known_holding_stretches: null, round_trip_count: null, win_rate_pct: null, realized_pl: null, known_realized_pl: null, avg_hold_days: null, median_hold_days: null, best_trip_pct: null, worst_trip_pct: null, coverage: { status: 'MISSING', reasons: ['Fixture ledger coverage unavailable'] } }
function missingDetail(symbol = 'GAP') {
  return { symbol, company_name: null, company_missing_reason: 'Company memory missing from test capture', stats: structuredClone(nilStats), account_segments: [],
    trips: [{ trade_id: 'fixture-trade-id', symbol, account_id: 'RAW_ACCOUNT_MUST_NEVER_RENDER', account_label: 'Named fixture account', entry_at: null, exit_at: null, entry_price: null, exit_price: null, shares: null, realized_pl: null, return_pct: null, hold_days: null, hold_days_basis: null, basis_unknown: true, basis_reason: 'Fixture missing purchase basis', source: 'fixture ledger', provenance: [{ source: 'fixture ledger', table: 'synthetic_trips', account_id: 'RAW_ACCOUNT_MUST_NEVER_RENDER' }] }], gaps: [] }
}
function missingName(symbol = 'GAP') { return { symbol, company_name: null, account_count: null, round_trip_count: null, realized_pl: null, known_realized_pl: null, held_now: null, basis_unknown: true, accounts: [], gaps: [{ reason: 'Fixture count coverage unavailable' }] } }
async function fixture(page: Page, response: (u: URL) => { status?: number; body: any }) {
  const forbidden: string[] = [], requests: string[] = []
  await page.clock.install({ time: new Date('2026-10-24T21:00:00Z') })
  await page.routeWebSocket('**/*', ws => { forbidden.push('WS:' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (req.method() !== 'GET' || u.origin !== origin) { forbidden.push(req.method() + ':' + req.url()); return route.abort() }
    if (u.pathname === '/fixture.js') return route.fulfill({ contentType: 'text/javascript', body: js })
    if (u.pathname === '/fixture.css') return route.fulfill({ contentType: 'text/css', body: css })
    if (u.pathname === '/api/v3/data-broker/holding-history') { requests.push(u.search); const r = response(u); return route.fulfill({ status: r.status || 200, contentType: 'application/json', body: JSON.stringify(r.body) }) }
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<html data-theme="dark"><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>' })
    forbidden.push('unlisted:' + req.url()); return route.abort()
  })
  return { forbidden, requests }
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  expect(await page.locator('.holding-history, .hh-main, .hh-panel, .hh-stat, .hh-trip').evaluateAll(es => es.every(e => e.scrollWidth <= e.clientWidth + 1))).toBe(true)
}
async function shot(page: Page, state: string, width: number) {
  if (process.env.HISTORY_SHOTS_DIR) { mkdirSync(process.env.HISTORY_SHOTS_DIR, { recursive: true }); await page.screenshot({ path: resolve(process.env.HISTORY_SHOTS_DIR, `impl-history-${state}-${width}.png`), fullPage: width > 820 }) }
}
async function inViewport(locator: ReturnType<Page['locator']>, page: Page, minimumHeight = 0) {
  const box = await locator.boundingBox(); expect(box).not.toBeNull()
  const viewport = page.viewportSize()!
  expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1)
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1)
  expect(box!.height).toBeGreaterThanOrEqual(minimumHeight)
}
test.describe('phone list and fullscreen detail interaction', () => {
  test.use({ hasTouch: true })
  for (const viewport of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
    test(`tap sort name Back browser Back Replay ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const rows = [missingName('BETA'), missingName('ALPHA')]
      const state = await fixture(page, u => ({ body: { ...capture, symbols: u.searchParams.get('sort') === 'realized' ? [...rows].reverse() : rows, detail: missingDetail(u.searchParams.get('symbol') || 'BETA') } }))
      await page.goto(origin + '/?tab=history&preserved=yes&fixture_mobile_flow=1')
      await expect(page.getByTestId('history-detail-sheet')).toHaveCount(0)
      const sort = page.getByRole('button', { name: 'Most realized', exact: true })
      await inViewport(sort, page, 44); await sort.tap()
      await expect(page).toHaveURL(/history_sort=realized/)
      const alpha = page.getByTestId('history-name').filter({ hasText: 'ALPHA' })
      await expect(page.getByTestId('history-name').first()).toContainText('ALPHA')
      await alpha.scrollIntoViewIfNeeded(); await inViewport(alpha, page, 44)
      await noOverflow(page); await shot(page, 'phone-names', viewport.width)
      await alpha.tap()
      await expect(page).toHaveURL(/symbol=ALPHA/); await expect(page).toHaveURL(/preserved=yes/)
      const sheet = page.getByTestId('history-detail-sheet'), back = page.getByTestId('history-back')
      await expect(sheet).toBeVisible(); await expect(back).toBeFocused()
      const rect = await sheet.boundingBox(); expect(rect).toEqual({ x: 0, y: 0, width: viewport.width, height: viewport.height })
      await inViewport(back, page, 44)
      expect(await page.locator('section[aria-label="Holding history"]').evaluate(el => (el as HTMLElement).inert)).toBe(true)
      await expect(sheet).toContainText('Named fixture account'); await expect(sheet).not.toContainText('RAW_ACCOUNT_MUST_NEVER_RENDER')
      await noOverflow(page); await shot(page, 'phone-detail', viewport.width)
      // Keyboard users cannot tab behind the same phone sheet.
      await back.press('Shift+Tab'); expect(await sheet.evaluate(el => el.contains(document.activeElement))).toBe(true)
      await back.tap()
      await expect(page.getByTestId('history-detail-sheet')).toHaveCount(0)
      expect(new URL(page.url()).searchParams.has('symbol')).toBe(false)
      await expect(alpha).toBeFocused(); await inViewport(alpha, page, 44)
      await alpha.tap(); await expect(sheet).toBeVisible(); await page.goBack()
      await expect(sheet).toHaveCount(0); await expect(alpha).toBeFocused()
      await alpha.tap(); await expect(sheet).toBeVisible()
      const provenance = sheet.getByText('Provenance', { exact: true })
      await provenance.scrollIntoViewIfNeeded(); await inViewport(provenance, page, 44); await provenance.tap()
      await expect(sheet).toContainText('synthetic_trips')
      const replay = sheet.getByTestId('history-replay')
      await replay.scrollIntoViewIfNeeded(); await inViewport(replay, page, 44)
      const actionBox = await replay.boundingBox(), card = await page.getByTestId('history-trip').boundingBox()
      expect(actionBox!.width).toBeGreaterThan(card!.width * .8)
      await replay.tap()
      await expect(page.getByTestId('fixture-replay')).toContainText('fixture-trade-id')
      await inViewport(page.getByTestId('fixture-replay'), page)
      // This proves C's callback only. Actual B shell/Replay integration is a separate package proof.
      expect(await page.evaluate(() => (window as any).__replayed)).toBe('fixture-trade-id')
      await noOverflow(page); expect(state.forbidden).toEqual([])
    })
    test(`deep linked phone Back retains other URL state ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const state = await fixture(page, () => ({ body: { ...capture, symbols: [missingName()], detail: missingDetail() } }))
      await page.goto(origin + '/?tab=history&symbol=GAP&history_sort=held_now&preserved=yes')
      const back = page.getByTestId('history-back'); await expect(back).toBeFocused(); await inViewport(back, page, 44)
      await back.tap()
      await expect(page.getByTestId('history-detail-sheet')).toHaveCount(0)
      const q = new URL(page.url()).searchParams
      expect(q.get('tab')).toBe('history'); expect(q.get('history_sort')).toBe('held_now'); expect(q.get('preserved')).toBe('yes'); expect(q.has('symbol')).toBe(false)
      await expect(page.getByTestId('history-name')).toBeFocused(); await noOverflow(page)
      expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
      expect(state.forbidden).toEqual([])
    })
  }
})
for (const width of [1440, 412]) {
  test(`missing coverage never becomes zero ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const state = await fixture(page, () => ({ body: { ...capture, symbols: [missingName()], detail: missingDetail() } }))
    await page.goto(origin + '/?tab=history&symbol=GAP')
    await expect(page.getByTestId('history-stat-realized_pl')).toContainText('—')
    await expect(page.getByTestId('history-stat-realized_pl')).toContainText('Fixture ledger coverage unavailable')
    await expect(page.getByTestId('history-trip')).toContainText('Basis unknown')
    await expect(page.getByTestId('history-trip')).toContainText('Fixture missing purchase basis')
    await expect(page.locator('body')).not.toContainText('RAW_ACCOUNT_MUST_NEVER_RENDER')
    await page.getByText('Provenance', { exact: true }).click()
    await expect(page.getByTestId('history-trip')).toContainText('synthetic_trips')
    await page.getByRole('button', { name: 'Replay GAP trade' }).click()
    expect(await page.evaluate(() => (window as any).__replayed)).toBe('fixture-trade-id')
    await noOverflow(page); expect(state.forbidden).toEqual([]); await shot(page, 'basis-unknown', width)
  })
  test(`empty source and schema refusal ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    let bad = false
    const state = await fixture(page, () => ({ body: bad ? { ...capture, schema: 'WrongSchema' } : capture }))
    await page.goto(origin + '/?tab=history')
    await expect(page.getByTestId('history-gaps')).toContainText('Missing capture')
    await expect(page.locator('.hh-name')).toHaveCount(0)
    await noOverflow(page); await shot(page, 'empty', width)
    bad = true; await page.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('does not match')
    expect(state.forbidden).toEqual([]); await shot(page, 'schema-error', width)
  })
}
test('server order URL selection and stale transport keep original clocks', async ({ page }) => {
  const rows = [missingName('BETA'), missingName('ALPHA')]
  let denied = false
  const state = await fixture(page, u => ({ status: denied ? 403 : 200, body: denied ? { error: 'forbidden' } : { ...capture, symbols: u.searchParams.get('sort') === 'realized' ? [...rows].reverse() : rows, detail: missingDetail(u.searchParams.get('symbol') || 'BETA') } }))
  await page.goto(origin + '/?tab=history&symbol=BETA&preserved=yes')
  await expect(page.getByTestId('history-name').first()).toContainText('BETA')
  await page.getByRole('button', { name: 'Most realized', exact: true }).click()
  await expect(page).toHaveURL(/history_sort=realized/)
  await expect(page.getByTestId('history-name').first()).toContainText('ALPHA')
  await page.getByTestId('history-name').first().click()
  await expect(page).toHaveURL(/symbol=ALPHA/)
  await expect(page).toHaveURL(/preserved=yes/)
  await expect(page.locator('.hh-detail-heading')).toContainText('ALPHA')
  expect(state.requests.every(s => new URLSearchParams(s).get('range') === 'all')).toBe(true)
  const original = await page.locator('.hh-request-status').innerText()
  denied = true; await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByRole('status').first()).toContainText('previously collected')
  await expect(page.locator('.hh-detail-heading')).toContainText('ALPHA')
  expect(await page.locator('.hh-request-status').innerText()).toBe(original)
  expect(state.forbidden).toEqual([])
})


// Private source-copy evidence stays outside git; no mockup financial data is imported.
// This optional protocol proof is also used by coordinator B for real History -> Replay wiring.
const copyPath = process.env.HISTORY_COPY_FIXTURE
if (copyPath) {
  const sourceCopy = JSON.parse(readFileSync(copyPath, 'utf8'))
  test.describe('actual COPY phone selection', () => {
    test.use({ hasTouch: true })
    for (const viewport of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) test(`actual source COPY tap flow ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const state = await fixture(page, () => ({ body: sourceCopy }))
      const detail = sourceCopy.detail
      await page.goto(origin + '/?tab=history&fixture_mobile_flow=1')
      const name = page.getByTestId('history-name').filter({ has: page.locator('b', { hasText: new RegExp('^' + detail.symbol + '$') }) })
      await name.scrollIntoViewIfNeeded(); await inViewport(name, page, 44); await name.tap()
      const sheet = page.getByTestId('history-detail-sheet')
      await expect(sheet).toBeVisible(); await expect(page.getByTestId('history-back')).toBeFocused()
      await expect(sheet.getByTestId('history-trip')).toHaveCount(detail.trips.length)
      await expect(sheet.getByTestId('history-account-timeline')).toHaveCount(detail.account_segments.length)
      for (const segment of detail.account_segments) if (segment.account_label) await expect(sheet).toContainText(segment.account_label)
      await noOverflow(page); await shot(page, 'actual-' + detail.symbol.toLowerCase() + '-phone-detail', viewport.width)
      await page.getByTestId('history-back').tap(); await expect(sheet).toHaveCount(0)
      await expect(name).toBeFocused(); await inViewport(name, page, 44)
      await name.tap(); await expect(sheet).toBeVisible()
      const trip = detail.trips.find((t: any) => t.trade_id)
      if (trip) {
        // Locator is bound to the actual producer row ID; no financial fixture value is substituted.
        const exact = sheet.locator('[data-testid="history-replay"]').and(page.locator('[data-trade-id=' + JSON.stringify(trip.trade_id) + ']'))
        await exact.scrollIntoViewIfNeeded(); await inViewport(exact, page, 44); await exact.tap()
        await expect(page.getByTestId('fixture-replay')).toContainText(trip.trade_id)
        await inViewport(page.getByTestId('fixture-replay'), page)
        expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
      }
      expect(state.forbidden).toEqual([])
    })
  })
  for (const width of [1440, 412]) test(`actual A source-copy history ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 })
    const state = await fixture(page, () => ({ body: sourceCopy }))
    const detail = sourceCopy.detail
    expect(detail?.symbol).toBeTruthy()
    await page.goto(origin + '/?tab=history&symbol=' + encodeURIComponent(detail.symbol))
    await expect(page.locator('.hh-detail-heading')).toContainText(detail.symbol)
    const rows = page.getByTestId('history-name')
    await expect(rows).toHaveCount(sourceCopy.symbols.length)
    for (const [i, row] of sourceCopy.symbols.entries()) await expect(rows.nth(i)).toContainText(row.symbol)
    expect(await rows.evaluateAll(es => es.every((el, i) => i === es.length - 1 || el.getBoundingClientRect().bottom <= es[i + 1].getBoundingClientRect().top))).toBe(true)
    for (const required of ['AXTI', 'V', 'SCHD', 'SCHG', 'SPCX', 'NFLX']) expect(sourceCopy.symbols.some((r: any) => r.symbol === required)).toBe(true)
    await expect(page.getByTestId('history-trip')).toHaveCount(detail.trips.length)
    await expect(page.getByTestId('history-account-timeline')).toHaveCount(detail.account_segments.length)
    await expect(page.getByTestId('history-stat-times_held')).toContainText(detail.stats.times_held == null ? '—' : String(detail.stats.times_held))
    if (detail.stats.realized_pl == null) await expect(page.getByTestId('history-stat-realized_pl')).toContainText('—')
    if (detail.stats.round_trip_count == null) await expect(page.getByTestId('history-stat-round_trip_count')).toContainText('—')
    await expect(page.locator('.hh-timelines')).toContainText('do not prove uninterrupted ownership')
    const replay = detail.trips.find((t: any) => t.trade_id)
    if (replay) {
      const row = page.getByTestId('history-trip').filter({ has: page.locator('[data-trade-id=' + JSON.stringify(replay.trade_id) + ']') })
      await row.getByText('Provenance', { exact: true }).click()
      for (const ref of replay.provenance || []) {
        if (ref.writer) await expect(row).toContainText(ref.writer)
        if (ref.record_id) await expect(row).toContainText('Record ' + ref.record_id)
      }
      await row.getByTestId('history-replay').click()
      expect(await page.evaluate(() => (window as any).__replayed)).toBe(replay.trade_id)
    }
    for (const gap of detail.gaps || []) {
      await expect(page.getByTestId('history-gaps').filter({ hasText: detail.symbol + ' source gaps' })).toContainText(gap.reason.replace(/_/g, ' '))
    }
    await noOverflow(page); expect(state.forbidden).toEqual([])
    await shot(page, 'actual-' + detail.symbol.toLowerCase(), width)
  })
}
