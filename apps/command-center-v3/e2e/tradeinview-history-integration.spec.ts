/** Batch-28 integration: the real TradeInView shell + C's HoldingHistory + B's stored Replay on a phone.
 * Every request is fulfilled from an isolated origin (no server). Journeys/Replay bodies come from the
 * builder-generated e2e/fixtures/tradeinviewRedesign.fixture.json; the History body is synthetic.
 */
import { expect, test, type Page } from '@playwright/test'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'

const tiv = JSON.parse(readFileSync(new URL('./fixtures/tradeinviewRedesign.fixture.json', import.meta.url), 'utf8'))
const origin = 'http://tradeinview-history.invalid'
const TRADE = tiv.replay.bars.trade_id as string
let js = '', css = ''
test.beforeAll(async () => {
  const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';
    import TradeInViewPage from'./src/pages/TradeInViewPage';import'./src/styles/tokens.css';import'./src/index.css';
    createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><TradeInViewPage onDrill={()=>{}}/></BrowserRouter>);`,
    resolveDir: process.cwd(), loader: 'tsx', sourcefile: 'tradeinview-history.tsx' },
    bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
  js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script'); css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
})
const stats = { times_held: null, known_holding_stretches: null, round_trip_count: null, win_rate_pct: null, realized_pl: null, known_realized_pl: null, avg_hold_days: null, median_hold_days: null, best_trip_pct: null, worst_trip_pct: null, coverage: { status: 'MISSING', reasons: ['Synthetic history coverage unavailable'] } }
function history(symbol: string | null) {
  const name = { symbol: 'TSTA', company_name: null, account_count: null, round_trip_count: null, realized_pl: null, known_realized_pl: null, held_now: null, basis_unknown: true, accounts: [], gaps: [{ reason: 'Synthetic count coverage unavailable' }] }
  return { schema: 'HoldingHistory@v1', ok: true, as_of: '2026-11-04T17:00:00Z', source: 'SYNTHETIC',
    range: { start_date: null, end_date: null, basis: 'synthetic', coverage: { status: 'MISSING', reasons: ['Synthetic range'] } },
    symbols: [name], account_options: [], gaps: [], provider_calls: 0, writes: 0, read_only: true,
    detail: symbol ? { symbol, company_name: null, company_missing_reason: 'Synthetic company memory missing', stats, account_segments: [], gaps: [],
      trips: [{ trade_id: TRADE, symbol, account_id: null, account_label: 'Synthetic account', entry_at: null, exit_at: null, entry_price: null, exit_price: null, shares: null, realized_pl: null, return_pct: null, hold_days: null, hold_days_basis: null, basis_unknown: true, basis_reason: 'Synthetic basis unknown', source: 'synthetic ledger', provenance: [] }] } : null }
}
async function serve(page: Page) {
  const forbidden: string[] = []
  await page.routeWebSocket('**/*', ws => { forbidden.push('WS:' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (req.method() !== 'GET' || u.origin !== origin) { forbidden.push(req.method() + ':' + req.url()); return route.abort() }
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname.startsWith('/v3/')) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0)}#root{padding:16px;box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
    if (u.pathname === '/api/v3/data-broker/holding-history') return json(history(u.searchParams.get('symbol')))
    if (u.pathname === '/api/v3/data-broker/trade-journeys') return json(tiv.journeys.fresh)
    if (u.pathname === '/api/v2/trade-chart') {
      if (u.searchParams.get('stored_only') !== '1') { forbidden.push('provider:' + u.search); return route.abort() }
      const body = Object.values(tiv.replay as Record<string, any>).find(r => r.trade_id === u.searchParams.get('trade_id'))
      return body ? json(body) : route.abort()
    }
    forbidden.push('unlisted:' + u.pathname); return route.abort()
  })
  return forbidden
}
test.describe('phone: History name → full-screen sheet → Replay this trip → Back', () => {
  test.use({ hasTouch: true })
  for (const viewport of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
    test(`integrated History to Replay ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const forbidden = await serve(page)
      await page.goto(origin + '/v3/journal?tab=history')
      await expect(page.getByRole('tab', { name: 'Holding history' })).toHaveAttribute('aria-selected', 'true')
      const name = page.getByTestId('history-name').filter({ hasText: 'TSTA' })
      await name.tap()
      const sheet = page.getByTestId('history-detail-sheet')
      await expect(sheet).toBeVisible()
      expect(await sheet.boundingBox()).toEqual({ x: 0, y: 0, width: viewport.width, height: viewport.height })
      await expect(page.getByTestId('history-back')).toBeFocused()
      const replay = sheet.getByTestId('history-replay')
      await replay.scrollIntoViewIfNeeded(); await replay.tap()
      await expect(page).toHaveURL(/tab=replay/)
      expect(new URL(page.url()).searchParams.get('trade')).toBe(TRADE)
      await expect(page.getByTestId('history-detail-sheet')).toHaveCount(0)
      await expect(page.getByRole('tab', { name: 'Replay' })).toHaveAttribute('aria-selected', 'true')
      await expect(page.getByTestId('trade-replay-chart').locator('canvas').first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
      // Browser/phone Back returns to the History name that was open.
      await page.goBack()
      await expect(page.getByRole('tab', { name: 'Holding history' })).toHaveAttribute('aria-selected', 'true')
      await expect(page.getByTestId('history-detail-sheet')).toBeVisible()
      await page.getByTestId('history-back').tap()
      await expect(page.getByTestId('history-detail-sheet')).toHaveCount(0)
      expect(forbidden).toEqual([])
    })
  }
})
