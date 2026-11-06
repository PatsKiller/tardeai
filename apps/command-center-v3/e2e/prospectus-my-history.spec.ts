/** Prospectus "My history" block (operator 2026-10-26: "What is my average cost? Have I won or lost, P&L? What were
 *  the catalysts that hit? ... multiple round trips ... analyzed?") and the fund profile, on the built app with every
 *  /api call fulfilled here (synthetic tickers, accounts and numbers only — public repo). Port 7777 and any non-local
 *  origin fail the test. Desktop 1440 and phone 412 / 390 with touch: the block sits right after the verdict tiles,
 *  trips open on tap (44px rows), wash-sale + stop flags, lessons, tax chips, no sideways scroll. A never-traded name
 *  shows one muted line. Screenshots go to $PROSPECTUS_SHOTS_DIR when set. */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { PROSPECTUS_INDEX } from '../src/fixtures/prospectus.fixture'
import { PROSPECTUS_ACME_MY_HISTORY, PROSPECTUS_ACME_NEVER_TRADED } from '../src/fixtures/prospectusMyHistory.fixture'

const SHOTS = process.env.PROSPECTUS_SHOTS_DIR || ''

async function mock(page: Page, opts: { never?: boolean } = {}) {
  const seen = { forbidden: [] as string[], posts: [] as string[] }
  await page.routeWebSocket(/.*/, ws => { ws.close() })
  await page.route('**/*', async route => {
    const req = route.request()
    const u = new URL(req.url())
    const base = new URL(page.url() === 'about:blank' ? (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173') : page.url())
    if (u.port === '7777' || (u.origin !== base.origin && !u.hostname.endsWith('.invalid'))) {
      if (!/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) seen.forbidden.push(`${req.method()} ${req.url()}`)
      return route.abort()
    }
    if (!u.pathname.startsWith('/api/')) return route.fallback()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (req.method() !== 'GET') { seen.posts.push(`${req.method()} ${u.pathname}`); return json({ ok: true }) }
    if (u.pathname === '/api/v2/prospectus/index') return json(PROSPECTUS_INDEX)
    if (u.pathname === '/api/v2/prospectus/ACME') return json(opts.never ? PROSPECTUS_ACME_NEVER_TRADED : PROSPECTUS_ACME_MY_HISTORY)
    return json({ ok: true, data: {} })
  })
  return seen
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
  const wide = await page.locator('.psp-card, .psp-mh-trip, .psp-mh-kpi, .psp-mh-card').evaluateAll(els =>
    els.filter(e => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
  expect(wide, 'no my-history block runs off the right edge').toEqual([])
}

async function expectHistory(page: Page) {
  const mh = page.getByTestId('prospectus-my-history')
  await expect(mh).toBeVisible({ timeout: 60_000 })
  // placed right after the verdict tiles
  const order = await page.evaluate(() => {
    const tiles = document.querySelector('[data-testid="prospectus-tiles"]')
    const next = tiles?.nextElementSibling as HTMLElement | null
    return next?.getAttribute('data-testid')
  })
  expect(order).toBe('prospectus-my-history')
  await expect(page.getByTestId('prospectus-mh-avg-cost')).toContainText('$58.75')
  await expect(page.getByTestId('prospectus-mh-open-pl')).toContainText('+$450.00')
  await expect(page.getByTestId('prospectus-mh-realized')).toContainText('+$105.00')
  await expect(page.getByTestId('prospectus-mh-winloss')).toContainText('2 / 1')
  await expect(page.getByTestId('prospectus-mh-summary')).toContainText('three round trips')
  await expect(page.getByTestId('prospectus-mh-lot')).toHaveCount(2)
  await expect(page.getByTestId('prospectus-mh-lots')).toContainText('Fixture Roth IRA')
  await expect(page.getByTestId('prospectus-mh-trip')).toHaveCount(3)
  await expect(page.getByTestId('prospectus-mh-trip').first()).toHaveAttribute('data-trip', '3')
  await expect(page.getByTestId('prospectus-mh-flag')).toHaveCount(3)
  await expect(page.getByTestId('prospectus-mh-tax-flag')).toContainText('Trip 2: wash-sale window')
  await expect(page.getByTestId('prospectus-mh-lessons')).toContainText('payoff ratio')
  await expect(page.getByTestId('prospectus-mh-lessons')).toContainText('Chased the breakout')
  await expect(page.getByTestId('prospectus-fund-profile')).toContainText('Aerospace & Defense')
  await expect(page.getByTestId('prospectus-fund-profile')).toContainText('0.35%')
  await expect(page.getByTestId('prospectus-fund-gaps')).toContainText('assets under management')
  await expect(mh).not.toContainText(/fixture_/)
}

test.describe('Prospectus — My history (desktop 1440)', () => {
  test.use({ viewport: { width: 1440, height: 1000 } })

  test('block after the tiles: KPIs, lots, trips open with events, flags, lessons, tax, fund profile', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    const seen = await mock(page)
    await page.goto('/v3/prospectus/ACME')
    await expectHistory(page)
    const trip2 = page.locator('[data-testid="prospectus-mh-trip"][data-trip="2"]')
    await trip2.locator('summary').click()
    await expect(trip2).toHaveAttribute('open', '')
    await expect(trip2.getByTestId('prospectus-mh-why')).toContainText('Watch list → Research')
    await expect(trip2.getByTestId('prospectus-mh-trip-events')).toContainText('ACME beats synthetic estimates')
    await expect(trip2.getByTestId('prospectus-mh-trip-events')).toContainText('day-of −0.9%')
    await expect(trip2.getByTestId('prospectus-mh-wash')).toContainText('Aug 18, 2025')
    await page.getByTestId('prospectus-mh-current').locator('summary').click()
    await expect(page.getByTestId('prospectus-mh-current-events')).toContainText('Fixture bank upgrades ACME')
    await noSideScroll(page)
    await page.getByTestId('prospectus-my-history').scrollIntoViewIfNeeded()
    await shot(page, 'prospectus-my-history-1440')
    expect(errors).toEqual([])
    expect(seen.posts).toEqual([])
    expect(seen.forbidden).toEqual([])
  })

  test('never traded → one muted line, no tables', async ({ page }) => {
    const seen = await mock(page, { never: true })
    await page.goto('/v3/prospectus/ACME')
    await expect(page.getByTestId('prospectus-mh-never')).toContainText('no position and no round trips')
    await expect(page.getByTestId('prospectus-mh-trip')).toHaveCount(0)
    expect(seen.forbidden).toEqual([])
  })
})

for (const vp of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test.describe(`Prospectus — My history phone ${vp.width}`, () => {
    test.use({ hasTouch: true, isMobile: true, viewport: vp })

    test(`lots as cards, trips tap open (44px), no sideways scroll (${vp.width})`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(String(e)))
      const seen = await mock(page)
      await page.goto('/v3/prospectus/ACME')
      await expectHistory(page)
      const rows = await page.locator('.psp-mh-trip-sum').evaluateAll(els => els.filter(e => (e as HTMLElement).offsetParent !== null).map(e => e.getBoundingClientRect().height))
      expect(rows.length).toBeGreaterThan(0)
      for (const h of rows) expect(h, 'trip row tap target').toBeGreaterThanOrEqual(44)
      const trip3 = page.locator('[data-testid="prospectus-mh-trip"][data-trip="3"]')
      await trip3.locator('summary').scrollIntoViewIfNeeded()
      await trip3.locator('summary').tap()
      await expect(trip3).toHaveAttribute('open', '')
      await expect(trip3.getByTestId('prospectus-mh-trip-events')).toContainText('Big day move +12.4%')
      await noSideScroll(page)
      await page.getByTestId('prospectus-my-history').scrollIntoViewIfNeeded()
      await shot(page, `prospectus-my-history-${vp.width}`)
      expect(errors).toEqual([])
      expect(seen.forbidden).toEqual([])
    })
  })
}
