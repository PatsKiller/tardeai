import { expect, test } from '@playwright/test'

const item = {
  id: 991,
  symbol: 'FATN',
  status: 'active',
  source: 'interaction-fixture',
  origin_system: 'operator',
  price: 31.25,
  change_pct: 1.4,
  latest_recommendation: 'RESEARCH_MORE',
  score: 82,
  rsi: 51,
  entry_limit: 30.8,
  entry_stop: 28.9,
  entry_target: 35.4,
  entry_rr: 2.4,
  last_enriched_at: '2026-07-25T01:55:00Z',
  profile_sector: 'Industrials',
}

async function installRoutes(page: any) {
  await page.route('**/api/**', async (route: any) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    let body: any = { ok: true, data: {} }

    if (pathname === '/api/v2/watchlist/items') {
      body = { ok: true, items: [item], universe_count: 1 }
    } else if (pathname.startsWith('/api/v2/hermes/intel/')) {
      const symbol = pathname.split('/').pop()
      body = { ok: true, data: { symbol, setup: { type: 'review fixture', entry: 'review only', invalidation: 'fixture invalidation', why: 'URL modal contract' } } }
    } else if (pathname.startsWith('/api/v2/watch/provenance/')) {
      const symbol = pathname.split('/').pop()
      body = { ok: true, symbol, source: 'interaction-fixture', evidence: ['price', 'technical', 'coverage'] }
    } else if (pathname === '/api/v2/watchlist/summary') {
      body = { ok: true, by_status: { active: 1, researched: 0 } }
    } else if (pathname === '/api/v2/symbol-cards') {
      body = { ok: true, cards: {} }
    } else if (pathname === '/api/v2/finviz-strip-map') {
      body = { ok: true, map: {} }
    } else if (pathname === '/api/v2/watch-directives') {
      body = { ok: true, directives: [] }
    } else if (pathname === '/api/v2/rec-intel/outcomes') {
      body = { ok: true, outcomes: {} }
    } else if (pathname === '/api/v2/proposal-accounts') {
      body = { ok: true, accounts: [], sizing_policy: {} }
    } else if (pathname === '/api/v2/portfolio/holdings') {
      body = { ok: true, holdings: [] }
    } else if (pathname === '/api/v2/sectors/monitor') {
      body = { ok: true, sectors: [], spy_change_pct: 0 }
    } else if (pathname === '/api/v2/defense/posture') {
      body = { ok: true, momentum: { rows: [], transitions_today: [] } }
    } else if (pathname === '/api/v2/defense/industries') {
      body = { ok: true, industries: [] }
    } else if (pathname === '/api/v2/defense/recommendations') {
      body = { ok: true, recommendations: { groups: { get_into: [], protect: [], short_side: [] }, accounts: {}, directive_reviews: [] } }
    } else if (pathname === '/api/health') {
      body = { ok: true }
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test.beforeEach(async ({ page }) => {
  await installRoutes(page)
})

test('review deep links open a real modal on Watchlist and Sectors', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/v3/watch?symbol=FATN&review=1&tab=watchlist')

  const fatnDialog = page.getByRole('dialog', { name: 'FATN operator review' })
  await expect(fatnDialog).toBeVisible()
  await expect(fatnDialog).toContainText('URL-addressable decision, provenance and evidence review')
  await expect(page.locator('[data-review-contract="command-center-global-review-v1"]')).toBeVisible()

  const drawerBox = await page.locator('.cc-drawer').boundingBox()
  expect(drawerBox).not.toBeNull()
  expect(drawerBox!.x).toBeGreaterThan(20)
  expect(drawerBox!.y).toBeGreaterThan(10)
  expect(drawerBox!.height).toBeLessThan(1000)

  await page.keyboard.press('Escape')
  await expect(fatnDialog).toHaveCount(0)
  await expect(page).not.toHaveURL(/review=1/)

  await page.goto('/v3/watch?symbol=SWBI&review=1&tab=sectors')
  await expect(page.getByRole('dialog', { name: 'SWBI operator review' })).toBeVisible()
  await expect(page).toHaveURL(/tab=sectors/)
})

test('clicking a Watchlist card opens the URL-addressable review modal', async ({ page }) => {
  await page.goto('/v3/watch?tab=watchlist')
  const card = page.locator('div:has(> .wlc-term-grid)').first()
  await expect(card).toBeVisible()
  await card.click({ position: { x: 8, y: 8 } })

  await expect(page.getByRole('dialog', { name: /FATN/ })).toBeVisible()
  await expect(page).toHaveURL(/symbol=FATN/)
  await expect(page).toHaveURL(/review=1/)
  await expect(page).toHaveURL(/modal=review/)
})
