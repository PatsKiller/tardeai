import { expect, test } from '@playwright/test'

const posture = {
  ok: true,
  momentum: {
    generated_at: '2026-07-24T14:10:01Z',
    rows: [
      { etf: 'XLK', sector: 'Technology', as_of: '2026-07-23', rs5: 9.36, rs20: -3.22, rs60: -9.36, slope: 2.89, state: 'IMPROVING', breadth_pct: 19, breadth_coverage_n: 58, breadth_membership_n: 58, breadth_quality: 'ok', book_pct: 13.6, book_direct_pct: 8.0, quality: 'narrow_participation' },
      { etf: 'XLF', sector: 'Financials', as_of: '2026-07-23', rs5: -0.5, rs20: 3.3, rs60: 3.11, slope: 0.0, state: 'LEADING', breadth_pct: 48, breadth_coverage_n: 58, breadth_membership_n: 58, breadth_quality: 'ok', book_pct: 23.4, book_direct_pct: 16.4 },
      { etf: 'XLE', sector: 'Energy', as_of: '2026-07-23', rs5: 7.85, rs20: 10.26, rs60: 2.28, slope: 2.28, state: 'LEADING', breadth_pct: 79, breadth_coverage_n: 56, breadth_membership_n: 56, breadth_quality: 'ok', book_pct: 3.6, book_direct_pct: 0.0 },
      { etf: 'XLV', sector: 'Healthcare', as_of: '2026-07-23', rs5: 0.25, rs20: 3.52, rs60: 7.01, slope: -2.21, state: 'WEAKENING', breadth_pct: 45, breadth_coverage_n: 60, breadth_membership_n: 60, breadth_quality: 'ok', book_pct: 8.6 },
      { etf: 'XLI', sector: 'Industrials', as_of: '2026-07-23', rs5: 2.12, rs20: -2.22, rs60: 1.94, slope: -1.1, state: 'LAGGING', breadth_pct: 34, breadth_coverage_n: 58, breadth_membership_n: 58, breadth_quality: 'ok', book_pct: 16.3 },
      { etf: 'XLRE', sector: 'Real Estate', as_of: '2026-07-13', rs5: 1.28, rs20: -2.44, rs60: -4.03, slope: -2.5, state: null, state_raw: 'LAGGING', quarantined: true, quarantine_reason: 'stale_row', breadth_pct: 45, book_pct: 0.6 },
    ],
    market: {
      state_line: 'Market: SPY -1.2% wk · equal-weight leading cap-weight (+0.3% 20d) · small caps lagging · top-movers NH/NL sample 15/15 · 7/11 sectors lagging',
      indices: [{ symbol: 'SPY', short: -1.23, mid: 0.85, long: 4.29 }],
      styles: [
        { key: 'growth_vs_value', pair: 'VUG−VTV', s20: -6.04, state: 'LAGGING' },
        { key: 'small_vs_large', pair: 'IWM−SPY', s20: -2.67, state: 'LAGGING' },
        { key: 'equal_vs_cap', pair: 'RSP−SPY', s20: 0.28, state: 'WEAKENING' },
      ],
      internals: { new_high: 15, new_low: 15, scope: 'capped_top_movers_sample' },
    },
    transitions_today: [],
    truth_ledger: { calculation_version: 'sector-rs-v3-exact20' },
  },
}

const industries = {
  ok: true,
  captured_at: '2026-07-23T16:30:05Z',
  capture_kind: 'refresh',
  spy_baseline: { w1: -2.22, m1: -0.26, provider: 'finviz_elite', quality: 'same_vendor_same_run' },
  industries: [
    { industry: 'Aerospace & Defense', sector: 'Industrials', perf_week: -1.8, perf_month: -9.41, rel1w: 0.42, rel1m: -9.15, state: 'IMPROVING', mapping_quality: 'exact', held: ['NOC', 'RTX', 'SPCX'], watched: ['BETA', 'MRLN'] },
    { industry: 'Building Products & Equipment', sector: 'Industrials', perf_week: -0.93, perf_month: -0.14, rel1w: 1.29, rel1m: 0.12, state: 'LEADING', mapping_quality: 'exact', held: [], watched: [] },
    { industry: 'Chemicals', sector: 'Materials', perf_week: 6.32, perf_month: 3.85, rel1w: 8.54, rel1m: 4.11, state: 'LEADING', mapping_quality: 'exact', held: [], watched: [] },
    { industry: 'Biotechnology', sector: 'Healthcare', perf_week: 0.48, perf_month: 5.18, rel1w: 2.7, rel1m: 5.44, state: 'LEADING', mapping_quality: 'exact', held: [], watched: [] },
    { industry: 'Computer Hardware', sector: 'Technology', perf_week: 16.14, perf_month: -6.96, rel1w: 18.36, rel1m: -6.7, state: 'IMPROVING', mapping_quality: 'exact', held: ['ANET'], watched: ['ANET', 'SMCI'] },
  ],
  transitions_confirmed: [],
  candidates: { mode: 'intraday_research_only', watch_rail: [] },
  data_quality: { unmapped_count: 0, mapping_version: 'finviz-industry-gics-v1-2026-07-24' },
}

