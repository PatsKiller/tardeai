/** Ticker Prospectus (/v3/prospectus) on the built app, approved design prospectus/v001, with every /api call fulfilled
 *  here (synthetic tickers and made-up numbers only — public repo). Port 7777 and any non-local origin fail the test.
 *  Desktop 1440: list table, stat tiles, chips, search, full report (tiles, charts, relative performance with window
 *  toggle, peers, estimates / ownership / risk, stop plan, scenarios, narrative, macro / filings / call / options, coverage,
 *  sources), versions, states, partial report with no blocks, operator-only Rewrite with confirm, ticker-modal link.
 *  Phone 412 and 390 with touch: tap a row → full-screen sheet, ← Back, 44px targets, downloads, narrative sections
 *  tap to open, peer table scrolls inside its card, no sideways page scroll.
 *  Screenshots go to $PROSPECTUS_SHOTS_DIR when set (keep real-data captures out of the repo). */
import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import {
  PROSPECTUS_ACME, PROSPECTUS_ACME_OLD, PROSPECTUS_BETA, PROSPECTUS_GAMMA_FAILED, PROSPECTUS_INDEX, PROSPECTUS_THETA_PARTIAL,
} from '../src/fixtures/prospectus.fixture'

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
        return json({ ok: true, queued: true, symbol: 'ACME', position: 1 }, 202)
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
      if (sym === 'THETA') return json(PROSPECTUS_THETA_PARTIAL)
      if (sym === 'EPSI') return json({ symbol: 'EPSI', status: 'queued', sections: [], charts: [], versions: [] })
      return json({ ok: false, error: 'not written yet', symbol: sym, status: 'missing' }, 404)
    }
    if (p === '/api/v3/opportunities/ACME') return json({ data: { symbol: 'ACME', assessment: { type: 'holding' }, market: {}, profile: { company: 'Acme Synthetic Corp' } } })
    return json({ ok: true, data: {} })
  })
  return seen
}

async function shot(page: Page, name: string, fullPage = false) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  // The shell scrolls inside .app-main; for a whole-report capture let the document grow instead.
  if (fullPage) await page.addStyleTag({ content: '.app-shell{height:auto!important}.app-body,.app-main{overflow:visible!important}' })
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage })
}

async function noSideScroll(page: Page) {
  const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth])
  expect(sw, 'no horizontal page scroll').toBeLessThanOrEqual(iw + 1)
  const wide = await page.locator('.psp-row, .psp-tbl, .psp-section, .psp-chart, .psp-report-head, .psp-stats, .psp-card, .psp-tile').evaluateAll(els =>
    els.filter(e => (e as HTMLElement).offsetParent !== null && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.className))
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

async function expectBlocks(page: Page) {
  await expect(page.getByTestId('prospectus-tile-verdict')).toContainText('HOLD')
  await expect(page.getByTestId('prospectus-tile-verdict')).toContainText('CIO conviction 72/100')
  await expect(page.getByTestId('prospectus-tile-price')).toContainText('$51.00')
  await expect(page.getByTestId('prospectus-tile-position')).toContainText('$5,100.00')
  await expect(page.getByTestId('prospectus-tile-stop')).toContainText('$42.00')
  await expect(page.getByTestId('prospectus-tile-stop')).toContainText('house $45.50')
  await expect(page.getByTestId('prospectus-stop-house')).toHaveText('$45.50')
  await expect(page.getByTestId('prospectus-stop-broker')).toContainText('$42.00 · Active')
  await expect(page.getByTestId('prospectus-stop-comparison')).toContainText('7.7% below the house level')
  await expect(page.getByTestId('prospectus-stop-advisory')).toHaveText('advisory — no AI places, sizes or stops orders')
  await expect(page.getByTestId('prospectus-rel-chart')).toBeVisible()
  await expect(page.getByTestId('prospectus-returns')).toContainText('S&P 500')
  await expect(page.getByTestId('prospectus-returns')).toContainText('Nasdaq-100')
  await expect(page.getByTestId('prospectus-relative')).toContainText('3 of 14')
  await expect(page.getByTestId('prospectus-peer-subject')).toContainText('ACME')
  await expect(page.getByTestId('prospectus-peer-median')).toContainText('Peer median')
  await expect(page.getByTestId('prospectus-scenarios')).toContainText('Analysis, not an order')
  await expect(page.getByTestId('prospectus-scenario-bull')).toContainText('$70.00')
  await expect(page.getByTestId('prospectus-macro')).toContainText('10-year Treasury yield')
  await expect(page.locator('[data-testid="prospectus-filings"] a[href="https://example.com/acme-10q"]')).toHaveCount(1)
  await expect(page.getByTestId('prospectus-coverage-chip')).toHaveCount(10)
  await expect(page.locator('[data-testid="prospectus-coverage-chip"][data-status="failed"]')).toHaveClass(/psp-tone-danger/)
  await expect(page.locator('[data-testid="prospectus-coverage-chip"][data-status="stale"]').first()).toHaveClass(/psp-tone-warning/)
}

