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
      // Producer shapes at 89663c715: day_change.value is {price, pct} with reference_session_date on the fact;
      // since_exit.value is the distance() dict; analysis_references.value is a {label: {...}} map; a headline row is
      // {title, source, url, published_at, guarded} with no age; volume carries its own basis text.
      day_change: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_data:daily_close', reference_session_date: '2026-10-30', value: { price: 0.4, pct: 0.8 } },
      since_exit: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'reentry_watch.exit_price+market_data:daily_close', value: { reference_price: 50, distance_price: -0.1, distance_pct: -0.3 } },
      analysis_references: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'analysis_references', value: {
        invalidation: { state: 'measured', reference_price: 47.5, distance_price: -2.4, distance_pct: -4.8, price_as_of: '2026-11-02T21:00:00Z' } } },
      headlines: { state: 'measured', as_of: '2026-11-02T18:00:00Z', source: 'guarded_symbol_headlines', value: [
        { title: 'Synthetic guarded headline', source: 'feed', url: 'https://example.invalid/a', published_at: '2026-11-02T18:00:00Z', guarded: true } ] },
      next_event: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'canonical_symbol_calendar', value: { kind: 'earnings', date: '2026-11-10' } },
      cio: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'cio_prospect:projection', age_seconds: 7200, value: { stance: 'hold', conviction: 3, stale: false, identity_status: 'CONFIRMED' } },
      market_risk_stance: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk.positions', value: { stance: 'elevated' } },
      volume_vs_20d: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'canonical_quote+daily_bars.volume', value: { ratio: 1.4, sample_sessions: 20, average_start_date: '2026-10-01', average_end_date: '2026-10-29', basis: 'observed session volume versus twenty prior completed-session volumes; not time-adjusted' } },
    },
    STALE1: { quote: { state: 'measured', age_seconds: 5400, as_of: '2026-11-02T19:30:00Z', value: { price: 12.5 } } },
    GONE: { quote: { state: 'missing', reason: 'canonical regular-session quote not measured', remediation: 'wait for the reader' } },
  },
  risk: { score: 61, categories: [{ category: 'tech', label: 'Technology', chip: 'STRESS', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'risk_engine' }], next_evaluation: { value: '2026-11-03T14:00:00Z', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk_evaluation_schedule', basis: 'registry declaration' } },
  hedge: { lagging_progress: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'defense_hedge_existing_thresholds', value: { current: 4, threshold: 10, unit: 'sectors', ratio: 0.4 } }, exposure_progress: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'sector_momentum_existing_exposure_trigger', value: { current: 1, threshold: 2, ratio: 0.5, group: 'Technology', basis: 'same sector_momentum.book_pct compared by existing Defense trigger' } }, inverse_moves: { SH: { quote: { state: 'measured', value: 31.2 }, day_change: { state: 'measured', value: { pct: 0.58 } } } } },
  // Rows carry the producer's own shape. `presentation_binding` / `budget_presentation_decision` and the top-level
  // ledger are E's forward contract, not fields the 2506 producer emits today; they are labelled here as such and the
  // parser unit test (homeV007.test.ts, "E's budget decision contract") is where that contract is pinned.
  budgets: [{ budget: 'unclocked_budget', actual: 900, limit: 500, unit: 'usd', state: 'unknown', as_of: null, reason: 'source clock unavailable or in the future', remediation: { key: 'HOMEV007:budget', action: 'restore the clock' }, operator_decision: { state: 'unavailable', reason: 'decision subtype not verified', remediation: { key: 'HOMEV007:budget_presentation_decision', action: 'wire the reviewed subtype' } } }, { budget: 'demo_taxable', actual: 21000, limit: 15000, unit: 'usd', clears_when: 'below 15000', scope_id: 'account:demo', breached: true, source_binding: { as_of: '2026-11-02T21:00:00Z', sha256: 'a'.repeat(64) }, presentation_binding: { sha256: 'b'.repeat(64) }, budget_presentation_decision: { active: true, intentional_until: '2026-11-09T05:00:00Z', actor: 'operator', receipt: 'rcpt-abcdef123', history: [{ state: 'previous' }] }, operator_decision: { state: 'available', subtype: 'market_risk_budget_presentation' } }, { budget: 'cash_reserve', actual: 1000, limit: 5000, unit: 'usd', operator_decision: { state: 'unavailable', remediation: { key: 'pending_route', action: 'pending reviewed route' } } }],
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
      assert.ok(/fetched .*ET/.test(m.v7text) && /trade time unverified/.test(m.v7text), `the quote clock is labelled a fetch observation, not trade time, at ${width}: ${m.v7text.slice(0, 300)}`)
      assert.ok(/intentional until/.test(m.v7text) && /breach still stands/.test(m.v7text), `an active decision reads back beside a breach that is still true at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/presentation/.test(m.v7text) && /src/.test(m.v7text), `both bindings are shown and kept distinct at ${width}`)
      assert.ok(/decision history is incomplete/.test(m.v7text), `a partial ledger says so at ${width}`)
      assert.ok(/inverse today: SH \+0\.58%/.test(m.v7text), `inverse moves render from the producer map at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/next evaluation/.test(m.v7text), `a bare next-evaluation timestamp still renders at ${width}`)
      assert.ok(/since exit .*\$-?0\.1/.test(m.v7text), `a measured since-exit renders its value at ${width}: ${m.v7text.slice(0, 400)}`)
      // The producer emits no exit date on this fact, so the card must not print one (it used to borrow day_change's).
      assert.ok(!/exited \d{4}-\d{2}-\d{2}/.test(m.v7text), `no exit date may be invented at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/to trigger invalidation -4\.80%/.test(m.v7text), `an analysis reference renders from the producer map at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/Synthetic guarded headline · Nov 2 13:00 ET/.test(m.v7text), `a headline shows its own published clock at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/lagging sectors 4 of 10 sectors/.test(m.v7text), `the hedge trigger reads the producer unit at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/volume 1\.4× 20-day · observed session volume/.test(m.v7text), `the volume line carries the producer basis at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/budget unclocked budget: unknown — source clock unavailable/.test(m.v7text), `an unclocked budget says unknown and why at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(!/\$900/.test(m.v7text), `an unclocked budget must not publish its numbers at ${width}`)
      assert.ok(/intentional decision pending reviewed route \(pending_route\)/.test(m.v7text), `an unavailable decision states its remediation at ${width}`)
      assert.ok(/Nov 2 16:00 ET · market_data:daily_close/.test(m.v7text), `a fact with a clock and source shows both in ET at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/Technology STRESS · Nov 2 16:00 ET · risk_engine/.test(m.v7text), `a risk category shows its own clock and source at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/a size, an order or a stop level/.test(m.v7text), `advisory line missing at ${width}`)
      // The control is gated by the payload, not by a build constant: exactly the one row whose operator_decision is
      // `available` AND names a scope offers it; every other row stays read-only and shows its own unavailability.
      assert.equal(m.v7buttons, 1, `exactly one operator control at ${width}, got ${m.v7buttons}`)
      assert.equal(m.v7intentOpen, 1, `the intent control must be the operator one at ${width}`)
      assert.equal(m.v7otherButtons, 0, `no other button may appear in the context at ${width}`)
      assert.ok(/intentional decision wire the reviewed subtype/.test(m.v7text), `the producer's own unavailable decision reason is shown at ${width}: ${m.v7text.slice(0, 600)}`)
    } catch (e) { process.exitCode = 1; throw e }
    const shot = path.join(out, `card-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width, shot, measured: m, traffic: t })
    await ctx.close()
  }

  // The producer stated a failure: {state:"unavailable", reason, remediation, gaps, read_errors}. It must render as a
  // stated failure, not as a present-but-empty frame over an empty body.
  {
    const UNAVAILABLE = { schema: 'HomeMarketRiskContext@v1', state: 'unavailable', generated_at: '2026-11-02T21:00:00Z',
      symbols: {}, positions: [], budgets: [],
      reason: 'the additive home context could not be built (TimeoutError)',
      remediation: { key: 'HOMEV007:context', action: 'Restore the additive context module; no fact is shown while it is unavailable.' },
      gaps: [{ symbol: null, field: 'home_v007', reason: 'the additive home context could not be built (TimeoutError)', remediation: { key: 'HOMEV007:context', action: 'Restore the additive context module' } }],
      read_errors: [{ source: 'home_v007_join', reason: 'TimeoutError', remediation: { key: 'HOMEV007:context', action: 'Restore' } }] }
    const ctx = await browser.newContext({ viewport: { width: 390, height: 900 }, serviceWorkers: 'block' })
    const page = await ctx.newPage()
    const t = { pageErrors: [], external: [] }
    page.on('pageerror', e => t.pageErrors.push(String(e.message || e)))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://v007.test') { t.external.push(route.request().url()); return route.abort() }
      if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
      if (url.pathname === '/api/v2/market-risk/latest') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { home_v007: UNAVAILABLE } }) })
      return route.fulfill({ contentType: 'application/json', body: '{"ok":false}' })
    })
    await page.goto('http://v007.test/')
    await page.waitForSelector('[data-testid="home-v007-unavailable"]', { timeout: 5000 })
    await page.waitForTimeout(200)
    const m = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="home-v007-unavailable"]')
      return {
        text: el?.innerText || '',
        presentFrame: !!document.querySelector('[data-testid="home-v007"]'),
        buttons: el?.querySelectorAll('button').length ?? -1,
      }
    })
    assert.deepEqual(t.pageErrors, [], 'page errors on the unavailable block')
    assert.ok(/unavailable/i.test(m.text), `the block says it is unavailable: ${m.text.slice(0, 300)}`)
    assert.ok(/could not be built \(TimeoutError\)/.test(m.text), `and states the producer's reason: ${m.text.slice(0, 300)}`)
    assert.ok(/Restore the additive context module/.test(m.text), `and its remediation: ${m.text.slice(0, 300)}`)
    assert.equal(m.presentFrame, false, 'no present-but-empty frame is rendered over the failure')
    assert.equal(m.buttons, 0, 'a failed block offers no control')
    const shot = path.join(out, 'card-unavailable-390.png')
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width: 390, case: 'unavailable', shot, measured: m, traffic: t })
    await ctx.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify({ fixture: 'home-v007-card', results }, null, 2))
for (const r of results) {
  const m = r.measured
  if (r.case === 'unavailable') {
    console.log(`  [CAPTURE] ${r.width} unavailable: stated-failure panel, no frame, ${m.buttons} buttons`)
    continue
  }
  console.log(`  [${m.overflow ? 'FAIL' : 'CAPTURE'}] ${r.width}: sections=${Object.entries(m.sections).filter(([, v]) => v).map(([k]) => k).join(',')} details=${m.details} rows=${m.tableRows} taps<44px=${m.smallTaps}/${m.taps} overflow=${m.overflow}`)
}
