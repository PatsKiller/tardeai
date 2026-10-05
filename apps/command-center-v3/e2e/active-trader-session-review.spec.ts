import { test, expect, type Page } from '@playwright/test'

// Active Trader session review (2026-10-05): engine vs "should have been" + auto-sim comparison.
// Fixture API only: every /api call is answered here. Rows mirror the operator's XNDU review.

const review = {
  day: '2026-10-05',
  symbols: [{
    symbol: 'XNDU', bars: 64,
    table: [
      { ts: 1, time: '09:50:13', price: 4.33, engine: '🟡 Heads-up', should: '✅ Correct — right before the move', source: 'engine' },
      { ts: 2, time: '09:51', price: 4.35, engine: 'Breakout happened, alert held until the next check (09:55:11, 4m12s later)', should: '🟢 Time to buy (best entry #1)', source: 'ideal_entry' },
      { ts: 3, time: '09:55:11', price: 4.43, engine: '🟢 Time to buy, 4m12s after the 09:51 entry, +1.8% already', should: '"Extended, don\'t chase; buy zone 4.38–4.40"', source: 'engine' },
      { ts: 4, time: '10:00:22', price: 4.40, engine: '⛔ heads-up blocked (COOLDOWN)', should: '🟢 Back in buy zone (best entry #2) — missed', source: 'engine' },
      { ts: 5, time: '10:07:09', price: 4.48, engine: 'Your buy, 1m53s after the 10:05 heads-up', should: 'After the top', source: 'you' },
    ],
    ideal_trades: [{ kind: 'breakout', ts: 2, price: 4.35, stop: 4.305, exit_ts: 6, exit_price: 4.4, exit_reason: 'closed below the prior bar\'s low', pnl_pct: 1.15, why: '' }],
    metrics: { latency_s: [252], latency_max_s: 252, missed: [{ reasons: ['COOLDOWN'] }], chases: [{}], correct_heads_up: 1, ideal_pnl_pct: 3.4, ideal_pnl_per_share: 0.15, your_pnl: 1.0 },
  }],
  auto_sim: {
    mode: 'manual', size_shares: null, size_notional_usd: 2000, improved_timing_label: 'simulated at the review\'s ideal entries',
    compare: { manual_pnl: 1.0, engine_sim_pnl: -15.91, improved_sim_pnl: 61.2, should_have_been_pnl: 70.0 },
    sources: { engine: { metrics: { attempted: 1, filled: 1, fill_feasibility: 1, win_rate: 0, net_pnl: -15.91, avg_r: -0.49, max_drawdown: 15.91 },
                         trades: [{ status: 'FILLED', kind: 'TRIGGERED', entry_ts: 1791208511, fill: 4.43, exit_price: 4.395, exit_reason: 'closed below the prior bar\'s low', pnl: -15.91, symbol: 'XNDU' }] } },
  },
}

async function open(page: Page, body: unknown) {
  await page.route('**/api/**', route => {
    const url = route.request().url()
    if (url.includes('/api/v3/active-trader/session-review')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
  })
  await page.goto('/v3/active-trader?tab=Session%20review')
  await expect(page.getByTestId('at-session-review')).toBeVisible({ timeout: 20_000 })
}

test('session review shows engine vs should-have-been and the auto-sim comparison', async ({ page }) => {
  await open(page, { day: '2026-10-05', days: ['2026-10-05'], review })
  await expect(page.getByTestId('at-review-compare')).toContainText('+$1.00')
  await expect(page.getByTestId('at-review-compare')).toContainText('−$15.91')
  await expect(page.getByTestId('at-review-symbol')).toContainText('Extended, don\'t chase; buy zone 4.38–4.40')
  await expect(page.getByTestId('at-review-symbol')).toContainText('1 entry missed (COOLDOWN)')
  await expect(page.getByTestId('at-review-symbol')).toContainText('After the top')
  await expect(page.getByText('Simulation only — no order, size or stop')).toBeVisible()
})

test('no review yet explains when it runs', async ({ page }) => {
  await open(page, { day: null, days: [], review: null })
  await expect(page.getByTestId('at-review-empty')).toContainText('12:05 ET')
})

test('phone width has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page, { day: '2026-10-05', days: ['2026-10-05'], review })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
