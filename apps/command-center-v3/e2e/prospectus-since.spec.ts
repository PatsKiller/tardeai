/** "Since this report" strip (operator 2026-10-27, Prospectus NEWS methodology) on the built app, every /api call
 *  fulfilled here (synthetic tickers, names and headlines only — public repo).
 *  At 1440 / 412 / 390: the strip renders at the top of the report with the price move, the stop event, a material
 *  item with its CIO note (impact + one line), a not-material item, the queued-rewrite status and the hidden
 *  collision/duplicate count; on a phone it shows 3 items and a 44px "Show all" button; no sideways scroll. */
import { expect, test, type Page } from '@playwright/test'
import { PROSPECTUS_ACME, PROSPECTUS_INDEX } from '../src/fixtures/prospectus.fixture'

const SINCE = {
  written_at: PROSPECTUS_ACME.generated_at, checked_at: '2026-10-27T21:46:00Z', item_count: 4,
  hidden: { collision: 1, duplicate: 2 },
  price: { at_report: 100, last_close: 91.5, as_of: '2026-10-27', move_pct: -8.5 },
  stop_events: [{ kind: 'stop_change', at_report: [88], now: [90], status: 'stop levels changed' }],
  rewrite: { reason: 'news_breaker', status: 'queued for the 07:00 run' },
  next_window: { id: 'pre_market', start: '2026-10-28T07:00:00-04:00', time: '07:00', label: 'Pre-market' },
  items: [
    { id: 'a1', at: '2026-10-27T13:05:00Z', kind: 'filing', title: 'ACME 8-K: Entry into a material agreement (Item 1.01) filed 2026-10-27', source: 'sec_edgar', url: 'https://example.invalid/acme-8k', material: true, badge: 'material', status: 'queued for the 07:00 run', note: { impact: 'breaker', which_breaker: 'B2', one_line: 'Supply deal concentrates revenue in one customer, the concentration breaker.' } },
    { id: 'a2', at: '2026-10-27T11:00:00Z', kind: 'catalyst', title: 'Acme Synthetic Corp raises full-year guidance', source: 'feed', url: null, material: true, badge: 'material', status: 'CIO note: watch', note: { impact: 'watch', which_breaker: null, one_line: 'Guidance up a little; thesis intact.' } },
    { id: 'a3', at: '2026-10-26T18:00:00Z', kind: 'headline', title: 'Acme Synthetic Corp to present at an industry conference', source: 'wire', url: null, material: false, badge: 'not material', status: 'not material', note: null },
    { id: 'a4', at: '2026-10-26T15:00:00Z', kind: 'headline', title: 'Acme Synthetic Corp names a new board member', source: 'wire', url: null, material: false, badge: 'not material', status: 'not material', note: null },
  ],
}
const DOC = { ...PROSPECTUS_ACME, since_report: SINCE }

async function mock(page: Page): Promise<string[]> {
  const forbidden: string[] = []
  await page.routeWebSocket(/.*/, ws => { ws.close() })
  await page.route('**/*', async route => {
    const req = route.request()
    const u = new URL(req.url())
    const base = new URL(page.url() === 'about:blank' ? (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173') : page.url())
    if (u.port === '7777' || (u.origin !== base.origin && !u.hostname.endsWith('.invalid'))) {
      if (!/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) forbidden.push(`${req.method()} ${req.url()}`)
      return route.abort()
    }
    if (!u.pathname.startsWith('/api/')) return route.fallback()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname === '/api/v2/prospectus/index') return json(PROSPECTUS_INDEX)
    if (u.pathname === '/api/v2/prospectus/ACME') return json(DOC)
    return json({ ok: true, data: {} })
  })
  return forbidden
}

async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
  const wide = await page.locator('.psp-since, .psp-since-item').evaluateAll(els =>
    els.filter(e => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
  expect(wide, 'nothing runs off the right edge').toEqual([])
}

async function checkStrip(page: Page, phone: boolean) {
  const strip = page.getByTestId('prospectus-since')
  await expect(strip).toBeVisible({ timeout: 60_000 })
  // at the top: before the summary card
  const order = await page.evaluate(() => {
    const s = document.querySelector('[data-testid="prospectus-since"]')
    const sum = document.querySelector('[data-testid="prospectus-summary"]')
    return !!s && !!sum && !!(s.compareDocumentPosition(sum) & Node.DOCUMENT_POSITION_FOLLOWING)
  })
  expect(order, 'strip renders above the summary').toBe(true)
  await expect(page.getByTestId('prospectus-since-move')).toContainText('-8.5%')
  await expect(page.getByTestId('prospectus-since-stop')).toContainText('Stop levels changed')
  await expect(page.getByTestId('prospectus-since-rewrite')).toContainText('queued for the 07:00 run')
  await expect(page.getByTestId('prospectus-since-hidden')).toContainText('1 about another company with this ticker')
  const first = page.getByTestId('prospectus-since-item').first()
  await expect(first.getByTestId('prospectus-since-badge')).toHaveText('Material')
  await expect(first.getByTestId('prospectus-since-status')).toContainText('(B2)')
  await expect(first.getByTestId('prospectus-since-status')).toContainText('concentration breaker')
  if (phone) {
    await expect(page.getByTestId('prospectus-since-item')).toHaveCount(3)
    const more = page.getByTestId('prospectus-since-more')
    const box = await more.boundingBox()
    expect(box?.height ?? 0, '"Show all" ≥ 44px').toBeGreaterThanOrEqual(43.5)
    await more.tap()
    await expect(page.getByTestId('prospectus-since-item')).toHaveCount(4)
    await expect(page.getByTestId('prospectus-since-item').nth(3).getByTestId('prospectus-since-badge')).toHaveText('Not material')
  } else {
    await expect(page.getByTestId('prospectus-since-item')).toHaveCount(4)
    await expect(page.getByTestId('prospectus-since-more')).toHaveCount(0)
  }
  const link = first.locator('a.psp-since-title')
  const lb = await link.boundingBox()
  expect(lb?.height ?? 0, 'headline link ≥ 44px').toBeGreaterThanOrEqual(43.5)
  await noSideScroll(page)
}

test.describe('Prospectus since-report strip at 1440', () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }) })
  test('strip at the top: price move, stop event, notes, badges, hidden count', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    const forbidden = await mock(page)
    await page.goto('/v3/prospectus/ACME')
    await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
    await checkStrip(page, false)
    expect(errors).toEqual([])
    expect(forbidden).toEqual([])
  })
})

for (const [w, h] of [[412, 915], [390, 844]] as const) {
  test.describe(`Prospectus since-report strip at ${w}`, () => {
    test.use({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true })
    test('phone sheet: 3 items then Show all (44px), notes and badges, no sideways scroll', async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(String(e)))
      const forbidden = await mock(page)
      await page.goto('/v3/prospectus/ACME')
      await expect(page.getByTestId('prospectus-sheet')).toBeVisible({ timeout: 60_000 })
      await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
      await checkStrip(page, true)
      expect(errors).toEqual([])
      expect(forbidden).toEqual([])
    })
  })
}
