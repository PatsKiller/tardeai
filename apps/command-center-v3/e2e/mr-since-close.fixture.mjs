// LQ-20261107-1239 — "Since the close" phone acceptance fixture.
// Renders the REAL actionable card (ActionableBody/Head) with the repo's synthetic v006 payload plus the two blocks
// the market-risk join now sends (`material_news`, `overnight_markets`), at 390 and 412 px.
//   node e2e/mr-since-close.fixture.mjs <outdir>
// No live API and no network: everything is a committed synthetic fixture. No private data.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
// esbuild is resolved from the vite toolchain (not a declared dependency of this app), same as the v007 fixture.
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const here = path.dirname(fileURLToPath(import.meta.url))
const app = path.resolve(here, '..')
const glossary = path.resolve(app, '../../config/market_risk_glossary.json')
const GLOSSARY_RAW = fs.readFileSync(glossary, 'utf8')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })

// Synthetic blocks, shaped exactly as `scripts/lib/market_risk_book_join.py` emits them. The futures/overseas rows
// are deliberately split: one LEVEL ONLY print (no dated reference — the card must not imply a change) and one
// measured print against a dated close.
const BLOCKS = `
  material_news: { schema: 'MaterialNews@v1', since: '2026-11-06T16:00:00-05:00', session: '2026-11-06', gaps: [],
    items: [ { symbol: 'NVDA', count: 2, catalyst_type: 'merger_acquisition', severity: 'high', latest: '2026-11-08T03:36:00+00:00' },
             { symbol: 'V', count: 1, catalyst_type: 'guidance raise', severity: 'critical', latest: '2026-11-06T18:38:00+00:00' } ] },
  overnight_markets: { schema: 'OvernightMarkets@v1', gaps: [], stale_after_hours: 12, items: [
    { symbol: '/ES', label: 'S&P 500 futures', session: 'futures_open', session_date: '2026-11-08', price: 6810.25,
      change_pct: null, reference_date: null, reference_basis: 'none_level_only_no_dated_reference_in_payload',
      level_only: true, as_of: '2026-11-08T21:30:00+00:00', age_hours: 0.4, stale: false },
    { symbol: '/NQ', label: 'Nasdaq 100 futures', session: 'futures_open', session_date: '2026-11-08', price: 25400.5,
      change_pct: null, reference_date: null, reference_basis: 'none_level_only_no_dated_reference_in_payload',
      level_only: true, as_of: '2026-11-08T21:30:00+00:00', age_hours: 0.4, stale: false },
    { symbol: '$NIKKEI', label: 'Nikkei 225', session: 'futures_open', session_date: '2026-11-06', price: 50100,
      change_pct: 0.8, reference_date: '2026-11-05', reference_basis: 'schwab_quote_close_price_settle_dated',
      level_only: false, as_of: '2026-11-06T06:00:00+00:00', age_hours: 64, stale: true },
    { symbol: '$DAX', label: 'DAX', session: 'futures_open', session_date: '2026-11-06', price: 23150.75,
      change_pct: -0.42, reference_date: '2026-11-05', reference_basis: 'schwab_quote_close_price_settle_dated',
      level_only: false, as_of: '2026-11-06T16:30:00+00:00', age_hours: 53, stale: true } ] },
`

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom';
      import {ActionableBody, ActionableHead, ACTIONABLE_CSS} from './src/components/home/MarketRiskActionable';
      import {GlossaryProvider} from './src/components/home/MarketRiskActions';
      import {actionableModel} from './src/lib/marketRisk';
      import './src/index.css';
      import {marketRiskV006} from './e2e/fixtures/marketRisk.fixture';
      const terms = ${JSON.stringify(JSON.parse(GLOSSARY_RAW).terms)};
      const PAYLOAD = { ...marketRiskV006('ORANGE', 'NOT_NOW'), ${BLOCKS} };
      const model = actionableModel(PAYLOAD);
      if (!model) throw new Error('fixture payload did not produce a model');
      createRoot(document.getElementById('root')).render(
        <MemoryRouter><GlossaryProvider terms={terms}>
          <div className="ops-evidence-page" data-testid="since-close-frame" style={{padding:8,background:'var(--bg0)',color:'var(--text0)',minHeight:'100vh'}}>
            <style dangerouslySetInnerHTML={{__html: ACTIONABLE_CSS}} />
            <div style={{fontSize:11,opacity:.7}}>SYNTHETIC — repo fixture only, no live data</div>
            <div data-testid="card"><ActionableHead m={model} /><ActionableBody m={model} why={<span>synthetic reasons for the fixture</span>} /></div>
          </div>
        </GlossaryProvider></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'since-close-fixture.tsx',
  },
  bundle: true, write: false, outfile: 'f.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{ name: 'stub-node-fs', setup(b) {
    b.onResolve({ filter: /^node:fs$/ }, () => ({ path: 'fs-stub', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export function readFileSync(p){return String(p).endsWith("config/market_risk_glossary.json") ? ' + JSON.stringify(GLOSSARY_RAW) + ' : "{}"}', loader: 'js' }))
  } }],
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css'))?.text ?? ''
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><main id="root"></main><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  for (const width of [390, 412]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
    const page = await ctx.newPage()
    const t = { pageErrors: [], external: [] }
    page.on('pageerror', e => t.pageErrors.push(String(e.message || e)))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://since-close.test') { t.external.push(route.request().url()); return route.abort() }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      return route.fulfill({ contentType: 'application/json', body: '{"ok":false}' })
    })
    await page.goto('http://since-close.test/')
    await page.waitForSelector('[data-testid="card"]', { timeout: 5000 })
    // the section is open by default (native <details open>), so its rows are in the DOM and visible
    await page.waitForSelector('[data-testid="mr-since-close"]', { timeout: 5000 })
    await page.waitForTimeout(200)
    const m = await page.evaluate(() => {
      const section = document.querySelector('[data-testid="mr-since-close"]')
      const text = section?.innerText || ''
      const taps = [...(section?.querySelectorAll('a,summary') ?? [])].map(el => {
        const r = el.getBoundingClientRect()
        return { w: Math.round(r.width), h: Math.round(r.height), text: (el.textContent || '').slice(0, 24) }
      })
      return {
        width: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        sectionPresent: !!section,
        newsRows: document.querySelectorAll('[data-testid="mr-since-close-news-row"]').length,
        marketRows: document.querySelectorAll('[data-testid="mr-since-close-market-row"]').length,
        levelOnlyRows: document.querySelectorAll('[data-testid="mr-since-close-market-row"][data-level-only="1"]').length,
        text,
        smallTaps: taps.filter(x => x.w > 0 && (x.w < 44 || x.h < 44)),
      }
    })
    assert.deepEqual(t.pageErrors, [], `page errors at ${width}`)
    assert.deepEqual(t.external, [], `the card must not reach any external origin at ${width}: ${JSON.stringify(t.external)}`)
    assert.ok(m.sectionPresent, `the "Since the close" section is missing at ${width}`)
    assert.equal(m.overflow, false, `horizontal overflow at ${width} (${m.width}/${m.scrollWidth})`)
    assert.equal(m.newsRows, 2, `news rows at ${width}`)
    assert.equal(m.marketRows, 4, `market rows at ${width}`)
    assert.equal(m.levelOnlyRows, 2, `level-only rows at ${width}`)
    // the window is the CLOSE, never "today"
    assert.ok(/since Fri 11-06 close/i.test(m.text), `the window floor is not named at ${width}: ${m.text.slice(0, 240)}`)
    // news: catalyst type, severity and the article count
    assert.ok(/merger acquisition \(2 articles\) · high/i.test(m.text), `the held-name news line at ${width}: ${m.text.slice(0, 400)}`)
    assert.ok(/guidance raise · critical/i.test(m.text), `a critical item keeps its severity at ${width}: ${m.text.slice(0, 400)}`)
    // futures: level only is SAID, and no change is invented for it
    assert.ok(/S&P 500 futures/.test(m.text) && /Nasdaq 100 futures/.test(m.text), `futures labels at ${width}`)
    assert.ok(/level only/.test(m.text), `a level-only print says so at ${width}: ${m.text.slice(0, 600)}`)
    assert.ok(!/S&P 500 futures[^]*?level only[^]*?[−+]0\.0%/.test(m.text), `a level-only row must not show a change at ${width}`)
    assert.ok(/Nikkei 225/.test(m.text) && /DAX/.test(m.text), `overseas index labels at ${width}`)
    assert.ok(/−0\.4%/.test(m.text), `a measured overseas print shows its signed change at ${width}: ${m.text.slice(0, 600)}`)
    assert.ok(/stale print/.test(m.text), `an old print is marked stale at ${width}: ${m.text.slice(0, 600)}`)
    assert.ok(m.smallTaps.length === 0, `taps under 44px at ${width}: ${JSON.stringify(m.smallTaps)}`)
    const shot = path.join(out, `since-close-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width, shot, measured: { ...m, text: m.text.slice(0, 1200) }, traffic: t })
    await ctx.close()
  }
  console.log(JSON.stringify({ ok: true, out, results }, null, 2))
} finally {
  await browser.close()
}
