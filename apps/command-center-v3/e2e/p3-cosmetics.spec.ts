/** P3 cosmetics (operator-approved mockups, 2026-10-23) at 1440 px and 412 px. Every API request is fulfilled
 *  locally from e2e/fixtures/p3Cosmetics.fixture.json (shapes from the site-crawl captures, synthetic money);
 *  any other path answers an empty envelope, and the test fails on any non-GET request. */
import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const FIXTURE: Record<string, unknown> = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'p3Cosmetics.fixture.json'), 'utf8'))

async function mockApi(page: Page, writes: string[]) {
  await page.route('**/api/**', async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() !== 'GET') writes.push(`${req.method()} ${url.pathname}`)
    const body = FIXTURE[url.pathname] ?? { ok: true, data: {} }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

async function openHeader(page: Page, width: number) {
  if (width >= 820) return
  const toggle = page.locator('.ms-compact__toggle')
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
}

for (const width of [1440, 412]) {
  test.describe(`P3 cosmetics @ ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } })

    test('header TRADING tile keeps its P&L; short provenance, full text in the tooltip', async ({ page }) => {
      const writes: string[] = []
      await mockApi(page, writes)
      await page.goto('/v3/risk')
      await openHeader(page, width)
      const tile = page.locator('.metric-strip-tile', { hasText: 'TRADING' }).first()
      const value = tile.locator('.ms-value')
      await expect(value).toHaveText('47.9% win · 238 · $25,505 P&L', { timeout: 60_000 })
      // Wrapped, not cut: the whole value fits inside the tile's two-line clamp.
      const clipped = await value.evaluate(el => el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1)
      expect(clipped).toBe(false)
      await expect(tile).toHaveAttribute('title', /47\.9% win rate · 238 trades · \$25,505 P&L/)
      await expect(page.locator('[data-price-stamp]')).toHaveText('Prices 16:45 ET · after-hours · 12/12')
      await expect(page.locator('[data-price-stamp]')).toHaveAttribute('title', /Finviz after-hours/)
      const vix = page.locator('.metric-strip-tile', { hasText: 'VIX' }).first()
      await expect(vix.locator('.ms-meta')).toHaveText('scanner · 17:30 run')
      await expect(vix).toHaveAttribute('title', /source trade_ai_run_summary/)
      expect(writes).toEqual([])
    })

    test('rotation advisory withheld: one amber line, reason chips, ET clocks, date-only source', async ({ page }) => {
      const writes: string[] = []
      await mockApi(page, writes)
      await page.goto('/v3/intelligence')
      const notice = page.getByTestId('rotation-publication-notice').first()
      await expect(notice).toBeVisible({ timeout: 60_000 })
      await expect(notice).toHaveAttribute('data-rotation-status', 'UNAVAILABLE')
      await expect(notice).toContainText('Rotation advisory UNAVAILABLE · withheld')
      await expect(notice.getByTestId('rotation-reason-chip')).toHaveText(['account data stale', 'position evidence stale', 'stop claim unsupported'])
      await expect(notice).toContainText('Source as of Oct 22 (date only) · checked Oct 23 08:09 ET')
      await expect(notice).not.toContainText('T00:00:00')
      await expect(notice).toHaveAttribute('title', /Source as of: 2026-10-22T00:00:00\+00:00/)
      await expect(page.getByText('AAA')).toHaveCount(0)
      if (width === 1440) {
        const box = await notice.boundingBox()
        expect(box!.height).toBeLessThan(40)
      }
      expect(writes).toEqual([])
    })

    test('Active Trader KPI captions wrap instead of being cut', async ({ page }) => {
      const writes: string[] = []
      await mockApi(page, writes)
      await page.goto('/v3/active-trader')
      const captions = page.locator('.at-kpi span')
      await expect(captions.first()).toBeVisible({ timeout: 60_000 })
      const cut = await captions.evaluateAll(els => els.filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent))
      expect(cut).toEqual([])
      expect(await captions.first().evaluate(el => getComputedStyle(el).whiteSpace)).toBe('normal')
      expect(writes).toEqual([])
    })

    test('strategy leaderboard shows human labels with the identifier in the tooltip', async ({ page }) => {
      const writes: string[] = []
      await mockApi(page, writes)
      await page.goto('/v3/strategy')
      const name = page.locator('[data-strategy-id="pullback_macd_reversal"]')
      await expect(name).toHaveText('Pullback MACD Reversal', { timeout: 60_000 })
      await expect(name).toHaveAttribute('title', 'pullback_macd_reversal')
      const row = page.locator('tr', { has: name })
      await expect(row.locator('td[title="review_risk_reward"]')).toHaveText('Review Risk Reward')
      await expect(page.locator('table', { hasText: 'Assessment' })).not.toContainText('fib_retracement_bounce')
      expect(writes).toEqual([])
    })

    test('legacy Trading ?tab= URLs are rewritten to canonical ones (history replace)', async ({ page }) => {
      const writes: string[] = []
      await mockApi(page, writes)
      await page.goto('/v3/')
      await page.goto('/v3/trading?tab=Entry+Desk&symbol=ABC')
      await expect(page).toHaveURL(/\/v3\/trading\?tab=Proposals&symbol=ABC&section=path-a$/, { timeout: 60_000 })
      await expect(page.getByTestId('proposals-section-path-a')).toHaveAttribute('aria-selected', 'true')
      // Replace, not push: Back leaves the hub instead of bouncing to the retired URL.
      await page.goBack()
      await expect(page).not.toHaveURL(/tab=Entry/)
      await page.goto('/v3/trading?tab=Broker+Recon')
      await expect(page).toHaveURL(/tab=Open\+Trades&drawer=recon$/, { timeout: 60_000 })
      await page.goto('/v3/trading?tab=Schwab+Accounts')
      await expect(page).toHaveURL(/tab=Broker\+Orders&section=schwab-accounts$/, { timeout: 60_000 })
      await page.goto('/v3/trading?tab=Broker+Proposals')
      await expect(page).toHaveURL(/tab=Proposals$/, { timeout: 60_000 })
      expect(writes).toEqual([])
    })
  })
}
