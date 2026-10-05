import { test, expect, type Page } from '@playwright/test'

// Active Trader Phase 1 alerts tab (2026-10-04). Fixture API only: every /api call is answered here.

const feed = {
  contract: 'active-trader-alerts-feed-v1', session_date: '2026-10-05', mode: 'send', delivery: 'telegram',
  engine: { window_et: ['09:30', '11:55'], last_pass_at: '2026-10-05T10:05:01-04:00', last_pass_age_s: 40, symbols_scored: 52 },
  l2: { source: 'moomoo OpenD (quote context)', levels_proven: 60, proven_at: '2026-10-04', compare: 'Schwab NASDAQ_BOOK' },
  rules: { triggered: 'trigger fired ≤ 6 min ago + book bid/ask ≥ 1.2x', freshness: 'quote ≤ 30s · book ≤ 15s · tape ≤ 60s' },
  counts: { triggered_alerts: 1, armed_alerts: 1, vetoes: 1, sent: 2, decisions: 3 },
  veto_reasons: { TAPE_SELLERS: 1 },
  precision: { '1m': {}, '5m': { 'TRIGGERED:ALERT': { n: 4, hit: 3, precision: 0.75 } }, '15m': {} },
  scored_total: 4,
  scored_session: 3,
  sessions: ['2026-10-05', '2026-10-02'],
  outcomes: {
    session: { 'TRIGGERED:ALERT': { n: 1, WORKED: 0, STOPPED: 0, NO_TOUCH: 1, AT_OR_BELOW_STOP: 0, worked_rate: 0, avg_best_exit_pct: 1.58, avg_rule_exit_pct: -1.13 } },
    all: { 'TRIGGERED:ALERT': { n: 1, WORKED: 0, STOPPED: 0, NO_TOUCH: 1, AT_OR_BELOW_STOP: 0, worked_rate: 0, avg_best_exit_pct: 1.58, avg_rule_exit_pct: -1.13 } },
    touch_min: 15, horizon_min: 30, pending: 1,
  },
  your_trades: [
    { symbol: 'SOUN', account: 'schwab_rollover_ira', qty: 100, buy_at: '2026-10-05T10:07:09-04:00', buy_price: 5.88, sell_at: '2026-10-05T10:08:15-04:00',
      sell_price: 5.89, pnl: 0.99, pnl_pct: 0.17, held_s: 66, source: 'active_trader',
      alert: { id: 'a', kind: 'TRIGGERED', at: '2026-10-05T10:05:01-04:00', ask_at_alert: 5.87, last_at_alert: 5.86, stop: 5.7, lag_s: 128 } },
  ],
  decisions: [
    { id: 'a', at: '2026-10-05T10:05:01-04:00', symbol: 'SOUN', kind: 'TRIGGERED', verdict: 'ALERT', veto_reasons: [], sent: true,
      last: 5.86, entry: 5.86, stop: 5.7, r: 0.16, float_mm: 310, rvol: 6.2, setup: 'Bull flag',
      l2: { source: 'moomoo', levels: 10, depth_ratio: 1.45, spread_bps: 17, age_s: 1 }, tape: { source: 'moomoo', prints: 50, buy_ratio: 0.71, age_s: 2 },
      score: { '5m': { mfe_r: 1.6, mae_r: 0.3 } },
      supply: { ask_size_inside: 300, bid_size_inside: 1200, ask_shares_near: 12400, ask_levels_near: 5, near_pct: 1, ask_wall_price: 5.9, ask_wall_size: 9000, ask_wall_x_median: 6.2 },
      outcome: { status: 'SCORED', result: 'NO_TOUCH', fill: 5.87, fill_source: 'ask', stop: 5.7, risk: 0.17, risk_pct: 2.9,
        best_exit: { price: 5.96, at: '2026-10-05T10:16:00-04:00', pct: 1.53, r: 0.53 },
        rule_exit: { price: 5.8, at: '2026-10-05T10:09:00-04:00', pct: -1.19, r: -0.41, reason: 'closed below prior bar low' } } },
    { id: 'b', at: '2026-10-05T10:00:01-04:00', symbol: 'ALXO', kind: 'ARMED', verdict: 'ALERT', veto_reasons: [], sent: true,
      last: 1.28, entry: 1.28, stop: 1.24, r: 0.04, float_mm: 40, rvol: 9, l2: { source: 'moomoo', levels: 10, depth_ratio: 1.1, spread_bps: 60, age_s: 2 } },
    { id: 'c', at: '2026-10-05T09:55:01-04:00', symbol: 'PLUG', kind: 'TRIGGERED', verdict: 'VETO', veto_reasons: ['TAPE_SELLERS'], sent: false,
      last: 2.13, entry: 2.13, stop: 2.12, r: 0.01, l2: { source: 'moomoo', levels: 10, depth_ratio: 1.3, spread_bps: 47, age_s: 1 }, tape: { prints: 50, buy_ratio: 0.3 } },
  ],
}

