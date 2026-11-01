/** Design home/v005: the actionable market-risk card on Home (YELLOW summary card and the ORANGE/RED banner).
 *  Synthetic fixtures only; every GET is fulfilled and any write is captured (there must be none from the card).
 *  Phone first (412, 390, touch), then 1440. V005_PNG_DIR saves review renders; V005_PROJECTION_JSON + the
 *  `local real render` test render a projection from disk (local review only, skipped unless set). */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
import { marketRiskRoutes } from './fixtures/marketRisk.fixture'

test.use({ hasTouch: true })

const PNG = process.env.V005_PNG_DIR || ''
async function shot(page: Page, name: string, fullPage = true) {
  if (PNG) await page.screenshot({ path: `${PNG}/${name}.png`, fullPage })
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)
async function minTap(page: Page, root: string) {
  return page.evaluate(sel => {
    const r = document.querySelector(sel)
    if (!r) return null
    const els = [...r.querySelectorAll('a, button')].filter(e => (e as HTMLElement).offsetParent !== null)
    return els.length ? Math.min(...els.map(e => e.getBoundingClientRect().height)) : null
  }, root)
}

async function open(page: Page, variant: Parameters<typeof marketRiskRoutes>[1], width: number, height = 915) {
  await page.setViewportSize({ width, height })
  const writes: string[] = []
  await homeFixtures(page)
  await marketRiskRoutes(page, variant, writes)
  await page.goto('/v3/')
  return writes
}

for (const width of [412, 390]) {
  test(`v005 ${width}: collapsed card shows the verdict, the exposure in dollars and the top review item`, async ({ page }) => {
    const writes = await open(page, 'v005_yellow', width, width === 412 ? 915 : 844)
    const card = page.getByTestId('home-market-risk-summary')
    await expect(card).toHaveAttribute('data-open', 'false')
    await expect(page.getByTestId('mr-verdict')).toHaveText('Sector selloff — Technology / Semis / AI basket. Not market-wide: 8 of 9 sectors holding.')
    await expect(page.getByTestId('mr-exposure')).toContainText('Your exposure: $12,400 (2.5% of book · 4.1% of invested) in stressed groups — mostly DEMOF\'s 8% technology. Cash 40%.')
    const top = page.getByTestId('mr-top-review')
    await expect(top).toBeVisible()
    await expect(top).toContainText('DEMOA · Demo Roth — stop 3.5% below last · $40,000')
    expect((await top.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await expect(page.getByTestId('mr-actionable-body')).toBeHidden()
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `v005-${width}-yellow-collapsed`, false)
    await page.getByTestId('home-market-risk-summary-toggle').tap()
    await expect(page.getByTestId('mr-actionable-body')).toBeVisible()
    // sector table: stressed-and-held first, UNKNOWN held flagged, no "% book" column on phone
    const rows = page.getByTestId('mr-sector-row')
    await expect(rows.first()).toHaveAttribute('data-key', 'tech')
    await expect(page.locator('[data-testid=mr-sector-row][data-key=comm]')).toContainText('not measured')
    // re-entry: the re-bought account is a holding; the wash sale has occurred (no forward warning)
    const rr = page.getByTestId('mr-reentry-row')
    await expect(rr).toHaveCount(2)
    await expect(rr.nth(1)).toContainText('still held in Demo Taxable')
    await expect(page.getByTestId('mr-reentry-wash')).toHaveAttribute('data-tone', 'info')
    await expect(page.getByTestId('mr-reentry-wash')).toContainText('wash sale occurred, $1,050 loss deferred into the new basis')
    await expect(rr.first()).toContainText('Stage 1 (early setup): 1 of 5')
    await expect(rr.first()).toContainText('Invalidates below $33.97')
    await expect(page.getByTestId('mr-reentry-more')).toContainText('+1 older exit')
    await expect(page.getByTestId('mr-review-item')).toHaveCount(5)
    await expect(page.getByTestId('mr-budget-row').first()).toContainText('Demo Taxable unprotected 46.6% ($21,000) vs 10% limit')
    await expect(page.getByTestId('mr-budget-row').first()).toContainText('DEMOB $20,000')
    expect(await minTap(page, '[data-testid=home-market-risk-summary]')).toBeGreaterThanOrEqual(44)
    expect(await noSideScroll(page)).toBeTruthy()
    // advisory only: no order, size or stop controls and no writes
    await expect(card.getByRole('button', { name: /\b(buy|sell|order|size|place)\b|set stop/i })).toHaveCount(0)
    expect(writes).toEqual([])
    await shot(page, `v005-${width}-yellow-expanded`)
  })

  test(`v005 ${width}: ORANGE banner keeps Acknowledge and adds the verdict, exposure and top review`, async ({ page }) => {
    await open(page, 'v005_orange', width, width === 412 ? 915 : 844)
    const banner = page.getByTestId('home-market-risk-banner')
    await expect(banner).toBeVisible()
    await expect(page.getByTestId('home-market-risk-ack')).toBeVisible()
    await expect(page.getByTestId('mr-verdict')).toContainText('Sector selloff')
    await expect(page.getByTestId('mr-top-review')).toBeVisible()
    await expect(page.getByTestId('home-market-risk-banner-details')).toHaveAttribute('aria-expanded', 'false')
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `v005-${width}-orange-collapsed`, false)
    await page.getByTestId('home-market-risk-banner-details').tap()
    await expect(page.getByTestId('mr-actionable-body')).toBeVisible()
    expect(await noSideScroll(page)).toBeTruthy()
    expect(await minTap(page, '[data-testid=home-market-risk-banner]')).toBeGreaterThanOrEqual(44)
  })
}

