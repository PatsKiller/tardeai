import { expect, test } from '@playwright/test'

const posture = {
  ok: true,
  momentum: {
    generated_at: '2026-07-24T14:10:01Z',
    rows: [
      { etf: 'XLK', sector: 'Technology', as_of: '2026-07-23', rs20: -3.22, slope: 2.89, state: 'IMPROVING', breadth_pct: 19, book_pct: 13.6, book_direct_pct: 8.0 },
      { etf: 'XLF', sector: 'Financials', as_of: '2026-07-23', rs20: 3.3, slope: 0.0, state: 'LEADING', breadth_pct: 48, book_pct: 23.4, book_direct_pct: 16.4 },
      { etf: 'XLE', sector: 'Energy', as_of: '2026-07-23', rs20: 10.26, slope: 2.28, state: 'LEADING', breadth_pct: 79, book_pct: 3.6, book_direct_pct: 0.0 },
      { etf: 'XLI', sector: 'Industrials', as_of: '2026-07-23', rs20: -2.22, slope: -1.1, state: 'LAGGING', breadth_pct: 34, book_pct: 16.3 },
    ],
    market: {
      state_line: 'Market: SPY -1.2% wk · equal-weight leading cap-weight · small caps lagging · top-movers NH/NL sample 15/15 · 1/4 displayed sectors lagging',
      indices: [{ symbol: 'SPY', long: 4.29 }],
      styles: [],
      internals: { new_high: 15, new_low: 15, scope: 'capped_top_movers_sample' },
    },
    transitions_today: [],
  },
  net_exposure: { equity_pct: 83, cash_pct: 17, cash_dollars: 210000 },
}

const industries = {
  ok: true,
  captured_at: '2026-07-23T16:30:05Z',
  capture_kind: 'refresh',
  industries: [
    { industry: 'Aerospace & Defense', sector: 'Industrials', rel1w: 0.42, rel1m: -9.15, state: 'IMPROVING' },
    { industry: 'Building Products & Equipment', sector: 'Industrials', rel1w: 1.29, rel1m: 0.12, state: 'LEADING' },
    { industry: 'Biotechnology', sector: 'Healthcare', rel1w: 2.7, rel1m: 5.44, state: 'LEADING' },
    { industry: 'Computer Hardware', sector: 'Technology', rel1w: 18.36, rel1m: -6.7, state: 'IMPROVING' },
  ],
}

const recs = {
  ok: true,
  recommendations: {
    generated_at: '2026-07-24T14:10:01Z',
    as_of: '2026-07-24',
    mode: 'SHADOW',
    sources: { sectors: '2026-07-24T14:10:01Z', industries: '2026-07-23T16:30:05Z' },
    groups: {
      get_into: [],
      protect: [{
        id: 'pput-XLI', group: 'protect', title: 'WITHHELD · XLI protective put failed liquidity rails',
        mode: 'SHADOW', instruments: [{ symbol: 'XLI', kind: 'protective put vs held shares' }],
        accounts: ['schwab_rollover_ira'], direction: 'buy put vs held shares', size_band: '2 contracts',
        entry_logic: 'No structure may be staged until liquidity rails pass.',
        invalidation: 'Industrials recovers out of LAGGING.', factors: [{ name: 'spread', value: '22.2% > 12%' }],
        as_of: '2026-07-24', impact_dollars: 36725,
      }],
      short_side: [], income: [],
    },
    empty_reasons: { get_into: 'Defensive lean remains active and requires dated review.' },
    stances: [], ladders: [], rotation_plan: [], round_trips: [], operator_items: [],
    not_decomposed: { dollars: 0, positions: [] },
  },
  intents: [], execution_log: [], execution_caps: {}, oversight: {},
}

async function installRoutes(page: any) {
  await page.route('**/api/**', async (route: any) => {
    const pathname = new URL(route.request().url()).pathname
    let body: any = { ok: true, data: {} }
    if (pathname === '/api/v2/defense/posture') body = posture
    else if (pathname === '/api/v2/defense/industries') body = industries
    else if (pathname === '/api/v2/defense/recommendations') body = recs
    else if (pathname === '/api/v2/risk-regime/latest') body = { ok: true, regime_label: 'defensive_rotation' }
    else if (pathname === '/api/v2/trade-ai/summary') body = { ok: true, vix: 24.5 }
    else if (pathname === '/api/health') body = { ok: true, data: { ok: true } }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function assertNoOverflow(page: any) {
  const values = await page.evaluate(() => {
    const body = document.querySelector('.app-body') as HTMLElement | null
    const main = document.querySelector('.app-main') as HTMLElement | null
    return {
      document: document.documentElement.scrollWidth - window.innerWidth,
      body: body ? body.scrollWidth - body.clientWidth : 0,
      main: main ? main.scrollWidth - main.clientWidth : 0,
    }
  })
  expect(values.document).toBeLessThanOrEqual(2)
  expect(values.body).toBeLessThanOrEqual(2)
  expect(values.main).toBeLessThanOrEqual(2)
}

test('Defense renders from navigation at desktop and narrow widths', async ({ page }) => {
  test.setTimeout(90_000)
  await installRoutes(page)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/v3/')
  await page.getByRole('link', { name: 'Defense', exact: true }).click()
  await expect(page).toHaveURL(/\/v3\/defense$/)
  const main = page.locator('main')
  await expect(main.getByText('Defense Desk', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(main.getByText('Institutional rotation brief', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(main.locator('b').filter({ hasText: 'No governed add card is active.' }).first()).toBeVisible()
  await expect(main.getByText(/WITHHELD/).first()).toBeVisible()
  await assertNoOverflow(page)
  await page.screenshot({ path: 'render-artifacts/defense-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(main.getByText('Defense Desk', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(main.getByText('Institutional rotation brief', { exact: true })).toBeVisible({ timeout: 15_000 })
  await assertNoOverflow(page)
  await main.evaluate((element: HTMLElement) => { element.scrollTop = 0 })
  await page.screenshot({ path: 'render-artifacts/defense-narrow.png', fullPage: true })
})
