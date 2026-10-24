/** Every Watch tab at desktop (1440) and phone (412) width, on captured fixtures only (operator 2026-10-23: "Playwright
 *  every one of those. Pages on the watch list."). No request leaves the browser: every /api call is fulfilled here,
 *  and any unexpected write fails the test. Screenshots go to $WATCH_SHOTS_DIR when set. */
import { expect, test, type Page } from '@playwright/test'
import { WATCH_LISTS_FIXTURE as FIX } from '../src/fixtures/watchLists.fixture'
import { FIXTURE as PROS } from '../src/fixtures/watchProspects.fixture'

const SHOTS = process.env.WATCH_SHOTS_DIR || ''
const WIDTHS = [1440, 412] as const
const SEARCH = { ok: true, results: [
  { symbol: 'NVDA', name: 'NVIDIA CORP', identity_status: 'CONFIRMED', on_my_list: false, match: 'name' },
  { symbol: 'NVDQ', name: 'T REX 2X INVERSE NVIDIA DAILY ETF', identity_status: 'CONFIRMED', on_my_list: false, match: 'name' },
] }

async function mock(page: Page, writes: { path: string; body: any }[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push({ path: url.pathname, body: req.postDataJSON?.() ?? null })
    const p = url.pathname
    const body = p === '/api/v3/data-broker/watch-curation' ? FIX.curation
      : p === '/api/v3/data-broker/watch-universe' ? { ...FIX.universe, position_filters: FIX.curation.my_watchlist.position_filters }
        : p === '/api/v3/data-broker/watch-prospects' ? { ...PROS.prospects, position_filters: FIX.curation.my_watchlist.position_filters, position_facets: FIX.universe.position_facets }
          : p === '/api/v3/data-broker/watch-symbol-search' ? SEARCH
            : p === '/api/v2/watch/alerts/list' ? PROS.alerts
              : p === '/api/v3/watch/commands/mine' ? { ok: true, action: req.postDataJSON()?.action, symbol: req.postDataJSON()?.symbol }
                : p === '/api/v3/watch/commands/suggest-dismiss' ? { ok: true }
                  : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}
async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false })
}
async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
}

