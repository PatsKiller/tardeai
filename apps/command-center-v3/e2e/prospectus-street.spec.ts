/** Prospectus institutional ("Street") blocks and the validation badge on the built app, every /api call fulfilled
 *  here (synthetic ticker, firms and numbers only — public repo).
 *  Operator 2026-10-27: "does it also have analyst reviews and what are analysts saying along with catalysts? …
 *  something I can use on the Goldman desk, Citadel, anywhere" and "We don't need to see [citations] on the frontend
 *  … If it's been validated, that's good."
 *  At 1440 / 412 / 390: analyst coverage, the analyst action log, estimates, earnings history, the catalyst calendar,
 *  positioning, valuation history and SEC quarters render from presentation.street; one validation badge (tap → a
 *  compact summary); no superscripts, no "Sources (n)", no Sources appendix, no raw fact ids; 44px targets on the
 *  phone; no sideways page scroll. Screenshots → $PROSPECTUS_SHOTS_DIR when set. */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { PROSPECTUS_ACME, PROSPECTUS_INDEX } from '../src/fixtures/prospectus.fixture'

const STREET = JSON.parse(readFileSync(new URL('./fixtures/prospectus-street.json', import.meta.url), 'utf8'))
const SHOTS = process.env.PROSPECTUS_SHOTS_DIR || ''
const ACME = {
  ...PROSPECTUS_ACME,
  blocks: { ...PROSPECTUS_ACME.blocks, analyst_coverage: {}, catalyst_calendar: {}, positioning: {} },
  presentation: { display_name: 'Acme Synthetic Corp', is_fund: false, footnotes: [], validation: STREET.validation, street: STREET.street },
}

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
    if (u.pathname === '/api/v2/prospectus/ACME') return json(ACME)
    return json({ ok: true, data: {} })
  })
  return forbidden
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.addStyleTag({ content: '.app-shell{height:auto!important}.app-body,.app-main{overflow:visible!important}.psp-sheet{position:static!important;height:auto!important;overflow:visible!important}' })
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
}

async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
  const wide = await page.locator('.psp-card, .psp-st-row, .psp-valid-panel, .psp-tile').evaluateAll(els =>
    els.filter(e => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
  expect(wide, 'nothing runs off the right edge').toEqual([])
}

async function checkReport(page: Page, phone: boolean, tag: string) {
  const report = page.getByTestId('prospectus-report')
  await expect(report).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
  for (const t of STREET.street) await expect(page.getByTestId(`prospectus-street-${t.id}`)).toHaveCount(1)
  const cov = page.getByTestId('prospectus-street-analyst_coverage')
  await expect(cov).toContainText('Analyst coverage · what the Street says')
  await expect(cov).toContainText('more bullish')
  const actions = page.getByTestId('prospectus-street-analyst_actions')
  await expect(actions).toContainText('Example Securities')
  await expect(actions).toContainText('Hold → Buy')
  await expect(actions).toContainText('$55.00 → $66.00')
  await expect(page.getByTestId('prospectus-street-catalyst_calendar')).toContainText('options imply ±')
  await expect(page.getByTestId('prospectus-street-estimates_history')).toContainText('2026-07-29')
  await expect(page.getByTestId('prospectus-street-positioning')).toContainText('Put/call')
  await expect(page.getByTestId('prospectus-street-fundamentals_xbrl')).toContainText('(derived)')
  // The old estimates card is replaced by the Street estimates table.
  await expect(page.getByTestId('prospectus-estimates')).toHaveCount(0)
  // No visible citations anywhere; ONE validation badge.
  await expect(report.locator('sup')).toHaveCount(0)
  await expect(page.getByTestId('prospectus-fn')).toHaveCount(0)
  await expect(page.getByTestId('prospectus-sources')).toHaveCount(0)
  await expect(report).not.toContainText(/Sources \(\d+\)/)
  const text = await report.innerText()
  expect(text).not.toMatch(/\[\^?[FW]\d+/)
  expect(text).not.toMatch(/\b[FW]\d{1,4}\b/)
  const badge = page.getByTestId('prospectus-validation-badge')
  await expect(badge).toHaveCount(1)
  await expect(badge).toContainText('✓ Validated — 2 figures checked against 2 sources')
  if (phone) {
    const h = (await badge.boundingBox())!.height
    expect(h, 'badge ≥ 44px').toBeGreaterThanOrEqual(43.5)
    await badge.tap()
  } else {
    await badge.click()
  }
  const panel = page.getByTestId('prospectus-validation-panel')
  await expect(panel).toContainText('Finviz enrichment cache')
  await expect(panel).not.toContainText(/\bF\d+\b/)
  if (phone) {
    // Phone: rows are stacked cards, never a wide table.
    await expect(actions.locator('table')).toHaveCount(0)
    expect(await actions.getByTestId('prospectus-street-row').count()).toBeGreaterThan(1)
  }
  await noSideScroll(page)
  await shot(page, `street-${tag}`)
}

test.describe('Prospectus Street blocks at 1440', () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }) })

  test('stock report: analyst coverage, action log, estimates, catalysts, positioning, valuation, validation badge', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    const forbidden = await mock(page)
    await page.goto('/v3/prospectus/ACME')
    await checkReport(page, false, '1440')
    expect(errors).toEqual([])
    expect(forbidden).toEqual([])
  })
})

for (const [w, h] of [[412, 915], [390, 844]] as const) {
  test.describe(`Prospectus Street blocks at ${w}`, () => {
    test.use({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true })

    test('phone sheet: stacked Street rows, validation badge tap, no citations, no sideways scroll', async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(String(e)))
      const forbidden = await mock(page)
      await page.goto('/v3/prospectus/ACME')
      await expect(page.getByTestId('prospectus-sheet')).toBeVisible({ timeout: 60_000 })
      await checkReport(page, true, String(w))
      expect(errors).toEqual([])
      expect(forbidden).toEqual([])
    })
  })
}
