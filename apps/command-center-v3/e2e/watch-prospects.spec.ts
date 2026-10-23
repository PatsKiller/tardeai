/** Watch redesign (Gate 3 mockup, 2026-10-22). Every API request is fulfilled locally from the captured fixture;
 *  the test records every non-GET and fails on any write other than the three existing operator flows it drives. */
import { expect, test, type Page } from '@playwright/test'
import { FIXTURE } from '../src/fixtures/watchProspects.fixture'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v3/data-broker/watch-prospects' ? FIXTURE.prospects
      : url.pathname === '/api/v2/watch/alerts/list' ? FIXTURE.alerts
        : url.pathname === '/api/v2/proposal-accounts' ? { ok: true, data: { accounts: [] } }
          : url.pathname.endsWith('/review-request') ? { ok: true, data: { ok: true, already_open: false } }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('Prospects is the default Watch view: interim label, chips, five lanes, one row per prospect', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/watch')
  await expect(page).toHaveURL(/tab=prospects/)
  const root = page.getByTestId('watch-prospects')
  await expect(root).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('watch-interim')).toHaveText('interim — CIO prospect store not live')
  await expect(page.getByTestId('watch-chip-conflicts')).toContainText('shown, not hidden')
  await expect(page.getByTestId('watch-chip-holdings')).toContainText('positions_store.positions_current')

  for (const [id, n] of [['actionable', 5], ['forming', 90], ['reentry', 19], ['manage', 20], ['expired', 67]] as const) {
    await expect(page.getByTestId(`watch-lane-${id}`)).toContainText(String(n))
  }
  // Actionable is the default lane: CACI (re-entry desk READY) leads with Propose.
  const rows = page.getByTestId('watch-row')
  await expect(rows).toHaveCount(5)
  await expect(rows.first()).toHaveAttribute('data-symbol', 'CACI')
  await expect(rows.first().getByTestId('watch-step')).toHaveText('Propose')

  // Manage: NAVN shows both conflicts and Protect first → Open Trades.
  await page.getByTestId('watch-lane-manage').click()
  await expect(page).toHaveURL(/lane=manage/)
  const navn = page.locator('[data-testid="watch-row"][data-symbol="NAVN"]')
  await expect(navn.getByTestId('watch-conflict')).toHaveCount(2)
  await expect(navn.getByTestId('watch-step')).toHaveText('Protect first')
  await expect(navn.getByTestId('watch-step')).toHaveAttribute('href', /\/v3\/trading\?tab=Open\+Trades&symbol=NAVN/)
  await expect(page.locator('[data-testid="watch-row"][data-lane="manage"]')).toHaveCount(8)
  await expect(page.getByTestId('watch-overflow')).toContainText('12 more below the 8-row cap')

  // Detail: components, conflicts with both sides, same record everywhere.
  await navn.getByRole('button', { name: /NAVN/ }).click()
  const detail = page.getByTestId('watch-detail')
  await expect(detail).toContainText('Conviction 88')
  await expect(page.getByTestId('watch-components')).toContainText('Risk/Reward')
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('SELL')
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('positions_store.positions_current')
  await expect(page.getByTestId('watch-same-record')).toContainText('not joined (interim)')
  await expect(page.getByTestId('watch-same-record')).toContainText('#1 · 88 · WATCH')
  await page.getByTestId('watch-ask-cio').click()
  await expect(page.getByTestId('watch-detail-conflicts')).toContainText('CIO review queued.')

  // Drawers: alerts tied/orphaned, expired, how this page works.
  await page.getByTestId('watch-drawer-alerts').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-alerts')).toContainText('16 armed → 8 belong to a prospect · 8 orphaned')
  await expect(page.getByTestId('watch-drawer-alerts-body')).toContainText('QCOM price')
  await expect(page.getByTestId('watch-orphan-alert')).toHaveCount(8)
  await page.getByTestId('watch-drawer-expired').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-expired-body')).toContainText('CVS')
  await page.getByTestId('watch-drawer-how').getByRole('button').click()
  await expect(page.getByTestId('watch-drawer-how-body')).toContainText('never silently resolved')

  expect(writes).toEqual(['POST /api/v3/opportunities/NAVN/review-request'])
})

test('Propose opens the existing propose form; Set alert opens the existing alert form', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/watch?tab=prospects&lane=actionable')
  const caci = page.locator('[data-testid="watch-row"][data-symbol="CACI"]')
  await caci.getByTestId('watch-step').click()
  await expect(page.getByText('Propose entry')).toBeVisible()
  await expect(page.getByText('CACI').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await page.goto('/v3/watch?tab=prospects&lane=reentry')
  const kbr = page.locator('[data-testid="watch-row"][data-symbol="KBR"]')
  await kbr.getByTestId('watch-step').click()
  const modal = page.getByTestId('reentry-alert-arm-modal')
  await expect(modal).toBeVisible()
  await expect(modal.locator('input[type="number"]').first()).toHaveValue('36.80')
  expect(writes).toEqual([])
})

test('Classic view keeps the old Intelligence page for one release', async ({ page }) => {
  await mockApi(page, [])
  await page.goto('/v3/watch?tab=prospects')
  await page.getByTestId('watch-tab-intelligence').click()
  await expect(page).toHaveURL(/tab=intelligence/)
  await expect(page.getByTestId('watch-tab-intelligence')).toHaveText('Classic view')
  await expect(page.getByTestId('watch-prospects')).toHaveCount(0)
})
