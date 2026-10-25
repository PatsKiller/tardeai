/** Batch-28 gaps, phone tap proof at 412 and 390 (every request intercepted; no server, no live data).
 * (a) the Awaiting-fill row's timeline exit and review "Status" rows read "Awaiting fill — …" in info tone,
 *     never "Stop likely filled — not confirmed";
 * (b) "Compare with a win" pairs only CLOSED trips with a realized gain; with none, it says
 *     "No closed winning trip yet" and never falls back to an open unrealized gain.
 * Journeys/Replay bodies are the builder-generated e2e/fixtures/tradeinviewRedesign.fixture.json (synthetic inputs).
 */
import { expect, test, type Page } from '@playwright/test'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'

const tiv = JSON.parse(readFileSync(new URL('./fixtures/tradeinviewRedesign.fixture.json', import.meta.url), 'utf8'))
const origin = 'http://tradeinview-gaps.invalid'
const fresh = tiv.journeys.fresh
const awaiting = fresh.journeys.find((j: any) => j.exit_cause.kind === 'stop_likely_filled')
const REPLAY_TRADE = tiv.replay.bars.trade_id as string
// Same journeys with every closed trip turned into a realized loss: only open (unrealized) rows could look like wins.
const ledgerStore = tiv.journeys.ledger_store, noLedger = tiv.journeys.no_ledger
const noClosedWin = { ...fresh, journeys: fresh.journeys.map((j: any) => j.status === 'closed' ? { ...j, pl: { ...j.pl, amount: -Math.abs(j.pl.amount ?? 1) } } : { ...j, pl: { ...j.pl, amount: 999 } }) }
let js = '', css = ''
test.beforeAll(async () => {
  const b = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';
    import TradeInViewPage from'./src/pages/TradeInViewPage';import'./src/styles/tokens.css';import'./src/index.css';
    createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><TradeInViewPage onDrill={()=>{}}/></BrowserRouter>);`,
    resolveDir: process.cwd(), loader: 'tsx', sourcefile: 'tradeinview-gaps.tsx' },
    bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent' })
  js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script'); css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
})
async function serve(page: Page, journeys: any) {
  const forbidden: string[] = []
  await page.routeWebSocket('**/*', ws => { forbidden.push('WS:' + ws.url()); ws.close() })
  await page.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url())
    if (req.method() !== 'GET' || u.origin !== origin) { forbidden.push(req.method() + ':' + req.url()); return route.abort() }
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    if (u.pathname.startsWith('/v3/')) return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0)}#root{padding:16px;box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
    if (u.pathname === '/api/v3/data-broker/trade-journeys') return json(journeys)
    if (u.pathname.startsWith('/api/v3/data-broker/trade-journeys/')) {
      const id = decodeURIComponent(u.pathname.slice('/api/v3/data-broker/trade-journeys/'.length)), journey = journeys.journeys.find((j: any) => j.trade_id === id)
      return journey ? json({ ...journeys, journeys: undefined, journey }) : route.abort()
    }
    if (u.pathname === '/api/v2/trade-chart') {
      if (u.searchParams.get('stored_only') !== '1') { forbidden.push('provider:' + u.search); return route.abort() }
      const body = Object.values(tiv.replay as Record<string, any>).find(r => r.trade_id === u.searchParams.get('trade_id'))
      return body ? json(body) : route.abort()
    }
    forbidden.push('unlisted:' + u.pathname); return route.abort()
  })
  return forbidden
}
const tapTarget = async (page: Page, locator: ReturnType<Page['locator']>) => {
  await locator.scrollIntoViewIfNeeded()
  const r = await locator.boundingBox(); expect(r && r.width >= 44 && r.height >= 44, JSON.stringify(r)).toBe(true)
  await locator.tap()
}

test.describe('phone: batch-28 gaps', () => {
  test.use({ hasTouch: true, isMobile: true })
  for (const viewport of [{ width: 412, height: 915 }, { width: 390, height: 844 }]) {
    test(`Awaiting fill wording in timeline + Status ${viewport.width}`, async ({ page }) => {
      expect(awaiting, 'fixture needs an Awaiting-fill journey').toBeTruthy()
      await page.setViewportSize(viewport)
      const forbidden = await serve(page, fresh)
      await page.goto(origin + '/v3/journal?tab=journeys')
      const row = page.locator(`[data-testid="tj-row"][data-trade-id=${JSON.stringify(awaiting.trade_id)}]`)
      await tapTarget(page, row.getByTestId('tj-open-journey'))
      const sheet = page.getByTestId('tj-detail-sheet')
      await expect(sheet).toBeVisible()
      expect(await sheet.boundingBox()).toEqual({ x: 0, y: 0, ...viewport })
      const exit = page.getByTestId('tj-timeline').locator('[data-testid="tj-event"][data-kind="exit_fill"]')
      await exit.scrollIntoViewIfNeeded()
      await expect(exit).toContainText('Awaiting fill — mark under stop $40.00 · fill sync')
      const status = page.getByTestId('tj-review').locator('div', { hasText: /^Status/ })
      await expect(status.first()).toContainText('Awaiting fill — mark under stop $40.00')
      await expect(sheet).not.toContainText(/likely filled/i)
      // info tone, the same colour as the info-toned Awaiting-fill banner title (not the warning token).
      const colours = await page.evaluate(() => ({
        label: getComputedStyle(document.querySelector('[data-testid="tj-event"][data-kind="exit_fill"] span:nth-child(2)') as HTMLElement).color,
        banner: getComputedStyle(document.querySelector('[data-testid="tj-awaiting-fill"] b') as HTMLElement).color }))
      expect(colours.label).toBe(colours.banner)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await tapTarget(page, page.getByTestId('tj-detail-back'))
      await expect(sheet).toBeHidden()
      expect(forbidden).toEqual([])
    })

    test(`Ledger synced chip reads the ledger store clock, labelled, or says Not measured ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      let forbidden = await serve(page, ledgerStore)
      await page.goto(origin + '/v3/journal?tab=journeys')
      const chip = page.getByTestId('tj-chip-ledger_sync')
      await chip.scrollIntoViewIfNeeded()
      await expect(chip).toContainText('Ledger synced 2026-11-04T16:48:02+00:00')
      await expect(page.getByTestId('tj-chip-ledger_sync-source')).toHaveText(/ledger row write/)
      await expect(chip).not.toContainText('Not measured')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      expect(forbidden).toEqual([])
      await page.unrouteAll({ behavior: 'ignoreErrors' })
      forbidden = await serve(page, noLedger)
      await page.goto(origin + '/v3/journal?tab=journeys')
      await expect(page.getByTestId('tj-chip-ledger_sync')).toContainText('Ledger synced Not measured')
      await expect(page.getByTestId('tj-chip-ledger_sync-source')).toHaveCount(0)
      expect(forbidden).toEqual([])
    })

    test(`Compare with a win pairs a closed realized win ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const forbidden = await serve(page, fresh)
      await page.goto(origin + '/v3/journal?tab=replay&trade=' + encodeURIComponent(REPLAY_TRADE))
      await tapTarget(page, page.getByTestId('replay-compare-win'))
      const dialog = page.getByRole('dialog', { name: 'Compare recorded trades' })
      await expect(dialog).toBeVisible()
      const partner = dialog.getByRole('combobox', { name: 'Closed winning trip' })
      const ids = await partner.locator('option').evaluateAll(os => os.map(o => (o as HTMLOptionElement).value))
      const closedWins = fresh.journeys.filter((j: any) => j.status === 'closed' && (j.pl.amount ?? 0) > 0 && j.trade_id !== REPLAY_TRADE).map((j: any) => j.trade_id)
      expect(ids.length).toBeGreaterThan(0)
      expect(ids.every(id => closedWins.includes(id))).toBe(true)
      await expect(dialog.getByTestId('compare-no-closed-win')).toHaveCount(0)
      await tapTarget(page, dialog.getByRole('button', { name: 'Close comparison' }))
      await expect(dialog).toHaveCount(0)
      expect(forbidden).toEqual([])
    })

    test(`Compare with a win shows "No closed winning trip yet", never an open gain ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const forbidden = await serve(page, noClosedWin)
      await page.goto(origin + '/v3/journal?tab=replay&trade=' + encodeURIComponent(REPLAY_TRADE))
      await tapTarget(page, page.getByTestId('replay-compare-win'))
      const dialog = page.getByRole('dialog', { name: 'Compare recorded trades' })
      await expect(dialog).toBeVisible()
      await expect(dialog.getByTestId('compare-no-closed-win')).toContainText('No closed winning trip yet')
      const partner = dialog.getByRole('combobox', { name: 'Closed winning trip' })
      const values = await partner.locator('option').evaluateAll(os => os.map(o => (o as HTMLOptionElement).value))
      expect(values).toEqual([''])
      // Exactly one chart (the selected trade): no open position was substituted as the "win".
      await expect(dialog.getByTestId('trade-replay-chart')).toHaveCount(1)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await tapTarget(page, dialog.getByRole('button', { name: 'Close comparison' }))
      await expect(dialog).toHaveCount(0)
      expect(forbidden).toEqual([])
    })
  }
})
