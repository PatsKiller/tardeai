/** W3 approved board18; all APIs intercepted, no served-backend traffic. */
import { expect, test, type Page } from '@playwright/test'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import fixture from './fixtures/w3_sectors.json'

const SHOTS = process.env.W3_SIGNAL_SHOTS || path.join(os.homedir(), '.cache/rtc/w3-signal-shots')
fs.mkdirSync(SHOTS, { recursive: true })
test.use({ serviceWorkers: 'block' })

async function mock(page: Page, baseURL: string, mode: string) {
  await page.clock.setFixedTime(new Date('2026-10-24T22:00:00Z'))
  const data: any = structuredClone(fixture)
  if (mode === 'missing') {
    data.gap = 'Sector prices unavailable'
    for (const s of data.sectors) Object.assign(s, { rs_20d_pct: null, rs_60d_pct: null, momentum: 'missing',
      trend: 'Not measured', cio_posture: 'Not measured', gap: 'Both 20- and 60-session relative strength are required' })
  }
  if (mode === 'stale') for (const s of data.sectors) s.stale = true
  const traffic = { writes: [] as string[], external: [] as string[], errors: [] as string[] }
  page.on('pageerror', e => traffic.errors.push(e.message))
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.origin !== new URL(baseURL).origin) { traffic.external.push(url.origin); return route.abort() }
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (req.method() !== 'GET' && mode === 'tap' && ['/api/v2/watch/directives', '/api/v2/pullback-macd/dismiss'].includes(url.pathname)) {
      if (url.pathname === '/api/v2/watch/directives') for (const sector of data.sectors) if (sector.etf === 'XLK') sector.is_watched = true
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, directive_id: 41 }) })
    }
    if (req.method() !== 'GET') { traffic.writes.push(`${req.method()} ${url.pathname}`); return route.abort() }
    const candidates = [
      { symbol: 'AES', tier: 'watch', proposal_id: 41, proposal_live: true, score: 90 },
      { symbol: 'RTX', tier: 'trigger', proposal_id: 42, proposal_live: true, score: 80, held: { shares: 10, market_value: 100, stop_price: 9, stop_state: 'pending_activation', account_labels: ['schwab_roth_ira'] } },
      { symbol: 'ABT', tier: 'trigger', proposal_id: 43, proposal_live: false, score: 70 },
    ]
    const payload = url.pathname === '/api/v2/sectors/monitor' ? data
      : url.pathname === '/api/v2/pullback-macd/candidates' ? { ok: true, candidates }
        : url.pathname === '/api/v2/overview' ? { portfolio_value: 0, today_change: 0, today_pct: 0, top_movers: [], account_labels: {} }
          : url.pathname === '/api/v2/watch/alerts/list' ? { alerts: [] }
            : { ok: true, data: {}, items: [], rows: [] }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  return traffic
}

