// LQ-20261107-1689 — the rotation card's FILLED tranche, rendered for real at phone widths.
// LQ-20261107-1784 rewrote the presentation: one HOLD action line, one NEXT line, no duplicated plan table. This
// fixture keeps the 1689 invariant — the card reports the shares/avg actually held and names the next step — and
// proves it in a browser:
//   filled    the action line reads HOLD and reports what was bought, at the current quote;
//   next step the next line is tranche 2 at the current price, after the CIO's own catalyst label;
//   at 390 / 412 / 1440 px nothing overflows the viewport (no sideways page scroll).
//   node e2e/rotation-filled-tranche.fixture.mjs <outdir>
// Synthetic fixture only (public repo): round figures, no operator quantities.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })

const AT = '2031-03-10T02:00:00+00:00'
const QUOTE_AT = '2031-03-10T14:45:00+00:00' // 10:45 AM ET on the fixture date
const HOLD_AT = '2031-03-10T19:54:02+00:00' // the holdings-store capture, 3:54 PM ET
const P = { source_id: 'market_risk:sectors:2031-03-07', as_of: '2031-03-07' }
const fact = (value) => ({ value, source_id: P.source_id, as_of: AT })

const PANEL = {
  header: { tier: fact('RED'), score: fact(59.6), evaluated: { value: AT, source_id: 'market_risk:x', as_of: AT },
            confirming: { n: 2, of: 4, source_id: 'market_risk:x', as_of: AT },
            sectors: { stressed: ['Technology'], stressed_sectors: 1, measured: 11, down_5d: 8, resilient: ['Healthcare'] } },
  protect: [],
  hedge: { verdict: 'WATCH', triggers: [], source_id: 'market_risk:x', as_of: AT },
  rotate: {
    source_id: 'market_risk:sectors:2031-03-07', as_of: '2031-03-07',
    candidates: [{
      ...P, key: 'xlv', symbol: 'XLV', label: 'Healthcare', state: 'RESILIENT', leadership: 'LEADERSHIP_CONFIRMED',
      qualifies: true, rs20: 9.0, dd20: -2.4, close: fact(183.6), avg20: fact(182.7),
      price: { value: 184.80, source_id: 'quote:finviz_quote_cache', as_of: QUOTE_AT },
      proposed: { target_pct: 4.0, target_usd: 16000.0, tranche1_usd: 12000.0, shares: 64, priced: true, proposed: true,
                  tranches: [{ tranche: 1, usd: 12000.0, shares: 64, leftover_usd: 844.80 },
                             { tranche: 2, usd: 12000.0, shares: 64, leftover_usd: 844.80 },
                             { tranche: 3, usd: 16000.0, shares: 86, leftover_usd: 147.20 }] },
      // 76 held of the 80 planned = 95%, a fill under the >= 90% rule. The card draws the server's record and never
      // recomputes the verdict, so the fixture supplies it whole.
      held: { shares: 76, avg_cost: 181.06, pct_of_tranche1: 95.0, filled: true, source_id: 'positions_current:sync_run_918', as_of: HOLD_AT },
      next_tranche: { tranche: 2, usd: 12000.0, shares: 64, after: 'CPI Tue 11-10 08:30 ET' },
    }],
    plan: { proposed: true, tranche1_usd: 12000.0, tranche1_pct_book: 1.2, cash_after_pct: 75.0, tranche1_filled: true,
            tranche2_after: 'CPI Tue 11-10 08:30 ET', tranche3_when: 'market tier YELLOW or better', split: [0.3, 0.3, 0.4],
            rule: 'proposed rule (fixture)' },
    buys: { gate: fact('OPEN'), line: fact('Buys open, slowly') },
    prices_as_of: QUOTE_AT, prices_sources: ['quote:finviz_quote_cache'],
  },
}

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import { createRoot } from 'react-dom/client';
      import { MemoryRouter } from 'react-router-dom';
      import MarketRiskPanelV5 from './src/components/home/MarketRiskPanelV5';
      import './src/index.css'; import './src/styles/cioCard.css';
      const panel = (window as any).PANEL;
      createRoot(document.getElementById('root')!).render(
        React.createElement(MemoryRouter, null, React.createElement(MarketRiskPanelV5, { panel, notes: [], mr: null })));`,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true, write: false, outdir: path.join(app, 'e2e/.rotation-filled-build'), format: 'esm', platform: 'browser', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent',
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const cssText = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''

function html() {
  return `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${cssText}</style>` +
    `<body style="margin:0;padding:12px;background:#0b0d10;color:#e8e8e8;font:14px system-ui"><div id="root"></div>` +
    `<script>window.PANEL = ${JSON.stringify(PANEL)}</script>` +
    `<script type="module">${js.replace(/<\/script/gi, '<\\/script')}</script>`
}

const receipt = { ticket: 'LQ-20261107-1689', viewports: [], checks: [], screenshots: [], passed: false }
const browser = await chromium.launch()
try {
  for (const [width, height] of [[390, 844], [412, 915], [1440, 1000]]) {
    const page = await browser.newPage({ viewport: { width, height } })
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html() })
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
    })
    await page.goto('http://fixture.invalid/')
    await page.waitForSelector('[data-testid="mr5-action"]')

    const act = (await page.textContent('[data-testid="mr5-action"]')).replace(/\s+/g, ' ').trim()
    const next = (await page.textContent('[data-testid="mr5-next"]')).replace(/\s+/g, ' ').trim()
    const head = (await page.textContent('[data-testid="mr5-rotate-row"]')).replace(/\s+/g, ' ').trim()

    // The action line reports what was bought — the shares and average cost the book actually holds, at the
    // current quote — and never the offer again.
    assert.equal(act, '▶ HOLD. Tranche 1 filled: 76 sh @ $181.06 (now $184.80).', `action line (${width}px): ${act}`)
    // The next step is tranche 2 at the current price, after the CIO's own catalyst label.
    assert.equal(next, 'Next: tranche 2 ≈ $12K (~64 sh). After CPI Tue 11-10 08:30 ET.', `next line (${width}px): ${next}`)
    // The header is one readable line and no longer runs the label, ticker and state together.
    assert.match(head, /^HEALTHCARE·XLV·LEADING \(confirmed\)/, `row header (${width}px): ${head}`)
    // The removed plan table cannot come back: the filled tranche is stated once, as a fact.
    assert.ok(!/Cash after tranche 1|PROPOSED · NEEDS YOUR OK/.test(head), `the old plan table is back (${width}px)`)

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      widest: Math.max(...[...document.querySelectorAll('[data-testid="mr5-panel"] *')].map(e => Math.ceil(e.getBoundingClientRect().right))),
    }))
    assert.equal(overflow.scrollWidth, overflow.clientWidth, `sideways page scroll at ${width}px`)
    assert.ok(overflow.widest <= width, `an element reaches ${overflow.widest}px in a ${width}px viewport`)
    assert.deepEqual(errors, [], `page errors at ${width}px`)

    const shot = path.join(out, `rotation-filled-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    receipt.screenshots.push(shot)
    receipt.checks.push({ width, act, next, overflow, ok: true })
    receipt.viewports.push(width)
    await page.close()
  }
  receipt.passed = true
} finally {
  await browser.close()
}
fs.writeFileSync(path.join(out, 'rotation-filled-tranche-receipt.json'), JSON.stringify(receipt, null, 2) + '\n')
console.log(`rotation-filled-tranche: ok — ${receipt.checks.length} renders at ${[...new Set(receipt.viewports)].join('/')} px`)
