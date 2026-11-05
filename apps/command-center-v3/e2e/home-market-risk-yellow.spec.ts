/** Design home/v004: the YELLOW market-risk summary card on Home (builds on home/v002).
 *  Synthetic fixtures only; every GET is fulfilled and any write is captured (there must be none at YELLOW).
 *  Phone first: 412 and 390 with touch, then 1440. Set V004_PNG_DIR to also save the review renders. */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
import { marketRiskRoutes } from './fixtures/marketRisk.fixture'

test.use({ hasTouch: true })

const PNG = process.env.V004_PNG_DIR || ''
async function shot(page: Page, name: string, fullPage = false) {
  if (PNG) await page.screenshot({ path: `${PNG}/${name}.png`, fullPage })
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

async function open(page: Page, variant: Parameters<typeof marketRiskRoutes>[1], width: number, height = 915) {
  await page.setViewportSize({ width, height })
  const writes: string[] = []
  await homeFixtures(page)
  await marketRiskRoutes(page, variant, writes)
  await page.goto('/v3/')
  return writes
}

for (const width of [412, 390]) {
  test(`Home ${width}: shadow YELLOW card is collapsed by default, Do now stays on the first screen, Details opens it`, async ({ page }) => {
    const writes = await open(page, 'yellow_shadow', width)
    const card = page.getByTestId('home-market-risk-summary')
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute('data-open', 'false')
    await expect(page.getByTestId('home-market-risk-banner')).toHaveCount(0)
    // above the header, never sticky
    const cardBox = (await card.boundingBox())!, header = (await page.getByTestId('home-header').boundingBox())!
    expect(cardBox.y).toBeLessThan(header.y)
    expect(await card.evaluate(el => getComputedStyle(el).position)).not.toMatch(/sticky|fixed/)
    // collapsed: pill, title, SHADOW label, one line with points, N of 9, evaluated time
    await expect(page.getByTestId('home-market-risk-summary-tier')).toHaveText('YELLOW')
    await expect(card).toContainText('Market risk 60/100')
    await expect(page.getByTestId('home-market-risk-summary-shadow')).toContainText('SHADOW')
    await expect(page.getByTestId('home-market-risk-summary-line')).toContainText('Options flow +34.4 · Technical +25.3 · 2 of 9 confirm · evaluated')
    await expect(page.getByTestId('home-market-risk-summary-body')).toBeHidden()
    const toggle = page.getByTestId('home-market-risk-summary-toggle')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect((await toggle.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    // no Acknowledge at YELLOW
    await expect(page.getByTestId('home-market-risk-ack')).toHaveCount(0)
    await expect(card.getByRole('button', { name: /acknowledge/i })).toHaveCount(0)
    // Do now starts inside the first screen
    const doNow = page.getByTestId('do-now')
    if (await doNow.count()) expect((await doNow.boundingBox())!.y).toBeLessThan(915)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `home-${width}-yellow-shadow-collapsed`)
    // Details ▾ opens it
    await toggle.tap()
    await expect(card).toHaveAttribute('data-open', 'true')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(2)
    await expect(page.getByTestId('home-market-risk-summary-contributor').first()).toContainText('+34.4')
    // the points sit at the right of their line on phone (never pushed onto a row of their own)
    const pts = (await page.getByTestId('home-market-risk-summary-contributor').first().locator(':scope > span').last().boundingBox())!
    const nm = (await page.getByTestId('home-market-risk-summary-contributor').first().locator(':scope > span').first().boundingBox())!
    expect(pts.x).toBeGreaterThan(nm.x + nm.width - 1)
    expect(pts.y).toBeLessThan(nm.y + 30)
    // "N of 9" once: in the evaluated line on phone, not repeated in the summary row
    await expect(page.getByTestId('home-market-risk-summary-confirm-wide')).toBeHidden()
    await expect(page.getByTestId('home-market-risk-summary-not-measured')).toContainText('Not measured: extended hours.')
    await expect(page.getByTestId('home-market-risk-summary-book')).toContainText('Vulnerability 8/100')
    await expect(page.getByTestId('home-market-risk-summary-book')).toContainText('4 budget breaches')
    await expect(page.getByTestId('home-market-risk-summary-book')).toContainText('Near a stop: DEMOA stop 4.5% below')
    await expect(page.getByTestId('home-market-risk-summary-book')).toContainText('DEMOB, DEMOC, DEMOD +1 more')
    await expect(page.getByTestId('home-market-risk-summary-deescalates')).toContainText('De-escalates if')
    await expect(page.getByTestId('home-market-risk-summary-footer')).toHaveText('YELLOW never pages and has nothing to acknowledge. Shadow mode: no alert was sent for this tier.')
    for (const id of ['home-market-risk-summary-open-risk', 'home-market-risk-summary-review-stops']) {
      const b = (await page.getByTestId(id).boundingBox())!
      expect(b.height).toBeGreaterThanOrEqual(44)
    }
    await expect(page.getByTestId('home-market-risk-summary-open-risk')).toHaveAttribute('href', '/v3/risk?tab=market-risk')
    await expect(page.getByTestId('home-market-risk-summary-review-stops')).toHaveAttribute('href', '/v3/risk?tab=exposure')
    await expect(page.getByTestId('home-market-risk-ack')).toHaveCount(0)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `home-${width}-yellow-shadow-expanded`, true)
    expect(writes.filter(w => w.startsWith('POST'))).toHaveLength(0)
  })

  test(`Home ${width}: stale YELLOW hides the numbers`, async ({ page }) => {
    await open(page, 'yellow_stale', width)
    const card = page.getByTestId('home-market-risk-summary')
    await expect(card).toHaveAttribute('data-open', 'false')
    await expect(card).toHaveAttribute('data-stale', 'true')
    await expect(page.getByTestId('home-market-risk-summary-line')).toContainText('stale — last evaluation')
    await expect(page.getByTestId('home-market-risk-summary-line')).toContainText('Numbers hidden until the engine runs again.')
    await expect(card).not.toContainText('60/100')
    await expect(card).not.toContainText('+34.4')
    await page.getByTestId('home-market-risk-summary-toggle').tap()
    await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(0)
    await expect(page.getByTestId('home-market-risk-summary-book')).toHaveCount(0)
    await expect(page.getByTestId('home-market-risk-summary-open-risk')).toBeVisible()
    await expect(page.getByTestId('home-market-risk-summary-review-stops')).toBeVisible()
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `home-${width}-yellow-stale-expanded`)
  })
}

