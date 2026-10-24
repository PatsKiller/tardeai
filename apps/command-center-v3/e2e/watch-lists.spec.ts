/** Watch IA (operator 2026-10-23): My Watchlist is the default tab, System Suggests, Full universe with position facts
 *  and filters. Every API request is fulfilled locally from the captured fixture; any write is recorded and checked. */
import { expect, test, type Page } from '@playwright/test'
import { WATCH_LISTS_FIXTURE as FIX } from '../src/fixtures/watchLists.fixture'

async function mockApi(page: Page, writes: string[], seen: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    seen.push(`${url.pathname}${url.search}`)
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v3/data-broker/watch-curation' ? FIX.curation
      : url.pathname === '/api/v3/data-broker/watch-universe' ? { ...FIX.universe, position_filters: FIX.curation.my_watchlist.position_filters }
        : url.pathname === '/api/v3/watch/commands/suggest-dismiss' ? { ok: true, event_type: 'watch_suggest_dismissed' }
          : url.pathname === '/api/v2/watch/directives' ? { ok: true, directive_id: 9999, reused: false }
            : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('My Watchlist is the default: every operator name, starred first, never capped', async ({ page }) => {
  const writes: string[] = []; const seen: string[] = []
  await mockApi(page, writes, seen)
  await page.goto('/v3/watch')
  await expect(page).toHaveURL(/tab=my-watchlist/)
  await expect(page.getByTestId('watch-my-list')).toBeVisible({ timeout: 60_000 })
  const rows = page.getByTestId('mine-row')
  await expect(rows).toHaveCount(FIX.curation.my_watchlist.rows.length)
  await expect(page.getByTestId('mine-kind-starred')).toContainText('12')
  await expect(page.getByTestId('watch-how')).toContainText('Proposals')
  expect(writes).toEqual([])
})

test('System Suggests: top of the Full universe ranking; Add (mine command) and Dismiss are the only writes', async ({ page }) => {
  const writes: string[] = []; const seen: string[] = []
  await mockApi(page, writes, seen)
  await page.goto('/v3/watch?tab=suggests')
  await expect(page.getByTestId('watch-suggests')).toBeVisible({ timeout: 60_000 })
  const rows = page.getByTestId('suggest-row')
  await expect(rows).toHaveCount(FIX.curation.suggests.rows.length)
  await rows.first().getByTestId('suggest-add').click()
  page.once('dialog', d => d.accept('not for me'))
  await rows.nth(1).getByTestId('suggest-dismiss').click()
  await expect.poll(() => writes).toEqual(['POST /api/v3/watch/commands/mine', 'POST /api/v3/watch/commands/suggest-dismiss'])
})

test('Full universe: NAVN is Re-entry / formerly held with its last trade; filters go to the server via the URL', async ({ page }) => {
  const writes: string[] = []; const seen: string[] = []
  await mockApi(page, writes, seen)
  await page.goto('/v3/watch?tab=opportunities&preset=reentry')
  const navn = page.locator('[data-opportunity-row="NAVN"]')
  await expect(navn).toBeVisible({ timeout: 60_000 })
  await expect(navn).toContainText('Re-Entry')
  await expect(navn).not.toContainText('Add-On')
  await expect(navn).toContainText('+1.48% · +$189.73')
  await navn.click()
  await expect(page.locator('[data-opportunity-detail="NAVN"]')).toContainText('25.853 / 25.1 / 26.02')
  await page.locator('[data-filter="position"][data-opt="formerly_held"]').click()
  await expect(page).toHaveURL(/position=formerly_held/)
  await expect.poll(() => seen.some(u => u.startsWith('/api/v3/data-broker/watch-universe') && u.includes('position=formerly_held'))).toBe(true)
  expect(writes).toEqual([])
})