for (const w of WIDTHS) {
  test.describe(`Watch at ${w}px`, () => {
    test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: w, height: 900 }) })

    test('My Watchlist: add box on top, stars, remove, empty hint, filters, detail', async ({ page }) => {
      const writes: { path: string; body: any }[] = []
      await mock(page, writes)
      await page.goto('/v3/watch')
      await expect(page).toHaveURL(/tab=my-watchlist/)
      const box = page.getByTestId('mine-add-box')
      await expect(box).toBeVisible({ timeout: 60_000 })
      await expect(box).toHaveAttribute('title', /Watching only/)
      await expect(page.getByTestId('mine-row')).toHaveCount(FIX.curation.my_watchlist.rows.length)
      await expect(page.getByTestId('mine-row').first().getByTestId('mine-star')).toHaveAttribute('data-on', '1')
      await noSideScroll(page)
      await shot(page, `my-watchlist_${w}`)
      // typeahead → add with a note
      await page.getByTestId('mine-add-input').fill('nvid')
      await expect(page.getByTestId('mine-add-hit')).toHaveCount(2)
      await shot(page, `my-watchlist-typeahead_${w}`)
      await page.getByTestId('mine-add-note').fill('AI capex')
      await page.getByTestId('mine-add-hit').first().click()
      // star off = remove; explicit Remove with a reason
      await page.getByTestId('mine-row').nth(1).getByTestId('mine-star').click()
      page.once('dialog', d => d.accept('done with it'))
      await page.getByTestId('mine-row').nth(2).getByTestId('mine-remove').click()
      await expect.poll(() => writes.map(x => `${x.path}:${x.body?.action}`)).toEqual([
        '/api/v3/watch/commands/mine:add', '/api/v3/watch/commands/mine:remove', '/api/v3/watch/commands/mine:remove'])
      expect(writes[0].body).toMatchObject({ symbol: 'NVDA', note: 'AI capex' })
      expect(writes[2].body).toMatchObject({ note: 'done with it' })
      // detail panel
      await page.getByTestId('mine-row').first().locator('button[aria-pressed]').nth(1).click()
      await expect(page.getByTestId('watch-detail')).toBeVisible()
      await shot(page, `my-watchlist-detail_${w}`)
      // filters in the URL; empty-state hint when nothing matches
      await page.getByRole('button', { name: /Position filters/ }).first().click()
      await page.locator('[data-filter="position"][data-opt="held"]').first().click()
      await expect(page).toHaveURL(/position=held/)
      await page.getByTestId('mine-kind-personal_watchlist').click()
      await expect(page.getByTestId('mine-empty')).toContainText('Search a ticker above, or ★ any row in Suggests/Full universe.')
      await shot(page, `my-watchlist-filtered-empty_${w}`)
      expect(writes.every(x => x.path === '/api/v3/watch/commands/mine')).toBe(true)
    })

    test('System Suggests: rows, star, add, dismiss', async ({ page }) => {
      const writes: { path: string; body: any }[] = []
      await mock(page, writes)
      await page.goto('/v3/watch?tab=suggests')
      const rows = page.getByTestId('suggest-row')
      await expect(rows).toHaveCount(FIX.curation.suggests.rows.length, { timeout: 60_000 })
      await noSideScroll(page)
      await shot(page, `suggests_${w}`)
      await rows.first().getByTestId('mine-star').click()
      await rows.nth(1).getByTestId('suggest-add').click()
      page.once('dialog', d => d.accept('not my style'))
      await rows.nth(2).getByTestId('suggest-dismiss').click()
      await expect.poll(() => writes.map(x => x.path)).toEqual([
        '/api/v3/watch/commands/mine', '/api/v3/watch/commands/mine', '/api/v3/watch/commands/suggest-dismiss'])
      expect(writes.slice(0, 2).every(x => x.body.action === 'add')).toBe(true)
    })

    test('Prospects: lanes, stars, position filters, detail', async ({ page }) => {
      const writes: { path: string; body: any }[] = []
      await mock(page, writes)
      await page.goto('/v3/watch?tab=prospects')
      await expect(page.getByTestId('watch-prospects')).toBeVisible({ timeout: 60_000 })
      await expect(page.getByTestId('watch-row').first().getByTestId('mine-star')).toBeVisible()
      await expect(page.getByTestId('prospects-position-filters')).toBeVisible()
      await noSideScroll(page)
      await shot(page, `prospects_${w}`)
      await page.getByTestId('watch-row').first().getByTestId('mine-star').click()
      await page.getByTestId('watch-lane-manage').click()
      await page.locator('[data-testid="watch-row"]').first().locator('button[aria-pressed]').nth(1).click()
      await expect(page.getByTestId('watch-detail')).toBeVisible()
      await shot(page, `prospects-detail_${w}`)
      await expect.poll(() => writes.length).toBe(1)
    })

    test('Full universe: stars, NAVN formerly held, row detail, filters, Re-entry preset', async ({ page }) => {
      const writes: { path: string; body: any }[] = []
      await mock(page, writes)
      await page.goto('/v3/watch?tab=opportunities&preset=reentry')
      const navn = page.locator('[data-opportunity-row="NAVN"]')
      await expect(navn).toBeVisible({ timeout: 60_000 })
      await expect(navn).toContainText('Re-Entry')
      await expect(navn).not.toContainText('Add-On')
      await expect(navn.getByTestId('mine-star')).toBeVisible()
      await noSideScroll(page)
      await shot(page, `full-universe_${w}`)
      await navn.click()
      await expect(page.locator('[data-opportunity-detail="NAVN"]')).toContainText('25.853 / 25.1 / 26.02')
      await shot(page, `full-universe-detail_${w}`)
      await navn.getByTestId('mine-star').click()
      await page.locator('[data-filter="position"][data-opt="formerly_held"]').click()
      await expect(page).toHaveURL(/position=formerly_held/)
      await page.getByRole('button', { name: /Position filters/ }).click()
      await page.locator('[data-filter="result"][data-opt="won"]').click()
      await expect(page).toHaveURL(/result=won/)
      await shot(page, `full-universe-filters_${w}`)
      await expect.poll(() => writes.map(x => `${x.path}:${x.body?.action}`)).toEqual(['/api/v3/watch/commands/mine:add'])
    })
  })
}