test('Home 1440: live YELLOW card is open by default, no SHADOW label, two links, no Acknowledge', async ({ page }) => {
  const writes = await open(page, 'yellow_live', 1440, 1100)
  const card = page.getByTestId('home-market-risk-summary')
  await expect(card).toHaveAttribute('data-open', 'true')
  await expect(page.getByTestId('home-market-risk-summary-shadow')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-summary-confirm-wide')).toHaveText('2 of 9 categories confirm')
  await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(2)
  await expect(page.getByTestId('home-market-risk-summary-book')).toBeVisible()
  await expect(page.getByTestId('home-market-risk-summary-footer')).toHaveText('YELLOW never pages and has nothing to acknowledge.')
  await expect(page.getByTestId('home-market-risk-ack')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-banner')).toHaveCount(0)
  // two columns: the book sits beside the contributors
  const c = (await page.getByTestId('home-market-risk-summary-contributor').first().boundingBox())!
  const b = (await page.getByTestId('home-market-risk-summary-book').boundingBox())!
  expect(b.x).toBeGreaterThan(c.x + c.width - 1)
  expect(await noSideScroll(page)).toBeTruthy()
  await shot(page, 'home-1440-yellow-live-expanded')
  expect(writes.filter(w => w.startsWith('POST'))).toHaveLength(0)
})

test('Home 1440: shadow YELLOW shows the SHADOW label; Less collapses it and the choice is remembered', async ({ page }) => {
  await open(page, 'yellow_shadow', 1440, 1100)
  const card = page.getByTestId('home-market-risk-summary')
  await expect(page.getByTestId('home-market-risk-summary-shadow')).toContainText('not alerting')
  await shot(page, 'home-1440-yellow-shadow-expanded')
  await page.getByTestId('home-market-risk-summary-toggle').click()
  await expect(card).toHaveAttribute('data-open', 'false')
  await page.reload()
  await expect(page.getByTestId('home-market-risk-summary')).toHaveAttribute('data-open', 'false')
  await shot(page, 'home-1440-yellow-shadow-collapsed')
})

test('Home 1440: stale YELLOW starts collapsed on desktop too', async ({ page }) => {
  await open(page, 'yellow_stale', 1440, 1100)
  await expect(page.getByTestId('home-market-risk-summary')).toHaveAttribute('data-open', 'false')
  await expect(page.getByTestId('home-market-risk-summary')).not.toContainText('60/100')
  await shot(page, 'home-1440-yellow-stale-collapsed')
})

test('Home 412: YELLOW with no contributor above 0 and no book', async ({ page }) => {
  await open(page, 'yellow_empty', 412)
  await expect(page.getByTestId('home-market-risk-summary-line')).toContainText('no category above 0 points')
  await page.getByTestId('home-market-risk-summary-toggle').tap()
  await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-summary-not-measured')).toContainText('Not measured: extended hours.')
  await expect(page.getByTestId('home-market-risk-summary-book')).toHaveCount(0)
})

test('Home 1440: no book in the API hides Your book', async ({ page }) => {
  await open(page, 'yellow_nobook', 1440, 1100)
  await expect(page.getByTestId('home-market-risk-summary-contributor')).toHaveCount(2)
  await expect(page.getByTestId('home-market-risk-summary-book')).toHaveCount(0)
})

test('Home 390: not evaluated shows no card (v002 unchanged)', async ({ page }) => {
  await open(page, 'not_evaluated', 390)
  await expect(page.getByTestId('home-market-risk-summary')).toHaveCount(0)
  await expect(page.getByTestId('home-market-risk-value')).toHaveText('NOT EVALUATED')
})

for (const variant of ['orange', 'red'] as const) {
  for (const width of [390, 1440]) {
    test(`Home ${width}: ${variant.toUpperCase()} keeps the v002 banner with Acknowledge; no YELLOW card`, async ({ page }) => {
      await open(page, variant, width, width === 1440 ? 1100 : 915)
      await expect(page.getByTestId('home-market-risk-summary')).toHaveCount(0)
      await expect(page.getByTestId('home-market-risk-banner')).toBeVisible()
      await expect(page.getByTestId('home-market-risk-tier')).toHaveText(variant.toUpperCase())
      await expect(page.getByTestId('home-market-risk-ack')).toHaveText('Acknowledge')
      await shot(page, `home-${width}-${variant}-banner-unchanged`)
    })
  }
}
