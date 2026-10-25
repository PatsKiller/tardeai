/** Watch page repair. Synthetic SYM001 only. Non-GET is aborted except the ask and the thesis-queue note. */
import { expect, test, type Page } from '@playwright/test'

const TABS: [string, string][] = [
  ['my-watchlist', 'My Watchlist'],
  ['suggests', 'System Suggests'],
  ['prospects', 'Prospects'],
  ['opportunities', 'Full universe'],
  ['watchpool', 'Watchpool'],
  ['sectors', 'Sectors'],
  ['pullback-macd', 'Pullback/MACD'],
  ['intelligence', 'Classic view'],
]

function lane(id: string, label: string, items: unknown[] = []) {
  return { id, label, hint: 'Synthetic', count: items.length, cap: 8, items, overflow: [] }
}

function prospects() {
  const row = {
    symbol: 'SYM001',
    company: null,
    company_facts: null,
    lane: 'actionable',
    stage: 'actionable',
    why: 'Synthetic setup is inside its reference.',
    summary: 'Synthetic summary for the watch card.',
    conviction: 61,
    conviction_components: [],
    conviction_missing: [],
    conviction_source: 'fixture',
    conviction_as_of: '2026-10-23T19:45:00Z',
    conviction_stale: false,
    stance: 'WATCH',
    whats_missing: [],
    conflicts: [],
    next_trigger: { label: 'Reference', level_ref: null, inside: false, distance_pct: null, observed_by: null },
    next_action: { kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'flags disagree' },
    review_state: {
      status: 'blocked', label: 'Blocked: waiting for evidence', open: true,
      queued_at: '2026-10-24T04:54:05+00:00', expires_at: '2026-10-31T04:54:05+00:00',
      last_attempt: { status: 'BLOCKED', at: '2026-10-25T08:25:03+00:00', block_reason: 'BLOCKED_PENDING_ACQUISITION_AND_CURATION' },
    },
    price: 12.5,
    price_as_of: '2026-10-23T19:45:00Z',
    rsi: null,
    held: false,
    surfaces: [],
    evidence_at: '2026-10-24T04:54:05+00:00',
    expires_at: '2026-10-31T04:54:05+00:00',
    stale: false,
    market_facts: {
      schema: 'WatchMarketFacts@v1',
      evaluated_at: '2026-10-23T19:45:00Z',
      price: { value: 12.5, as_of: '2026-10-23T19:45:00Z', source: 'fixture', source_label: 'Fixture quote', stale: false, freshness: 'CURRENT', as_of_basis: 'observation timestamp' },
      support: { value: 10, as_of: '2026-10-23T19:45:00Z', source: 'watchlist_symbol_master', source_label: 'Watch symbol master', stale: null, freshness: 'UNKNOWN', as_of_basis: 'strategy card created_at' },
      resistance: { value: 14, as_of: '2026-10-23T19:45:00Z', source: 'watchlist_symbol_master', source_label: 'Watch symbol master', stale: null, freshness: 'UNKNOWN', as_of_basis: 'strategy card created_at' },
    },
  }
  return {
    ok: true,
    schema: 'fixture',
    generated_at: '2026-10-25T20:00:00Z',
    source: 'fixture',
    interim: false,
    source_label: 'Synthetic',
    sources: { held: { source: 'fixture', stale: false }, conviction: { as_of: '2026-10-25T20:00:00Z' } },
    curation: { one_membership: true, caps: {}, sort_order: 'conviction', expiry: 'fixture' },
    lanes: [lane('actionable', 'Actionable', [row]), lane('forming', 'Forming'), lane('reentry', 'Re-entry'), lane('manage', 'Manage'), lane('expired', 'Expired')],
    counts: {},
    conflict_count: null,
  }
}

async function install(page: Page) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') {
      if (url.pathname === '/api/v2/cio/ask') {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, data: { ask_id: 'ask-sym', thread_id: 'thread-sym', answer_text: 'Synthetic answer.', thread: null } }),
        })
        return
      }
      if (url.pathname.endsWith('/review-request')) {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ ok: true, data: { ok: true, already_open: false } }),
        })
        return
      }
      await route.abort()
      return
    }
    const body = url.pathname.includes('/watch-prospects') ? { ok: true, data: prospects() } : { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

for (const width of [412, 390, 1440]) {
  test(`watch tabs, ask, and layout at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await install(page)
    for (const [slug, label] of TABS) {
      await page.goto(`/v3/watch?tab=${slug}`)
      await expect(page.getByRole('heading', { level: 1 })).toContainText(label, { timeout: 30_000 })
      await noSidewaysScroll(page)
    }
    await page.goto('/v3/watch/discovery')
    await expect(page.getByText('Watch Discovery & Administration')).toBeVisible()
    await noSidewaysScroll(page)

    await page.goto('/v3/watch?tab=prospects')
    await expect(page.getByTestId('watch-prospects')).toBeVisible()
    const card = page.locator('[data-testid="watch-row"][data-symbol="SYM001"]')
    await expect(card).toBeVisible()
    await expect(card).toContainText('Oct 23, 3:45 PM ET')
    await expect(card.getByTestId('watch-market-time-unknown')).toHaveCount(0)
    await card.getByTestId('watch-step').click()
    const detail = page.getByTestId('watch-detail')
    await expect(detail).toBeVisible()
    await expect(detail.getByTestId('watch-detail-next')).toContainText('Conflict check unavailable')
    await expect(detail.getByTestId('watch-detail-next')).not.toContainText('Resolve conflict')
    await expect(detail).toContainText('Oct 24, 12:54 AM ET')
    await expect(detail).not.toContainText('UTC')
    await detail.getByTestId('watch-ask-cio').click()
    await expect(page.getByTestId('watch-ask-phase')).toHaveAttribute('data-phase', 'answered')
    await expect(page.getByTestId('watch-ask-stance-gap')).toHaveText('CIO stance was not in this answer.')
    await expect(page.getByTestId('watch-ask-thread')).toHaveAttribute('href', /\/v3\/cio\/questions\/thread-sym$/)
    await expect(page.getByTestId('watch-ask-queue')).toContainText('CIO review queued.')
    const ask = page.getByTestId('watch-ask-cio')
    const box = await ask.boundingBox()
    expect(box && box.height).toBeGreaterThanOrEqual(44)
    if (width >= 1280) {
      const list = await page.locator('.watch-record-panel').boundingBox()
      const panel = await page.locator('aside.watch-card-detail').boundingBox()
      expect(list && panel && panel.x).toBeGreaterThanOrEqual((list?.x || 0) + (list?.width || 0) - 2)
    }
    await noSidewaysScroll(page)
  })
}