test('v005 1440: expanded by default, two columns, every section present', async ({ page }) => {
  const writes = await open(page, 'v005_yellow', 1440, 1000)
  await expect(page.getByTestId('home-market-risk-summary')).toHaveAttribute('data-open', 'true')
  for (const id of ['mr-sectors', 'mr-reentry', 'mr-positions', 'mr-review', 'mr-budgets', 'mr-why']) await expect(page.getByTestId(id)).toBeVisible()
  await expect(page.getByTestId('mr-position-row').first()).toContainText('$12,000')
  await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(2)
  const s = (await page.getByTestId('mr-sectors').boundingBox())!, p = (await page.getByTestId('mr-positions').boundingBox())!
  expect(p.x).toBeGreaterThan(s.x + 300)  // right column
  expect(await noSideScroll(page)).toBeTruthy()
  expect(await minTap(page, '[data-testid=home-market-risk-summary]')).toBeGreaterThanOrEqual(44)
  expect(writes).toEqual([])
  await shot(page, 'v005-1440-yellow-expanded')
})

test('v005 1440: ORANGE banner open by default with the sections', async ({ page }) => {
  await open(page, 'v005_orange', 1440, 1000)
  await expect(page.getByTestId('mr-actionable-body')).toBeVisible()
  await expect(page.getByTestId('home-market-risk-ack')).toBeVisible()
  await shot(page, 'v005-1440-orange-expanded')
})

test('v005: a book total that does not reconcile hides the dollars', async ({ page }) => {
  await open(page, 'v005_unreconciled', 1440, 1000)
  await expect(page.getByTestId('mr-exposure')).toHaveText('Your exposure: book total does not reconcile to All accounts — dollars hidden.')
})

test('v005: the v004 card still renders when the projection has no v005 data', async ({ page }) => {
  await open(page, 'yellow_live', 1440, 1000)
  await expect(page.getByTestId('home-market-risk-summary')).toBeVisible()
  await expect(page.getByTestId('mr-verdict')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-summary-book')).toBeVisible()
})

// LOCAL review render of a real projection (never in CI: skipped unless V005_PROJECTION_JSON is set)
for (const width of [1440, 412, 390]) {
  test(`local real render ${width}`, async ({ page }) => {
    test.skip(!process.env.V005_PROJECTION_JSON, 'local review only')
    await open(page, 'v005_file', width, width === 1440 ? 1000 : width === 412 ? 915 : 844)
    await expect(page.getByTestId('home-market-risk-summary').or(page.getByTestId('home-market-risk-banner'))).toBeVisible()
    await shot(page, `real-${width}-collapsed-or-default`, width === 1440)
    if (width !== 1440) {
      await page.getByTestId('home-market-risk-summary-toggle').tap()
      await shot(page, `real-${width}-expanded`)
    }
    expect(await noSideScroll(page)).toBeTruthy()
  })
}