for (const width of [1440, 412, 390]) {
  test.describe(`${width}px W3`, () => {
    test.use({ viewport: { width, height: width === 412 ? 915 : width === 390 ? 844 : 1100 }, hasTouch: width < 821 })
    for (const mode of ['current', 'missing', 'stale']) test(`sectors ${mode}`, async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, mode)
      await page.goto('/v3/watch?tab=sectors')
      const tech = page.getByTestId('sector-XLK')
      await expect(tech).toBeVisible()
      if (mode === 'missing') await expect(tech).toContainText('Not measured')
      else {
        await expect(tech).toContainText('Weakening')
        await expect(tech).toContainText('Review')
        await expect(tech).toContainText('+1.40%')
        await expect(page.getByTestId('sector-XLP')).toContainText('Favoured')
      }
      if (mode === 'stale') await expect(tech).toContainText('Historical observation')
      const geometry = await tech.evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth }))
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: path.join(SHOTS, `impl-18-${mode}-${width}.png`), fullPage: true })
      expect(traffic).toEqual({ writes: [], external: [], errors: [] })
    })

    test('sector tap flow: filter, detail, back, browser Back, watch', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'tap')
      await page.goto('/v3/watch?tab=sectors')
      await page.getByLabel('Filter sector trend').selectOption('lagging')
      await expect(page.getByTestId('sector-XLP')).toHaveCount(0)
      const open = page.getByRole('button', { name: 'View Technology' })
      const activate = async (button: ReturnType<Page['getByRole']>) => { await button.scrollIntoViewIfNeeded(); width < 821 ? await button.tap() : await button.click() }
      await activate(open)
      const detail = page.getByRole('dialog', { name: 'Technology detail' })
      await expect(detail).toBeVisible()
      const box = await detail.boundingBox(); expect(box).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
      if (width < 821) { expect(box!.x).toBe(0); expect(box!.y).toBe(0); expect(box!.height).toBe(width === 412 ? 915 : 844) }
      await activate(detail.getByRole('button', { name: 'Back' }))
      await expect(detail).toHaveCount(0)
      await activate(open); await page.goBack(); await expect(detail).toHaveCount(0)
      await activate(open)
      const watch = detail.getByRole('button', { name: 'Watch sector', exact: true })
      const actionBox = await watch.boundingBox(); expect(actionBox!.height).toBeGreaterThanOrEqual(44)
      await activate(watch)
      await expect(detail.getByRole('status')).toContainText('Now watching Technology')
      await expect(detail.getByRole('status')).toBeInViewport()
      await expect(detail.getByRole('button', { name: 'Watching sector' })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: path.join(SHOTS, `impl-18-tap-watch-${width}.png`) })
      expect(traffic).toEqual({ writes: [], external: [], errors: [] })
    })
    test('pullback tap flow: filter, setup detail, back and dismiss', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'tap')
      await page.goto('/v3/watch?tab=pullback-macd')
      await page.getByLabel('Filter setup tier').selectOption('watch')
      await expect(page.getByRole('button', { name: 'View RTX setup' })).toHaveCount(0)
      const open = page.getByRole('button', { name: 'View AES setup' })
      const activate = async (button: ReturnType<Page['getByRole']>) => { await button.scrollIntoViewIfNeeded(); width < 821 ? await button.tap() : await button.click() }
      await activate(open)
      const detail = page.getByRole('dialog', { name: 'AES setup detail' })
      await expect(detail).toBeVisible()
      const box = await detail.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.y).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
      await activate(detail.getByRole('button', { name: 'Back' })); await expect(detail).toHaveCount(0)
      await activate(open); await page.goBack(); await expect(detail).toHaveCount(0)
      await activate(open)
      const dismiss = detail.getByRole('button', { name: 'Dismiss from this screen' })
      expect((await dismiss.boundingBox())!.height).toBeGreaterThanOrEqual(44)
      await activate(dismiss)
      await expect(detail).toHaveCount(0)
      await expect(page.getByTestId('pullback-action-notice')).toContainText('✓ AES dismissed')
      await expect(page.getByTestId('pullback-action-notice')).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: path.join(SHOTS, `impl-pullback-tap-dismiss-${width}.png`) })
      expect(traffic).toEqual({ writes: [], external: [], errors: [] })
    })
    test('pullback queue requires a trigger and a live proposal', async ({ page, baseURL }) => {
      const traffic = await mock(page, baseURL!, 'pullback')
      await page.goto('/v3/watch?tab=pullback-macd')
      await expect(page.getByTestId('pullback-RTX').getByText('Advisory proposal in approval queue')).toBeVisible()
      await expect(page.getByTestId('pullback-RTX')).toContainText('Pending activation')
      await expect(page.getByTestId('pullback-RTX')).toContainText('Schwab Roth IRA')
      await expect(page.getByTestId('pullback-RTX')).not.toContainText('schwab_roth_ira')
      await expect(page.getByTestId('pullback-AES').getByText('Advisory proposal in approval queue')).toHaveCount(0)
      await expect(page.getByTestId('pullback-ABT').getByText('Advisory proposal in approval queue')).toHaveCount(0)
      await expect(page.getByText('Watching · trigger confirmation required')).toBeVisible()
      await page.screenshot({ path: path.join(SHOTS, `impl-pullback-queue-${width}.png`), fullPage: true })
      expect(traffic).toEqual({ writes: [], external: [], errors: [] })
    })
  })
}