async function open(page: Page, body: unknown, path = '/v3/active-trader') {
  await page.route('**/api/**', route => {
    const url = route.request().url()
    if (url.includes('/api/v3/active-trader/alerts')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
  })
  await page.goto(path)
  await expect(page.getByTestId('at-alerts')).toBeVisible({ timeout: 20_000 })
}

test('alerts is the landing tab and shows live Telegram mode, KPIs and the decision feed', async ({ page }) => {
  await open(page, feed)
  await expect(page.getByTestId('at-alerts-mode')).toContainText('LIVE → Telegram')
  await expect(page.getByTestId('at-alert-row')).toHaveCount(3)
  await expect(page.getByTestId('at-alert-row').first()).toContainText('TIME TO BUY')
  await expect(page.getByTestId('at-alert-row').first()).toContainText('✓ Telegram')
  await expect(page.getByTestId('at-alert-row').nth(2)).toContainText('tape selling')
  // audit 2026-10-05: honest track record — measured from the ask at the alert, stop-first is a miss
  await expect(page.getByText('0/1').first()).toBeVisible()
  await expect(page.getByTestId('at-alert-outcome').first()).toContainText('neither in window')
  await expect(page.getByTestId('at-alert-outcome').first()).toContainText('best exit 5.96 at 10:16')
  await expect(page.getByTestId('at-alert-outcome').first()).toContainText('rule exit 5.80 at 10:09')
  await expect(page.getByTestId('at-alert-row').first()).toContainText('12,400 sh within 1%')
  await expect(page.getByTestId('at-alert-row').first()).toContainText('you bought 5.88 10:07')
  await expect(page.getByTestId('at-your-trades')).toContainText('after time-to-buy 10:05')
  await expect(page.getByTestId('at-alert-outcome').nth(1)).toContainText('Not scored yet')
  await page.getByRole('button', { name: 'Vetoed', exact: true }).click()
  await expect(page.getByTestId('at-alert-row')).toHaveCount(1)
})

test('KPI tiles filter the decision list on click; clicking again clears', async ({ page }) => {
  await open(page, feed)
  const tile = page.locator('.at-kpi', { hasText: 'Heads-up' })
  await tile.click()
  await expect(page.getByTestId('at-alert-row')).toHaveCount(1)
  await expect(page.getByTestId('at-alert-row').first()).toContainText('ALXO')
  await expect(tile).toHaveAttribute('aria-pressed', 'true')
  await tile.click()
  await expect(page.getByTestId('at-alert-row')).toHaveCount(3)
  await page.locator('.at-kpi', { hasText: 'Your trades' }).click()
  await expect(page.getByTestId('at-alert-row')).toHaveCount(1)
  await expect(page.getByTestId('at-alert-row').first()).toContainText('SOUN')
  await page.getByLabel('Outcome').selectOption('pending')
  await expect(page.getByTestId('at-alerts-empty')).toContainText('No decisions match')
})

test('empty session explains when the engine runs; shadow mode is labelled', async ({ page }) => {
  await open(page, { ...feed, mode: 'shadow', decisions: [], counts: {}, veto_reasons: {}, latest_session_with_decisions: null })
  await expect(page.getByTestId('at-alerts-mode')).toContainText('SHADOW')
  await expect(page.getByTestId('at-alerts-empty')).toContainText('09:30')
})

test('phone width has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page, feed)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
