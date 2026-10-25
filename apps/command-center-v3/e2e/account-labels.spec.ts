/** Account name on every position / trade row (operator 2026-10-23: "two SpaceX and two different accounts" …
 *  "just a name, not the account numbers"). Fixture-only: every /api call is fulfilled here, nothing reaches a server.
 *
 *   npm run build && (serve dist at /v3 with no /api proxy) &
 *   PLAYWRIGHT_BASE_URL=http://127.0.0.1:4179 npx playwright test e2e/account-labels.spec.ts
 *
 *  Screenshots: $ACCTLABEL_SHOTS or ~/.cache/rtc/acctlabel (1440 and 412 px).
 */
import { test, expect, type Page } from '@playwright/test'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import FX from './fixtures/accountLabels.fixture.json' with { type: 'json' }
import W7 from './fixtures/w7Pages.fixture.json' with { type: 'json' }

const SHOTS = process.env.ACCTLABEL_SHOTS || path.join(os.homedir(), '.cache', 'rtc', 'acctlabel')
fs.mkdirSync(SHOTS, { recursive: true })
const iso = () => new Date().toISOString()
// An account number or a masked tail must never render (names only).
const NUMBER_LEAK = /(\.\.\.|··|…|\*\*)\s*\d{2,}|\b\d{6,}\b/

const overview = () => ({
  portfolio_value: 1255076, today_change: FX.today_change, today_pct: 0.003, total_cash: 654000, position_count: 31,
  observation: { envelopes: { holdings: { observed_at_utc: iso(), freshness: { status: 'FRESH', observed_at_utc: iso() } } } },
  top_movers: FX.top_movers,
  account_labels: { schwab_rollover_ira: 'Schwab Rollover IRA', schwab_taxable: 'Schwab Individual', schwab_roth: 'Schwab Roth IRA' },
  today_by_account: {},
})

// Home and Risk (approved boards 14/15) read one CIO truth document, /api/v2/cio/pages. Positions and
// Do-now items carry the server's account display name (W1 cio_truth); the page renders it as given.
const cioPages = () => {
  const payload: any = structuredClone((W7 as any).payload)
  payload.positions.rows = FX.risk_positions.map((p: any) => ({ symbol: p.symbol, account_id: p.account_id, account_label: p.account_label,
    market_value: p.market_value, stop_price: p.stop_price, stop_source: p.has_stop ? 'broker' : 'none', stop_state: p.has_stop ? 'active' : 'none',
    price: p.current_price, loss_at_stop_usd: null }))
  payload.do_now.items = FX.risk_positions.filter((p: any) => p.symbol === 'SPCX').map((p: any) => ({ id: `spcx-${p.account_id}`, symbol: 'SPCX',
    title: 'Review protection', reason: 'No active broker stop', account_label: p.account_label, href: '/risk?symbol=SPCX', cta: 'Review' }))
  return payload
}

async function fixtures(page: Page) {
  await page.route('**/api/**', route => {
    const p = new URL(route.request().url()).pathname
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/overview') return json(overview())
    if (p === '/api/v2/cio/pages') return json({ ok: true, data: cioPages() })
    if (p === '/api/v2/risk') return json({ positions: FX.risk_positions, position_count: 4, pct_protected: 50, total_risk_dollars: 22840, stops: {} })
    if (p === '/api/v2/journal') return json({ trades: FX.journal_trades, trade_count: 2 })
    if (p === '/api/v2/automated-trade-journal') return json({ trades: [] })
    if (p === '/api/v2/home/do-now') return json({ schema: 'HomeDoNow@v1', status: 'OK', as_of: iso(), all_sources_answered: true, items: [], counts: { all: 0 }, numbers: {}, sources: {} })
    if (p.startsWith('/api/v2/portfolio/performance')) return json({ current_value: 1255076, periods: { '1D': { change: FX.today_change } }, accounts: {} })
    return json({ ok: true, items: [], rows: [], data: {} })
  })
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: false })
}

for (const width of [1440, 412]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: width > 600 ? 1000 : 900 } })

    // Board 14 (desks-redesign 2026-10-24) removed the movers card from Home ("the header already carries
    // the numbers; Home never repeats them"). The operator rule — a name on every position row, never an
    // account number — is asserted on Home's own rows, the CIO-ranked Do-now list.
    test(`Home Do now: each SPCX row names its account (${width})`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(e.message))
      await fixtures(page)
      await page.goto('/v3/')
      const card = page.getByTestId('home-do-now')
      await expect(card).toBeVisible()
      await expect(page.getByTestId('home-movers')).toHaveCount(0)
      await expect(card).toContainText('Schwab Rollover IRA')
      await expect(card).toContainText('Schwab Individual')
      expect(await card.innerText()).not.toMatch(NUMBER_LEAK)
      await card.scrollIntoViewIfNeeded()
      await shot(page, `home-do-now-${width}.png`)
      expect(errors).toEqual([])
    })

    test(`Risk: each SPCX position row names its account (${width})`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(e.message))
      await fixtures(page)
      await page.goto('/v3/risk')
      // Board 15: one positions table, one row per account holding (the per-symbol chips were retired).
      const spcx = page.locator('article.w7-position-row').filter({ hasText: 'SPCX' })
      await expect(spcx).toHaveCount(2)
      await expect(spcx.nth(0)).toContainText('Schwab Rollover IRA')
      await expect(spcx.nth(1)).toContainText('Schwab Individual')
      expect(await page.locator('body').innerText()).not.toMatch(NUMBER_LEAK)
      await spcx.first().scrollIntoViewIfNeeded()
      await shot(page, `risk-${width}.png`)
      expect(errors).toEqual([])
    })

    test(`Journal table: Account column shows names (${width})`, async ({ page }) => {
      await fixtures(page)
      // /v3/journal opens the per-trade journey view (#1955); the trade log table is on the classic journal.
      await page.goto('/v3/journal?view=classic')
      const table = page.getByRole('button', { name: 'Table', exact: true })
      await table.click()
      const rows = page.locator('tr[data-account]').filter({ hasText: 'SPCX' })
      await expect(rows).toHaveCount(2)
      await expect(rows.filter({ hasText: 'Schwab Rollover IRA' })).toHaveCount(1)
      await expect(rows.filter({ hasText: 'Schwab Individual' })).toHaveCount(1)
      expect(await page.locator('body').innerText()).not.toMatch(NUMBER_LEAK)
      await rows.first().scrollIntoViewIfNeeded()
      await shot(page, `journal-table-${width}.png`)
    })
  })
}
