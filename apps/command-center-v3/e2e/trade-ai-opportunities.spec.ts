/** Trade AI opportunities page (operator-approved Gate 3 Main.dc.html, 2026-10-22). Every API request is
 *  fulfilled locally from the captured scanner fixture (+ one synthetic Active Trader alerts row); the test
 *  fails on any non-GET request. */
import { expect, test, type Page } from '@playwright/test'
import { TRADE_AI_FIXTURE } from '../src/lib/tradeAiOpportunities.fixture'

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = url.pathname === '/api/v2/trade-ai/scanner' ? TRADE_AI_FIXTURE.scanner
      : url.pathname === '/api/v3/active-trader/alerts' ? TRADE_AI_FIXTURE.alerts
        : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('six tiles filter the float-first table; Gate 2 fields show —', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Trade+AI')
  await expect(page.getByTestId('trade-ai-opportunities')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('ta-population-line')).toContainText('awareness only')
  // Latest run vs today's universe are named separately (operator 2026-10-23).
  await expect(page.getByTestId('ta-latest-run-tally')).toContainText('latest run:')
  await expect(page.getByTestId('ta-universe-count')).toContainText('rows today (all runs)')
  await expect(page.getByTestId('ta-run-age')).toContainText('Latest run')
  await expect(page.getByTestId('ta-tile-go')).toContainText("today's universe")
  const rows = page.getByTestId('ta-row')
  const total = await rows.count()
  expect(total).toBeGreaterThan(20)

  await expect(page.getByTestId('ta-tile-grade')).toBeDisabled()
  await page.getByTestId('ta-tile-go').click()
  await expect(rows).toHaveCount(3)
  await expect(page.getByTestId('ta-filter-chip')).toHaveText(/Decision: GO/)
  await page.getByTestId('ta-tile-go').click()
  await expect(rows).toHaveCount(total)

  await page.getByTestId('ta-tile-float').click()
  for (const t of await rows.allTextContents()) expect(t).toMatch(/\d\.\d\dM/)
  await page.getByRole('button', { name: 'Clear all' }).click()
  await expect(rows).toHaveCount(total)

  // Gate 2 cells carry the explanatory tooltip instead of an invented value.
  await expect(rows.first().locator('[data-gate2="true"]').first()).toHaveAttribute('title', /Gate 2/)
  expect(writes).toEqual([])
})

test('analysis panel shows served Level 2 entry signals; cards view works', async ({ page }) => {
  const writes: string[] = []
  await mockApi(page, writes)
  await page.goto('/v3/trading?tab=Trade+AI')
  await page.getByRole('button', { name: 'Show analysis for BHVN' }).click({ timeout: 60_000 })
  const panel = page.getByTestId('ta-analysis')
  await expect(panel).toContainText('BHVN')
  await expect(page.getByTestId('ta-l2-state')).toHaveText('AT approaching')
  await expect(page.getByTestId('l2-spread')).toHaveAttribute('data-on', 'true')
  await expect(page.getByTestId('l2-volume_acceleration')).toHaveAttribute('data-on', 'true')
  await expect(page.getByTestId('l2-tape_flip')).toHaveAttribute('data-on', 'null')

  await page.getByRole('button', { name: 'Show analysis for SKYQ' }).click()
  await expect(page.getByTestId('ta-l2-state')).toHaveText('NOT WATCHED')

  await page.getByTestId('ta-view-cards').click()
  await expect(page.getByTestId('ta-card').first()).toBeVisible()
  await expect(page.getByTestId('ta-momentum-drawer')).toContainText('Shared Momentum')
  await expect(page.getByTestId('ta-classic-drawer')).toContainText('Scanner tools')
  expect(writes).toEqual([])
})

test('narrow viewport: no horizontal page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, [])
  await page.goto('/v3/trading?tab=Trade+AI')
  await expect(page.getByTestId('trade-ai-opportunities')).toBeVisible({ timeout: 60_000 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  expect(overflow).toBeFalsy()
})

test('run age: red after 10 min in the scalp window, on the page and in the header', async ({ page }) => {
  // Fixture run finished 2026-10-22T13:02:47Z = 09:02 ET (Thursday). At 09:20 ET it is 17 min old.
  await page.clock.setFixedTime(new Date('2026-10-22T09:20:00-04:00'))
  await mockApi(page, [])
  // The header reads the same run from /trade-ai/summary; serve it the same fixture (later routes win).
  await page.route(/\/api\/v2\/trade-ai\/summary/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(TRADE_AI_FIXTURE.scanner) }))
  await page.goto('/v3/trading?tab=Trade+AI')
  const age = page.getByTestId('ta-run-age')
  await expect(age).toBeVisible({ timeout: 60_000 })
  await expect(age).toHaveAttribute('data-run-age-tone', 'bad')
  await expect(age).toContainText('finished 09:02 ET · 17 min ago')
  await expect(page.locator('.metric-strip-tile [data-run-age-tone]').first()).toHaveAttribute('data-run-age-tone', 'bad')
})

