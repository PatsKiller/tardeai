/** Trading tabs 8 → 4 and the protect-first Open Trades desk (operator-approved Gate 3, 2026-10-22).
 *  Every API request is fulfilled locally from the captured fixture; the test records every non-GET
 *  request and fails on any write except the advisory stop-alert snooze it clicks on purpose. */
import { expect, test, type Page } from '@playwright/test'
import { OPEN_TRADES_FIXTURE } from '../src/lib/openTradesDesk.fixture'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v2/open-trades/intelligence' ? OPEN_TRADES_FIXTURE.intelligence
      : url.pathname === '/api/v2/broker-reconciliation' ? OPEN_TRADES_FIXTURE.recon
        : url.pathname === '/api/v2/broker-proposals/summary' ? { ok: true, total: 7 }
          : url.pathname === '/api/v2/holdings/stop-snooze' ? { ok: true, snoozed_until: '2026-10-29T00:00:00Z' }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('Trading shows four tabs; Broker Orders and ATM moved', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Open+Trades')
  const tabs = page.getByRole('tablist', { name: 'Trading desk tabs' }).getByRole('tab')
  await expect(tabs).toHaveText(['Trade AI', 'Options', 'Open Trades', /^Proposals/], { timeout: 60_000 })
  await expect(page.getByTestId('proposals-tab-count')).toHaveText('7')
  await expect(page.getByTestId('trading-moved-note')).toContainText('ATM controls moved to')
  await expect(page.getByTestId('desk-health-open')).toHaveText('23 open')
  expect(writes).toEqual([])
})

test('Open Trades: protect first, one table, PAPER badge, detail panel, stop controls', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Open+Trades')
  const desk = page.getByTestId('open-trades-desk')
  await expect(desk).toBeVisible({ timeout: 60_000 })
  const headline = page.getByTestId('ot-headline')
  await expect(headline).toContainText('23 positions across')
  await expect(headline).toContainText('excluding 1 write-off')
  await expect(headline).toContainText('have no working stop')
  await expect(page.getByTestId('ot-freshness')).toContainText('1 stale')

  const protect = page.getByTestId('ot-protect-card')
  await expect(protect.first()).toContainText('SCHD')
  await expect(page.getByTestId('ot-row').filter({ hasText: 'SRNE' })).toHaveCount(0)

  await page.getByTestId('ot-filter-paper').click()
  const rows = page.getByTestId('ot-row')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('DELL')
  await expect(rows.first()).toContainText('PAPER')
  await expect(rows.first()).toContainText('Alpaca Paper')
  await page.getByTestId('ot-filter-all').click()

  await rows.filter({ hasText: 'Schwab Roth IRA' }).getByRole('button', { name: 'Show details for V' }).click()
  const detail = page.getByTestId('ot-detail')
  await expect(detail).toContainText('Schwab Roth IRA')
  await expect(page.getByTestId('ot-stop-history')).toContainText('Broker stop $399.82 × 130')
  await expect(page.getByTestId('ot-stop-history')).toContainText('Covers 130 of 130.4985 shares held')

  // Arm stop opens the existing decision card (Stage 2c ARM + 2FA flow) — nothing is sent by opening it.
  await page.getByTestId('ot-arm-stop').click()
  await expect(page.getByTestId('ot-stop-controls')).toBeVisible()
  await expect(page.getByTestId('ot-stop-controls')).toContainText('Stop controls · V')
  expect(writes).toEqual([])

  await page.getByTestId('ot-snooze').click()
  await expect(detail.getByRole('status')).toContainText('snoozed until 2026-10-29')
  expect(writes).toEqual(['POST /api/v2/holdings/stop-snooze'])

  await page.getByRole('button', { name: /Write-offs/ }).click()
  await expect(page.getByTestId('ot-writeoff-row')).toContainText('SRNE')
})

test('retired tabs redirect: Broker Recon → Open Trades drawer, Entry Desk → Proposals Path A', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Broker+Recon')
  await expect(page.getByRole('tab', { name: 'Open Trades' })).toHaveAttribute('aria-selected', 'true', { timeout: 60_000 })
  await expect(page.getByTestId('ot-recon')).toBeVisible()
  await expect(page.getByTestId('ot-recon')).toContainText('closed but held')

  await page.goto('/v3/trading?tab=Entry+Desk&symbol=ABC')
  await expect(page.getByTestId('proposals-section-path-a')).toHaveAttribute('aria-selected', 'true', { timeout: 60_000 })
  await page.goto('/v3/manual-execution')
  await expect(page).toHaveURL(/tab=Proposals&section=path-a/)
  expect(writes).toEqual([])
})

test('retired tabs that left the hub redirect to their new pages', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Scalp&symbol=adv')
  await expect(page).toHaveURL(/\/v3\/active-trader\?tab=Scalp&symbol=ADV/, { timeout: 60_000 })
  await page.goto('/v3/trading?tab=ATM+Controls')
  await expect(page).toHaveURL(/\/v3\/system\/broker-access#automation-controls/, { timeout: 60_000 })
  await expect(page.getByTestId('automation-controls')).toBeVisible()
  await page.goto('/v3/trading?tab=Execution')
  await expect(page).toHaveURL(/\/v3\/journal/, { timeout: 60_000 })
  await page.goto('/v3/go/order/intent-123')
  await expect(page.getByTestId('trading-desk-broker-orders')).toBeVisible({ timeout: 60_000 })
  await expect(page).toHaveURL(/intent=intent-123/)
  expect(writes).toEqual([])
})

test('narrow viewport: Open Trades has no horizontal page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, [])
  await page.goto('/v3/trading?tab=Open+Trades')
  await expect(page.getByTestId('open-trades-desk')).toBeVisible({ timeout: 60_000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  expect(overflow).toBeFalsy()
})