const recommendations = {
  ok: true,
  recommendations: {
    generated_at: '2026-07-24T14:10:01Z',
    as_of: '2026-07-24',
    mode: 'SHADOW',
    groups: {
      get_into: [],
      protect: [
        { id: 'pput-XLI', group: 'protect', title: 'WITHHELD · XLI protective put failed liquidity rails', mode: 'SHADOW', instruments: [{ symbol: 'XLI', kind: 'protective put vs held shares' }], entry_logic: 'No structure may be staged until open-interest and spread rails pass.', invalidation: 'Industrials recovers out of LAGGING.', quality_gate: { passed: false, reasons: ['spread 22.2% > 12%', 'volume 8 below threshold'] } },
        { id: 'moveout-ARKX', group: 'protect', title: 'CORE TRIM · ARKX', mode: 'SHADOW', instruments: [{ symbol: 'ARKX', kind: 'holding' }], entry_logic: 'Stage only through the governed trim workflow.', invalidation: 'Industrials recovers and ARKX reclaims the 50DMA.' },
      ],
      short_side: [],
      income: [],
    },
    empty_reasons: { get_into: 'Defensive lean remains active and requires dated review.' },
    directive_reviews: [{ requires_review: true, conflicting_sectors: ['Energy', 'Technology'] }],
  },
}

const sectors = {
  ok: true,
  spy_change_pct: 0.584,
  sectors: [
    { sector: 'Financials', etf: 'XLF', etf_change_pct: 0.797, spy_change_pct: 0.584, rel_strength: 0.21, momentum: 'leading', constituent_count: 27, setup_count: 5, book_weight_pct: 23.4, rs_20d_pct: 3.86, rs_trend: 'improving', candidates: [{ symbol: 'ARES', rsi: 49.95, trend: 'bearish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
    { sector: 'Healthcare', etf: 'XLV', etf_change_pct: 0.929, spy_change_pct: 0.584, rel_strength: 0.35, momentum: 'leading', constituent_count: 225, setup_count: 7, book_weight_pct: 8.6, rs_20d_pct: 3.12, rs_trend: 'improving', candidates: [{ symbol: 'ABT', rsi: 65.76, trend: 'neutral', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: false, cio_view: null }] },
    { sector: 'Consumer Discretionary', etf: 'XLY', etf_change_pct: 0.912, spy_change_pct: 0.584, rel_strength: 0.32, momentum: 'leading', constituent_count: 93, setup_count: 8, book_weight_pct: 3.5, rs_20d_pct: -4.62, rs_trend: 'deteriorating', candidates: [{ symbol: 'ANF', rsi: 51.99, trend: 'bullish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
    { sector: 'Industrials', etf: 'XLI', etf_change_pct: 0.868, spy_change_pct: 0.584, rel_strength: 0.28, momentum: 'leading', constituent_count: 174, setup_count: 3, book_weight_pct: 16.3, rs_20d_pct: -2.22, rs_trend: 'deteriorating', candidates: [{ symbol: 'ALSN', rsi: 65.43, trend: 'bullish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
  ],
}

async function installRoutes(page: any) {
  await page.route('**/api/**', async (route: any) => {
    const url = new URL(route.request().url())
    let data: any = {}
    if (url.pathname === '/api/v2/defense/posture') data = posture
    else if (url.pathname === '/api/v2/defense/industries') data = industries
    else if (url.pathname === '/api/v2/defense/recommendations') data = recommendations
    else if (url.pathname === '/api/v2/sectors/monitor') data = sectors
    else if (url.pathname === '/api/health') data = { ok: true, data: { ok: true } }
    else data = { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
  })
}

async function assertNoHorizontalOverflow(page: any) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(2)
}

test('defense desktop and narrow render gate', async ({ page }) => {
  await installRoutes(page)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/v3/defense')
  await expect(page.getByText('Defense Desk', { exact: true })).toBeVisible()
  await expect(page.getByText('Institutional rotation brief', { exact: true })).toBeVisible()
  await expect(page.locator('b').filter({ hasText: 'No governed add card is active.' }).first()).toBeVisible()
  await expect(page.getByText(/WITHHELD/).first()).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'render-artifacts/defense-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByText('Defense Desk', { exact: true })).toBeVisible()
  await expect(page.getByText('Institutional rotation brief', { exact: true })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'render-artifacts/defense-narrow.png', fullPage: true })
})

test('sectors desktop and narrow render gate', async ({ page }) => {
  await installRoutes(page)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/v3/sectors')
  await expect(page.getByText('Sectors & Industries', { exact: true })).toBeVisible()
  await expect(page.getByText(/screen matches/i).first()).toBeVisible()
  await page.getByRole('button', { name: /Screened names/ }).first().click()
  await expect(page.getByText('THIN COVERAGE', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('NO CIO VIEW', { exact: true }).first()).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'render-artifacts/sectors-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByText('Sectors & Industries', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Screened names/ }).first().click()
  await expect(page.getByText('THIN COVERAGE', { exact: true }).first()).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'render-artifacts/sectors-narrow.png', fullPage: true })
})
