/** Ticker Prospectus (/v3/prospectus) on the built app with every /api call fulfilled here (synthetic tickers and
 *  made-up numbers only — public repo). Port 7777 and any non-local origin are forbidden and fail the test.
 *  Desktop 1440; phone 412 and 390 with touch: tap a row → full-screen sheet, ← Back, 44px targets, no sideways scroll,
 *  download hrefs, filter chips, missing / failed / stale / loading / queued states, operator-only Rewrite with confirm.
 *  Screenshots go to $PROSPECTUS_SHOTS_DIR when set (keep real-data captures out of the repo). */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { PROSPECTUS_ACME, PROSPECTUS_ACME_OLD, PROSPECTUS_BETA, PROSPECTUS_GAMMA_FAILED, PROSPECTUS_INDEX } from '../src/fixtures/prospectus.fixture'

const SHOTS = process.env.PROSPECTUS_SHOTS_DIR || ''
type Opts = { operator?: boolean; slowDetail?: boolean }
type Seen = { forbidden: string[]; posts: string[]; detail: string[] }

async function mock(page: Page, opts: Opts = {}): Promise<Seen> {
  const seen: Seen = { forbidden: [], posts: [], detail: [] }
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
    const p = u.pathname
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (req.method() !== 'GET') {
      if (p.startsWith('/api/v2/prospectus/')) {
        seen.posts.push(`${req.method()} ${p}`)
        return json({ ok: true, message: 'Rewrite queued — position 1' })
      }
      return json({ ok: true })
    }
    if (p === '/api/v2/prospectus/index') return json(opts.operator ? { ...PROSPECTUS_INDEX, viewer: { operator: true } } : PROSPECTUS_INDEX)
    const m = /^\/api\/v2\/prospectus\/([^/]+)$/.exec(p)
    if (m) {
      seen.detail.push(p + u.search)
      if (opts.slowDetail) await new Promise(r => setTimeout(r, 1500))
      const sym = decodeURIComponent(m[1])
      if (sym === 'ACME') return json(u.searchParams.get('version') === '20260926T120000Z' ? PROSPECTUS_ACME_OLD : PROSPECTUS_ACME)
      if (sym === 'BETA') return json(PROSPECTUS_BETA)
      if (sym === 'GAMMA') return json(PROSPECTUS_GAMMA_FAILED)
      if (sym === 'EPSI') return json({ symbol: 'EPSI', status: 'queued', sections: [], charts: [], versions: [] })
      return json({ ok: false, error: 'not written yet' }, 404)
    }
    if (p === '/api/v3/opportunities/ACME') return json({ data: { symbol: 'ACME', assessment: { type: 'holding' }, market: {}, profile: { company: 'Acme Synthetic Corp' } } })
    return json({ ok: true, data: {} })
  })
  return seen
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false })
}

