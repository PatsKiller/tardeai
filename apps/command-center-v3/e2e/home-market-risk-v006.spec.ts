/** Design home/v006: Protect / Hedge / Rotate under the verdict, the collapsed digest, tap-to-explain (i) sheets, folded
 *  groups, the RESILIENT chip and the issuer-segment section, on the YELLOW card and the ORANGE banner.
 *  Synthetic fixtures only; every GET is fulfilled and any write is captured (there must be none from the card).
 *  Phone first (412, 390, touch), then 1440. V006_PNG_DIR saves review renders; V006_PROJECTION_JSON + the
 *  `local real render` test render a projection from disk (local review only, skipped unless set). */
import { test, expect, type Page } from '@playwright/test'
import { homeFixtures } from './fixtures/homeDoNow.fixture'
import { marketRiskRoutes } from './fixtures/marketRisk.fixture'

test.use({ hasTouch: true })

const PNG = process.env.V006_PNG_DIR || ''
async function shot(page: Page, name: string, fullPage = true) {
  if (PNG) await page.screenshot({ path: `${PNG}/${name}.png`, fullPage })
}
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)
/** Smallest visible link/button height inside ``sel`` (the (i) buttons included). */
async function minTap(page: Page, sel: string) {
  return page.evaluate(s => {
    const els = [...document.querySelectorAll(`${s} a, ${s} button`)].filter(e => (e as HTMLElement).offsetParent !== null)
    return els.length ? Math.min(...els.map(e => e.getBoundingClientRect().height)) : null
  }, sel)
}

type Variant = Parameters<typeof marketRiskRoutes>[1]
/** Open the card on phone whatever the remembered choice (the open/closed choice is kept in browser storage). */
async function expand(page: Page) {
  const card = page.getByTestId('home-market-risk-summary')
  if ((await card.getAttribute('data-open')) !== 'true') await page.getByTestId('home-market-risk-summary-toggle').tap()
  await expect(card).toHaveAttribute('data-open', 'true')
}

async function open(page: Page, variant: Variant, width: number, height = 915) {
  await page.setViewportSize({ width, height })
  const writes: string[] = []
  await homeFixtures(page)
  await marketRiskRoutes(page, variant, writes)
  await page.goto('/v3/')
  return writes
}

const ACTION_WORDS = /\b(buy|sell|trim|size|sizing|shares to|place an order|set a stop)\b/i