test('run age: fresh run is not flagged', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-22T09:05:00-04:00'))
  await mockApi(page, [])
  await page.goto('/v3/trading?tab=Trade+AI')
  await expect(page.getByTestId('ta-run-age')).toHaveAttribute('data-run-age-tone', 'ok', { timeout: 60_000 })
})

// 2026-10-23 alignment (SAIQ): an unverified headline is labelled with the SHARED verdict, the readiness block
// says what is missing, and the AT veto is named as AT's (not "L2 veto · 0/5") — at desktop and 412 px.
const SAIQ_ROW = {
  symbol: 'SAIQ', decision: 'MANUAL_REVIEW', float_m: '2.21', volume: 2025083, rvol: 12.84, change_pct: '25.76',
  catalyst: 'WISeSat.Space and SEALSQ Advance Satellite Cybersecurity Hardening', catalyst_source: 'yahoo_finance',
  catalyst_verified: false, catalyst_confidence: 0,
  setup_readiness: {
    schema: 'SetupReadiness@v1', status: 'NOT_READY', ready: false, passed: 4, required: 5, blockers: [],
    driven_by: [{ id: 'rvol', label: 'RVOL', status: 'PASSED', value_text: '12.8x', rule: '≥ 5x' },
      { id: 'catalyst', label: 'Verified catalyst', status: 'FAILED', value_text: 'unverified headline', rule: 'verified, current session' }],
    missing: ['Verified catalyst: unverified headline — scan marked it NOT verified (yahoo_finance, confidence 0); Hermes 08:25: no clear catalyst (no primary source)'],
    summary: 'NOT READY — needs 5/5, has 4/5',
    catalyst: { status: 'UNVERIFIED_HEADLINE', text: 'WISeSat.Space and SEALSQ Advance Satellite Cybersecurity Hardening', reason: 'scan marked it NOT verified (yahoo_finance, confidence 0); Hermes 08:25: no clear catalyst (no primary source)' },
  },
}
const SAIQ_ALERT = { symbol: 'SAIQ', kind: 'PREMARKET_WATCH', verdict: 'VETO', at: '2026-10-23T08:55:01-04:00', ts_epoch: 4e9,
  veto_reasons: ['BELOW_PM_VWAP', 'L2_ASK_HEAVY'], l2: { source: 'moomoo', levels: 10, spread_bps: 14.9, depth_ratio: 0.191, age_s: 1 }, signals: null }

for (const width of [1440, 412]) {
  test(`SAIQ unverified headline + readiness + AT veto label @${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url())
      const body = url.pathname === '/api/v2/trade-ai/scanner'
        ? { ...TRADE_AI_FIXTURE.scanner, tickers: [SAIQ_ROW, ...(TRADE_AI_FIXTURE.scanner.tickers as any[])] }
        : url.pathname === '/api/v3/active-trader/alerts'
          ? { ...TRADE_AI_FIXTURE.alerts, decisions: [SAIQ_ALERT, ...((TRADE_AI_FIXTURE.alerts as any).decisions ?? [])] }
          : { ok: true, data: {} }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto('/v3/trading?tab=Trade+AI')
    const row = page.locator('[data-testid="ta-row"][data-symbol="SAIQ"]')
    await expect(row).toBeVisible({ timeout: 60_000 })
    await expect(row.getByTestId('ta-catalyst-verdict')).toHaveAttribute('data-status', 'UNVERIFIED_HEADLINE')
    await expect(row.getByTestId('ta-l2-brief')).toHaveText('AT veto · L2 1/2')
    await expect(row.getByTestId('ta-ready')).toHaveText('not ready · 4/5')
    await page.getByRole('button', { name: 'Show analysis for SAIQ' }).click()
    const ready = page.getByTestId('ta-readiness')
    await expect(ready).toHaveAttribute('data-ready', 'NOT_READY')
    await expect(ready).toContainText('Missing: Verified catalyst: unverified headline')
    await expect(ready).toContainText('Hermes 08:25')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
}
