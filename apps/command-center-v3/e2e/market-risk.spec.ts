/** Market risk on Home and the Risk page — design home/v002 and risk/v002 (DSN-20261031-market-risk-ui).
 *  Synthetic fixtures only; GETs are fulfilled, the one POST (Acknowledge) is captured and answered with the server's
 *  honest refusal. Phone first: 390 and 412 with a touch context, then 1440. */
import { test, expect, devices } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
import { marketRiskRoutes } from './fixtures/marketRisk.fixture'

test.use({ ...devices['Pixel 7'], hasTouch: true })

for (const width of [390, 412]) {
  test(`Home ${width}: RED episode shows the banner above the header, five contributors, Acknowledge records the server's answer`, async ({ page }) => {
    await page.setViewportSize({ width, height: 915 })
    const writes: string[] = []
    await homeFixtures(page)
    await marketRiskRoutes(page, 'red', writes)
    await page.goto('/v3/')
    const banner = page.getByTestId('home-market-risk-banner')
    await expect(banner).toBeVisible()
    await expect(page.getByTestId('home-market-risk-tier')).toHaveText('RED')
    await expect(page.getByTestId('home-market-risk-contributor')).toHaveCount(5)
    await expect(page.getByTestId('home-market-risk-value')).toHaveText('RED 83')
    // the banner sits above the header facts (design §2) and nothing on the page scrolls sideways
    const bannerBox = await banner.boundingBox(), header = await page.getByTestId('home-header').boundingBox()
    expect(bannerBox!.y).toBeLessThan(header!.y)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
    const ack = page.getByTestId('home-market-risk-ack')
    const box = await ack.boundingBox(); expect(box!.height).toBeGreaterThanOrEqual(44)
    await ack.tap()
    await expect(page.getByTestId('home-market-risk-ack-note')).toContainText('Not recorded: acknowledgment store not built yet')
    expect(writes.some(w => w.startsWith('POST /api/v2/market-risk/ack') && w.includes('EP-FIXTURE-1'))).toBeTruthy()
    // the old regime text lives on in the Market-in-one-look card
    await expect(page.getByTestId('home-market')).toBeVisible()
    await expect(page.getByTestId('home-market-risk-compact')).toContainText('RED')
  })
}

test('Home 390: GREEN shows the fact only — no banner', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 915 })
  await homeFixtures(page)
  await marketRiskRoutes(page, 'green')
  await page.goto('/v3/')
  await expect(page.getByTestId('home-market-risk-value')).toHaveText('GREEN 18')
  await expect(page.getByTestId('home-market-risk-banner')).toHaveCount(0)
})

test('Home 390: engine not live reads NOT EVALUATED and names the only live source', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 915 })
  await homeFixtures(page)
  await marketRiskRoutes(page, 'not_evaluated')
  await page.goto('/v3/')
  await expect(page.getByTestId('home-market-risk-value')).toHaveText('NOT EVALUATED')
  await expect(page.getByTestId('home-market-risk-banner')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-compact')).toContainText('not yet evaluated')
})

test('Home 1440: the same data laid out wider', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 2000 })
  await homeFixtures(page)
  await marketRiskRoutes(page, 'red')
  await page.goto('/v3/')
  await expect(page.getByTestId('home-market-risk-banner')).toBeVisible()
  await expect(page.getByTestId('home-market-risk-contributor')).toHaveCount(5)
})

for (const width of [390, 1440]) {
  test(`Risk ${width}: the Market risk tab replaces Regime and keeps the legacy panel last`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 2200 : 915 })
    await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { positions: { rows: [] }, stops: {}, regime: { label: 'high_volatility', vix: 19.4, as_of: '2031-03-10T14:05:00Z' } } }) }))
    await marketRiskRoutes(page, 'red')
    await page.goto('/v3/risk?tab=market-risk')
    await expect(page.getByRole('tab', { name: 'Market risk' }).or(page.getByText('Market risk', { exact: true }).first())).toBeVisible()
    await expect(page.getByTestId('risk-market-risk-tier')).toHaveText('RED')
    await expect(page.getByTestId('risk-market-risk-category')).toHaveCount(9)
    await expect(page.getByTestId('risk-market-risk-budget')).toHaveCount(4)
    await expect(page.getByTestId('risk-market-risk-legacy-regime')).toBeVisible()
    await expect(page.getByText('Not classified')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
  })
}

test('Risk: the old ?tab=regime link lands on Market risk', async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 })
  await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { positions: { rows: [] }, stops: {}, regime: {} } }) }))
  await marketRiskRoutes(page, 'not_evaluated')
  await page.goto('/v3/risk?tab=regime')
  await expect(page.getByTestId('risk-market-risk-tier')).toHaveText('NOT EVALUATED')
})
