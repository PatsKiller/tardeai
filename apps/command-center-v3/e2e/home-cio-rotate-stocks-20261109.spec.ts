/** LQ-20261107-1655 — the individual stock rows under a defensive ETF row, measured at 412 px.
 *
 *  The operator asked for the names to sit under each ETF row in the Home CIO card's rotate column. The column
 *  is 344 px wide inside the phone's 20 px padding at 412 px, and a stock row carries four pieces of text a
 *  phone can be pushed sideways by: a symbol, a close with its date, an RS figure and the stock-vs-ETF sentence.
 *
 *  This spec bundles MarketRiskPanelV5 on its own with a synthetic panel and serves it at a fake origin — no
 *  server, no /api, no writes, no live symbol or dollar amount. Two apples are checked, both operator-visible:
 *  the document does not scroll sideways, and no descendant spills past the card's right edge (a page can
 *  "fit" while a child is clipped inside an overflow:hidden ancestor, which is the same invisible loss).
 *
 *  Fail-before on the parent revision: the base component renders no stock rows at all, so the presence
 *  assertion fails before the width assertion is even reached.
 *
 *    npx playwright test e2e/home-cio-rotate-stocks-20261109.spec.ts --project=chromium --workers=1
 */
import { expect, test } from '@playwright/test'
import { build } from 'esbuild'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const ORIGIN = 'http://home-cio-rotate-stocks-20261109.invalid'
const PHONE = { width: 412, height: 915 }
const T = '2031-03-07'

const fact = (value: number, source_id: string) => ({ value, source_id, as_of: T })
const stock = (symbol: string, held: boolean, close: number, rs: number, shares?: number) => ({
  symbol, held, close: fact(close, `ticker_prices:daily:${symbol}`), rs20: fact(rs, `ticker_prices:rs20_vs_spy:${symbol}`),
  ...(shares ? { tranche1_usd: 1200, tranche1_shares: shares, proposed: true as const } : {}),
  // the longest a real comparison line gets: both RS readings, the gap and both closes
  compare: `RS ${rs >= 0 ? '+' : ''}${rs.toFixed(1)} vs XLV +13.8 pts vs SPY over 20 sessions — `
    + `${rs >= 13.8 ? 'leads' : 'trails'} the ETF by ${Math.abs(rs - 13.8).toFixed(1)} pts; close ${close.toFixed(2)} vs XLV 184.40`,
  source_id: `ticker_prices:daily:${symbol}`, as_of: T,
})

const PANEL = {
  header: { tier: fact('YELLOW', 'market_risk:2031-03-07'), held: { readings_support: 'ORANGE', held_tier: 'YELLOW', sessions_recorded: 2, sessions_needed: 3 } },
  protect: [], positions: { rows: [] },
  rotate: {
    source_id: 'market_risk:sectors:2031-03-07', as_of: T,
    candidates: [
      { key: 'healthcare', symbol: 'XLV', label: 'Healthcare', state: 'RESILIENT', rs20: 13.8, qualifies: true,
        close: fact(184.4, 'market_ohlcv_bars:daily:XLV:2031-03-07'), source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        proposed: { target_pct: 4.0, target_usd: 4000.0, tranche1_usd: 1200.0, shares: 6, proposed: true },
        stocks: [stock('DEMOH', true, 30.0, -4.25, 40), stock('DEMOB', false, 12.5, 21.0, 96),
          stock('DEMOC', false, 7.375, 18.25, 162), stock('DEMOD', false, 104.5, 16.0, 11)] },
      { key: 'staples', symbol: 'XLP', label: 'Staples', state: 'RESILIENT', rs20: 13.5, qualifies: true,
        close: fact(99.0, 'market_ohlcv_bars:daily:XLP:2031-03-07'), source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        proposed: { target_pct: 3.0, target_usd: 3000.0, tranche1_usd: 900.0, shares: 9, proposed: true },
        stocks: [stock('DEMOE', false, 5.125, 9.0, 175), stock('DEMOF', false, 61.0, 4.5, 14)] },
      { key: 'utilities', symbol: 'XLU', label: 'Utilities', state: 'NEUTRAL', rs20: 9.7, qualifies: false,
        source_id: 'market_risk:sectors:2031-03-07', as_of: T,
        stocks: [stock('DEMOU', false, 41.0, 6.0)] },
    ],
    plan: { proposed: true, tranche1_usd: 2100.0, split: [0.3, 0.3, 0.4] },
  },
}

let js = '', css = ''
test.beforeAll(async () => {
  const b = await build({
    stdin: {
      contents: `import React from 'react';import{createRoot}from'react-dom/client';
        import { MemoryRouter } from 'react-router-dom';
        import Panel from './src/components/home/MarketRiskPanelV5';
        import'./src/styles/tokens.css';import'./src/index.css';
        const panel = ${JSON.stringify(PANEL)};
        createRoot(document.getElementById('root')).render(<MemoryRouter><main className="app-main" style={{padding:20}}>
          <div id="card" style={{width:344}}><Panel panel={panel} notes={[]} mr={null}/></div></main></MemoryRouter>);`,
      resolveDir: app, loader: 'tsx', sourcefile: 'home-cio-rotate-stocks.tsx',
    },
    bundle: true, write: false, outfile: 'fixture.js', platform: 'browser', jsx: 'automatic',
    define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false' }, logLevel: 'silent',
  })
  js = b.outputFiles.find(f => f.path.endsWith('.js'))!.text.replace(/<\/script/gi, '<\\/script')
  css = b.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
})

test('the stock rows are drawn under their ETF row at 412 px, and nothing is pushed sideways', async ({ page }) => {
  await page.setViewportSize(PHONE)
  await page.route('**/*', async route => {
    const u = new URL(route.request().url())
    if (u.origin !== ORIGIN) return route.abort()
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg0);color:var(--text0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
  })
  await page.goto(ORIGIN + '/')
  await expect(page.getByTestId('mr5-rotate-stocks').first()).toBeVisible()
  // every name on the wire is drawn: held first, then the ranked constituents
  expect(await page.getByTestId('mr5-stock-row').count()).toBe(7)
  const first = page.getByTestId('mr5-stock-row').first()
  expect(await first.innerText()).toContain('DEMOH')
  expect(await first.innerText()).toContain('HELD')

  const sidewaysBy = await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth)
  expect(sidewaysBy, 'the rotate column pushed the document past 412 px').toBeLessThanOrEqual(0)

  const spill = await page.evaluate(() => {
    const card = document.getElementById('card')!
    const right = card.getBoundingClientRect().right
    const worst = [...card.querySelectorAll('*')].reduce((m, n) => Math.max(m, n.getBoundingClientRect().right), 0)
    return Math.round(worst - right)
  })
  expect(spill, 'a stock row spills past the card right edge').toBeLessThanOrEqual(0)

  // and the sub-list is one column: its rows all start at the same x, whatever their text length
  const lefts = await page.getByTestId('mr5-stock-row').evaluateAll(rows => rows.map(r => Math.round(r.getBoundingClientRect().left)))
  expect(new Set(lefts).size, 'stock rows are not in one column').toBe(1)
})

test('390 px keeps the same promise', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/*', async route => {
    const u = new URL(route.request().url())
    if (u.origin !== ORIGIN) return route.abort()
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}body{margin:0;background:var(--bg0);color:var(--text0)}</style></head><body><div id="root"></div><script>${js}</script></body></html>` })
  })
  await page.goto(ORIGIN + '/')
  await expect(page.getByTestId('mr5-rotate-stocks').first()).toBeVisible()
  expect(await page.evaluate(() => document.scrollingElement!.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0)
})
