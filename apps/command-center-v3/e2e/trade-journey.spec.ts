/** TradeInView per-trade journey (operator directive 2026-10-22) on the NAVN fixture — the trade_journey projection's
 *  own output (src/fixtures/tradeJourneys.fixture.ts, drift-checked by tests/test_trade_journey_20261022.py).
 *  Every API request is fulfilled locally; the test records every non-GET and fails on any write other than the one
 *  existing operator flow it drives (Set alert → POST /api/v2/watch/alerts). */
import { expect, test, type Page } from '@playwright/test'
import { TRADE_JOURNEYS_FIXTURE as FIX } from '../src/fixtures/tradeJourneys.fixture'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const p = url.pathname
    let body: unknown = { ok: true, data: {} }
    if (p === '/api/v3/data-broker/trade-journeys') body = FIX
    else if (p.startsWith('/api/v3/data-broker/trade-journeys/')) {
      const id = decodeURIComponent(p.slice('/api/v3/data-broker/trade-journeys/'.length))
      const j = FIX.journeys.find(x => x.trade_id === id)
      body = j ? { ...FIX, journeys: undefined, journey: j } : { ok: false, error: 'not_found' }
    } else if (p === '/api/v2/watch/alerts') body = { ok: true, id: 1 }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('TradeInView opens on trade journeys: interim label, chips, origin badges, NAVN journey', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/journal?symbol=NAVN')
  const root = page.getByTestId('trade-journey')
  await expect(root).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('tj-interim')).toHaveText('interim — CIO prospect store not live')
  for (const k of ['fills', 'holdings', 'stops', 'cio', 'reentry', 'links', 'source']) {
    await expect(page.getByTestId(`tj-chip-${k}`)).toBeVisible()
  }
  await expect(page.getByTestId('tj-chip-stops')).toHaveAttribute('title', /stop_last_known/)

  const rows = page.getByTestId('tj-row')
  await expect(rows).toHaveCount(3)
  const navn = page.locator('[data-testid="tj-row"][data-symbol="NAVN"]')
  await expect(navn.getByTestId('tj-origin')).toHaveText('INTERNAL · Home #4 · 86')
  await expect(navn.getByTestId('tj-origin')).toHaveAttribute('title', /Home #4 · conviction 86 · CIO BUY_READY 10-16/)
  await expect(navn.getByTestId('tj-exit')).toContainText('Trailing stop (ratchet)')
  await expect(page.locator('[data-testid="tj-row"][data-symbol="BAH"]').getByTestId('tj-origin')).toHaveText('YOUR PICK')
  await expect(page.locator('[data-testid="tj-row"][data-symbol="V"]').getByTestId('tj-origin')).toHaveText('ORIGIN ?')

  // ?symbol=NAVN selected the NAVN journey
  const detail = page.getByTestId('tj-detail')
  await expect(detail).toContainText('NAVN · schwab_rollover_ira')
  await expect(page.getByTestId('tj-origin-card')).toContainText('Home #4 · conviction 86 · CIO BUY_READY 10-16')
  await expect(page.getByTestId('tj-origin-card')).toContainText('cio_opportunity_assessments: v26')

  // timeline: origin → entry → 7 stop levels → CIO change → exit with cause
  const events = page.getByTestId('tj-event')
  await expect(events.first()).toHaveAttribute('data-kind', 'origin')
  await expect(page.locator('[data-testid="tj-event"][data-kind="stop_change"]')).toHaveCount(7)
  await expect(page.getByTestId('tj-timeline')).toContainText('Stop raised $25.61 → $26.02')
  await expect(page.getByTestId('tj-timeline')).toContainText('CIO stance WATCH → ADD · conviction 86 → 88 · rank #4 → #1')
  await expect(events.last()).toHaveAttribute('data-kind', 'exit_fill')
  await expect(events.last()).toContainText('Sold @ $26.02 · Trailing stop (ratchet)')
  await expect(events.last()).toContainText('raised 6× (24.31 → 24.59 → 24.70 → 24.97 → 25.51 → 25.61 → 26.02)')

  // price band from the detail endpoint: one segment per stop level
  await expect(page.getByTestId('tj-chart')).toBeVisible()
  await expect(page.getByTestId('tj-chart-stop')).toHaveCount(7)

  // review: facts first, model prose labelled advisory
  await expect(page.getByTestId('tj-review')).toContainText('High while held')
  await expect(page.getByTestId('tj-review')).toContainText('$26.62')
  await expect(page.getByTestId('tj-review')).toContainText('noise — gave back 2.27% from the high, trend intact')
  await expect(page.getByTestId('tj-advisory')).toContainText('ADVISORY · deepseek-flash')
  await expect(page.getByTestId('tj-advisory')).toContainText('model output, not a fact')

  // re-entry: desk record, conditions, levels
  const re = page.getByTestId('tj-reentry')
  await expect(re).toContainText('WAIT — Wait for the zone. Zone $24.80–$25.10, invalidation $23.90. 6 of 8 conditions met.')
  await expect(page.getByTestId('tj-conditions')).toContainText('Reclaims your exit price $26.02 (reference)')
  await expect(re).toContainText('same record as Watch')

  // conflicts shown, never resolved
  await expect(page.getByTestId('tj-conflicts')).toContainText('CIO still treats this as owned after the exit')

  // drawers
  await page.getByTestId('tj-drawer-how').getByRole('button').click()
  await expect(page.getByTestId('tj-drawer-how-body')).toContainText('Nothing on this page sizes, places, moves or cancels an order')
  await page.getByTestId('tj-drawer-conflicts').getByRole('button').click()
  await expect(page.getByTestId('tj-drawer-conflicts-body')).toContainText('NAVN: CIO still treats this as owned')

  expect(writes).toEqual([])
})

test('filters narrow the one table; Set alert opens the existing advisory alert form', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/journal')
  await expect(page.getByTestId('trade-journey')).toBeVisible({ timeout: 60_000 })
  await page.getByTestId('tj-filter-mine').click()
  await expect(page).toHaveURL(/filter=mine/)
  await expect(page.getByTestId('tj-row')).toHaveCount(1)
  await expect(page.getByTestId('tj-row').first()).toHaveAttribute('data-symbol', 'BAH')
  await page.getByTestId('tj-filter-internal').click()
  await expect(page.getByTestId('tj-row')).toHaveCount(1)
  await page.getByTestId('tj-filter-open').click()
  await expect(page.getByTestId('tj-row').first()).toHaveAttribute('data-symbol', 'V')
  await page.getByTestId('tj-filter-all').click()
  await expect(page.getByTestId('tj-row')).toHaveCount(3)

  await page.locator('[data-testid="tj-row"][data-symbol="NAVN"]').getByRole('button', { name: 'NAVN' }).click()
  await page.getByTestId('tj-set-alert').click()
  const modal = page.getByText('Arm', { exact: false }).first()
  await expect(modal).toBeVisible()
  expect(writes).toEqual([])
})

test('legacy deep links still open the classic journal', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/journal?tab=Options')
  await expect(page.getByTestId('tj-back')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('trade-journey')).toHaveCount(0)
  await page.getByTestId('tj-back').click()
  await expect(page.getByTestId('trade-journey')).toBeVisible()
})