async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
  const wide = await page.locator('.psp-row, .psp-section, .psp-chart, .psp-report-head, .psp-strip').evaluateAll(els =>
    els.filter(e => e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
  expect(wide, 'no prospectus block runs off the right edge').toEqual([])
}

async function tapTarget(page: Page, selector: string, min = 44) {
  const boxes = await page.locator(selector).evaluateAll(els => els.filter(e => (e as HTMLElement).offsetParent !== null).map(e => { const r = e.getBoundingClientRect(); return { h: r.height, w: r.width } }))
  expect(boxes.length, `${selector} visible`).toBeGreaterThan(0)
  for (const b of boxes) { expect(b.h, `${selector} height`).toBeGreaterThanOrEqual(min - 0.5); expect(b.w, `${selector} width`).toBeGreaterThanOrEqual(min - 0.5) }
}

function expectDownloads(page: Page, sym: string, version?: string) {
  const q = version ? `?version=${version}` : ''
  return Promise.all([
    expect(page.getByTestId('prospectus-dl-pdf')).toHaveAttribute('href', `/api/v2/prospectus/${sym}/file/pdf${q}`),
    expect(page.getByTestId('prospectus-dl-docx')).toHaveAttribute('href', `/api/v2/prospectus/${sym}/file/docx${q}`),
    expect(page.getByTestId('prospectus-open-html')).toHaveAttribute('href', `/api/v2/prospectus/${sym}/file/html${q}`),
  ])
}

test.describe('Prospectus at 1440', () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }) })

  test('nav entry, header strip, filter chips, search, report with charts, sections, citations, downloads, versions', async ({ page }) => {
    const seen = await mock(page)
    await page.goto('/v3/prospectus')
    const nav = page.locator('nav a[href="/v3/prospectus"]')
    await expect(nav).toBeVisible({ timeout: 60_000 })
    // Appended to Intel: Communications stays where it was, Prospectus comes right after it.
    const intel = await page.locator('nav a').evaluateAll(as => as.map(a => a.getAttribute('href')))
    expect(intel.indexOf('/v3/prospectus')).toBe(intel.indexOf('/v3/communications') + 1)

    await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
    await expect(page.getByTestId('prospectus-total-ready')).toContainText('3')
    await expect(page.getByTestId('prospectus-total-failed')).toContainText('1')
    await expect(page.getByTestId('prospectus-budget')).toContainText('$150.25')
    await expect(page.getByTestId('prospectus-budget-today')).toHaveText('$6.50 / $25.00')
    // Holdings first, failures first within holdings.
    await expect(page.getByTestId('prospectus-row').first()).toHaveAttribute('data-symbol', 'GAMMA')
    const acmeRow = page.locator('[data-testid="prospectus-row"][data-symbol="ACME"]')
    await expect(acmeRow.getByTestId('prospectus-model')).toHaveText('Fable')
    await expect(acmeRow.getByTestId('prospectus-verdict')).toContainText('moat intact')
    await expect(page.locator('[data-symbol="BETA"]').getByTestId('prospectus-stale')).toBeVisible()
    await expect(page.locator('[data-symbol="BETA"]').getByTestId('prospectus-model')).toHaveText('Opus')
    await expect(page.locator('[data-symbol="GAMMA"]').getByTestId('prospectus-verdict')).toContainText('too few cited facts')
    await expect(page.locator('[data-symbol="DELTA"]').getByTestId('prospectus-verdict')).toContainText('Not written yet — queued')
    await expect(page.getByTestId('prospectus-page')).not.toContainText(/\d{4}-\d{2}-\d{2}T\d{2}:/)

    await page.getByTestId('prospectus-filter-holdings').click()
    await expect(page).toHaveURL(/scope=holdings/)
    await expect(page.getByTestId('prospectus-row')).toHaveCount(3)
    await page.getByTestId('prospectus-filter-watch').click()
    await expect(page.getByTestId('prospectus-row')).toHaveCount(4)
    await page.getByTestId('prospectus-filter-all').click()
    await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
    await page.getByTestId('prospectus-search').fill('demo software')
    await expect(page.getByTestId('prospectus-row')).toHaveCount(1)
    await expect(page.getByTestId('prospectus-row')).toHaveAttribute('data-symbol', 'THETA')
    await page.getByTestId('prospectus-search').fill('')
    await noSideScroll(page)
    await shot(page, 'prospectus-list-1440')

    await acmeRow.click()
    await expect(page).toHaveURL(/\/v3\/prospectus\/ACME/)
    const report = page.getByTestId('prospectus-report')
    await expect(report).toHaveAttribute('data-state', 'ready')
    await expect(page.getByTestId('prospectus-section')).toHaveCount(9)
    await expect(page.getByTestId('prospectus-section').first()).toHaveAttribute('data-section', 'summary_verdict')
    await expect(page.getByTestId('prospectus-chart')).toHaveCount(4)
    await expect(page.locator('[data-chart-id="price_1y"] svg').first()).toBeVisible()
    await expect(page.getByTestId('prospectus-chart-levels')).toContainText('Stop 42')
    await expect(page.getByTestId('prospectus-target-range')).toContainText('Mean 58')
    await expect(page.getByTestId('prospectus-cite').first()).toContainText('c1')
    await expect(page.getByTestId('prospectus-cite-inline').first()).toHaveText('c1')
    await expect(page.locator('a[data-testid="prospectus-cite"][href="https://example.com/acme-calendar"]')).toHaveCount(1)
    await expect(page.getByTestId('prospectus-rewrite')).toHaveCount(0)
    await expectDownloads(page, 'ACME')
    await noSideScroll(page)
    await shot(page, 'prospectus-detail-1440')

    await page.getByTestId('prospectus-version').selectOption('20260926T120000Z')
    await expect(page).toHaveURL(/version=20260926T120000Z/)
    await expect(page.getByTestId('prospectus-section')).toHaveCount(1)
    await expect(page.getByTestId('prospectus-section')).toContainText('Older version')
    await expectDownloads(page, 'ACME', '20260926T120000Z')
    expect(seen.detail).toContain('/api/v2/prospectus/ACME?version=20260926T120000Z')

    expect(seen.posts).toEqual([])
    expect(seen.forbidden).toEqual([])
  })

  test('states: missing, failed with reason, stale, queued, loading', async ({ page }) => {
    const seen = await mock(page, { slowDetail: true })
    await page.goto('/v3/prospectus/ACME')
    await expect(page.getByTestId('prospectus-loading')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready', { timeout: 10_000 })

    await page.goto('/v3/prospectus/DELTA')
    await expect(page.getByTestId('prospectus-missing')).toContainText('Not written yet — queued', { timeout: 60_000 })
    await expect(page.getByTestId('prospectus-dl-pdf')).toHaveCount(0)

    await page.goto('/v3/prospectus/GAMMA')
    await expect(page.getByTestId('prospectus-failed')).toContainText('too few cited facts', { timeout: 60_000 })

    await page.goto('/v3/prospectus/EPSI')
    await expect(page.getByTestId('prospectus-queued')).toBeVisible({ timeout: 60_000 })

    await page.goto('/v3/prospectus/BETA')
    await expect(page.getByTestId('prospectus-stale-banner')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('prospectus-detail-stale')).toBeVisible()
    await expectDownloads(page, 'BETA')
    expect(seen.forbidden).toEqual([])
  })

  test('operator sees Rewrite now; it asks first, Cancel sends nothing, Queue rewrite POSTs refresh once', async ({ page }) => {
    const seen = await mock(page, { operator: true })
    await page.goto('/v3/prospectus/ACME')
    const btn = page.getByTestId('prospectus-rewrite')
    await expect(btn).toBeVisible({ timeout: 60_000 })
    await btn.click()
    await expect(page.getByTestId('prospectus-rewrite-confirm')).toBeVisible()
    await page.getByTestId('prospectus-rewrite-cancel').click()
    await expect(page.getByTestId('prospectus-rewrite-confirm')).toHaveCount(0)
    expect(seen.posts).toEqual([])
    await btn.click()
    await page.getByTestId('prospectus-rewrite-confirm-go').click()
    await expect(page.getByTestId('prospectus-rewrite-msg')).toContainText('Rewrite queued')
    expect(seen.posts).toEqual(['POST /api/v2/prospectus/ACME/refresh'])
    expect(seen.forbidden).toEqual([])
  })

  test('shared ticker modal links to the prospectus', async ({ page }) => {
    const seen = await mock(page)
    await page.goto('/v3/prospectus?opp=ACME')
    const link = page.getByTestId('opportunity-prospectus-link')
    await expect(link).toBeVisible({ timeout: 60_000 })
    await expect(link).toHaveAttribute('href', '/v3/prospectus/ACME')
    await link.click()
    await expect(page).toHaveURL(/\/v3\/prospectus\/ACME/)
    await expect(page.getByTestId('prospectus-report')).toBeVisible()
    expect(seen.forbidden).toEqual([])
  })
})

