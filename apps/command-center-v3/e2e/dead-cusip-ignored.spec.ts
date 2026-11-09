/** LQ-20261107-1418: a CUSIP-only delisted holding is ignored on the page.
 * Synthetic fixtures only. Every /api call is fulfilled here. Nothing reaches :7777.
 *
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4188 npx playwright test e2e/dead-cusip-ignored.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'

const DEAD = '000000AA0'
const PRICED = '000000BB1'
const TICKER = 'ZZZT'

const HOLDINGS = [
  { symbol: DEAD, account: 'acct-a', shares: 3, current_price: 0, market_value: 0, name: 'Dead fixture' },
  { symbol: PRICED, account: 'acct-b', shares: 8, current_price: 12.5, market_value: 100, name: 'Priced fixture' },
  { symbol: TICKER, account: 'acct-a', shares: 5, current_price: 10, market_value: 50, name: 'Ticker fixture' },
]

const RISK_ROWS = [
  { symbol: DEAD, account_id: 'acct-a', account_label: 'Fixture A', shares: 3, current_price: 0, price: 0, market_value: 0, stop_state: 'none', stop_source: 'none' },
  { symbol: PRICED, account_id: 'acct-b', account_label: 'Fixture B', shares: 8, price: 12.5, market_value: 100, stop_state: 'none', stop_source: 'none' },
  { symbol: TICKER, account_id: 'acct-a', account_label: 'Fixture A', shares: 5, current_price: 10, price: 10, market_value: 50, stop_state: 'none', stop_source: 'none' },
]

async function fixtures(page: Page, seen: string[]) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    seen.push(url.pathname + url.search)
    if (url.pathname === '/api/v2/portfolio/holdings') {
      return route.fulfill({ status: 200, json: { ok: true, data: { holdings: HOLDINGS, as_of: '2026-11-09T05:40:00Z' } } })
    }
    if (url.pathname === '/api/v2/cio/pages') {
      return route.fulfill({
        status: 200,
        json: {
          ok: true,
          data: {
            positions: { rows: RISK_ROWS, as_of: '2026-11-09T05:40:00Z' },
            stops: { as_of: '2026-11-09T05:40:00Z' },
            conflicts: { findings: [] },
          },
        },
      })
    }
    return route.fulfill({ status: 200, json: { ok: true, items: [], rows: [], data: {} } })
  })
}

test('portfolio hides the unpriced CUSIP and still shows a priced one', async ({ page }) => {
  const seen: string[] = []
  await fixtures(page, seen)
  await page.goto('/v3/portfolio?tab=Holdings')
  const panel = page.getByTestId('holdings-panel')
  await expect(panel.getByRole('button', { name: 'All (2)' })).toBeVisible()
  await expect(panel.getByText(TICKER, { exact: true }).first()).toBeVisible()
  await expect(panel.getByText(PRICED, { exact: true }).first()).toBeVisible()
  await expect(panel.getByText(DEAD)).toHaveCount(0)
  await expect.poll(() => seen.some(p => p.startsWith('/api/v2/symbol-cards?'))).toBeTruthy()
  const cards = seen.filter(p => p.startsWith('/api/v2/symbol-cards?') || p.startsWith('/api/v2/finviz-strip-map?'))
  expect(cards.length).toBeGreaterThan(0)
  expect(cards.every(p => !p.includes(DEAD))).toBeTruthy()
  expect(cards.some(p => p.includes(TICKER) && p.includes(PRICED))).toBeTruthy()
})

test('risk board hides the unpriced CUSIP and keeps a price-only row', async ({ page }) => {
  const seen: string[] = []
  await fixtures(page, seen)
  await page.goto('/v3/risk')
  const board = page.getByTestId('risk-positions')
  await expect(board).toBeVisible()
  await expect(board.getByText(TICKER, { exact: true })).toBeVisible()
  await expect(board.getByText(PRICED, { exact: true })).toBeVisible()
  await expect(board.getByText(DEAD)).toHaveCount(0)
})
