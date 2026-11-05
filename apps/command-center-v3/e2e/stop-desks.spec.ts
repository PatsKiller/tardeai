/** Stop desks (boards 14, 15, 3): Risk KPI row + stop source per position, Home "Review protection" → that position,
 * Defense "Your book" stop categories. Synthetic fixtures only; every non-GET is aborted and must not happen.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/stop-desks.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'
import W7 from './fixtures/w7Pages.fixture.json' with { type: 'json' }

test.use({ hasTouch: true })

const AT = '2031-03-07T20:55:00-05:00'
const READ = 'Fri Mar 7 20:55 ET'
type Cat = 'active' | 'pending_activation' | 'filled' | 'unknown' | 'planned' | 'none'
const row = (symbol: string, account_id: string, account_label: string, shares: number, price: number, cat: Cat, stop: number | null, counted = true) => {
  const resting = cat === 'active' || cat === 'pending_activation'
  return {
    symbol, account_id, account_label, shares, price, market_value: shares * price, counted, stop_category: cat,
    stop_state: cat === 'planned' ? 'none' : cat, stop_source: cat === 'planned' ? 'planned' : cat === 'none' ? 'none' : 'broker_resting',
    stop_price: stop, stop_captured_at: AT, broker_protected: cat === 'active',
    distance_to_stop_pct: cat === 'active' && stop ? Math.round(10000 * (price - stop) / price) / 100 : null,
    loss_at_stop_usd: cat === 'active' && stop ? (price - stop) * shares : null,
    resting_stop_distance_pct: resting && stop ? Math.round(10000 * (price - stop) / price) / 100 : null,
    loss_at_resting_stop_usd: resting && stop ? (price - stop) * shares : null,
    planned_stop_distance_pct: cat === 'planned' && stop ? Math.round(10000 * (price - stop) / price) / 100 : null,
  }
}
const ROWS = [
  row('PNDA', 'synthetic_a', 'Synthetic Account A', 100, 50, 'pending_activation', 45),
  row('PNDB', 'synthetic_b', 'Synthetic Account B', 10, 80, 'pending_activation', 60),
  row('FILA', 'synthetic_a', 'Synthetic Account A', 20, 30, 'filled', 31),
  row('FILA', 'synthetic_b', 'Synthetic Account B', 5, 30, 'filled', 31),
  row('UNKA', 'synthetic_b', 'Synthetic Account B', 4, 60, 'unknown', 55),
  row('PLNA', 'synthetic_a', 'Synthetic Account A', 3, 80, 'planned', 60),
  row('NONA', 'synthetic_a', 'Synthetic Account A', 40, 25, 'none', null),
  row('DUST', 'synthetic_a', 'Synthetic Account A', 1, 5, 'none', null, false),
]
const counted = ROWS.filter(r => r.counted)
const bucket = (c: Cat) => { const g = counted.filter(r => r.stop_category === c); return { count: g.length, value_usd: g.reduce((a, r) => a + r.market_value, 0), symbols: g.map(r => ({ symbol: r.symbol, account_id: r.account_id, account_label: r.account_label })) } }

function cioPages() {
  const payload: any = structuredClone((W7 as any).payload)
  const total = ROWS.reduce((a, r) => a + r.market_value, 0)
  const resting = counted.reduce((a, r) => a + (r.loss_at_resting_stop_usd || 0), 0)
  payload.portfolio = { ...payload.portfolio, position_counts: { definition: 'held non-cash account+symbol with market_value >= 100', counted: counted.length } }
  payload.positions = {
    ...payload.positions, rows: ROWS, loss_at_stop_usd: 0, portfolio_heat_pct: 0, unprotected_value_usd: counted.reduce((a, r) => a + r.market_value, 0),
    loss_at_resting_stops_usd: resting, resting_heat_pct: Math.round(100000 * resting / total) / 1000,
    stop_breakdown: Object.fromEntries((['active', 'pending_activation', 'filled', 'unknown', 'planned', 'none'] as Cat[]).map(c => [c, bucket(c)])),
    largest_name: { symbol: 'PNDA', pct: 40 }, gap: null, as_of: AT,
  }
  payload.stops = {
    ...payload.stops, rows: [], active_count: 0, pending_count: 2, filled_count: 2, unprotected_count: counted.length, position_count: counted.length,
    nearest: null, awaiting_fill: [], awaiting_fill_count: 0, gap: null, stale: false, as_of: AT, last_broker_read_label: READ,
    filled_awaiting_sync: counted.filter(r => r.stop_category === 'filled').map(r => ({ symbol: r.symbol, account_id: r.account_id, account_label: r.account_label })),
  }
  payload.do_now = { items: [{ id: 'protection:synthetic_b:PNDB', symbol: 'PNDB', title: 'PNDB · Synthetic Account B', reason: 'Stop awaiting activation', href: '/v3/risk', cta: 'Review protection' }] }
  payload.conflicts = null
  return payload
}

function defenseProjection() {
  const r = (id: string, label: string, value: string, extra: object = {}) => ({ id, label, value, ...extra })
  return {
    ok: true, desk: 'defense', as_of: AT, sources: [], decisions: [], tabs: {
      'your-book': { panels: [{ id: 'book', title: 'Your book', sub: 'held names · stops from the CIO record', rows: [
        r('bk-unprot', 'Positions with no broker stop', '2 (1 planned level only)', { tone: 'warn', href: '/risk?tab=exposure' }),
        r('bk-pending', 'Stops resting · pending activation', '2', { tone: 'warn' }),
        r('bk-filled', 'Stops filled · awaiting holdings sync', '2 · FILA ×2', { tone: 'warn' }),
        r('bk-PNDA-synthetic_a', 'PNDA · Synthetic Account A', '$5,000 · stop pending activation', { tone: 'warn', detail: {
          title: 'PNDA · Synthetic Account A', fields: [{ label: 'Stop', value: 'stop pending activation' }, { label: 'Distance to stop', value: '10.00%' }],
          source: 'cio_truth.resolve', href: '/risk?tab=exposure&detail=position:synthetic_a:PNDA', href_label: 'Stop review on Risk →' } }),
      ] }] },
    },
  }
}

async function fixtures(page: Page) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const p = new URL(req.url()).pathname
    if (req.method() !== 'GET' || p.includes('/stops/lifecycle')) { writes.push(`${req.method()} ${p}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/cio/pages') return json({ ok: true, data: cioPages() })
    if (p === '/api/v2/desks/defense') return json(defenseProjection())
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

/** Optional evidence shots into a private directory (never committed). */
const shot = async (page: Page, name: string) => { if (process.env.STOP_DESKS_SHOTS) await page.screenshot({ path: `${process.env.STOP_DESKS_SHOTS}/${name}.png`, fullPage: true }) }
const noHorizontalScroll = async (page: Page) => expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  const phone = width < 821
  test(`Risk ${width}: KPI row by stop category, stop source per position, sheet`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page)
    await page.goto('/v3/risk')
    const kpis = page.getByTestId('risk-kpis')
    await expect(kpis).toContainText('Loss if every resting stop fills')
    await expect(kpis).toContainText('$700')                                 // 100×(50−45) + 10×(80−60)
    await expect(page.getByTestId('risk-kpi-loss')).toContainText('0 active, 2 pending activation')
    await expect(kpis).toContainText('Value with no broker stop')
    await expect(page.getByTestId('risk-kpi-nostop')).toHaveText('2 positions · 1 with a planned level only')
    await expect(kpis).toContainText('$1,240')                               // 3×80 + 40×25
    await expect(page.getByTestId('risk-kpi-awaiting')).toHaveText('2')
    await expect(kpis).toContainText('FILA ×2 · stop filled · awaiting holdings sync')
    await expect(page.getByTestId('risk-stop-breakdown')).toContainText('2 broker resting · pending activation · 2 broker stop filled · awaiting holdings sync · 1 broker stop · state not recorded · 1 planned level · no resting order · 1 no stop — of 7 counted positions')
    await expect(page.getByText('UNKA · Synthetic Account B: a broker stop was read but its state was not recorded.', { exact: false })).toBeVisible()
    const table = page.getByTestId('risk-positions')
    await expect(table).toContainText(`Stops · last broker read ${READ}`)
    await expect(table.locator('[data-stop-category]')).toHaveCount(7)
    const pend = table.locator('article', { hasText: 'PNDA' })
    await expect(pend).toContainText('10%')
    await expect(pend).toContainText('$500')
    await expect(pend).toContainText('Broker resting · pending activation')
    await expect(table.locator('article', { hasText: 'PLNA' })).toContainText('25%')
    await expect(table.locator('article', { hasText: 'NONA' })).toContainText('No stop')
    await expect(table).not.toContainText('Not measured')
    const toggle = page.getByTestId('risk-toggle-small')
    expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    if (phone) await toggle.tap(); else await toggle.click()
    await expect(table.locator('[data-stop-category]')).toHaveCount(8)
    await noHorizontalScroll(page)
    await shot(page, `impl-15-risk-exposure-${width}`)
    const review = table.getByRole('button', { name: 'Review PNDA →' })
    expect((await review.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    if (phone) await review.tap(); else await review.click()
    const sheet = page.getByRole('dialog', { name: 'PNDA · stop details' })
    await expect(sheet).toContainText('Broker resting · pending activation')
    await expect(sheet).toContainText('awaiting activation. It does not provide active protection yet.')
    await expect(sheet.getByRole('link', { name: 'Stop review and advice →' })).toHaveAttribute('href', '/v3/portfolio?tab=Stop%20Management')
    expect(writes).toEqual([])
  })

  test(`Home ${width}: Review protection opens that account's position on Risk`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page)
    await page.goto('/v3/')
    const link = page.getByTestId('home-do-now').getByRole('link', { name: /Review protection/ })
    await expect(link).toHaveAttribute('href', '/v3/risk?tab=exposure&detail=position%3Asynthetic_b%3APNDB')
    expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    if (phone) await link.tap(); else await link.click()
    await expect(page).toHaveURL(/\/v3\/risk\?tab=exposure&detail=position%3Asynthetic_b%3APNDB/)
    const sheet = page.getByRole('dialog', { name: 'PNDB · stop details' })
    await expect(sheet).toContainText('Synthetic Account B')
    await shot(page, `impl-14-home-review-protection-sheet-${width}`)
    await noHorizontalScroll(page)
    expect(writes).toEqual([])
  })

  test(`Defense ${width}: Your book stop categories and position link to Risk`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page)
    await page.goto('/v3/defense?tab=your-book')
    const book = page.getByTestId('desk-panel-book')
    await expect(book).toContainText('Positions with no broker stop')
    await expect(book).toContainText('2 · FILA ×2')
    await shot(page, `impl-3-your-book-${width}`)
    const pos = book.getByRole('button', { name: /PNDA · Synthetic Account A/ })
    expect((await pos.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    if (phone) await pos.tap(); else await pos.click()
    const toRisk = page.getByRole('dialog').getByRole('link', { name: 'Stop review on Risk →' })
    await expect(toRisk).toBeVisible()
    if (phone) await toRisk.tap(); else await toRisk.click()
    await expect(page).toHaveURL(/\/v3\/risk\?tab=exposure&detail=position/)
    await expect(page.getByRole('dialog', { name: 'PNDA · stop details' })).toBeVisible()
    await noHorizontalScroll(page)
    expect(writes).toEqual([])
  })
}
