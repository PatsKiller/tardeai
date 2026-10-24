/** MyList market facts: synthetic stored evidence, no provider/live API, pinned clock. */
import { expect, test, type Page } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'
import { WATCH_LISTS_FIXTURE as FX } from '../src/fixtures/watchLists.fixture'
import { FIXTURE as PROS } from '../src/fixtures/watchProspects.fixture'

const CLOCK = '2026-10-23T14:00:00Z'
const SHOTS = process.env.WATCH_MARKET_SHOTS || path.join(os.homedir(), '.cache/rtc/codex-watch-market-facts-20261024/screenshots')
fs.mkdirSync(SHOTS, { recursive: true })
test.use({ serviceWorkers: 'block' })

async function mock(page: Page, baseURL: string, mode = 'current') {
  if (mode.startsWith('refresh-')) await page.clock.install({ time: new Date(CLOCK) })
  else await page.clock.setFixedTime(new Date(CLOCK))
  const c: any = structuredClone(FX.curation); const row: any = structuredClone(c.my_watchlist.rows[0])
  const field = { stale: null, freshness: 'UNKNOWN', compatibility: 'BELOW_OR_AT_PRICE', reason: null }
  const facts: any = { schema: 'WatchMarketFacts@v1', evaluated_at: '2026-10-24T14:00:00Z',
    price: { ...field, value: 10, as_of: '2026-10-23T13:59:00Z', source: 'data_broker.latest_quote:schwab', source_label: 'Stored quote · schwab', stale: false, freshness: 'CURRENT' },
    support: { ...field, value: 9, as_of: null, source: 'watchlist_symbol_master', source_label: 'Watch symbol master', reason: 'Level observation time unavailable.' },
    resistance: { ...field, value: 11, as_of: '2026-10-22', source: 'ui_prefs:portfolio.reentry.resistance.v1', source_label: 'Closed-session resistance cache', reason: 'Closed-session date; level freshness is not assessed.' } }
  if (mode === 'stale') Object.assign(facts.price, { as_of: '2026-10-22T19:00:00Z', stale: true, freshness: 'STALE', reason: 'Price observation is stale.' })
  if (mode === 'no-price') {
    Object.assign(facts.price, { value: null, as_of: null, stale: true, freshness: 'MISSING', reason: 'Stored quote read unavailable.' })
    for (const kind of ['support', 'resistance']) Object.assign(facts[kind], { compatibility: 'UNKNOWN', reason: 'Price unavailable; nearest-level relation is unknown.' })
  }
  if (mode === 'future') Object.assign(facts.price, { as_of: '2026-10-25T14:00:00Z', stale: true, freshness: 'UNKNOWN', reason: 'Price observation timestamp is in the future.' })
  if (mode === 'missing-support') Object.assign(facts.support, { value: null, source: null, source_label: 'No reference', freshness: 'MISSING', reason: 'Watch symbol master support read unavailable. Strategy card support missing.' })
  if (mode === 'micro') { facts.price.value = 0.0042; facts.support.value = 0.0041; facts.resistance.value = 0.0043 }
  Object.assign(row, { symbol: 'SPCX', company: 'Synthetic stored market facts', lane: 'manage', stage: 'held_review', stance: 'HOLD',
    why: 'Fixture account and source facts.', summary: 'Synthetic display only.', conflicts: [], whats_missing: [], reentry: null, last_round_trip: null,
    mine: true, starred: true, position_state: 'held', held_accounts: ['schwab_rollover_ira', 'schwab_taxable'],
    held_account_labels: ['Schwab Rollover IRA', 'Schwab Individual'], membership: [], market_facts: facts,
    next_action: { kind: 'none', label: 'Observe', reason: 'Fixture only' } })
  Object.assign(c, { interim: false, source_label: 'Fixture' })
  Object.assign(c.my_watchlist, { rows: [row], count: 1, unfiltered_count: 1, starred: 1, sources: {}, position_filters: {}, position_facets: {} })
  const traffic = { writes: [] as string[], external: [] as string[], errors: [] as string[] }
  const counts = { curation: 0 }
  page.on('pageerror', e => traffic.errors.push(e.message))
  await page.route('**/*', async route => {
    const req = route.request(); const url = new URL(req.url())
    if (url.origin !== new URL(baseURL).origin) { traffic.external.push(url.origin); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (req.method() !== 'GET') { traffic.writes.push(`${req.method()} ${url.pathname}`); return route.abort() }
    if (url.pathname === '/api/v3/data-broker/watch-curation') {
      counts.curation++
      if (mode.startsWith('refresh-') && counts.curation > 1) return route.fulfill({
        status: Number(mode.split('-')[1]), contentType: 'application/json', body: JSON.stringify({ error: 'Fixture unavailable' }),
      })
    }
    const payload = url.pathname === '/api/v3/data-broker/watch-curation' ? c
      : url.pathname === '/api/v3/data-broker/watch-prospects' ? PROS.prospects
        : url.pathname === '/api/v2/overview' ? { portfolio_value: 0, today_change: 0, today_pct: 0, top_movers: [], account_labels: {} }
          : url.pathname === '/api/v2/watch/alerts/list' ? { alerts: [] } : { ok: true, data: {}, items: [], rows: [] }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  return { facts, traffic, counts }
}

function clean(traffic: { writes: string[]; external: string[]; errors: string[] }) {
  expect(traffic).toEqual({ writes: [], external: [], errors: [] })
}

for (const width of [1440, 412]) {
  test.describe(`${width}px market facts`, () => {
    test.use({ viewport: { width, height: width === 412 ? 1300 : 1000 } })
    for (const mode of ['current', 'stale']) test(`${mode} price keeps visible source/asof and closed-session level date`, async ({ page, baseURL }) => {
      const { facts, traffic } = await mock(page, baseURL!, mode)
      await page.goto('/v3/watch?tab=my-watchlist')
      const panel = page.getByTestId('watch-market-facts'); await expect(panel).toBeVisible()
      const price = panel.getByTestId('watch-market-price')
      await expect(price).toContainText('$10.00'); await expect(price).toContainText('schwab')
      await expect(price).toContainText(mode === 'stale' ? 'Oct 22' : 'Oct 23')
      await expect(price).not.toContainText('Oct 24')
      await expect(price.locator('[data-state]')).toHaveText(mode === 'stale' ? 'Stale' : 'Current')
      await expect(panel.getByTestId('watch-market-support')).toContainText('$9.00')
      await expect(panel.getByTestId('watch-market-resistance')).toContainText('Closed session')
      await expect(panel.getByTestId('watch-market-resistance').locator('[title]')).toHaveAttribute('title', /2026-10-22 · closed session/)
      await expect(page.getByRole('heading', { level: 1, name: /Watch.*My Watchlist/ })).toBeVisible()
      await expect(page.getByTestId('mine-row')).toContainText('Schwab Rollover IRA')
      await expect(page.getByTestId('mine-row')).toContainText('Schwab Individual')
      await panel.scrollIntoViewIfNeeded()
      const geometry = await panel.evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth }))
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1)
      await page.screenshot({ path: path.join(SHOTS, `${mode}-${width}.png`), animations: 'disabled' })
      fs.writeFileSync(path.join(SHOTS, `${mode}-${width}.json`), JSON.stringify({ fixture: true, clock: CLOCK,
        viewport: page.viewportSize(), input: facts, displayed: await panel.innerText(), geometry, traffic }, null, 2) + '\n')
      clean(traffic)
    })
    test('price absence retains known levels and explicitly unknown nearest relation', async ({ page, baseURL }) => {
      const { traffic } = await mock(page, baseURL!, 'no-price'); await page.goto('/v3/watch?tab=my-watchlist')
      await expect(page.getByTestId('watch-market-price')).toContainText('—')
      await expect(page.getByTestId('watch-market-price')).toContainText('Stored quote read unavailable.')
      await expect(page.getByTestId('watch-market-support')).toContainText('$9.00')
      await expect(page.getByTestId('watch-market-resistance')).toContainText('$11.00')
      await expect(page.getByTestId('watch-market-facts')).toContainText('Price unavailable; nearest relation unknown'); clean(traffic)
    })
    test('future time and a missing level expose specific reasons', async ({ page, baseURL }) => {
      const { traffic } = await mock(page, baseURL!, 'future'); await page.goto('/v3/watch?tab=my-watchlist')
      await expect(page.getByTestId('watch-market-price')).toContainText('in the future')
      await expect(page.getByTestId('watch-market-price').locator('[data-state]')).toHaveText('Time / freshness unknown'); clean(traffic)
    })
    test('missing support is a dash with source-read reason and never a zero', async ({ page, baseURL }) => {
      const { traffic } = await mock(page, baseURL!, 'missing-support'); await page.goto('/v3/watch?tab=my-watchlist')
      await expect(page.getByTestId('watch-market-support')).toContainText('—')
      await expect(page.getByTestId('watch-market-support').locator('[title]')).toHaveAttribute('title', /read unavailable/)
      await expect(page.getByTestId('watch-market-support')).not.toContainText('$0.00'); clean(traffic)
    })
    test('sub-cent values retain distinct nonzero prices and levels', async ({ page, baseURL }) => {
      const { traffic } = await mock(page, baseURL!, 'micro'); await page.goto('/v3/watch?tab=my-watchlist')
      await expect(page.getByTestId('watch-market-price')).toContainText('$0.0042')
      await expect(page.getByTestId('watch-market-support')).toContainText('$0.0041')
      await expect(page.getByTestId('watch-market-resistance')).toContainText('$0.0043'); clean(traffic)
    })
    test('market facts are opt-in to MyList and do not alter the Prospects grid', async ({ page, baseURL }) => {
      const { traffic } = await mock(page, baseURL!); await page.goto('/v3/watch?tab=prospects')
      await expect(page.getByTestId('watch-prospects')).toBeVisible()
      await expect(page.getByTestId('watch-market-facts')).toHaveCount(0); clean(traffic)
    })
    for (const status of [503, 403]) test(`failed ${status} poll retains evidence but withdraws Current`, async ({ page, baseURL }) => {
      const { traffic, counts } = await mock(page, baseURL!, `refresh-${status}`)
      await page.goto('/v3/watch?tab=my-watchlist')
      const price = page.getByTestId('watch-market-price')
      await expect(price.locator('[data-state]')).toHaveText('Current')
      const sourceAndTime = await price.innerText()
      await page.clock.runFor(120_001)
      await expect(page.getByTestId('watch-market-refresh-warning')).toContainText('last successful snapshot')
      await expect(price.locator('[data-state]')).toHaveText('Last snapshot')
      await expect(price).toContainText('$10.00'); await expect(price).toContainText('schwab')
      await expect(price).toContainText('Oct 23, 2026, 09:59:00 AM EDT')
      expect(sourceAndTime.replace('Current', 'Last snapshot')).toBe(await price.innerText())
      expect(counts.curation).toBeGreaterThanOrEqual(2)
      if (status === 403) {
        const stopped = counts.curation; await page.clock.runFor(120_001)
        expect(counts.curation).toBe(stopped)
      }
      clean(traffic)
    })
  })
}
