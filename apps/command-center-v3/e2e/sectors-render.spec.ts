import { expect, test } from '@playwright/test'

const posture = {
  ok: true,
  momentum: {
    generated_at: '2026-07-24T14:10:01Z',
    rows: [
      { etf: 'XLK', sector: 'Technology', as_of: '2026-07-23', rs20: -3.22, slope: 2.89, state: 'IMPROVING', breadth_pct: 19, book_pct: 13.6 },
      { etf: 'XLF', sector: 'Financials', as_of: '2026-07-23', rs20: 3.3, slope: 0.0, state: 'LEADING', breadth_pct: 48, book_pct: 23.4 },
      { etf: 'XLE', sector: 'Energy', as_of: '2026-07-23', rs20: 10.26, slope: 2.28, state: 'LEADING', breadth_pct: 79, book_pct: 3.6 },
      { etf: 'XLI', sector: 'Industrials', as_of: '2026-07-23', rs20: -2.22, slope: -1.1, state: 'LAGGING', breadth_pct: 34, book_pct: 16.3 },
    ],
  },
}

const industries = {
  ok: true,
  captured_at: '2026-07-23T16:30:05Z',
  capture_kind: 'refresh',
  industries: [
    { industry: 'Aerospace & Defense', sector: 'Industrials', rel1w: 0.42, rel1m: -9.15, state: 'IMPROVING' },
    { industry: 'Building Products & Equipment', sector: 'Industrials', rel1w: 1.29, rel1m: 0.12, state: 'LEADING' },
    { industry: 'Oil & Gas E&P', sector: 'Energy', rel1w: 2.2, rel1m: 4.7, state: 'LEADING' },
    { industry: 'Biotechnology', sector: 'Healthcare', rel1w: 2.7, rel1m: 5.44, state: 'LEADING' },
    { industry: 'Computer Hardware', sector: 'Technology', rel1w: 18.36, rel1m: -6.7, state: 'IMPROVING' },
  ],
}

const recommendations = {
  ok: true,
  recommendations: {
    generated_at: '2026-07-24T14:10:01Z',
    as_of: '2026-07-24',
    accounts: { schwab_rollover_ira: 'Rollover IRA' },
    groups: {
      get_into: [{
        id: 'rotatein-XLE-2026-07-24', group: 'get_into',
        title: 'ROTATE-IN · Energy (LEADING, RS20 +10.3)',
        instruments: [{ symbol: 'XLE', kind: 'sector ETF', price: 89.4, note: 'policy and risk-capacity qualified' }],
        accounts: ['schwab_rollover_ira'], direction: 'long',
        size_band: 'account-specific; see sizing matrix',
        entry_logic: 'stagger only on a pullback toward the 20DMA',
        invalidation: 'Energy exits LEADING on a two-close confirmation or account capacity falls below 1%',
        factors: [{ name: 'sector state', value: 'LEADING' }, { name: 'RS20 vs SPY', value: '+10.26%' }],
        as_of: '2026-07-24', mode: 'SHADOW',
        levels: { price: 89.4, entry_zone: 'pullback toward 20DMA ≈ $87.80', stop: 'thesis stop: exits LEADING' },
        account_sizing: {
          schwab_rollover_ira: { pct_band: [1, 2], dollar_band: [12000, 24000] },
        },
        allocation_policy: {
          schwab_rollover_ira: {
            current_account_weight_pct: 3.6, risk_target_pct: 8.1,
            capacity_pct: 4.5, quality: 'ok',
          },
        },
      }],
      protect: [
        { id: 'pput-XLI', title: 'WITHHELD · XLI protective put failed liquidity rails', mode: 'SHADOW', invalidation: 'Industrials recovers.' },
        { id: 'moveout-ARKX', title: 'CORE TRIM · ARKX', mode: 'SHADOW', invalidation: 'ARKX reclaims trend.' },
      ],
      short_side: [], income: [],
    },
  },
}

