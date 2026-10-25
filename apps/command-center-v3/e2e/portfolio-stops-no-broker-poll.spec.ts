import { test, expect, type Page } from '@playwright/test'
test.use({ hasTouch: true })

// Portfolio page views never trigger a broker read (page audit 2026-10-25). Holdings / Stop Management used to
// poll /api/v2/holdings/live-stops every 60 s (a live Schwab read on cache miss). Now: no live-stops request,
// llm-coverage and stops/management are asked for the stored model, and /api/v2/stops/lifecycle is never hit.
// Synthetic fixture inputs only; every /api request is intercepted, non-GET requests are aborted and live
// :7777 traffic fails the test.
const HOLDINGS = [
  { symbol: 'FIXA', account: 'schwab_fixture', shares: 10, price: 50, market_value: 500, cost_basis: 400, name: 'Fixture A',
    stop_source: 'broker_resting', stop_state: 'active', stop_price: 45, stop_qty: 10, stop_order_id: 'fixture-order-1',
    stop_captured_at: '2026-10-24T20:00:00Z', broker_protected: true },
  { symbol: 'FIXB', account: 'schwab_fixture', shares: 5, price: 20, market_value: 100, cost_basis: 90, name: 'Fixture B',
    stop_source: 'none', stop_state: 'none', stop_price: null },
]

async function fixtures(page: Page, seen: string[]) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.port === '7777') throw new Error('Live API traffic is forbidden')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') return route.abort()
    seen.push(url.pathname + url.search)
    if (url.pathname === '/api/v2/portfolio/holdings') return route.fulfill({ status: 200, json: { ok: true, data: { holdings: HOLDINGS, as_of: '2026-10-25T12:00:00Z' } } })
    if (url.pathname === '/api/v2/stops/management') return route.fulfill({ status: 200, json: { ok: true, data: { rows: [], summary: {} } } })
    return route.fulfill({ status: 200, json: {} })
  })
}

const size = (width: number) => ({ width, height: width === 412 ? 915 : width === 390 ? 844 : 1000 })

for (const width of [1440, 412, 390]) {
  for (const tab of ['Holdings', 'Stop Management']) {
    test(`portfolio ${tab}: no broker-reading poll ${width}`, async ({ page }) => {
      const seen: string[] = []
      await page.setViewportSize(size(width))
      await fixtures(page, seen)
      await page.clock.install()
      await page.goto(`/v3/portfolio?tab=${encodeURIComponent(tab)}`)
      await expect(page.getByTestId('portfolio-desk-health')).toBeVisible()
      await expect(page.getByTestId('desk-health-stops')).toHaveText('Broker stops: last known (stored)')
      await page.clock.runFor(185_000)  // three 60 s poll periods
      await page.waitForTimeout(300)
      expect(seen.filter(p => p.startsWith('/api/v2/holdings/live-stops'))).toEqual([])
      expect(seen.filter(p => p.startsWith('/api/v2/stops/lifecycle'))).toEqual([])
      const cov = seen.filter(p => p.startsWith('/api/v2/portfolio/llm-coverage'))
      expect(cov.length).toBeGreaterThan(0)
      expect(cov.every(p => p.includes('stops=stored'))).toBeTruthy()
      if (tab === 'Stop Management') {
        const mgmt = seen.filter(p => p.startsWith('/api/v2/stops/management'))
        expect(mgmt.length).toBeGreaterThan(0)
        expect(mgmt.every(p => p.includes('stops=stored'))).toBeTruthy()
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy()
    })
  }
}