for (const vp of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
  test.describe(`Prospectus phone ${vp.width}`, () => {
    test.use({ hasTouch: true, isMobile: true, viewport: vp })

    test(`tap row → full-screen sheet, downloads, ← Back, 44px targets, no sideways scroll (${vp.width})`, async ({ page }) => {
      const seen = await mock(page)
      await page.goto('/v3/prospectus')
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7, { timeout: 60_000 })
      await expect(page.getByTestId('prospectus-sheet')).toHaveCount(0)
      await tapTarget(page, '[data-testid^="prospectus-filter-"]')
      await tapTarget(page, '[data-testid="prospectus-row"]', 44)
      await page.getByTestId('prospectus-filter-holdings').tap()
      await expect(page.getByTestId('prospectus-row')).toHaveCount(3)
      await page.getByTestId('prospectus-filter-watch').tap()
      await expect(page.getByTestId('prospectus-row')).toHaveCount(4)
      await page.getByTestId('prospectus-filter-all').tap()
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
      await noSideScroll(page)
      await shot(page, `prospectus-list-${vp.width}`)

      const acme = page.locator('[data-testid="prospectus-row"][data-symbol="ACME"]')
      await acme.scrollIntoViewIfNeeded()
      await acme.tap()
      await expect(page).toHaveURL(/\/v3\/prospectus\/ACME/)
      const sheet = page.getByTestId('prospectus-sheet')
      await expect(sheet).toBeVisible()
      expect(await sheet.boundingBox()).toEqual({ x: 0, y: 0, width: vp.width, height: vp.height })
      await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'ready')
      await expect(page.getByTestId('prospectus-back')).toBeFocused()
      await tapTarget(page, '[data-testid="prospectus-back"]')
      await tapTarget(page, '[data-testid="prospectus-dl-pdf"], [data-testid="prospectus-dl-docx"], [data-testid="prospectus-open-html"]')
      await expectDownloads(page, 'ACME')
      await expect(page.getByTestId('prospectus-section')).toHaveCount(9)
      await expect(page.getByTestId('prospectus-chart')).toHaveCount(4)
      const sheetScroll = await sheet.evaluate(el => [el.scrollWidth, el.clientWidth])
      expect(sheetScroll[0], 'sheet has no sideways scroll').toBeLessThanOrEqual(sheetScroll[1] + 1)
      await noSideScroll(page)
      await shot(page, `prospectus-detail-${vp.width}`)
      await page.getByTestId('prospectus-section').nth(4).scrollIntoViewIfNeeded()
      await shot(page, `prospectus-detail-${vp.width}-sections`)

      await page.getByTestId('prospectus-back').tap()
      await expect(page).toHaveURL(/\/v3\/prospectus(\?|$)/)
      await expect(page.getByTestId('prospectus-sheet')).toHaveCount(0)
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
      expect(seen.posts).toEqual([])
      expect(seen.forbidden).toEqual([])
    })

    test(`failed and missing states fit the sheet (${vp.width})`, async ({ page }) => {
      const seen = await mock(page)
      await page.goto('/v3/prospectus')
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7, { timeout: 60_000 })
      await page.locator('[data-testid="prospectus-row"][data-symbol="GAMMA"]').tap()
      await expect(page.getByTestId('prospectus-failed')).toContainText('too few cited facts')
      await noSideScroll(page)
      await page.getByTestId('prospectus-back').tap()
      await page.locator('[data-testid="prospectus-row"][data-symbol="DELTA"]').tap()
      await expect(page.getByTestId('prospectus-missing')).toContainText('Not written yet — queued')
      await noSideScroll(page)
      expect(seen.forbidden).toEqual([])
    })
  })
}
