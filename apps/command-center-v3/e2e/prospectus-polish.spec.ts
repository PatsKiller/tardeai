/** Prospectus presentation polish (design prospectus/v001.1) on the built app, every /api call fulfilled here
 *  (synthetic tickers, names and numbers only — public repo).
 *  Operator 2026-10-26: "what are these F with the numbers all over the pages? … internal pointers." and, on a fund,
 *  "ETF shouldn't have this. They should have something else that's relative to ETF."
 *  At 1440 / 412 / 390: no raw fact id anywhere; a footnote tap opens a popover with source + as-of; per-section
 *  "Sources (n)" disclosures; one Sources appendix (collapsed on phone); fund layout (Fund structure & holdings, no
 *  ownership / estimates / call); one "not in our data" line; header name; concise stop tile; coverage collapsed;
 *  chart axis in date order; 44px targets; no sideways scroll. Screenshots → $PROSPECTUS_SHOTS_DIR when set. */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { PROSPECTUS_ACME, PROSPECTUS_INDEX } from '../src/fixtures/prospectus.fixture'

const FUND = JSON.parse(readFileSync(new URL('./fixtures/prospectus-fund.json', import.meta.url), 'utf8'))
const FUND_DOC = { ...FUND.doc, presentation: FUND.presentation }
const SHOTS = process.env.PROSPECTUS_SHOTS_DIR || ''
const INDEX = { ...PROSPECTUS_INDEX, items: [...PROSPECTUS_INDEX.items, { symbol: 'ZFUND', name: 'Zed Synthetic Dividend Fund', scope: 'holding', version: FUND.doc.version, generated_at: FUND.doc.generated_at, model: FUND.doc.model, status: 'ready', stale: false, verdict_line: 'HOLD — cheap, diversified income.' }] }

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
    const p = u.pathname
    if (p === '/api/v2/prospectus/index') return json(INDEX)
    if (p === '/api/v2/prospectus/ZFUND') return json(FUND_DOC)
    if (p === '/api/v2/prospectus/ACME') return json(PROSPECTUS_ACME)
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
  const wide = await page.locator('.psp-card, .psp-section, .psp-tile, .psp-fn-pop').evaluateAll(els =>
    els.filter(e => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
  expect(wide, 'nothing runs off the right edge').toEqual([])
}

/** Visible text never shows an internal fact id ("[F7]" / "F42"). */
async function noRawFactIds(page: Page) {
  const text = await page.locator('[data-testid="prospectus-report"]').innerText()
  expect(text).not.toMatch(/\[\^?F\d+/)
  expect(text).not.toMatch(/\bF\d{1,4}\b/)
}

/** A footnote's tap area: the point 20px left / right / above / below its centre still lands on the button. */
async function footnoteHitArea(page: Page) {
  const fn = page.getByTestId('prospectus-fn').first()
  await fn.scrollIntoViewIfNeeded()
  const ok = await fn.evaluate(el => {
    const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2
    return [[0, 0], [-20, 0], [20, 0], [0, -20], [0, 20]].every(([dx, dy]) => { const hit = document.elementFromPoint(cx + dx, cy + dy); return !!hit && (hit === el || el.contains(hit)) })
  })
  expect(ok, 'footnote hit area ≥ 44×44').toBe(true)
}

async function minTarget(page: Page, selector: string) {
  const boxes = await page.locator(selector).evaluateAll(els => els.filter(e => (e as HTMLElement).offsetParent !== null).map(e => e.getBoundingClientRect().height))
  expect(boxes.length, `${selector} visible`).toBeGreaterThan(0)
  for (const h of boxes) expect(h, `${selector} height`).toBeGreaterThanOrEqual(43.5)
}

async function checkFundReport(page: Page, phone: boolean, tag: string) {
  const report = page.getByTestId('prospectus-report')
  await expect(report).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
  // Header: the security's full name once, never "ZFUND ZFUND".
  await expect(page.getByTestId('prospectus-name')).toHaveText('Zed Synthetic Dividend Fund')
  // Stop tile concise; other accounts only in the stop-plan block.
  await expect(page.getByTestId('prospectus-tile-stop')).toContainText('$28.40 · resting')
  await expect(page.getByTestId('prospectus-tile-stop')).toContainText('house $27.90')
  await expect(page.getByTestId('prospectus-tile-stop')).not.toContainText('other accounts')
  await expect(page.getByTestId('prospectus-stop-plan')).toContainText('Example Account B: filled $29.10')
  if (!phone) await expect(page.getByTestId('prospectus-tile-yield')).toContainText('3.10% · 0.07%')
  // Fund layout: structure block in, stock-only blocks out.
  await expect(page.getByTestId('prospectus-fund-structure')).toContainText('Top 3 concentration')
  await expect(page.getByTestId('prospectus-fund-structure')).toContainText('Synthetic Staples')
  await expect(page.getByTestId('prospectus-fund-missing')).toContainText('Not in our data: Index tracked')
  await expect(page.getByTestId('prospectus-fund-missing')).toHaveCount(1)
  for (const id of ['prospectus-ownership', 'prospectus-estimates', 'prospectus-earnings-call', 'prospectus-fund-profile']) await expect(page.getByTestId(id)).toHaveCount(0)
  await expect(page.getByTestId('prospectus-options')).not.toContainText('Dividend')
  // Muted "not reliable" note, no "not available yet".
  await expect(page.getByTestId('prospectus-unreliable').first()).toBeVisible()
  await expect(report).not.toContainText('not available yet')
  await noRawFactIds(page)
  // Footnotes: superscript numbers 1..n, fact id kept in the DOM, popover with source and as-of.
  const fn = page.getByTestId('prospectus-fn').first()
  await expect(fn).toHaveText('1,2')
  await expect(fn).toHaveAttribute('data-fact-id', 'F1 F2')
  await footnoteHitArea(page)
  if (phone) await fn.tap(); else await fn.click()
  const pop = page.getByTestId('prospectus-fn-popover')
  await expect(pop).toBeVisible()
  await expect(pop).toContainText('Fund distribution yield %')
  await expect(pop).toContainText('synthetic fund store')
  await expect(pop).toContainText('Oct 25')
  const box = await pop.boundingBox()
  const vw = page.viewportSize()!.width
  expect(box!.x).toBeGreaterThanOrEqual(15)
  expect(box!.x + box!.width).toBeLessThanOrEqual(vw - 15)
  await shot(page, `polish-fund-popover-${tag}`)
  await page.keyboard.press('Escape')
  await expect(pop).toHaveCount(0)
  // Coverage collapsed with counts; plumbing hidden.
  const cov = page.getByTestId('prospectus-coverage')
  await expect(page.getByTestId('prospectus-coverage-count-used')).toHaveText('2 used')
  await expect(page.getByTestId('prospectus-coverage-chip').first()).toBeHidden()
  await page.getByTestId('prospectus-coverage-toggle').click()
  await expect(page.getByTestId('prospectus-coverage-chip')).toHaveCount(5)
  await expect(cov).not.toContainText(/supervisor|ledger|chooser/i)
  // Sources appendix: open on desktop, collapsed on phone.
  const list = page.getByTestId('prospectus-sources-list')
  if (phone) {
    await expect(list).toBeHidden()
    await page.getByTestId('prospectus-sources').locator('summary').click()
  }
  await expect(list).toBeVisible()
  await expect(list.locator('li')).toHaveCount(FUND.presentation.footnotes.length)
  await expect(list.locator('li').first()).toHaveAttribute('data-fact-id', 'F1')
  // Per-section disclosure.
  if (phone) await page.locator('[data-section="business_and_moat"] > summary').click()
  const secSrc = page.locator('[data-section="business_and_moat"] [data-testid="prospectus-section-sources"]')
  await expect(secSrc.locator('summary')).toHaveText('Sources (2)')
  await secSrc.locator('summary').click()
  await expect(secSrc.locator('li')).toHaveCount(2)
  // Relative performance: month ticks in order, the empty series has no legend entry.
  const ticks = await page.locator('[data-testid="prospectus-rel-chart"] .recharts-xAxis .recharts-cartesian-axis-tick-value').evaluateAll(els => els.map(e => (e.textContent || '').trim()))
  expect(ticks.length).toBeGreaterThan(2)
  for (const t of ticks) expect(t).toMatch(/^[A-Z][a-z]{2} \d\d$/)
  const months = ticks.map(t => ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(t.slice(0, 3)) + 12 * Number(t.slice(4)))
  expect([...months].sort((a, b) => a - b)).toEqual(months)
  await expect(page.getByTestId('prospectus-rel-legend')).not.toContainText('EMPTYF')
  if (phone) {
    await minTarget(page, '[data-testid="prospectus-section-sources"] summary:visible, [data-testid="prospectus-coverage-toggle"]')
  }
  await noSideScroll(page)
}

test.describe('Prospectus polish at 1440', () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }) })

  test('fund report: footnotes, popover, sources, fund structure, coverage, chart axis', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
    const forbidden = await mock(page)
    await page.goto('/v3/prospectus/ZFUND')
    await checkFundReport(page, false, '1440')
    await page.reload()
    await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
    await shot(page, 'polish-fund-1440')
    expect(errors).toEqual([])
    expect(forbidden).toEqual([])
  })

  test('stock report keeps ownership / estimates / call and shows footnotes, no raw ids', async ({ page }) => {
    await mock(page)
    await page.goto('/v3/prospectus/ACME')
    await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
    for (const id of ['prospectus-ownership', 'prospectus-estimates', 'prospectus-earnings-call']) await expect(page.getByTestId(id)).toBeVisible()
    await expect(page.getByTestId('prospectus-fund-structure')).toHaveCount(0)
    await expect(page.getByTestId('prospectus-ownership')).not.toContainText('Fund flows')
    await expect(page.getByTestId('prospectus-ownership').getByTestId('prospectus-not-in-data')).toHaveCount(1)
    await expect(page.getByTestId('prospectus-name')).toHaveText('Acme Synthetic Corp')
    await noRawFactIds(page)
    await page.getByTestId('prospectus-fn').first().hover()
    await expect(page.getByTestId('prospectus-fn-popover')).toContainText('house financials')
    await noSideScroll(page)
  })
})

for (const [w, h] of [[412, 915], [390, 844]] as const) {
  test.describe(`Prospectus polish at ${w}`, () => {
    test.use({ viewport: { width: w, height: h }, hasTouch: true, isMobile: true })

    test('fund report on the phone sheet: tap a footnote, sources collapsed, 44px targets, no sideways scroll', async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(String(e)))
      const forbidden = await mock(page)
      await page.goto('/v3/prospectus/ZFUND')
      await expect(page.getByTestId('prospectus-sheet')).toBeVisible({ timeout: 60_000 })
      await checkFundReport(page, true, String(w))
      await page.reload()
      await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
      await page.evaluate(() => document.querySelectorAll('[data-testid="prospectus-section"]').forEach(d => { (d as HTMLDetailsElement).open = true }))
      await shot(page, `polish-fund-${w}`)
      expect(errors).toEqual([])
      expect(forbidden).toEqual([])
    })
  })
}
