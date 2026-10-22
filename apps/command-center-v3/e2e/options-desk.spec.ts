/** Options desk redesign (2026-10-22). Every API request is fulfilled locally from the captured
 *  fixture; the test fails on any write other than the existing quote-validation route. */
import { expect, test, type Page } from '@playwright/test'
import { FIXTURE } from '../src/lib/optionsDesk.fixture'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v2/options/proposals' ? FIXTURE.proposals
      : url.pathname === '/api/v2/options/intents' ? FIXTURE.intents
        : url.pathname === '/api/v2/options/execution/status' ? FIXTURE.execStatus
          : url.pathname === '/api/v2/options/open-positions' ? FIXTURE.openPositions
            : url.pathname === '/api/v2/options/validate' ? { ok: true, data: { ok: true, status: 'VALIDATED', validated_at: '2026-10-22T15:01:00Z' } }
              : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('desk is the default Options view: truth, freshness, lifecycle, one merged idea table, checklist', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Options')
  const desk = page.getByTestId('options-desk')
  await expect(desk).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('options-desk-truth')).toContainText('no idea on this desk is eligible')
  await expect(page.getByTestId('options-desk-chip-market-value')).toContainText('Open')
  await expect(page.getByTestId('options-desk-chip-market-value')).not.toContainText(/closed/i)
  await expect(page.getByTestId('options-desk-chip-scan-value')).toContainText('4 of 5,646 evaluated')

  await expect(page.getByTestId('options-desk-lane-you')).toContainText('1')
  await expect(page.getByTestId('options-desk-lane-plan')).toContainText('13')
  const rows = page.getByTestId('options-desk-row')
  await expect(rows.filter({ hasText: 'SPCX' }).filter({ hasText: 'Protective put' })).toHaveCount(1)
  await expect(rows.filter({ hasText: 'Nov 20 $148P × 8' })).toHaveCount(1)

  await page.getByTestId('options-desk-lane-data').click()
  await expect(rows).toHaveCount(2)
  await page.getByTestId('options-desk-lane-data').click()

  await rows.filter({ hasText: 'SPCX' }).filter({ hasText: 'Protective put' }).click()
  const detail = page.getByTestId('options-desk-detail')
  await expect(detail).toContainText('$114,680')
  await expect(detail).toContainText('−$12,330')
  await expect(page.getByTestId('options-desk-checklist')).toContainText('per-order 2FA')
  await expect(page.getByTestId('options-desk-model')).toContainText('advice, not a decision')

  // Keyboard-focusable glossary tooltip, described by aria-describedby.
  const floor = detail.locator('[data-glossary-key="term.floor"] [tabindex="0"]').first()
  await floor.focus()
  await expect(detail.getByRole('tooltip')).toContainText('(strike − premium) × insured shares')
  const describedBy = await floor.getAttribute('aria-describedby')
  expect(describedBy).toBeTruthy()

  // Plans: conflict warning and both earnings dates.
  const plans = page.getByTestId('options-desk-plans')
  await expect(plans).toContainText('hedging')
  await expect(plans).toContainText('2027-02-09')
  await expect(plans).toContainText('2026-11-03')
  await expect(plans).toContainText('simple annualized (not repeatable)')

  await page.getByRole('button', { name: /How this page works/ }).click()
  await expect(page.getByRole('region', { name: 'How this page works' })).toContainText('never sizes, orders')

  expect(writes).toEqual([])
})

test('re-quote uses the existing validate route only; decide opens the existing review modal', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Options&otab=Desk')
  const xlb = page.getByTestId('options-desk-row').filter({ hasText: 'XLB' })
  await xlb.getByRole('button', { name: 'Re-quote now' }).click()
  await expect(xlb.getByRole('status')).toContainText('No order was sent')
  expect(writes).toEqual(['POST /api/v2/options/validate'])
  await page.getByTestId('options-desk-row').filter({ hasText: 'SPCX' }).filter({ hasText: 'Protective put' }).getByRole('button', { name: 'Decide' }).click()
  await expect(page.getByRole('dialog', { name: 'Strategy Proposal' })).toBeVisible()
  expect(writes.filter(w => /submit|confirm|order|preflight|2fa/i.test(w))).toEqual([])
})
