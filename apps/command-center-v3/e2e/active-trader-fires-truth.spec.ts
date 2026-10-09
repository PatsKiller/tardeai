/** Fixture-only alert-count truth: no host API, broker, model or notification calls. */
import { expect, test, type Page, type Route } from '@playwright/test'

const trade = {
  ok: true, run_id: '2026-10-09::1000', run_label: '1000', run_date: '2026-10-09',
  current_run_scanned: 1, latest_run_symbols_scanned: 1, ticker_count: 1,
  run_health_status: 'RUN_HEALTHY', stale: false, cache_age_sec: 1,
  cached_at: new Date().toISOString(),
  tickers: [{ symbol: 'WFF', decision: 'GO', score: 44 }],
}
const sent = { id: 'fixture-1', symbol: 'WFF', sent: true, kind: 'TRIGGERED', at: '2026-10-09T10:00:00-04:00' }

async function fixture(page: Page, alerts: (route: Route) => Promise<void>) {
  await page.route('**/api/**', async route => {
    const url = route.request().url()
    if (url.includes('/active-trader/alerts')) return alerts(route)
    const body = url.includes('/trade-ai') ? trade : { ok: true }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/v3/trading?tab=Trade%20AI')
  await expect(page.getByTestId('at-fires-strip')).toBeVisible()
}

const response = (body: unknown, status = 200) => async (route: Route) => {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

test('loading alerts have an unknown count until the API is measured', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await fixture(page, async route => { await pending; await response({ decisions: [] })(route) })
  const strip = page.getByTestId('at-fires-strip')
  await expect(strip).toContainText('Active Trader fired today · —')
  await expect(strip).toContainText('Loading alerts')
  await expect(strip).not.toContainText('No Active Trader alerts sent today.')
  release()
})

for (const [name, body] of [
  ['missing decisions', { ok: true }],
  ['invalid decisions', { decisions: 'unknown' }],
  ['invalid decision row', { decisions: [null] }],
] as const) {
  test(`${name} cannot become a confirmed zero`, async ({ page }) => {
    await fixture(page, response(body))
    const strip = page.getByTestId('at-fires-strip')
    await expect(strip).toContainText('Active Trader fired today · —')
    await expect(strip).toContainText('Alerts unavailable')
    await expect(strip).not.toContainText('No Active Trader alerts sent today.')
  })
}

test('failed alert API is unavailable, not an empty session', async ({ page }) => {
  await fixture(page, response({ error: 'fixture failure' }, 500))
  const strip = page.getByTestId('at-fires-strip')
  await expect(strip).toContainText('Alerts unavailable')
  await expect(strip).toContainText('Active Trader fired today · —')
  await expect(strip).not.toContainText('No Active Trader alerts sent today.')
})

test('a measured empty alert response can show zero', async ({ page }) => {
  await fixture(page, response({ decisions: [] }))
  const strip = page.getByTestId('at-fires-strip')
  await expect(strip).toContainText('Active Trader fired today · 0')
  await expect(strip).toContainText('No Active Trader alerts sent today.')
})

test('failed refetch labels retained sent alerts as stale', async ({ page }) => {
  await page.clock.install()
  let requests = 0
  await fixture(page, async route => {
    requests++
    await response(requests === 1 ? { decisions: [sent] } : { error: 'fixture failure' }, requests === 1 ? 200 : 500)(route)
  })
  const strip = page.getByTestId('at-fires-strip')
  await expect(strip).toContainText('Active Trader fired today · 1')
  await expect(strip).toContainText('WFF')
  await page.clock.fastForward(30_001)
  await expect(strip).toContainText('Active Trader last observed · 1')
  await expect(strip).toContainText('Stale alerts')
  await expect(strip).not.toContainText('Active Trader fired today')
})
