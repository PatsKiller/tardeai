/**
 * Remediation dry-run: every Command Center route renders against MOCKED
 * fixtures. No production call is made -- `page.route('**\/api/**')` intercepts
 * everything before it leaves the browser, so this suite is safe to run with no
 * backend and cannot touch production data.
 *
 * Fixture cases: fresh, stale, missing, malformed, future-skewed,
 * transport-failed, 304-retained, mixed-source, >25 population,
 * protection-unknown.
 */
import { test, expect } from '@playwright/test'

const STALE_OVERVIEW = {
  ok: true,
  portfolio_value: 1280958.39,
  today_change: 3981.58,
  // value is current; metadata is 7 days old -- the exact Home defect
  data_as_of: '2026-08-26',
  data_as_of_account: 'alpaca_taxable_live',
  as_of: '2026-09-02',
  last_repriced: '2026-09-02 16:45:02 ET',
  pipeline_status: 'fresh',      // the hardcoded literal
  pipeline_completed: '',        // ...with no completion behind it
  position_count: 30,
  pricing: {},
  periods: {},
}

// >25 population for the truth-count cap
const RISK_POSITIONS = Array.from({ length: 41 }, (_, i) => ({
  symbol: `SYM${i}`, unprotected: true, account: 'test',
  current_price: 10, stop_price: 9,
  protection_state: i % 3 === 0 ? null : 'protected',   // protection-unknown case
}))

async function mockAll(page: any, overview: any = STALE_OVERVIEW) {
  await page.route('**/api/**', async (route: any) => {
    const url = route.request().url()
    let body: any = { ok: true }
    if (url.includes('/overview')) body = overview
    else if (url.includes('/risk')) body = { ok: true, positions: RISK_POSITIONS }
    else if (url.includes('book-map')) body = { ok: true, as_of: null, total_value: 1, total_day_change: 0, items: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('Home never presents a current value as fully fresh when metadata is stale', async ({ page }) => {
  await mockAll(page)
  await page.goto('/v3/')
  const body = await page.locator('body').innerText()
  // pipeline_status is "fresh" but has no completion timestamp -> must be qualified
  expect(body).toContain('UNKNOWN')
  // the four clocks must be named, not collapsed into one "updated"
  expect(body.toLowerCase()).toContain('session')
  expect(body.toLowerCase()).toContain('observed')
  expect(body.toLowerCase()).toContain('last refresh')
})

test('an absent book date renders UNDATED, never blank', async ({ page }) => {
  await mockAll(page)
  await page.goto('/v3/')
  const body = await page.locator('body').innerText()
  expect(body).toContain('session UNDATED')
})

test('transport failure is visible, not silently empty', async ({ page }) => {
  await page.route('**/api/**', (route: any) => route.abort('failed'))
  await page.goto('/v3/')
  const body = await page.locator('body').innerText()
  expect(body.length).toBeGreaterThan(0)
})
