import { test, expect } from '@playwright/test';

const json = (body: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

async function openActiveTrader(page: import('@playwright/test').Page) {
  await page.goto('/v3/active-trader');
  await expect(page.getByRole('heading', { name: 'Current scanner marks' })).toBeVisible({ timeout: 20_000 });
}

test('scanner candidate shows a distinct timestamped current mark from the gateway', async ({ page }) => {
  await page.route('**/api/v3/active-trader/permission-queue*', route => route.fulfill(json({
    data_state: 'LIVE_DATA', actionable_count: 1, ign_trigger_count: 0, scanner_go_count: 1,
    accounts: [], engine_status: { scanner: { available: true, go_count_today: 1, manual_review_count_today: 0 }, ign: { market_open: false, opens_et: '09:30', today_trigger_count: 0 } },
    signals: [{
      source: 'scanner', id: 'tai-NUAI-1', symbol: 'NUAI', scannedAt: '2026-07-28T13:30:00Z', scannedAtEt: '09:30',
      score: 91, grade: 'A', decision: 'GO', route: 'momentum', routeStrategyId: null, routeActionability: null,
      setupClass: 'high_rvol_runner', operatorPill: 'RUNNER', operatorSubtitle: 'scan snapshot', criticVerdict: 'GO',
      catalystVerified: true, rvol: 12.4, gapPct: 18.1, changePct: 21.2, price: 4.20, floatM: 8.5,
      sector: 'Technology', manualReviewRequired: false, notTradeable: false, reviewState: 'GO'
    }]
  })));
  await page.route('**/api/v3/active-trader/current-marks*', route => route.fulfill(json({
    snapshot_fresh: true, snapshot_reason: 'OK', generated_at: '2026-07-28T13:31:01Z',
    marks: [{ symbol: 'NUAI', bid: 4.31, ask: 4.33, last: 4.32, source: 'moomoo_quote', received_at: '2026-07-28T13:31:00Z', age_ms: 210, available: true, stale: false, fallback: false }]
  })));
  await page.route('**/api/v3/active-trader/fire-performance*', route => route.fulfill(json({ active_fires: [], fire_history: [], active_count: 0, history_count: 0 })));
  await page.route('**/api/v3/active-trader/l2-status*', route => route.fulfill(json({ connected: true, provider_state: 'CONNECTED', entitlement_state: 'AVAILABLE_REALTIME', quota: null, symbols: {} })));
  await page.route('**/api/v3/active-trader/scalp/setups*', route => route.fulfill(json({ setup_registry: { setups: [] } })));

  await openActiveTrader(page);
  const mark = page.getByTestId('current-mark-NUAI');
  await expect(mark).toContainText('4.32');
  await expect(mark).toContainText('moomoo_quote');
  await expect(page.getByText(/separate from the immutable scan-time price/i)).toBeVisible();
  await expect(page.getByText('4.20').first()).toBeVisible();
  await expect(page.getByText('ACTIVE TRADER ROUTES: OFF')).toBeVisible();
});

test('stale/unavailable current mark never appears as fresh', async ({ page }) => {
  await page.route('**/api/v3/active-trader/permission-queue*', route => route.fulfill(json({
    data_state: 'LIVE_DATA', actionable_count: 1, signals: [{ source: 'scanner', id: 's', symbol: 'ATAI', decision: 'GO', reviewState: 'GO', price: 3.10, changePct: 5, score: 80, grade: 'B', rvol: 5, gapPct: 3, floatM: 10, setupClass: 'runner' }],
    accounts: [], engine_status: { scanner: { available: true, go_count_today: 1, manual_review_count_today: 0 }, ign: { market_open: false, opens_et: '09:30', today_trigger_count: 0 } }
  })));
  await page.route('**/api/v3/active-trader/current-marks*', route => route.fulfill(json({
    snapshot_fresh: false, snapshot_reason: 'SNAPSHOT_STALE', marks: [{ symbol: 'ATAI', available: false, stale: true }]
  })));
  await page.route('**/api/v3/active-trader/fire-performance*', route => route.fulfill(json({ active_fires: [], fire_history: [] })));
  await page.route('**/api/v3/active-trader/l2-status*', route => route.fulfill(json({ connected: false, provider_state: 'SNAPSHOT_STALE', symbols: {} })));
  await page.route('**/api/v3/active-trader/scalp/setups*', route => route.fulfill(json({ setup_registry: { setups: [] } })));

  await openActiveTrader(page);
  await expect(page.getByTestId('current-mark-ATAI')).toContainText('UNAVAILABLE');
  await expect(page.getByText('APPROVED FALLBACK / WAITING')).toBeVisible();
});