for (const width of [412, 390]) {
  test(`v006 ${width}: collapsed digest (Protect / Hedge / Rotate), then the blocks, (i) sheet, fold and chip`, async ({ page }) => {
    const writes = await open(page, 'v006_yellow', width, width === 412 ? 915 : 844)
    const card = page.getByTestId('home-market-risk-summary')
    await expect(card).toHaveAttribute('data-open', 'false')
    const digest = page.getByTestId('mr-actions-digest')
    await expect(digest).toBeVisible()
    await expect(page.getByTestId('mr-digest-protect')).toContainText('DEMOA · Demo Roth ($40,000) — stop 2.9% below last')
    await expect(page.getByTestId('mr-digest-hedge')).toContainText('Not now — 2.5% of book in stressed groups')
    await expect(page.getByTestId('mr-digest-rotate')).toContainText('Healthcare +2.3%/+3.7%')
    for (const id of ['mr-digest-protect', 'mr-digest-hedge', 'mr-digest-rotate']) expect((await page.getByTestId(id).boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await expect(page.getByTestId('mr-digest-hedge')).toHaveAttribute('href', '/v3/defense')
    await expect(page.getByTestId('mr-digest-rotate')).toHaveAttribute('href', '/v3/rotation')
    await expect(page.getByTestId('mr-top-review')).toHaveCount(0) // replaced by the digest (SPEC moves)
    expect(await noSideScroll(page)).toBeTruthy()
    const h = (await card.boundingBox())!.height
    expect(h).toBeLessThan((width === 412 ? 915 : 844) * 0.6) // the rest of Home still starts in the first screen
    await shot(page, `v006-${width}-collapsed`, false)

    await page.getByTestId('home-market-risk-summary-toggle').tap()
    await expect(page.getByTestId('mr-actions')).toBeVisible()
    await expect(page.getByTestId('mr-actions-digest')).toHaveCount(0)
    const pi = page.getByTestId('mr-protect-item')
    await expect(pi).toHaveCount(3)
    await expect(pi.first()).toContainText('DEMOA')
    await expect(pi.first()).toContainText('(89% of account)')
    await expect(pi.first().getByTestId('mr-protect-consideration')).toHaveText('stop 2.9% below last; one stock is 89% of the account, far above the 30% sector budget; with the Demo IRA position, $70,000 in DEMOA across 2 accounts')
    await expect(pi.first().getByTestId('mr-protect-link')).toHaveText('Review stop →')
    await expect(page.getByTestId('mr-protect')).toContainText('+2 more: DEMOF · Demo IRA (8% in stressed groups) · DEMOM · Demo IRA (no stop)')
    await expect(page.getByTestId('mr-hedge-verdict')).toHaveText('NOT NOW')
    await expect(page.getByTestId('mr-hedge')).toContainText('$12,400 (2.5% of book · 4.1% of invested) is in stressed groups. The Defense desk considers a hedge when one weakening sector is ≥ 10% of invested, or 4+ sectors lag — now Technology 4.1%, 1 sector lagging.')
    await expect(page.getByTestId('mr-hedge-lane')).toContainText('Inverse lane SH · PSQ · DOG · RWM: no bearish thesis since')
    await expect(page.getByTestId('mr-rotate-row')).toHaveCount(3)
    await expect(page.getByTestId('mr-rotate-row').first()).toContainText('Healthcare')
    await expect(page.getByTestId('mr-rotate-row').first()).toContainText('desk LEADING')
    await expect(page.getByTestId('mr-opportunities-link')).toHaveAttribute('href', '/v3/watch?tab=opportunities&preset=top5')
    // "Review now" moved into Protect
    await expect(page.getByTestId('mr-review')).toHaveCount(0)
    // folded groups and the chip split
    await expect(page.locator('[data-testid=mr-sector-row][data-key=ai_basket]')).toHaveCount(0)
    await expect(page.locator('[data-testid=mr-sector-row][data-key=real_estate]')).toHaveCount(0)
    await expect(page.getByTestId('mr-sectors-folded')).toHaveText('Also stressed, you hold under $100: AI basket ($28). Not measured, you hold under $100: Real estate ($1).')
    await expect(page.locator('[data-testid=mr-sector-row][data-key=healthcare]')).toHaveAttribute('data-chip', 'RESILIENT')
    // segments: approved split with its source
    await expect(page.getByTestId('mr-segment-row')).toHaveAttribute('data-status', 'approved')
    await expect(page.getByTestId('mr-segment-row')).toContainText('weights approved, DEMO 10-Q, Notes 3 and 18')
    // advisory only
    // advisory only: the considerations, the hedge line and the rotate rows carry no action or size (the disclaimers
    // "no order, size or stop level" and "not a buy list" are the only places those words appear)
    const advisory = [...await page.getByTestId('mr-protect-consideration').allInnerTexts(), await page.getByTestId('mr-hedge').innerText(), ...await page.getByTestId('mr-rotate-row').allInnerTexts()]
    for (const t of advisory) expect(ACTION_WORDS.test(t), t).toBeFalsy()
    expect(await noSideScroll(page)).toBeTruthy()
    expect(await minTap(page, '[data-testid=home-market-risk-summary]')).toBeGreaterThanOrEqual(44)
    await shot(page, `v006-${width}-expanded`)

    // tap-to-explain: the STRESS (i) opens a bottom sheet with the glossary text; Close (≥44 px) closes it
    const stressI = page.locator('[data-testid=mr-sector-row][data-key=tech] [data-testid=mr-explain]')
    expect((await stressI.boundingBox())!.height).toBeGreaterThanOrEqual(44)
    await stressI.tap()
    const sheet = page.getByTestId('mr-explain-sheet')
    await expect(sheet).toBeVisible()
    await expect(sheet).toHaveAttribute('role', 'dialog')
    await expect(sheet).toContainText('STRESS')
    await expect(sheet).toContainText("measured against the group's own past year")
    const sb = (await sheet.boundingBox())!
    expect(Math.round(sb.y + sb.height)).toBeGreaterThanOrEqual((width === 412 ? 915 : 844) - 1) // a bottom sheet on phone
    expect(Math.round(sb.width)).toBe(width)
    expect((await page.getByTestId('mr-explain-close').boundingBox())!.height).toBeGreaterThanOrEqual(44)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `v006-${width}-explain-sheet`, false)
    await page.getByTestId('mr-explain-close').tap()
    await expect(sheet).toHaveCount(0)
    expect(writes).toEqual([])
  })
}

test('v006 1440: expanded by default, three blocks side by side, every term has an (i), Esc closes the dialog', async ({ page }) => {
  const writes = await open(page, 'v006_yellow', 1440, 1000)
  await expect(page.getByTestId('home-market-risk-summary')).toHaveAttribute('data-open', 'true')
  const boxes = await Promise.all(['mr-protect', 'mr-hedge', 'mr-rotate'].map(id => page.getByTestId(id).boundingBox()))
  expect(Math.abs(boxes[0]!.y - boxes[1]!.y)).toBeLessThan(2)
  expect(Math.abs(boxes[1]!.y - boxes[2]!.y)).toBeLessThan(2)
  expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x)
  expect(boxes[1]!.x).toBeLessThan(boxes[2]!.x)
  // the actions sit under the verdict and above the sections
  expect(boxes[0]!.y).toBeGreaterThan((await page.getByTestId('mr-verdict').boundingBox())!.y)
  expect(boxes[0]!.y).toBeLessThan((await page.getByTestId('mr-sectors').boundingBox())!.y)
  const terms = await page.locator('[data-testid=home-market-risk-summary] [data-testid=mr-explain]').evaluateAll(es => [...new Set(es.map(e => e.getAttribute('data-term')))].sort())
  for (const t of ['budget_breach', 'carried', 'hedge_verdict', 'invalidates_below', 'look_through', 'not_measured', 'pc_oi', 'pct_book', 'protect',
    'resilient', 'rotate_rs', 'stage1', 'stage2', 'stress', 'stressed_pct', 'usd_exposed', 'vulnerability']) {
    if (t === 'carried') continue // the fixture card is SHADOW, not CARRIED
    expect(terms).toContain(t)
  }
  expect(terms).toContain('shadow')
  await page.locator('[data-testid=mr-hedge] [data-testid=mr-explain]').click()
  const sheet = page.getByTestId('mr-explain-sheet')
  await expect(sheet).toContainText('at least 10% of your invested money, or 4 or more sectors are lagging')
  const sb = (await sheet.boundingBox())!
  expect(sb.width).toBeLessThanOrEqual(420) // a centred dialog on desktop
  await page.keyboard.press('Escape')
  await expect(sheet).toHaveCount(0)
  await expect(page.locator('[data-testid=mr-hedge] [data-testid=mr-explain]')).toBeFocused()
  expect(await noSideScroll(page)).toBeTruthy()
  expect(await minTap(page, '[data-testid=mr-actions]')).toBeGreaterThanOrEqual(44)
  await shot(page, 'v006-1440-yellow-expanded')
  expect(writes).toEqual([])
})

