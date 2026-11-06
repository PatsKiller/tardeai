/** Market-session-aware freshness (live audit 2026-10-25, a Sunday). Synthetic fixtures; every non-GET aborted.
 *
 * Friday's close is the latest data that can exist on a weekend: the CIO market view must say
 * "Market closed · last close Fri 4:00 PM ET · next update Mon", never "refresh overdue". On a weekday during
 * regular hours a Friday view is overdue (wall-clock rule unchanged). The helper itself is pinned by
 * src/lib/marketSessionFreshness.test.ts and tests/test_session_freshness_20261025.py (one shared case table).
 *
 * NOTE for PR #2144 (HomeBoard14 replaces W7HomePanels on Home): it must render the clock through
 * marketViewNote and keep data-testid="w7-market-view-clock" (or update this spec) when the two meet.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/session-freshness.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'
import W7 from './fixtures/w7Pages.fixture.json' with { type: 'json' }

test.use({ hasTouch: true })

const SUNDAY = '2026-10-25T20:00:00Z'      // Sun 4:00 PM ET
const MONDAY_RTH = '2026-10-26T15:00:00Z'  // Mon 11:00 AM ET
const FRIDAY_CLOSE = '2026-10-23T20:05:00+00:00'
const PHRASE = 'Market closed · last close Fri 4:00 PM ET · next update Mon'

async function fixtures(page: Page, clock: string) {
  const writes: string[] = []
  await page.clock.install({ time: new Date(clock) })
  await page.route('**/api/**', route => {
    const req = route.request()
    const p = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${p}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/cio/pages') {
      const payload: any = structuredClone((W7 as any).payload)
      // The backend still ages this in wall-clock hours (stale: true); the display must not call it overdue.
      payload.regime = { ...payload.regime, as_of: FRIDAY_CLOSE, stale: true }
      return json({ ok: true, data: payload })
    }
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`${width}: Sunday — CIO market view says market closed, not refresh overdue`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page, SUNDAY)
    await page.goto('/v3/')
    const clock = page.getByTestId('w7-market-view-clock')
    await expect(clock).toContainText(PHRASE)
    await expect(clock).not.toContainText('overdue')
    expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)).toBeLessThanOrEqual(0)
    if (width < 821) {
      // Phone tap: the protection link next to the market view is ≥44 px and navigates.
      const link = page.getByRole('link', { name: /All positions and stops/ })
      const box = (await link.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      await link.tap()
      await expect(page).toHaveURL(/\/v3\/risk/)
    }
    expect(writes).toEqual([])
  })
}

test('Monday regular hours: a Friday market view is overdue', async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 })
  const writes = await fixtures(page, MONDAY_RTH)
  await page.goto('/v3/')
  const clock = page.getByTestId('w7-market-view-clock')
  await expect(clock).toContainText('refresh overdue')
  await expect(clock).not.toContainText('Market closed')
  expect(writes).toEqual([])
})
