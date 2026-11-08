/** LQ-20261107-1240: the RED/ORANGE banner body must not leave a dead dark panel under its first column.
 *  "Your names today" is the longest block; 1240a moves its stopped-out part into the left column under Multi-segment
 *  issuer so the columns end within 400 px of each other. Phone (412) is one column: holdings, why, reentry, names,
 *  stressed groups, in that order, no side scroll.
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

test('1440 (LQ-1240a): stopped-out names sit in the LEFT column; column heights differ by < 400 px', async ({ page }) => {
  await open(page, 1440, 1000)
  const a = (await box(page, 'mr-col-holdings'))!, b = (await box(page, 'mr-col-context'))!
  expect(b.x).toBeGreaterThan(a.x + a.width - 1) // two columns on desktop
  const names = page.getByTestId('mr-row-names')
  if (await names.count()) {
    const n = (await names.boundingBox())!
    expect(n.x).toBeLessThan(a.x + a.width) // in the left column,
    expect(n.y).toBeGreaterThan(a.y) // below the holdings blocks
    const seg = page.getByTestId('mr-advisory-section')
    if (await seg.count()) expect(n.y).toBeGreaterThanOrEqual((await seg.boundingBox())!.y + (await seg.boundingBox())!.height - 1) // under Multi-segment issuer
  }
  // Nothing removed: the right column keeps Reentry and the stressed-groups block, the left keeps the stopped-out block.
  await expect(page.getByTestId('mr-row-stressed')).toHaveCount(1)
  expect(Math.abs((a.y + a.height) - (b.y + b.height))).toBeLessThan(400)
  await shot(page, REAL ? 'after-real-1440' : 'after-1440')
})

test('412: one column in the old order (holdings, why, reentry, names, stressed), no side scroll', async ({ page }) => {
  await open(page, 412, 915)
  const names = page.getByTestId('mr-row-names'), stressed = page.getByTestId('mr-row-stressed')
  const why = page.getByTestId('mr-why-section'), seg = page.getByTestId('mr-advisory-section')
  if (await names.count()) {
    const n = (await names.boundingBox())!
    if (await why.count()) expect(n.y).toBeGreaterThan((await why.boundingBox())!.y) // names come after why/reentry on a phone
    if (await seg.count()) expect(n.y).toBeGreaterThan((await seg.boundingBox())!.y)
    if (await stressed.count() && (await stressed.boundingBox())) expect((await stressed.boundingBox())!.y).toBeGreaterThan(n.y)
    expect(Math.abs(n.x - (await box(page, 'mr-actionable-body'))!.x)).toBeLessThan(2) // one column
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy()
  await shot(page, REAL ? 'after-real-412' : 'after-412')
})
