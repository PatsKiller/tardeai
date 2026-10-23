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

async function fixtures(page: Page) {
  await page.route('**/api/**', route => {
    const p = new URL(route.request().url()).pathname
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (p === '/api/v2/overview') return json(overview())
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

    test(`Home movers: SPCX is one row "2 accounts" that expands per account; footer sums unchanged (${width})`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(e.message))
      await fixtures(page)
      await page.goto('/v3/')
      const card = page.getByTestId('home-movers')
      await expect(card).toBeVisible()
      const spcx = card.locator('[data-testid="mover-group"][data-symbol="SPCX"]')
      await expect(spcx).toHaveCount(1)
      await expect(spcx).toHaveAttribute('data-multi', 'true')
      await expect(spcx.getByTestId('accounts-badge')).toHaveText('2 accounts')
      await expect(spcx).toContainText('+$1,995')
      // single-account rows name their account
      await expect(card.locator('[data-symbol="V"]').getByTestId('account-chip')).toHaveText('Schwab Roth IRA')
      await expect(card.locator('[data-symbol="SCHD"]').getByTestId('account-chip')).toHaveText('Schwab Rollover IRA')
      await expect(card).toContainText('Shown +$154 · rest of the book −$117 · day +$37')
      await card.scrollIntoViewIfNeeded()
      await shot(page, `home-movers-collapsed-${width}.png`)
      await spcx.getByTestId('mover-expand').click()
      const parts = spcx.getByTestId('mover-account-row')
      await expect(parts).toHaveCount(2)
      await expect(parts.nth(0)).toContainText('Schwab Rollover IRA')
      await expect(parts.nth(0)).toContainText('+$1,488')
      await expect(parts.nth(1)).toContainText('Schwab Individual')
      await expect(parts.nth(1)).toContainText('+$507')
      await expect(card).toContainText('Shown +$154 · rest of the book −$117 · day +$37')
      expect(await card.innerText()).not.toMatch(NUMBER_LEAK)
      await card.screenshot({ path: path.join(SHOTS, `home-movers-expanded-${width}.png`) })
      expect(errors).toEqual([])
    })

    test(`Risk: each SPCX chip names its account (${width})`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', e => errors.push(e.message))
      await fixtures(page)
      await page.goto('/v3/risk')
      const spcx = page.locator('[data-account] >> text=SPCX →')
      await expect(spcx).toHaveCount(2)
      const chips = page.locator('span[data-account]').filter({ hasText: 'SPCX' }).getByTestId('account-chip')
      await expect(chips).toHaveText(['Schwab Rollover IRA', 'Schwab Individual'])
      // risk bars / heatmap: one cell per account for a symbol held in two accounts
      await expect(page.getByText('SPCX · Schwab Individual')).not.toHaveCount(0)
      expect(await page.locator('body').innerText()).not.toMatch(NUMBER_LEAK)
      await page.locator('span[data-account]').filter({ hasText: 'SPCX' }).first().scrollIntoViewIfNeeded()
      await shot(page, `risk-${width}.png`)
      expect(errors).toEqual([])
    })

    test(`Journal table: Account column shows names (${width})`, async ({ page }) => {
      await fixtures(page)
      await page.goto('/v3/journal')
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
