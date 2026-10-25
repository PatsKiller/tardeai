/** Home Protection stop clock (operator phone, 2026-10-25). Synthetic fixtures, no production calls or writes.
 *
 * Counts are labelled with the last broker stop read; a stale read shows its gap; a stop that filled while the position
 * is still in holdings reads "stop filled · awaiting holdings sync". Real taps at 412 and 390, layout at 1440.
 *
 *   npm run build && npm run preview -- --port 4173 &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/home-protection-stops.spec.ts
 */
import { test, expect, type Page } from '@playwright/test'
import W7 from './fixtures/w7Pages.fixture.json' with { type: 'json' }

test.use({ hasTouch: true })

const READ = 'Fri Mar 7 20:55 ET'
function cioPages(stale: boolean) {
  const payload: any = structuredClone((W7 as any).payload)
  payload.stops = {
    ...payload.stops, rows: [], active_count: 1, pending_count: 0, filled_count: 1, unprotected_count: 2, position_count: 3,
    nearest: { symbol: 'AAA', distance_pct: 10 }, awaiting_fill: [], awaiting_fill_count: 0,
    filled_awaiting_sync: [{ symbol: 'BBB', account_id: 'synthetic_a', account_label: 'Synthetic Account', stop_price: 41,
      captured_at: '2031-03-07T20:55:00-05:00', reason: 'stop filled · awaiting holdings sync' }],
    as_of: '2031-03-07T20:55:00-05:00', last_broker_read_at: '2031-03-07T20:55:00-05:00', last_broker_read_label: READ,
    stale, gap: stale ? { reason: `Stop data is 85 h old — counts from the last broker stop read on ${READ}.` } : null,
  }
  return payload
}

async function fixtures(page: Page, stale: boolean) {
  const writes: string[] = []
  await page.route('**/api/**', route => {
    const req = route.request()
    const p = new URL(req.url()).pathname
    if (req.method() !== 'GET') { writes.push(`${req.method()} ${p}`); return route.abort() }
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/cio/pages') return json({ ok: true, data: cioPages(stale) })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
  return writes
}

for (const { width, height } of [{ width: 412, height: 915 }, { width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
  test(`Home Protection ${width}: broker-read label, stale gap, filled awaiting sync`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const writes = await fixtures(page, true)
    await page.goto('/v3/')
    const protection = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Protection' }) })
    await expect(protection.getByTestId('home-stops-as-of')).toHaveText(`As of last broker read ${READ}`)
    await expect(protection.getByRole('status')).toHaveText(`Stop data is 85 h old — counts from the last broker stop read on ${READ}.`)
    await expect(protection.getByTestId('home-filled-awaiting-sync')).toHaveText('BBB (Synthetic Account): stop filled · awaiting holdings sync')
    await expect(protection).toContainText('Awaiting fill')
    await expect(protection).toContainText('BBB')
    const overflowX = await page.evaluate(() => document.scrollingElement!.scrollWidth - innerWidth)
    expect(overflowX).toBeLessThanOrEqual(0)
    if (width < 821) {
      const risk = protection.getByRole('link', { name: /All positions and stops/ })
      const box = (await risk.boundingBox())!
      expect(box.height).toBeGreaterThanOrEqual(44)
      await risk.tap()
      await expect(page).toHaveURL(/\/v3\/risk/)
    }
    expect(writes).toEqual([])
  })
}

test('fresh read: label without a stale gap', async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 })
  await fixtures(page, false)
  await page.goto('/v3/')
  const protection = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Protection' }) })
  await expect(protection.getByTestId('home-stops-as-of')).toBeVisible()
  await expect(protection.getByRole('status')).toHaveCount(0)
})