test.describe('Prospectus at 1440', () => {
  test.beforeEach(async ({ page }) => { await page.setViewportSize({ width: 1440, height: 900 }) })

  test('nav entry, stat tiles, chips, search, full report with every block, downloads, versions', async ({ page }) => {
    const seen = await mock(page)
    await page.goto('/v3/prospectus')
    const nav = page.locator('nav a[href="/v3/prospectus"]')
    await expect(nav).toBeVisible({ timeout: 60_000 })
    // Appended to Intel: Communications stays where it was, Prospectus comes right after it.
    const hrefs = await page.locator('nav a').evaluateAll(as => as.map(a => a.getAttribute('href')))
    expect(hrefs.indexOf('/v3/prospectus')).toBe(hrefs.indexOf('/v3/communications') + 1)

    await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
    await expect(page.getByTestId('prospectus-total-ready')).toContainText('3 / 7')
    await expect(page.getByTestId('prospectus-budget')).toContainText('$150.25 left')
    await expect(page.getByTestId('prospectus-budget-today')).toHaveText('today $6.50 of $25.00 cap')
    await expect(page.getByTestId('prospectus-row').first()).toHaveAttribute('data-symbol', 'GAMMA')
    const acmeRow = page.locator('[data-testid="prospectus-row"][data-symbol="ACME"]')
    await expect(acmeRow.getByTestId('prospectus-model')).toHaveText('Fable')
    await expect(acmeRow.getByTestId('prospectus-type')).toHaveText('Holding')
    await expect(acmeRow.getByTestId('prospectus-verdict')).toContainText('moat intact')
    await expect(page.locator('[data-symbol="BETA"]').getByTestId('prospectus-status')).toHaveText('Needs rewrite')
    await expect(page.locator('[data-symbol="BETA"]').getByTestId('prospectus-model')).toHaveText('Opus')
    await expect(page.locator('[data-symbol="THETA"]').getByTestId('prospectus-status')).toHaveText('Partial')
    await expect(page.locator('[data-symbol="GAMMA"]').getByTestId('prospectus-verdict')).toContainText('too few cited facts')
    await expect(page.locator('[data-symbol="DELTA"]').getByTestId('prospectus-verdict')).toContainText('Not written yet — queued')
    await expect(page.locator('[data-symbol="DELTA"]').getByTestId('prospectus-status')).toHaveText('Missing')
    await expect(page.getByTestId('prospectus-page')).not.toContainText(/\d{4}-\d{2}-\d{2}T\d{2}:/)

    for (const [chip, n] of [['holdings', 3], ['watch', 4], ['rewrite', 2], ['all', 7]] as const) {
      await page.getByTestId(`prospectus-filter-${chip}`).click()
      await expect(page.getByTestId('prospectus-row')).toHaveCount(n)
    }
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
    await expect(page.getByTestId('prospectus-back')).toHaveText('← All prospectuses')
    await expect(page.getByTestId('prospectus-tiles')).toBeVisible()
    await shot(page, 'prospectus-detail-1440')
    await expect(page.getByTestId('prospectus-summary')).toContainText('Hold.')
    await expect(page.getByTestId('prospectus-section')).toHaveCount(8)
    await expect(page.getByTestId('prospectus-section').first()).toHaveAttribute('data-section', 'business_and_moat')
    await expect(page.getByTestId('prospectus-chart')).toHaveCount(4)
    await expect(page.locator('[data-chart-id="price_1y"] svg').first()).toBeVisible()
    await expect(page.getByTestId('prospectus-chart-levels')).toContainText('Stop 42')
    await expect(page.getByTestId('prospectus-target-range')).toContainText('Mean 58')
    await expectBlocks(page)
    await expect(page.getByTestId('prospectus-rel-chart')).toHaveAttribute('data-window', '1Y')
    await page.getByTestId('prospectus-rel-3M').click()
    await expect(page.getByTestId('prospectus-rel-chart')).toHaveAttribute('data-window', '3M')
    await expect(page.getByTestId('prospectus-sources')).toContainText('c1')
    await expect(page.getByTestId('prospectus-cite-inline').first()).toHaveText('c1')
    await expect(page.getByTestId('prospectus-rewrite')).toHaveCount(0)
    await expectDownloads(page, 'ACME')
    await noSideScroll(page)

    await page.getByTestId('prospectus-version').selectOption('20260926T120000Z')
    await expect(page).toHaveURL(/version=20260926T120000Z/)
    await expect(page.getByTestId('prospectus-summary')).toContainText('Older version')
    await expectDownloads(page, 'ACME', '20260926T120000Z')
    expect(seen.detail).toContain('/api/v2/prospectus/ACME?version=20260926T120000Z')

    await page.getByTestId('prospectus-back').click()
    await expect(page).toHaveURL(/\/v3\/prospectus$/)
    await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
    if (SHOTS) {
      await page.goto('/v3/prospectus/ACME')
      await expect(page.getByTestId('prospectus-tiles')).toBeVisible()
      await shot(page, 'prospectus-detail-1440-full', true)
    }
    expect(seen.posts).toEqual([])
    expect(seen.forbidden).toEqual([])
  })

  test('states: loading, missing, failed with reason, queued, stale, partial with no blocks', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', e => errors.push(String(e)))
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
    await expect(page.getByTestId('prospectus-detail-status')).toHaveText('Needs rewrite')
    await expectDownloads(page, 'BETA')

    await page.goto('/v3/prospectus/THETA')
    await expect(page.getByTestId('prospectus-report')).toHaveAttribute('data-state', 'partial', { timeout: 60_000 })
    await expect(page.getByTestId('prospectus-partial-banner')).toContainText('prices: empty')
    expect(await page.getByTestId('prospectus-na').count()).toBeGreaterThanOrEqual(9)
    await expect(page.getByTestId('prospectus-tile-position')).toContainText('Not held')
    await expect(page.getByTestId('prospectus-tile-price')).toContainText('not available yet')
    await expectDownloads(page, 'THETA')
    await shot(page, 'prospectus-partial-1440')
    expect(errors).toEqual([])
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
    await expect(page.getByTestId('prospectus-rewrite-msg')).toContainText('Rewrite queued · #1 in line')
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

    test(`tap row → full-screen sheet, blocks, details, downloads, ← Back, 44px targets, no sideways scroll (${vp.width})`, async ({ page }) => {
      const seen = await mock(page)
      await page.goto('/v3/prospectus')
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7, { timeout: 60_000 })
      await expect(page.getByTestId('prospectus-sheet')).toHaveCount(0)
      await expect(page.getByTestId('prospectus-total-ready')).toContainText('3 / 7')
      await expect(page.getByTestId('prospectus-budget')).toContainText('$150.25')
      await tapTarget(page, '[data-testid^="prospectus-filter-"]')
      await tapTarget(page, '[data-testid="prospectus-row"]', 44)
      await tapTarget(page, '[data-testid="prospectus-search"]')
      for (const [chip, n] of [['holdings', 3], ['watch', 4], ['rewrite', 2], ['all', 7]] as const) {
        await page.getByTestId(`prospectus-filter-${chip}`).tap()
        await expect(page.getByTestId('prospectus-row')).toHaveCount(n)
      }
      await expect(page.locator('[data-symbol="ACME"]')).toContainText('Holding · Fable · Oct 26')
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
      await expect(page.getByTestId('prospectus-back')).toHaveText('← Back')
      await tapTarget(page, '[data-testid="prospectus-back"]')
      await tapTarget(page, '[data-testid="prospectus-dl-pdf"], [data-testid="prospectus-dl-docx"], [data-testid="prospectus-open-html"]', 48)
      await expectDownloads(page, 'ACME')
      await expect(page.getByTestId('prospectus-tile-yield')).toBeHidden()
      await expectBlocks(page)
      await tapTarget(page, '[data-testid^="prospectus-rel-"][data-testid$="M"], [data-testid="prospectus-rel-YTD"], [data-testid="prospectus-rel-1Y"], [data-testid="prospectus-rel-3Y"]')
      // Peer table scrolls inside its card; the page never does.
      const peer = await page.getByTestId('prospectus-peers-scroll').evaluate(el => [el.scrollWidth, el.clientWidth])
      expect(peer[0], 'peer table wider than the card (it scrolls)').toBeGreaterThan(peer[1])
      // Narrative sections are tap-to-open; institutional blocks are already expanded.
      const sections = page.getByTestId('prospectus-section')
      await expect(sections).toHaveCount(8)
      expect(await sections.evaluateAll(els => els.every(e => e.tagName === 'DETAILS' && !(e as HTMLDetailsElement).open))).toBe(true)
      await tapTarget(page, '.psp-summary')
      const risks = page.locator('[data-testid="prospectus-section"][data-section="risks"]')
      await risks.locator('summary').scrollIntoViewIfNeeded()
      await risks.locator('summary').tap()
      await expect(risks).toHaveAttribute('open', '')
      await expect(risks).toContainText('Customer concentration')
      const sheetScroll = await sheet.evaluate(el => [el.scrollWidth, el.clientWidth])
      expect(sheetScroll[0], 'sheet has no sideways scroll').toBeLessThanOrEqual(sheetScroll[1] + 1)
      await noSideScroll(page)
      await sheet.evaluate(el => el.scrollTo(0, 0))
      await shot(page, `prospectus-detail-${vp.width}`)
      await page.getByTestId('prospectus-relative').scrollIntoViewIfNeeded()
      await shot(page, `prospectus-detail-${vp.width}-blocks`)
      await risks.scrollIntoViewIfNeeded()
      await shot(page, `prospectus-detail-${vp.width}-sections`)

      await sheet.evaluate(el => el.scrollTo(0, 0))
      await page.getByTestId('prospectus-back').tap()
      await expect(page).toHaveURL(/\/v3\/prospectus(\?|$)/)
      await expect(page.getByTestId('prospectus-sheet')).toHaveCount(0)
      await expect(page.getByTestId('prospectus-row')).toHaveCount(7)
      expect(seen.posts).toEqual([])
      expect(seen.forbidden).toEqual([])
    })

    test(`failed, missing and partial states fit the sheet (${vp.width})`, async ({ page }) => {
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
      await page.getByTestId('prospectus-back').tap()
      await page.locator('[data-testid="prospectus-row"][data-symbol="THETA"]').scrollIntoViewIfNeeded()
      await page.locator('[data-testid="prospectus-row"][data-symbol="THETA"]').tap()
      await expect(page.getByTestId('prospectus-partial-banner')).toBeVisible()
      expect(await page.getByTestId('prospectus-na').count()).toBeGreaterThanOrEqual(8)
      await noSideScroll(page)
      expect(seen.forbidden).toEqual([])
    })
  })
}
