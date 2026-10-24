/** WP-29(c): actual Watch/CIO/AT rendering with one synthetic two-account symbol.
 * All APIs are fulfilled, non-GET requests/external traffic are aborted, and
 * the static server has no proxy. No real positions, fills or orders are used.
 */
import { expect, test, type Page } from '@playwright/test'
import * as fs from 'node:fs'
import * as path from 'node:path'
import * as os from 'node:os'
import FX from './fixtures/accountLabelFollowups.fixture.json' with { type: 'json' }

const SHOTS = process.env.WP29_SHOTS || path.join(os.homedir(), '.cache', 'rtc', 'codex-wp29c-20261023', 'screenshots')
fs.mkdirSync(SHOTS, { recursive: true })

test.use({ serviceWorkers: 'block' })

async function fixtures(page: Page, baseURL: string) {
  await page.clock.setFixedTime(new Date(FX.clock))
  const writes: string[] = []; const external: string[] = []; const seen: string[] = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', async route => {
    const request = route.request(); const url = new URL(request.url())
    if (url.origin !== new URL(baseURL).origin) {
      external.push(url.origin)
      return route.abort()
    }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    seen.push(url.pathname)
    if (request.method() !== 'GET') {
      writes.push(`${request.method()} ${url.pathname}`)
      return route.abort()
    }
    const payload = (FX.api as Record<string, unknown>)[url.pathname] || { ok: true, data: {}, items: [], rows: [] }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  return { writes, external, seen, errors }
}

async function evidence(page: Page, name: string, traffic: Awaited<ReturnType<typeof fixtures>>, detail: object) {
  const receipt = { fixture: true, clock: FX.clock, symbol: FX.symbol, accounts: FX.accounts,
    viewport: page.viewportSize(), route: new URL(page.url()).pathname + new URL(page.url()).search,
    screenshot_full_page: false, traffic, ...detail }
  fs.writeFileSync(path.join(SHOTS, `${name}.json`), JSON.stringify(receipt, null, 2) + '\n')
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), animations: 'disabled' })
  expect(traffic.writes, 'a read-only page attempted a mutation').toEqual([])
  expect(traffic.external, 'fixture attempted external traffic').toEqual([])
  expect(traffic.errors).toEqual([])
}

for (const width of [1440, 412]) {
  test.describe(`${width}px account scope`, () => {
    test.use({ viewport: { width, height: 1000 } })

    test('Watch keeps the two-account count and exact account-name tooltip', async ({ page, baseURL }) => {
      const traffic = await fixtures(page, baseURL!)
      await page.goto('/v3/watch?tab=my-watchlist')
      const row = page.locator('[data-testid="mine-row"][data-symbol="SPCX"]')
      await expect(row).toBeVisible()
      const chip = row.getByTestId('watch-position-chip')
      await expect(chip).toHaveText('held · 2 accounts')
      for (const account of FX.accounts) await expect(chip).toHaveAttribute('title', new RegExp(account.label))
      await row.scrollIntoViewIfNeeded()
      const title = await chip.getAttribute('title')
      const layout = await row.evaluate(el => ({ clientWidth: el.clientWidth, scrollWidth: el.scrollWidth }))
      const visibleNames = await row.getByTestId('account-chip').count()
      await evidence(page, `watch-${width}`, traffic, { account_names_in_tooltip: title,
        visible_account_names: visibleNames, layout,
        gap: visibleNames ? null : 'Current held row names both accounts only in its title tooltip; screenshot shows count.' })
    })

    test('CIO Desk renders both account names on the shared position decision', async ({ page, baseURL }) => {
      const traffic = await fixtures(page, baseURL!)
      await page.goto('/v3/cio?tab=decisions')
      const card = page.getByTestId('cio-decision-card').filter({ hasText: 'SPCX' })
      await expect(card).toHaveCount(1)
      const accounts = card.getByTestId('cio-decision-accounts')
      await expect(accounts.getByTestId('accounts-badge')).toHaveText('2 accounts')
      await expect(accounts.getByTestId('account-chip')).toHaveText(FX.accounts.map(account => account.label))
      await card.scrollIntoViewIfNeeded()
      await evidence(page, `cio-${width}`, traffic, { visible_account_names: await accounts.innerText(),
        scope: 'One position decision spanning both declared accounts; no disposition button is clicked.' })
    })

    test('Active Trader review labels account fills while the shared engine signal stays accountless', async ({ page, baseURL }) => {
      const traffic = await fixtures(page, baseURL!)
      await page.goto('/v3/active-trader?tab=Session%20review')
      const section = page.getByTestId('at-review-symbol').filter({ hasText: 'SPCX' })
      await expect(section).toHaveCount(1)
      const accountCells = section.getByTestId('at-review-account')
      await expect(accountCells).toHaveCount(2)
      for (const account of FX.accounts) await expect(accountCells.filter({ hasText: account.label })).toHaveCount(1)
      const shared = section.locator('tr').filter({ hasText: 'Shared engine signal (fixture)' })
      await expect(shared).toHaveCount(1)
      await expect(shared.getByTestId('at-review-account')).toHaveCount(0)
      // The app scrolls inside its layout; scrolling the last row puts both labels
      // in the mobile viewport rather than relying on fullPage to expand that container.
      await accountCells.last().scrollIntoViewIfNeeded()
      for (const cell of await accountCells.all()) await expect(cell).toBeInViewport()
      const layout = await section.locator('.at-review__tablewrap').evaluate(el => ({ clientWidth: el.clientWidth, scrollWidth: el.scrollWidth, scrollLeft: el.scrollLeft }))
      await evidence(page, `active-trader-${width}`, traffic, { account_labels: await accountCells.allTextContents(),
        shared_signal_account_labels: 0, layout,
        scope: 'Synthetic per-account manual-fill review rows; shared advisory signal has no account authority.' })
    })
  })
}