test('v006 1440 ORANGE: the banner carries the same blocks', async ({ page }) => {
  await open(page, 'v006_orange', 1440, 1000)
  await expect(page.getByTestId('home-market-risk-banner')).toBeVisible()
  await expect(page.getByTestId('mr-actions-digest').or(page.getByTestId('mr-actions'))).toBeVisible()
  await shot(page, 'v006-1440-orange')
})

for (const width of [1440, 412, 390]) {
  test(`v006 ${width}: hedge CONSIDER and UNKNOWN, rotate none, segments pending`, async ({ page }) => {
    await open(page, 'v006_consider', width, width === 1440 ? 1000 : 915)
    if (width !== 1440) await expand(page)
    await expect(page.getByTestId('mr-hedge-verdict')).toHaveText('CONSIDER')
    await expect(page.getByTestId('mr-hedge')).toContainText('Technology is 11.2% of invested and weakening — above the 10% the Defense desk uses. PSQ: thesis green · entry wait for bounce day')
    expect(await page.getByTestId('mr-hedge').innerText()).not.toMatch(/size|band|take profit|\$\d+.*per/i)
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `v006-${width}-hedge-consider`)

    await open(page, 'v006_unknown', width, width === 1440 ? 1000 : 915)
    if (width !== 1440) await expand(page)
    await expect(page.getByTestId('mr-hedge-verdict')).toHaveText('UNKNOWN')
    await expect(page.getByTestId('mr-hedge')).toContainText('no verdict until it runs again')

    await open(page, 'v006_rotate_none', width, width === 1440 ? 1000 : 915)
    if (width !== 1440) await expand(page)
    await expect(page.getByTestId('mr-rotate')).toContainText('No group is beating SPY on both 1 and 5 sessions today.')
    await expect(page.getByTestId('mr-rotate-link')).toBeVisible()

    await open(page, 'v006_pending', width, width === 1440 ? 1000 : 915)
    if (width !== 1440) await expand(page)
    await expect(page.getByTestId('mr-segment-row')).toHaveAttribute('data-status', 'pending')
    await expect(page.getByTestId('mr-segment-row')).toContainText('segment weights pending approval — counted as Industrials')
    await expect(page.getByTestId('mr-reentry-row').nth(1)).toContainText('segment weights pending approval — counted as Industrials')
  })
}

test('v006: a projection without the v006 blocks keeps the v005 top review item', async ({ page }) => {
  await open(page, 'v005_yellow', 412)
  await expect(page.getByTestId('mr-top-review')).toBeVisible()
  await expect(page.getByTestId('mr-actions-digest')).toHaveCount(0)
})

test('v006 local real render (V006_PROJECTION_JSON; local only)', async ({ page }) => {
  test.skip(!process.env.V006_PROJECTION_JSON, 'local review render only')
  process.env.V005_PROJECTION_JSON = process.env.V006_PROJECTION_JSON
  for (const [w, h, open_] of [[1440, 1000, false], [412, 915, false], [412, 915, true], [390, 844, false], [390, 844, true]] as const) {
    await open(page, 'v005_file', w, h)
    await expect(page.getByTestId('home-market-risk-summary').or(page.getByTestId('home-market-risk-banner'))).toBeVisible()
    if (open_) await expand(page)
    else if (w !== 1440 && (await page.getByTestId('home-market-risk-summary').getAttribute('data-open')) === 'true') await page.getByTestId('home-market-risk-summary-toggle').tap()
    expect(await noSideScroll(page)).toBeTruthy()
    await shot(page, `real-${w}-${open_ ? 'expanded' : w === 1440 ? 'expanded' : 'collapsed'}`, w === 1440 || open_)
  }
})
