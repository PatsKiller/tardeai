// LQ-20261107-1654 — the rotation card's whole-share sizing, rendered for real at phone widths.
// Renders the actual MarketRiskPanelV5 with a synthetic HomeCioCard@v1 `panel` and proves, in a browser:
//   priced    the action line shows floor-shares at the LIVE quote, and the card states "Prices as of <ET>" from
//             the oldest quote in the batch;
//   unpriced  with no quote the action line says the share count needs a live price (never a count off yesterday's
//             close) and the card says there is no current quote;
//   at 390 / 412 / 1440 px nothing overflows the viewport (no sideways page scroll).
//   node e2e/rotation-whole-shares.fixture.mjs <outdir>
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
const P = { source_id: 'market_risk:sectors:2031-03-07', as_of: '2031-03-07' }
const fact = (value) => ({ value, source_id: P.source_id, as_of: AT })

// Two qualifying defensives, one at 184.80 (the operator's worked example price) and one at 85.40.
const CANDIDATE = (symbol, label, state, price, rows, over = {}) => ({
  ...P, key: symbol.toLowerCase(), symbol, label, state, leadership: 'RESILIENT', qualifies: true, rs20: 9.0, dd20: -2.4,
  close: fact(price - 1.2), avg20: fact(price - 2.1),
  ...(price == null ? {} : { price: { value: price, source_id: 'quote:finviz_quote_cache', as_of: QUOTE_AT } }),
  proposed: { target_pct: 4.0, target_usd: 150650.0, tranche1_usd: 45195.0, shares: rows[0].shares, priced: price != null,
              tranches: rows, proposed: true },
  ...over,
})

const PANEL = (priced) => ({
  header: { tier: fact('RED'), score: fact(59.6), evaluated: { value: AT, source_id: 'market_risk:x', as_of: AT },
            confirming: { n: 2, of: 4, source_id: 'market_risk:x', as_of: AT },
            sectors: { stressed: ['Technology'], stressed_sectors: 1, measured: 11, down_5d: 8, resilient: ['Healthcare', 'Staples'] } },
  protect: [],
  hedge: { verdict: 'WATCH', triggers: [], source_id: 'market_risk:x', as_of: AT },
  rotate: {
    source_id: 'market_risk:sectors:2031-03-07', as_of: '2031-03-07',
    candidates: [
      CANDIDATE('XLV', 'Healthcare', 'RESILIENT', priced ? 184.80 : null, [
        { tranche: 1, usd: 4520.0, shares: priced ? 24 : null, leftover_usd: priced ? 84.80 : null },
        { tranche: 2, usd: 4520.0, shares: priced ? 24 : null, leftover_usd: priced ? 84.80 : null },
        { tranche: 3, usd: 6026.0, shares: priced ? 32 : null, leftover_usd: priced ? 112.40 : null }]),
      CANDIDATE('XLP', 'Staples', 'RESILIENT', priced ? 85.40 : null, [
        { tranche: 1, usd: 4520.0, shares: priced ? 52 : null, leftover_usd: priced ? 79.20 : null },
        { tranche: 2, usd: 4520.0, shares: priced ? 52 : null, leftover_usd: priced ? 79.20 : null },
        { tranche: 3, usd: 6026.0, shares: priced ? 70 : null, leftover_usd: priced ? 48.00 : null }]),
    ],
    plan: { proposed: true, tranche1_usd: 90390.0, tranche1_pct_book: 3.0, split: [0.3, 0.3, 0.4], rule: 'proposed rule (fixture)' },
    ...(priced ? { prices_as_of: QUOTE_AT, prices_sources: ['quote:finviz_quote_cache'] }
               : { prices_missing: ['XLV', 'XLP'] }),
  },
})

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
  bundle: true, write: false, outdir: path.join(app, 'e2e/.rotation-build'), format: 'esm', platform: 'browser', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent',
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const cssText = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''

function html(panel) {
  return `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${cssText}</style>` +
    `<body style="margin:0;padding:12px;background:#0b0d10;color:#e8e8e8;font:14px system-ui"><div id="root"></div>` +
    `<script>window.PANEL = ${JSON.stringify(panel)}</script>` +
    `<script type="module">${js.replace(/<\/script/gi, '<\\/script')}</script>`
}

const receipt = { ticket: 'LQ-20261107-1654', viewports: [], checks: [], screenshots: [], passed: false }
const browser = await chromium.launch()
try {
  for (const [width, height] of [[390, 844], [412, 915], [1440, 1000]]) {
    for (const variant of ['priced', 'unpriced']) {
      const priced = variant === 'priced'
      const page = await browser.newPage({ viewport: { width, height } })
      const errors = []
      page.on('pageerror', e => errors.push(String(e)))
      await page.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html(PANEL(priced)) })
        return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' })
      })
      await page.goto('http://fixture.invalid/')
      await page.waitForSelector('[data-testid="mr5-action"]')

      const actions = await page.$$eval('[data-testid="mr5-action"]', els => els.map(e => e.textContent.replace(/\s+/g, ' ').trim()))
      const asof = (await page.textContent('[data-testid="mr5-prices-asof"]')).replace(/\s+/g, ' ')

      if (priced) {
        assert.deepEqual(actions, [
          '▶ PROPOSED. Tranche 1 $45,195 ≈ 24 sh at $184.80. Needs your OK.',
          '▶ PROPOSED. Tranche 1 $45,195 ≈ 52 sh at $85.40. Needs your OK.',
        ], `action lines (${width}px)`)
        assert.match(asof, /Prices as of 10:45 AM ET\./)
      } else {
        // The dollars still show — only the share count refuses, and it says why.
        assert.ok(actions.length > 0 && actions.every(a => /\$45,195/.test(a) && /share count needs a live price/.test(a)),
                  `unpriced action lines (${width}px): ${JSON.stringify(actions)}`)
        assert.match(asof, /No current quote: share counts need a live price\./)
        assert.match(asof, /Not priced: XLV, XLP\./)
      }

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        widest: Math.max(...[...document.querySelectorAll('[data-testid="mr5-panel"] *')].map(e => Math.ceil(e.getBoundingClientRect().right))),
      }))
      assert.equal(overflow.scrollWidth, overflow.clientWidth, `sideways page scroll at ${width}px (${variant})`)
      assert.ok(overflow.widest <= width, `an element reaches ${overflow.widest}px in a ${width}px viewport (${variant})`)
      assert.deepEqual(errors, [], `page errors at ${width}px (${variant})`)

      const shot = path.join(out, `rotation-${variant}-${width}.png`)
      await page.screenshot({ path: shot, fullPage: true })
      receipt.screenshots.push(shot)
      receipt.checks.push({ width, variant, actions, overflow, ok: true })
      receipt.viewports.push(width)
      await page.close()
    }
  }
  receipt.passed = true
} finally {
  await browser.close()
}
fs.writeFileSync(path.join(out, 'rotation-whole-shares-receipt.json'), JSON.stringify(receipt, null, 2) + '\n')
console.log(`rotation-whole-shares: ok — ${receipt.checks.length} renders at ${[...new Set(receipt.viewports)].join('/')} px`)
