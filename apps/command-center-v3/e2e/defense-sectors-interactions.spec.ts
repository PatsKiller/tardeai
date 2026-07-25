import { expect, test } from '@playwright/test'

const posture = {
  ok: true,
  momentum: {
    generated_at: '2026-07-24T20:40:00Z',
    rows: [
      { etf: 'XLE', sector: 'Energy', as_of: '2026-07-24', rs20: 10.1, slope: 2.6, state: 'LEADING', breadth_pct: 75, breadth_coverage_n: 56, book_pct: 3.6 },
      { etf: 'XLF', sector: 'Financials', as_of: '2026-07-24', rs20: 4.6, slope: -1.6, state: 'WEAKENING', breadth_pct: 41, breadth_coverage_n: 58, book_pct: 23.6 },
      { etf: 'XLRE', sector: 'Real Estate', as_of: '2026-07-10', rs20: -3.7, slope: -1.1, state: 'LAGGING', breadth_pct: null, book_pct: 2.0, quarantined: true, quarantine_reason: 'stale_row' },
    ],
    market: { state_line: 'Mixed tape · interaction fixture', indices: [{ symbol: 'SPY', long: 1.0 }], transitions_today: [] },
    transitions_today: [],
  },
  net_exposure: { equity_pct: 57.1, cash_pct: 42.9, cash_dollars: 537000 },
}

const industries = {
  ok: true,
  captured_at: '2026-07-24T20:35:00Z',
  industries: [
    { industry: 'Oil & Gas Integrated', sector: 'Energy', rel1m: 12.5, rel1w: 1.4, state: 'LEADING' },
    { industry: 'Oil & Gas E&P', sector: 'Energy', rel1m: 6.7, rel1w: 1.1, state: 'IMPROVING' },
    { industry: 'Insurance - Life', sector: 'Financials', rel1m: 4.0, rel1w: -1.2, state: 'LEADING' },
  ],
}

const recommendations = {
  ok: true,
  recommendations: {
    accounts: {},
    groups: {
      get_into: [],
      protect: [{ id: 'pput-XLI', title: 'PROTECTIVE PUT · XLI', entry_logic: 'Review liquid put structure only after rails pass.', invalidation: 'Sector exits lagging state.', mode: 'SHADOW' }],
      short_side: [],
    },
    empty_reasons: { get_into: 'DEFENSIVE LEAN active: cyclical rotate-ins excluded.' },
    directive_reviews: [{ enabled: true, requires_review: true, set_at: '2026-07-18', conflicting_sectors: ['Energy'] }],
    sources: {},
    generated_at: '2026-07-24T20:40:00Z',
  },
  hedging_radar: {},
  execution_log: [],
  intents: [],
}

const sectorMonitor = {
  ok: true,
  spy_change_pct: -0.4,
  sectors: [
    { sector: 'Energy', etf: 'XLE', momentum: 'leading', setup_count: 2, constituent_count: 25, is_watched: false, candidates: [
      { symbol: 'XOM', rsi: 52, trend: 'bullish', score: 88 },
      { symbol: 'CVX', rsi: 48, trend: 'neutral', score: 76 },
    ] },
    { sector: 'Financials', etf: 'XLF', momentum: 'lagging', setup_count: 1, constituent_count: 30, is_watched: false, candidates: [] },
  ],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) }))
  await page.route(/\/api\/v2\/defense\/posture(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(posture) }))
  await page.route(/\/api\/v2\/defense\/industries(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(industries) }))
  await page.route(/\/api\/v2\/defense\/recommendations(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(recommendations) }))
  await page.route(/\/api\/v2\/sectors\/monitor(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sectorMonitor) }))
  await page.route(/\/api\/v2\/risk-regime\/latest(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ regime_label: 'risk_off' }) }))
  await page.route(/\/api\/v2\/watch\/alerts\/list(?:\?.*)?$/, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ active_count: 2 }) }))
  await page.route(/\/api\/v2\/watch\/provenance\/[^?]+(?:\?.*)?$/, route => {
    const symbol = route.request().url().split('/').pop()?.split('?')[0]
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, symbol, source: 'interaction-fixture', evidence: ['price', 'technical', 'coverage'] }) })
  })
  await page.route(/\/api\/v2\/watch\/directives(?:\?.*)?$/, async route => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, directive_id: 321 }) })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, directives: [] }) })
  })
})

test('Watch sectors board supports filtering, evidence, governed watch creation and Watchlist return', async ({ page }) => {
  await page.goto('/v3/watch?tab=sectors')

  await expect(page.getByText(/Watch.*Sectors/).first()).toBeVisible()
  await expect(page.getByText('Sector decision board')).toBeVisible()

  await page.getByRole('button', { name: 'Filter RESEARCH WATCH (1)' }).click()
  await expect(page.getByText('Energy', { exact: true })).toBeVisible()
  await expect(page.getByText('Financials', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear filters' }).click()

  await page.getByRole('button', { name: 'Oil & Gas Integrated' }).click()
  await expect(page.getByText('Active filter:')).toBeVisible()
  await expect(page.getByText('Financials', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Clear filters' }).click()

  const energyCard = page.locator('article').filter({ hasText: 'Energy' }).first()
  await energyCard.getByRole('button', { name: 'Review decision' }).click()
  const sectorDialog = page.getByRole('dialog', { name: 'Energy decision review' })
  await expect(sectorDialog).toBeVisible()

  await sectorDialog.getByRole('button', { name: 'XOM — open evidence' }).click()
  const evidenceDialog = page.getByRole('dialog', { name: 'Symbol evidence · XOM' })
  await expect(evidenceDialog).toContainText('interaction-fixture')
  await evidenceDialog.getByRole('button', { name: 'Close' }).last().click()

  page.once('dialog', dialog => dialog.accept())
  await sectorDialog.getByRole('button', { name: 'Watch sector' }).click()
  await expect(page.getByRole('status')).toContainText('Watching Energy')
  await sectorDialog.getByRole('button', { name: 'Close' }).last().click()

  await page.getByRole('link', { name: 'Watch', exact: true }).click()
  await expect(page).toHaveURL(/\/v3\/watch\?tab=watchlist/)
  await expect(page.getByText(/Watch.*Watchlist/).first()).toBeVisible()
})

test('Defense board opens risk and policy reviews and exposes refresh mechanics', async ({ page }) => {
  const recResponse = page.waitForResponse(response => /\/api\/v2\/defense\/recommendations(?:\?|$)/.test(response.url()))
  await page.goto('/v3/defense')
  const recPayload = await (await recResponse).json()
  expect(recPayload.recommendations.groups.protect).toHaveLength(1)
  await expect(page.getByText('Sector decision board')).toBeVisible()

  await page.getByRole('button', { name: /PROTECTIVE PUT · XLI/ }).click()
  await expect(page.getByRole('dialog', { name: 'Governed defense action review' })).toContainText('Review liquid put structure')
  await page.getByRole('dialog', { name: 'Governed defense action review' }).getByRole('button', { name: 'Close' }).last().click()

  await page.getByRole('button', { name: 'Open policy review' }).click()
  await expect(page.getByRole('dialog', { name: 'Operator policy review' })).toContainText('DEFENSIVE LEAN enabled')
  await page.getByRole('dialog', { name: 'Operator policy review' }).getByRole('button', { name: 'Close without change' }).click()

  await page.getByRole('button', { name: 'Filter NO DECISION (1)' }).click()
  const staleCard = page.locator('article').filter({ hasText: 'Real Estate' }).first()
  await expect(staleCard.getByRole('button', { name: 'Refresh evidence' })).toBeVisible()
})
