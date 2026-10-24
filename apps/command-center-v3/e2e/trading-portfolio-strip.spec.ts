/**
 * The portfolio strip is app-shell chrome: /trading and /active-trader show the same
 * PORTFOLIO · TODAY · TRADING · REALIZED · REGIME tiles as every other page.
 *
 * Regression guard for 2026-10-23. A 10-13 change hid PORTFOLIO…REGIME behind a
 * "▸ PORTFOLIO drawer" toggle (default closed) on the trading routes only, and the
 * operator reported: "I'm missing my portfolio information on the top of the trading
 * page — it seems to work on the other pages."
 *
 * Hermetic: every API call is stubbed; the test fails on any non-GET request.
 */
import { expect, test, type Page } from '@playwright/test'

const OVERVIEW = {
  ok: true,
  portfolio_value: 123456.78,
  portfolio_aggregate: { portfolio_scope: 'ALL_ACCOUNTS' },
}

async function stub(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v2/overview' ? OVERVIEW : { ok: true }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

const DRAWER_TILES = ['PORTFOLIO', 'TODAY', 'TRADING', 'REALIZED', 'REGIME']

for (const path of ['/v3/', '/v3/trading', '/v3/active-trader']) {
  test(`desktop 1440: ${path} shows the full portfolio strip, no drawer`, async ({ page }) => {
    const writes: string[] = []
    await page.setViewportSize({ width: 1440, height: 900 })
    await stub(page, writes)
    await page.goto(path)
    const labels = page.locator('#ms-full .metric-strip-tile .ms-label')
    await expect(labels.first()).toBeVisible({ timeout: 30_000 })
    const text = (await labels.allTextContents()).map(t => t.trim())
    for (const want of DRAWER_TILES) {
      expect(text.some(t => t.startsWith(want)), `${want} tile on ${path}`).toBeTruthy()
    }
    await expect(page.getByTestId('metric-strip-trading-drawer-toggle')).toHaveCount(0)
    expect(writes).toEqual([])
  })
}

test('phone 412: /trading compact line shows PORT and TODAY; expand shows the strip', async ({ page }) => {
  const writes: string[] = []
  await page.setViewportSize({ width: 412, height: 915 })
  await stub(page, writes)
  await page.goto('/v3/trading')
  const compact = page.getByTestId('ms-compact')
  await expect(compact).toBeVisible({ timeout: 30_000 })
  await expect(compact).toContainText('PORT')
  await expect(compact).toContainText('TODAY')
  await page.locator('.ms-compact__toggle').click()
  await expect(page.locator('#ms-full .metric-strip-tile .ms-label', { hasText: 'PORTFOLIO' })).toBeVisible()
  await expect(page.getByTestId('metric-strip-trading-drawer-toggle')).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  expect(overflow).toBeFalsy()
  expect(writes).toEqual([])
})