const sectors = {
  ok: true,
  spy_change_pct: 0.584,
  sectors: [
    { sector: 'Financials', etf: 'XLF', etf_change_pct: 0.797, rel_strength: 0.21, momentum: 'leading', constituent_count: 27, setup_count: 5, book_weight_pct: 23.4, rs_20d_pct: 3.86, rs_trend: 'improving', candidates: [{ symbol: 'ARES', rsi: 49.95, trend: 'bearish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
    { sector: 'Healthcare', etf: 'XLV', etf_change_pct: 0.929, rel_strength: 0.35, momentum: 'leading', constituent_count: 225, setup_count: 7, book_weight_pct: 8.6, rs_20d_pct: 3.12, rs_trend: 'improving', candidates: [{ symbol: 'ABT', rsi: 65.76, trend: 'neutral', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: false, cio_view: null }] },
    { sector: 'Consumer Discretionary', etf: 'XLY', etf_change_pct: 0.912, rel_strength: 0.32, momentum: 'leading', constituent_count: 93, setup_count: 8, book_weight_pct: 3.5, rs_20d_pct: -4.62, rs_trend: 'deteriorating', candidates: [{ symbol: 'ANF', rsi: 51.99, trend: 'bullish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
    { sector: 'Industrials', etf: 'XLI', etf_change_pct: 0.868, rel_strength: 0.28, momentum: 'leading', constituent_count: 174, setup_count: 3, book_weight_pct: 16.3, rs_20d_pct: -2.22, rs_trend: 'deteriorating', candidates: [{ symbol: 'ALSN', rsi: 65.43, trend: 'bullish', score: 95, watch_score_kind: 'strategy_qualified', thin_coverage: true, cio_view: null }] },
  ],
}

async function installRoutes(page: any) {
  await page.route('**/api/**', async (route: any) => {
    const pathname = new URL(route.request().url()).pathname
    let body: any = { ok: true, data: {} }
    if (pathname === '/api/v2/defense/posture') body = posture
    else if (pathname === '/api/v2/defense/industries') body = industries
    else if (pathname === '/api/v2/defense/recommendations') body = recommendations
    else if (pathname === '/api/v2/sectors/monitor') body = sectors
    else if (pathname === '/api/health') body = { ok: true, data: { ok: true } }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function assertNoContentOverflow(page: any) {
  const values = await page.evaluate(() => {
    const body = document.querySelector('.app-body') as HTMLElement | null
    const main = document.querySelector('.app-main') as HTMLElement | null
    const bodyRect = body?.getBoundingClientRect()
    return {
      document: document.documentElement.scrollWidth - window.innerWidth,
      bodyLeft: bodyRect ? Math.max(0, -bodyRect.left) : 0,
      bodyRight: bodyRect ? Math.max(0, bodyRect.right - window.innerWidth) : 0,
      main: main ? main.scrollWidth - main.clientWidth : 0,
    }
  })
  expect(values.document).toBeLessThanOrEqual(2)
  expect(values.bodyLeft).toBeLessThanOrEqual(2)
  expect(values.bodyRight).toBeLessThanOrEqual(2)
  expect(values.main).toBeLessThanOrEqual(2)
}

test('Sectors renders and opens actionable sizing and screening evidence at desktop and narrow widths', async ({ page }) => {
  test.setTimeout(90_000)
  await installRoutes(page)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/v3/sectors')
  const main = page.locator('main')
  await expect(main.getByText('Sectors & Industries', { exact: true })).toBeVisible()
  await expect(main.getByText('Sector decision board', { exact: true })).toBeVisible()
  await expect(main.getByText('ELIGIBLE NOW', { exact: true }).first()).toBeVisible()
  await expect(main.getByText(/pullback toward 20DMA ≈ \$87\.80/).first()).toBeVisible()
  await expect(main.getByRole('button', { name: 'Review decision' }).first()).toBeVisible()
  await expect(main.getByRole('button', { name: 'Watch sector' }).first()).toBeVisible()
  await expect(main.getByRole('button', { name: 'Copy brief + Rotation' }).first()).toBeVisible()

  const energyCard = main.locator('article').filter({ hasText: 'Energy' }).first()
  await energyCard.getByRole('button', { name: 'Review decision' }).click()
  const review = page.getByRole('dialog', { name: 'Energy decision review' })
  await expect(review.getByText(/Rollover IRA.*current 3\.6%.*capacity 4\.5%/).first()).toBeVisible()
  await expect(review.getByText(/\$12,000–\$24,000/).first()).toBeVisible()
  await expect(review.getByText('Account-specific capacity', { exact: true })).toBeVisible()
  await review.getByRole('button', { name: 'Close' }).last().click()

  await expect(main.getByText('RESEARCH WATCH', { exact: true }).first()).toBeVisible()
  await expect(main.getByText('AVOID / REDUCE', { exact: true }).first()).toBeVisible()
  await expect(main.getByText(/screen matches/i).first()).toBeVisible()
  await page.getByRole('button', { name: /Screened names/ }).first().click()
  await expect(main.getByText('THIN COVERAGE', { exact: true }).first()).toBeVisible()
  await expect(main.getByText('NO CIO VIEW', { exact: true }).first()).toBeVisible()
  await assertNoContentOverflow(page)
  await page.screenshot({ path: 'render-artifacts/sectors-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(main.getByText('Sectors & Industries', { exact: true })).toBeVisible()
  await expect(main.getByText('Sector decision board', { exact: true })).toBeVisible()
  await expect(main.getByText('ELIGIBLE NOW', { exact: true }).first()).toBeVisible()
  await expect(main.getByRole('button', { name: 'Review decision' }).first()).toBeVisible()
  await page.getByRole('button', { name: /Screened names/ }).first().click()
  await expect(main.getByText('THIN COVERAGE', { exact: true }).first()).toBeVisible()
  await assertNoContentOverflow(page)
  await main.evaluate((element: HTMLElement) => { element.scrollTop = 0 })
  await page.screenshot({ path: 'render-artifacts/sectors-narrow.png', fullPage: true })
})
