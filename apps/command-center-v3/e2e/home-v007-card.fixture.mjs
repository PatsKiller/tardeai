// Home market-risk card v007 — phone acceptance fixture.
// Renders the REAL actionable card (ActionableBody/Head) with the repo's own v006 synthetic payload,
// at 390 and 412, and records what is visible before/after the v007 build.
//   node e2e/home-v007-card.fixture.mjs <outdir>
// No live API: everything is the committed synthetic fixture. No private data.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const GLOSSARY_RAW = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../config/market_risk_glossary.json'), 'utf8')
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
fs.mkdirSync(out, { recursive: true })

const bundled = await build({
  stdin: {
    contents: `(globalThis as any).process = (globalThis as any).process || { env: {}, cwd: () => '.', platform: 'browser' };
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom';
      import {ActionableBody, ActionableHead, ACTIONABLE_CSS} from './src/components/home/MarketRiskActionable';
      import {GlossaryProvider} from './src/components/home/MarketRiskActions';
      import {actionableModel} from './src/lib/marketRisk';
      import './src/index.css';
      const terms = ${JSON.stringify(JSON.parse(fs.readFileSync(path.join(app, '../../config/market_risk_glossary.json'), 'utf8')).terms)};
      import {marketRiskV006} from './e2e/fixtures/marketRisk.fixture';
      const PAYLOAD = marketRiskV006('ORANGE', 'NOT_NOW');
      const model = actionableModel(PAYLOAD);
      createRoot(document.getElementById('root')).render(
        <MemoryRouter><GlossaryProvider terms={terms}>
          <div className="ops-evidence-page" data-testid="v007-frame" style={{padding:8,background:'var(--bg0)',color:'var(--text0)',minHeight:'100vh'}}>
            <style dangerouslySetInnerHTML={{__html: ACTIONABLE_CSS}} />
            <div style={{fontSize:11,opacity:.7}}>SYNTHETIC — repo fixture only, no live data</div>
            <div data-testid="card"><ActionableHead m={model} /><ActionableBody m={model} why={<span>synthetic reasons for the fixture</span>} /></div>
          </div>
        </GlossaryProvider></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'v007-fixture.tsx',
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

const V7 = {
  symbols: {
    DEMO: {
      quote: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_quotes:alpaca', age_seconds: 30, session: 'regular', session_date: '2026-11-02', expected_session_date: '2026-11-02', basis: 'last trade', value: { price: 49.87 } },
      day_change: { state: 'ok', value: { usd: 0.4, pct: 0.8, reference_date: '2026-10-30' } },
      since_exit: { state: 'ok', value: { usd: -0.1, pct: -0.3, exit_price: 50, exit_date: '2026-10-30' } },
      analysis_references: [{ label: 'invalidation', price: 47.5, distance_usd: -2.4, distance_pct: -4.8, state: 'ok' }],
      headlines: [{ title: 'Synthetic guarded headline', source: 'feed', published_at: '2026-11-02T18:00:00Z', age_seconds: 10800 }],
      next_event: { label: 'earnings', at: '2026-11-10T21:00:00Z', state: 'ok' },
      cio: { state: 'measured', value: { stance: 'hold', conviction: 3, store_label: 'canonical', stale: false }, age_seconds: 7200 },
      market_risk_stance: { state: 'measured', value: { stance: 'elevated' } },
      volume_vs_20d: { state: 'ok', value: { ratio: 1.4, sample_dates: ['2026-10-31'], not_time_adjusted: true } },
    },
    STALE1: { quote: { state: 'measured', age_seconds: 5400, as_of: '2026-11-02T19:30:00Z', value: { price: 12.5 } } },
    GONE: { quote: { state: 'missing', reason: 'canonical regular-session quote not measured', remediation: 'wait for the reader' } },
  },
  risk: { score: 61, categories: [{ category: 'tech', label: 'Technology', chip: 'STRESS', state: 'measured' }], next_evaluation: { value: '2026-11-03T14:00:00Z', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk_evaluation_schedule', basis: 'registry declaration' } },
  hedge: { lagging_progress: { value: { current: 4.8, threshold: 10, met: false }, state: 'measured' }, exposure_progress: { value: { current: 1, threshold: 2, met: false }, state: 'measured' }, inverse_moves: { SH: { quote: { state: 'measured', value: 31.2 }, day_change: { state: 'measured', value: { pct: 0.58 } } } } },
  budgets: [{ budget: 'demo_taxable', actual: 21000, limit: 15000, unit: 'usd', clears_when: 'below 15000', scope_id: 'account:demo', breached: true, source_binding: { as_of: '2026-11-02T21:00:00Z', sha256: 'a'.repeat(64) }, presentation_binding: { sha256: 'b'.repeat(64) }, budget_presentation_decision: { active: true, intentional_until: '2026-11-09T05:00:00Z', actor: 'operator', receipt: 'rcpt-abcdef123', history: [{ state: 'previous' }] }, operator_decision: { state: 'available', subtype: 'market_risk_budget_presentation' } }, { budget: 'cash_reserve', actual: 1000, limit: 5000, unit: 'usd', operator_decision: { state: 'unavailable', remediation: { key: 'pending_route', action: 'pending reviewed route' } } }],
  budget_presentation_decisions: { complete: false, items: 3, history: [{ state: 'previous' }] },
  gaps: [{ symbol: 'DEMO', field: 'cio.rationale', reason: 'store does not expose it', remediation: { key: 'ask_owner', action: 'ask owner' } }],
}
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
      if (url.origin !== 'http://v007.test') { t.external.push(route.request().url()); return route.abort() }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      if (url.pathname === '/api/v2/market-risk/latest') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { home_v007: V7 } }) })
      return route.fulfill({ contentType: 'application/json', body: '{"ok":false}' })
    })
    await page.goto('http://v007.test/')
    try { await page.waitForSelector('[data-testid="card"]', { timeout: 5000 }) }
    catch (e) {
      const txt = await page.evaluate(() => document.body.innerText.slice(0, 300))
      const errs = t.pageErrors.join(' | ')
      throw new Error(`card not rendered at ${width}; pageErrors=${errs}; text=${txt}`)
    }
    await page.waitForTimeout(300)
    const m = await page.evaluate(() => {
      const text = document.body.innerText || ''
      const taps = [...document.querySelectorAll('button,a,[role="button"],summary')].map(el => {
        const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), text: (el.textContent || '').slice(0, 24) }
      })
      return {
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        sections: { protect: /Protect/i.test(text), hedge: /Hedge/i.test(text), rotate: /Rotate/i.test(text), sectors: /Sectors vs SPY/i.test(text), reentry: /Since you were stopped out/i.test(text) },
        details: document.querySelectorAll('details').length,
        tableRows: document.querySelectorAll('[data-mr-actionable] tbody tr').length,
        smallTaps: taps.filter(x => (x.w > 0 || x.h > 0) && (x.w < 44 || x.h < 44)).length, taps: taps.filter(x => x.w > 0 || x.h > 0).length,
        smallDetail: taps.filter(x => (x.w > 0 || x.h > 0) && (x.w < 44 || x.h < 44)).slice(0, 4),
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        v7: !!document.querySelector('[data-testid="home-v007"]'),
        v7text: document.querySelector('[data-testid="home-v007"]')?.innerText || '',
        v7buttons: document.querySelectorAll('[data-testid="home-v007"] button').length,
        v7intentOpen: document.querySelectorAll('[data-testid="v7-intent-open"]').length,
        v7otherButtons: [...document.querySelectorAll('[data-testid="home-v007"] button')].filter(b => b.getAttribute('data-testid') !== 'v7-intent-open').length,
      }
    })
    assert.deepEqual(t.pageErrors, [], `page errors at ${width}`)
    try {
      assert.ok(Object.values(m.sections).every(Boolean), `a section is missing at ${width}: ${JSON.stringify(m.sections)}`)
      assert.equal(m.details, 6, `collapsible count at ${width}`)
      assert.equal(m.tableRows, 13, `sector row count at ${width}`)
      assert.equal(m.overflow, false, `horizontal overflow at ${width}`)
      assert.ok(m.smallTaps === 0, `taps under 44px at ${width}: ${JSON.stringify(m.smallDetail)}`)
      assert.ok(m.taps >= 20, `too few interactive targets measured at ${width}: ${m.taps}`)
      assert.ok(m.v7, `home_v007 section missing at ${width}`)
      assert.ok(m.v7text.includes('DEMO'), `v7 symbol missing at ${width}`)
      assert.ok(m.v7text.includes('$49.87'), `v7 price missing at ${width}`)
      assert.ok(/\$12\.5/.test(m.v7text) && /stale/.test(m.v7text) && /90m old/.test(m.v7text), `a measured-but-old quote must show its value, the word stale and its age at ${width}: ${m.v7text.slice(0,400)}`)
      assert.ok(/price unknown/.test(m.v7text) && /not measured/.test(m.v7text), `missing case not explicit at ${width}`)
      assert.ok(/intentional until/.test(m.v7text) && /breach still stands/.test(m.v7text), `an active decision reads back beside a breach that is still true at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/presentation/.test(m.v7text) && /src/.test(m.v7text), `both bindings are shown and kept distinct at ${width}`)
      assert.ok(/decision history is incomplete/.test(m.v7text), `a partial ledger says so at ${width}`)
      assert.ok(/inverse today: SH \+0\.58%/.test(m.v7text), `inverse moves render from the producer map at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/next evaluation/.test(m.v7text), `a bare next-evaluation timestamp still renders at ${width}`)
      assert.ok(/intentional decision pending reviewed route \(pending_route\)/.test(m.v7text), `an unavailable decision states its remediation at ${width}`)
      assert.ok(/a size, an order or a stop level/.test(m.v7text), `advisory line missing at ${width}`)
      // One control is legitimate now: the operator-only intent for the row that declares a decision available.
      // Everything else in the section stays read-only, and an unavailable decision still offers nothing.
      assert.equal(m.v7buttons, 1, `exactly one operator intent control at ${width}, got ${m.v7buttons}`)
      assert.equal(m.v7intentOpen, 1, `the intent control must be the operator one at ${width}`)
      assert.equal(m.v7otherButtons, 0, `no other button may appear in the context at ${width}`)
    } catch (e) { process.exitCode = 1; throw e }
    const shot = path.join(out, `card-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width, shot, measured: m, traffic: t })
    await ctx.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify({ fixture: 'home-v007-card', results }, null, 2))
for (const r of results) {
  const m = r.measured
  console.log(`  [${m.overflow ? 'FAIL' : 'CAPTURE'}] ${r.width}: sections=${Object.entries(m.sections).filter(([, v]) => v).map(([k]) => k).join(',')} details=${m.details} rows=${m.tableRows} taps<44px=${m.smallTaps}/${m.taps} overflow=${m.overflow}`)
}
