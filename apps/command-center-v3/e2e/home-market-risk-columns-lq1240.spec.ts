/** LQ-20261107-1240: the RED/ORANGE banner body must not leave a dead dark panel under its first column.
 *  "Your names today" is the longest block; it sits in its own full-width row under both columns, so neither column
 *  ends far above the other. Phone (412) is one column: holdings, context, names, in that order, no side scroll.
 *  Synthetic fixtures; LQ1240_PROJECTION_JSON + LQ1240_PNG_DIR render a real projection for local review only. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
import { marketRiskRoutes } from './fixtures/marketRisk.fixture'

const REAL = process.env.LQ1240_PROJECTION_JSON || ''
const PNG = process.env.LQ1240_PNG_DIR || ''

async function open(page: Page, width: number, height: number) {
  await page.setViewportSize({ width, height })
  if (REAL) process.env.V005_PROJECTION_JSON = REAL
  await homeFixtures(page)
  await marketRiskRoutes(page, REAL ? 'v005_file' : 'v006_orange', [])
  await page.goto('/v3/')
  await expect(page.getByTestId('home-market-risk-banner')).toBeVisible()
  const more = page.getByTestId('home-market-risk-banner-details')
  if ((await more.textContent())?.includes('Details')) await more.click()
  await expect(page.getByTestId('mr-actionable-body')).toBeVisible()
}
const box = (page: Page, id: string) => page.getByTestId(id).boundingBox()
// The page scrolls inside main.app-main, so a full-page capture is only the viewport: shoot the banner element.
const shot = async (page: Page, name: string) => { if (PNG) await page.getByTestId('home-market-risk-banner').screenshot({ path: `${PNG}/${name}.png` }) }

test('1440: names row spans both columns; columns are side by side; no dead panel', async ({ page }) => {
  await open(page, 1440, 1000)
  const body = (await box(page, 'mr-actionable-body'))!, a = (await box(page, 'mr-col-holdings'))!, b = (await box(page, 'mr-col-context'))!
  expect(b.x).toBeGreaterThan(a.x + a.width - 1) // two columns on desktop
  const names = page.getByTestId('mr-row-names')
  if (await names.count()) {
    const n = (await names.boundingBox())!
    expect(n.width).toBeGreaterThan(body.width - 2) // full width
    expect(n.y).toBeGreaterThanOrEqual(Math.max(a.y + a.height, b.y + b.height) - 1) // under both columns
  }
  // Neither column may end more than 700 px above the other (the live defect was ~1500 px of empty red).
  expect(Math.abs((a.y + a.height) - (b.y + b.height))).toBeLessThan(700)
  await shot(page, REAL ? 'after-real-1440' : 'after-1440')
})

test('412: one column in the old order, no side scroll', async ({ page }) => {
  await open(page, 412, 915)
  const a = (await box(page, 'mr-col-holdings'))!, b = (await box(page, 'mr-col-context'))!
  expect(Math.abs(a.x - b.x)).toBeLessThan(2)
  expect(b.y).toBeGreaterThan(a.y)
  const names = page.getByTestId('mr-row-names')
  if (await names.count()) expect((await names.boundingBox())!.y).toBeGreaterThan(b.y)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
  await shot(page, REAL ? 'after-real-412' : 'after-412')
})
