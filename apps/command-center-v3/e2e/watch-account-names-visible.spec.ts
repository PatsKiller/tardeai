/** WP-29c actual UI follow-up: fully mocked, names only, pinned clock, no mutation/external traffic. */
import { expect, test, type Page } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'
import { WATCH_LISTS_FIXTURE as FX } from '../src/fixtures/watchLists.fixture'

const CLOCK = '2026-10-23T20:30:00Z'
const NAMES = ['Schwab Rollover IRA', 'Schwab Individual']
const SHOTS = process.env.WATCH_ACCOUNTS_SHOTS || path.join(os.homedir(), '.cache/rtc/codex-wp29c-ui-20261024/screenshots')
fs.mkdirSync(SHOTS, { recursive: true })
test.use({ serviceWorkers: 'block' })

async function mock(page: Page, baseURL: string, accounts: 'normal' | 'digit-labels' | 'numeric-keys' | 'missing-names' = 'normal') {
  await page.clock.setFixedTime(new Date(CLOCK))
  const curation: any = structuredClone(FX.curation)
  const row = structuredClone(curation.my_watchlist.rows[0])
  Object.assign(row, { symbol: 'SPCX', company: 'Synthetic two-account fixture', why: 'Fixture account scope; read-only observation.',
    summary: 'Synthetic holding display. No real position or trading action.', position_state: 'held', held: true,
    lane: 'manage', stage: 'held_review', stance: 'HOLD', conviction: 65, conflicts: [], whats_missing: [],
    reentry: null, last_round_trip: null, last_sell_account: null, last_sell_account_label: null, last_sell_at: null,
    membership: [{ kind: 'starred', label: 'Synthetic starred example', at: CLOCK, ref: null }],
    next_trigger: { label: 'Review account scope', level_ref: null, inside: false, distance_pct: null, observed_by: 'fixture' },
    mine: true, starred: true,
    held_accounts: accounts === 'numeric-keys' ? ['fixture-account-123456789', 'fixture-account-987654321']
      : accounts === 'missing-names' ? ['internal-storage-account', 'fixture-account-123456789'] : ['schwab_rollover_ira', 'schwab_taxable'],
    held_account_labels: accounts === 'digit-labels' ? ['Fixture 123456789', 'Fixture 987654321'] : accounts === 'missing-names' ? [] : NAMES,
    next_action: { kind: 'open_position', label: 'Open position', href: '/v3/trading?tab=open-trades&symbol=SPCX', reason: 'Fixture navigation only' } })
  Object.assign(curation, { interim: false, source: 'fixture', source_label: 'Synthetic fixture' })
  Object.assign(curation.my_watchlist, { rows: [row], count: 1, unfiltered_count: 1, starred: 1, sources: {},
    position_facets: {}, position_filters: {}, filters: {} })
  const traffic = { writes: [] as string[], external: [] as string[], errors: [] as string[], reads: [] as string[] }
  page.on('pageerror', error => traffic.errors.push(error.message))
  await page.route('**/*', async route => {
    const req = route.request(); const url = new URL(req.url())
    if (url.origin !== new URL(baseURL).origin) { traffic.external.push(url.origin); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (req.method() !== 'GET') { traffic.writes.push(`${req.method()} ${url.pathname}`); return route.abort() }
    traffic.reads.push(url.pathname)
    const body = url.pathname === '/api/v3/data-broker/watch-curation' ? curation
      : url.pathname === '/api/v2/overview' ? { portfolio_value: 0, today_change: 0, today_pct: 0, top_movers: [], account_labels: {} }
        : url.pathname === '/api/v2/watch/alerts/list' ? { alerts: [] }
          : { ok: true, data: {}, items: [], rows: [] }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return traffic
}

async function rowNames(page: Page, width: number, expectedNames = NAMES) {
  const row = page.getByTestId('mine-row').filter({ has: page.locator('[data-symbol="SPCX"]') })
  await expect(row).toHaveCount(1)
  const names = width <= 820 ? row.getByTestId('watch-phone-ownership')
    : row.getByTestId('watch-row-account-names')
  await expect(names).toBeVisible()
  for (const name of expectedNames) await expect(names).toContainText(name)
  return { row, names }
}

function clean(traffic: Awaited<ReturnType<typeof mock>>) {
  expect(traffic.writes).toEqual([]); expect(traffic.external).toEqual([]); expect(traffic.errors).toEqual([])
}

for (const width of [1440, 412]) {
  test.describe(`${width}px Watch account names`, () => {
    test.use({ viewport: { width, height: 1000 } })

    test('the current Watch view has a visible semantic page heading', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!)
      await page.goto('/v3/watch?tab=my-watchlist')
      const heading = page.getByRole('heading', { level: 1, name: /Watch.*My Watchlist/ })
      await expect(heading).toBeVisible()
      await expect(heading).toBeInViewport()
      clean(traffic)
    })

    test('both account names are readable without hover and selection preserves action targets', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!)
      await page.goto('/v3/watch?tab=my-watchlist')
      const { row, names } = await rowNames(page, width)
      await expect(page.getByRole('heading', { level: 1, name: /Watch.*My Watchlist/ })).toBeInViewport()
      await page.screenshot({ path: path.join(SHOTS, `impl-watch-heading-${width}.png`), animations: 'disabled' })
      await names.scrollIntoViewIfNeeded()
      const layout = await names.evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth }))
      expect(layout.scroll).toBeLessThanOrEqual(layout.client + 1)
      await expect(row).not.toContainText(/123456789|987654321/)
      const open = row.getByTestId('watch-step')
      await expect(open).toHaveAttribute('data-step', 'open_position')
      await expect(open).toHaveAttribute('data-href', '/v3/trading?tab=open-trades&symbol=SPCX')
      await expect(row.getByTestId('mine-star')).toHaveAttribute('data-on', '1')
      await expect(row.getByTestId('mine-remove')).toHaveCount(1)
      const choose = row.locator('button[title="Open the SPCX record"]')
      await expect(choose).toHaveAttribute('aria-pressed', 'false')
      await page.screenshot({ path: path.join(SHOTS, `impl-watch-accounts-${width}.png`), animations: 'disabled' })
      fs.writeFileSync(path.join(SHOTS, `watch-accounts-${width}.json`), JSON.stringify({ fixture: true,
        clock: CLOCK, viewport: page.viewportSize(), account_names: NAMES, visible_names: await names.innerText(),
        heading: await page.getByRole('heading', { level: 1 }).innerText(), layout, traffic }, null, 2) + '\n')
      await choose.click()
      await expect(choose).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByTestId('watch-detail')).toContainText('SPCX')
      await expect(open).toHaveAttribute('data-href', '/v3/trading?tab=open-trades&symbol=SPCX')
      clean(traffic)
    })

    test('digit-bearing supplied account labels fall back to the known names', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'digit-labels')
      await page.goto('/v3/watch?tab=my-watchlist')
      const { row } = await rowNames(page, width)
      await expect(row).not.toContainText(/123456789|987654321/)
      clean(traffic)
    })

    test('numeric account identifiers use supplied human names without exposing identifiers', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'numeric-keys')
      await page.goto('/v3/watch?tab=my-watchlist')
      const { row } = await rowNames(page, width)
      await expect(row).not.toContainText(/fixture-account|123456789|987654321/)
      clean(traffic)
    })

    test('unknown keys with missing labels remain explicitly unlabelled rather than invented names', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'missing-names')
      await page.goto('/v3/watch?tab=my-watchlist')
      const { row } = await rowNames(page, width, ['Unlabelled account'])
      await expect(row).not.toContainText(/Internal Storage Account|internal-storage-account|fixture-account|123456789|987654321/)
      for (const name of NAMES) await expect(row).not.toContainText(name)
      clean(traffic)
    })
  })
}
