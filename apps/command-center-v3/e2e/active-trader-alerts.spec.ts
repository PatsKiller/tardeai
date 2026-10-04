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
  decisions: [
    { id: 'a', at: '2026-10-05T10:05:01-04:00', symbol: 'SOUN', kind: 'TRIGGERED', verdict: 'ALERT', veto_reasons: [], sent: true,
      last: 5.86, entry: 5.86, stop: 5.7, r: 0.16, float_mm: 310, rvol: 6.2, setup: 'Bull flag',
      l2: { source: 'moomoo', levels: 10, depth_ratio: 1.45, spread_bps: 17, age_s: 1 }, tape: { source: 'moomoo', prints: 50, buy_ratio: 0.71, age_s: 2 },
      score: { '5m': { mfe_r: 1.6, mae_r: 0.3 } } },
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
  await expect(page.getByText('75% (3/4)').first()).toBeVisible()
  await page.getByRole('button', { name: 'vetoes' }).click()
  await expect(page.getByTestId('at-alert-row')).toHaveCount(1)
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
