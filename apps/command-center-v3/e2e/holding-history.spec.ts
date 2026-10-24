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
  const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';
    import HoldingHistory from'./src/components/tradeinview/HoldingHistory';import'./src/index.css';
    createRoot(document.getElementById('root')).render(<BrowserRouter><main className="cc-terminal-ui" style={{padding:20,minHeight:'100vh',background:'var(--bg-0)',color:'var(--text-0)'}}>
    <h1 style={{fontSize:24,fontWeight:600}}>TradeInView</h1><nav style={{padding:'8px 0 16px'}}>Journeys · Calendar · Replay · <b>Holding history</b> · Journal (classic tabs)</nav>
    <HoldingHistory onReplay={id=>{window.__replayed=id}}/></main></BrowserRouter>);`, resolveDir: process.cwd(), loader: 'tsx', sourcefile: 'history-fixture.tsx' },
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
    if (u.pathname === '/') return route.fulfill({ contentType: 'text/html', body: '<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>' })
    forbidden.push('unlisted:' + req.url()); return route.abort()
  })
  return { forbidden, requests }
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  expect(await page.locator('.holding-history, .hh-main, .hh-panel, .hh-stat, .hh-trip').evaluateAll(es => es.every(e => e.scrollWidth <= e.clientWidth + 1))).toBe(true)
}
async function shot(page: Page, state: string, width: number) {
  if (process.env.HISTORY_SHOTS_DIR) { mkdirSync(process.env.HISTORY_SHOTS_DIR, { recursive: true }); await page.screenshot({ path: resolve(process.env.HISTORY_SHOTS_DIR, `impl-history-${state}-${width}.png`), fullPage: true }) }
}
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
