/** Options lifecycle desk (Gate 3, 2026-10-22): act-first order with open legs in step 7, freshness on
 *  every cost, the act-first strip, the classic view kept one release via ?view=classic, and the
 *  ?symbol= deep link. Every API request is fulfilled from fixtures; the test fails on any write. */
import { expect, test, type Page } from '@playwright/test'
import { FIXTURE } from '../src/lib/optionsDesk.fixture'
import { OPEN_POSITIONS_FIXTURE } from '../src/lib/optionsOpenPositions.fixture'

async function mockApi(page: Page, writes: string[], openPositions: unknown = OPEN_POSITIONS_FIXTURE) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v2/options/proposals' ? FIXTURE.proposals
      : url.pathname === '/api/v2/options/intents' ? FIXTURE.intents
        : url.pathname === '/api/v2/options/execution/status' ? FIXTURE.execStatus
          : url.pathname === '/api/v2/options/open-positions' ? openPositions
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('act-first order: defend leg, your decision, harvest leg, then data/research/plan, calm legs last', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Options')
  await expect(page.getByTestId('options-desk')).toBeVisible({ timeout: 60_000 })
  // The old tab strip is gone from the desk; the classic view is one link away.
  await expect(page.getByTestId('options-classic-tabs')).toHaveCount(0)
  await expect(page.getByTestId('options-classic-view-link')).toBeVisible()

  const rows = page.getByTestId('options-desk-row')
  await expect(rows.first()).toContainText('XYZ')
  const lanes = await rows.evaluateAll(els => els.map(e => e.getAttribute('data-lane')))
  expect(lanes.slice(0, 3)).toEqual(['open', 'you', 'open'])
  expect(lanes.indexOf('data')).toBeLessThan(lanes.indexOf('research'))
  expect(lanes.indexOf('research')).toBeLessThan(lanes.indexOf('plan'))
  expect(lanes.slice(-2)).toEqual(['open', 'open'])

  // Every cost states the quote (or monitor run) it came from.
  const ages = page.getByTestId('options-desk-cost-age')
  await expect(ages).toHaveCount(await rows.count())
  for (const t of await ages.allInnerTexts()) expect(t.trim().length).toBeGreaterThan(0)
  await expect(rows.filter({ hasText: 'SPCX' }).filter({ hasText: 'Protective put' }).getByTestId('options-desk-cost-age')).toContainText('quote Oct 21 16:00 ET')
  await expect(rows.first().getByTestId('options-desk-cost-age')).toContainText('monitored')

  // Act-first strip: the defend and harvest legs, each a rule and not an order.
  const strip = page.getByTestId('options-desk-act-first')
  await expect(strip.getByTestId('options-desk-act-card')).toHaveCount(2)
  await expect(strip).toContainText('Short call ITM and DTE ≤ 7')
  await expect(strip).toContainText('a rule, not an order')
  await expect(page.getByTestId('options-desk-chip-open-value')).toContainText('monitored')
  await expect(page.getByTestId('options-desk-lane-open')).toContainText('4')

  // Open-leg detail: monitor rule, mark freshness, the decision stays yours.
  await rows.first().click()
  const detail = page.getByTestId('options-desk-detail')
  await expect(detail).toContainText('XYZ · Short call')
  await expect(detail).toContainText('provider quote time not served')
  await expect(page.getByTestId('options-desk-checklist')).toContainText('What the monitor says')
  await expect(page.getByTestId('options-desk-checklist')).toContainText('per-order 2FA')
  await expect(page.getByTestId('options-desk-model')).toContainText('never closes or rolls anything')

  // The step-7 next step opens the existing Lifecycle view (classic), nothing else.
  await rows.first().getByRole('button', { name: 'Manage in Lifecycle' }).click()
  await expect(page).toHaveURL(/otab=Lifecycle/)
  await expect(page).toHaveURL(/view=classic/)
  await expect(page.getByTestId('options-classic-tabs')).toBeVisible()
  await page.getByTestId('options-back-to-desk').click()
  await expect(page.getByTestId('options-desk')).toBeVisible()
  await expect(page).not.toHaveURL(/view=classic/)
  expect(writes).toEqual([])
})

test('classic view stays reachable for one release via ?view=classic', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Options&view=classic')
  await expect(page.getByTestId('options-classic-tabs')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('options-desk')).toHaveCount(0)
  await expect(page.getByTestId('options-classic-tabs').getByRole('button', { name: 'Proposals', exact: true })).toHaveAttribute('aria-pressed', 'true')
  // The Defense strip's deep link still lands on Lifecycle.
  await page.goto('/v3/trading?tab=Options&otab=Lifecycle')
  await expect(page.getByTestId('options-classic-tabs').getByRole('button', { name: 'Lifecycle', exact: true })).toHaveAttribute('aria-pressed', 'true', { timeout: 60_000 })
  expect(writes).toEqual([])
})

test('?symbol= filters the desk (Open Trades → Protective put ideas) and the filter is removable', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Options&symbol=xlb')
  await expect(page.getByTestId('options-desk')).toBeVisible({ timeout: 60_000 })
  const rows = page.getByTestId('options-desk-row')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('XLB')
  await page.getByTestId('options-desk-clear-filters').click()
  await expect(rows.filter({ hasText: 'SPCX' }).first()).toBeVisible()
  expect(writes).toEqual([])
})

test('no open legs: no act-first strip, step 7 says so with the monitor time', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes, FIXTURE.openPositions)
  await page.goto('/v3/trading?tab=Options')
  await expect(page.getByTestId('options-desk')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('options-desk-act-first')).toHaveCount(0)
  await page.getByTestId('options-desk-lane-open').click()
  await expect(page.getByTestId('options-desk-empty')).toContainText('No open option legs at the broker (monitored')
  expect(writes).toEqual([])
})
