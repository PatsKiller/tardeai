// Home market-risk card v007 — phone acceptance fixture.
// Renders the REAL actionable card (ActionableBody/Head) with the repo's own v006 synthetic payload,
// at 390 and 412, and records what is visible before/after the v007 build.
//   node e2e/home-v007-card.fixture.mjs <outdir>
// No live API: everything is the committed synthetic fixture. No private data.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
// esbuild is resolved from the vite toolchain (it is not a declared dependency of this app); a strict, non-hoisting
// install layout would need it declared explicitly. Follow-up, not a runtime assumption of the shipped app.
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
      // The producer's quote fact carries the price as a BARE NUMBER in `value` (market_risk_home_context.py:546).
      quote: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_quotes:alpaca', age_seconds: 30, session: 'regular', session_date: '2026-11-02', expected_session_date: '2026-11-02', basis: 'last trade', value: 49.87 },
      // Producer shapes at 89663c715: day_change.value is {price, pct} with reference_session_date on the fact;
      // since_exit.value is the distance() dict; analysis_references.value is a {label: {...}} map; a headline row is
      // {title, source, url, published_at, guarded} with no age; volume carries its own basis text.
      day_change: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_data:daily_close', reference_session_date: '2026-10-30', value: { price: 0.4, pct: 0.8 } },
      since_exit: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'reentry_watch.exit_price+market_data:daily_close',
        price_as_of: '2026-11-02T21:00:00Z', reference_as_of: '2026-10-30', basis: 'distance from the recorded exit price to the current quote; the fact is clocked by the quote',
        value: { reference_price: 50, distance_price: -0.1, distance_pct: -0.3 } },
      analysis_references: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'analysis_references', value: {
        invalidation_level: { state: 'measured', reference_price: 47.5, distance_price: -2.4, distance_pct: -4.8, price_as_of: '2026-11-02T21:00:00Z', reference_as_of: '2026-11-02T20:00:00Z' },
        sma20: { state: 'unknown', reference_price: null, distance_price: null, distance_pct: null, remediation: { key: 'HOMEV007:analysis_reference:sma20', action: 'Refresh the canonical observation' } } } },
      headlines: { state: 'measured', as_of: '2026-11-02T18:00:00Z', source: 'guarded_symbol_headlines', value: [
        { title: 'Synthetic guarded headline', source: 'feed', url: 'https://example.invalid/a', published_at: '2026-11-02T18:00:00Z', guarded: true } ] },
      next_event: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'canonical_symbol_calendar', value: { kind: 'earnings', date: '2026-11-10' } },
      cio: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'cio_prospect:projection', age_seconds: 7200, value: { stance: 'hold', conviction: 3, stale: false, identity_status: 'CONFIRMED' } },
      market_risk_stance: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk.positions', value: { stance: 'elevated' } },
      volume_vs_20d: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'canonical_quote+daily_bars.volume', value: { ratio: 1.4, sample_sessions: 20, average_start_date: '2026-10-01', average_end_date: '2026-10-29', basis: 'observed session volume versus twenty prior completed-session volumes; not time-adjusted' } },
    },
    STALE1: { quote: { state: 'measured', age_seconds: 5400, as_of: '2026-11-02T19:30:00Z', value: { price: 12.5 } } },
    // COMPATIBILITY CASES, not producer shapes: the producer emits only measured | partial | unknown |
    // not_applicable. `stale` and `missing` are legacy spellings the parser still accepts, kept here to prove the
    // parser keeps the stale word (with no age) and the missing reason; do not read them as producer coverage.
    STALEWORD: { quote: { state: 'stale', as_of: '2026-11-02T20:00:00Z', value: { price: 7.25 } } },
    GONE: { quote: { state: 'missing', reason: 'canonical regular-session quote not measured', remediation: 'wait for the reader' } },
    // The producer's dual-mark conflict (same instant, two recorded observations disagree) and its
    // "source not recorded" refusal: both are payload states the card must name, not soften.
    CONFLICT: { quote: { state: 'unknown', as_of: '2026-11-02T21:00:00Z', source: 'market_quotes:alpaca',
      reason: 'Two observations of the same instant disagree',
      conflict: { reason: 'The stored observation and the reader disagree at the same instant', as_of: '2026-11-02T21:00:00Z',
        marks: [{ price: 18.04, source: 'market_quotes:alpaca' }, { price: 18.31, source: 'market_quotes' }] },
      remediation: { key: 'HOMEV007:quote.conflict', action: 'Reconcile the two recorded observations; never keep one silently.' } } },
    NOSRC: { quote: { state: 'unknown', as_of: '2026-11-02T21:00:00Z', source: 'not_recorded',
      reason: 'Canonical quote source not recorded', value: null } },
  },
  // The producer carries the risk score on the latest `history` row, not at the top level. `label` on a category is
  // NOT a producer field (it emits `category` only; the card falls back to the key) — kept here so the fixture can
  // assert a human label without pretending the payload supplies one.
  risk: { as_of: '2026-11-02T21:00:00Z', history: [{ as_of: '2026-11-02T20:00:00Z', score: 58 }, { as_of: '2026-11-02T21:00:00Z', score: 61 }], categories: [
    { category: 'tech', label: 'Technology', chip: 'STRESS', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk.category.tech' },
    { category: 'volatility', label: 'Volatility', chip: 'not_measured', state: 'unknown', as_of: '2026-10-30T20:00:00Z', carried: true,
      source: 'market_risk.category.volatility',
      reason: 'carried across a closure: the 2026-10-30 observation is not current for the 2026-11-02 session',
      remediation: { key: 'HOMEV007:market_risk_category.carried', action: 'Recompute the category from this session’s canonical observations' } },
  ], next_evaluation: { value: '2026-11-03T14:00:00Z', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk_evaluation_schedule', basis: 'registry declaration' } },
  hedge: { lagging_progress: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'defense_hedge_existing_thresholds', value: { current: 4, threshold: 10, unit: 'sectors', ratio: 0.4 } }, exposure_progress: { state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'sector_momentum_existing_exposure_trigger', value: { current: 1, threshold: 2, ratio: 0.5, group: 'Technology', basis: 'same sector_momentum.book_pct compared by existing Defense trigger' } }, inverse_moves: { SH: { quote: { state: 'measured', value: 31.2 }, day_change: { state: 'measured', value: { pct: 0.58 } } } } },
  // Rows carry the merged producer's own shape (E #2508 at f010cffac emits `presentation_binding`,
  // `budget_presentation_decision` and `source_binding` on every row, plus `state`/`as_of`). The `cash_reserve` row is a
  // COMPATIBILITY CASE: a row with no producer `state`/`as_of`/`source_binding`, kept to prove the arithmetic fallback
  // stays unknown without a clock. `risk_budget` carries the producer's `%` unit, which must not render as dollars.
  budgets: [{ budget: 'unclocked_budget', actual: 900, limit: 500, unit: 'usd', state: 'unknown', as_of: null, reason: 'source clock unavailable or in the future', remediation: { key: 'HOMEV007:budget', action: 'restore the clock' }, operator_decision: { state: 'unavailable', reason: 'decision subtype not verified', remediation: { key: 'HOMEV007:budget_presentation_decision', action: 'wire the reviewed subtype' } } }, { budget: 'demo_taxable', actual: 21000, limit: 15000, unit: 'usd', clears_when: 'below 15000', scope_id: 'account:demo', breached: true, source_binding: { as_of: '2026-11-02T21:00:00Z', sha256: 'a'.repeat(64) }, presentation_binding: { sha256: 'b'.repeat(64) }, budget_presentation_decision: { active: true, intentional_until: '2026-11-09T05:00:00Z', actor: 'operator', receipt: 'rcpt-abcdef123', history: [{ state: 'previous' }] }, operator_decision: { state: 'available', subtype: 'market_risk_budget_presentation' } }, { budget: 'risk_budget', actual: 52, limit: 35, unit: '%', state: 'measured', as_of: '2026-11-02T21:00:00Z', source: 'market_risk.budgets_detail', source_binding: { as_of: '2026-11-02T21:00:00Z', sha256: 'c'.repeat(64) }, operator_decision: { state: 'unavailable', remediation: { key: 'HOMEV007:budget_presentation_decision', action: 'wire the reviewed subtype' } } }, { budget: 'stale_budget', actual: 9000, limit: 5000, unit: 'usd', state: 'stale', as_of: '2026-11-02T19:00:00Z', source: 'market_risk.budgets_detail', source_binding: { as_of: '2026-11-02T19:00:00Z', sha256: 'd'.repeat(64) }, operator_decision: { state: 'unavailable', remediation: { key: 'HOMEV007:budget_presentation_decision', action: 'wire the reviewed subtype' } } }, { budget: 'cash_reserve', actual: 1000, limit: 5000, unit: 'usd', operator_decision: { state: 'unavailable', remediation: { key: 'pending_route', action: 'pending reviewed route' } } }],
  // COMPATIBILITY SHAPE: E's real `items` is a LIST of decisions (operator_approvals.py:494-516); `items: 3` is the
  // legacy count the parser still reads for the incomplete-ledger line. Kept to exercise that line, not as a producer.
  budget_presentation_decisions: { complete: false, items: 3, history: [{ state: 'previous' }] },
  gaps: [{ symbol: 'DEMO', field: 'cio.rationale', reason: 'store does not expose it', remediation: { key: 'ask_owner', action: 'ask owner' } }],
}
// v008 "Your names today" reads the sibling fields of the same response. Made-up symbols only (the repo is public).
// Exits are dated today (ET) so they land in the "Stopped out" group whatever day the fixture runs.
const TODAY_ET = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date())
const NAMES = {
  reentry_watch: {
    DEMO: { exit_date: TODAY_ET, exit_price: 50 },
    AAA: { exit_date: TODAY_ET, exit_price: 10, current_quote: { price: 11, pct_vs_exit: 10, as_of: '2026-11-02T21:00:00Z' } },
    BBB: { exit_date: TODAY_ET, exit_price: 20, current_quote: { reason: 'no canonical quote for this name yet' } },
    OLD1: { exit_date: '2026-10-01', exit_price: 10, current_quote: { price: 9, pct_vs_exit: -10 } },
    SH: { exit_date: TODAY_ET, exit_price: 31 },
  },
  reentry_detail: { AAA: { exit_account_label: 'Demo IRA', held_elsewhere_labels: ['Demo Taxable'] } },
  book_exposure: { stops_known: true, rows: [
    { symbol: 'CCC', account_label: 'Demo IRA', value_usd: 5000, pct_account: 12, stop_distance_pct: 4.2, stance: 'exit review' },
    { symbol: 'TINY', account_label: 'Demo IRA', value_usd: 40, stance: 'exit review' },
  ] },
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
      if (url.pathname === '/api/v2/market-risk/latest') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { home_v007: V7, ...NAMES } }) })
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
    // LIVEFIX-R (operator 2026-11-06): as first seen — sectors and diagnostics collapsed, one compact row per symbol,
    // no inline provenance or gap lines. Captured before anything is opened.
    const first = await page.evaluate(() => {
      const open = id => document.querySelector(`[data-testid="${id}"]`)?.open ?? null
      const v7 = document.querySelector('[data-testid="home-v007"]')
      const order = [...document.querySelectorAll('[data-testid="mr-actionable-body"] [data-testid$="-section"], [data-testid="home-v007"], [data-testid="v7-diagnostics"]')]
        .map(el => el.getAttribute('data-testid'))
      return {
        sectorsOpen: open('mr-sectors-section'), diagnosticsOpen: open('v7-diagnostics'),
        stoppedRows: [...document.querySelectorAll('[data-testid^="v8-stopped-"]')].filter(el => el.hasAttribute('data-status')).map(el => `${el.getAttribute('data-testid')}:${el.getAttribute('data-status')}`),
        heldRows: document.querySelectorAll('[data-testid^="v8-held-"]').length,
        olderOpen: open('v8-older'),
        v7text: v7?.innerText || '', order,
        multiSegmentHeadings: (document.body.innerText.match(/Multi-segment issuer/gi) || []).length,
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
      }
    })
    await page.screenshot({ path: path.join(out, `card-${width}-first-view.png`), fullPage: true })
    try {
      assert.equal(first.sectorsOpen, false, `the sector table is collapsed by default at ${width}`)
      assert.equal(first.diagnosticsOpen, false, `diagnostics are collapsed by default at ${width}`)
      // v008: stopped-out names grouped by their position vs the exit (above, then no price, then below); the hedge ETF is left out.
      assert.deepEqual(first.stoppedRows, ['v8-stopped-AAA:above', 'v8-stopped-BBB:no_price', 'v8-stopped-DEMO:below'], `stopped-out rows at ${width}`)
      assert.equal(first.heldRows, 1, `one held name in a stressed group at ${width}`)
      assert.equal(first.olderOpen, false, `older exits are collapsed by default at ${width}`)
      assert.ok(/Your names today/.test(first.v7text) && !/Today’s context/.test(first.v7text), `the card is renamed at ${width}`)
      assert.ok(/1 of 2 now above your exit · 1 without a price/.test(first.v7text), `the stopped-out takeaway at ${width}: ${first.v7text.slice(0, 600)}`)
      assert.ok(/ABOVE EXIT \+10\.0%/.test(first.v7text) && /NO PRICE/.test(first.v7text) && /BELOW EXIT −0\.3%/.test(first.v7text), `status pills at ${width}`)
      assert.ok(/The stop did its job/.test(first.v7text), `a below-exit row says the stop did its job at ${width}`)
      assert.ok(/still held in Demo Taxable/.test(first.v7text), `the account line names where it is still held at ${width}`)
      assert.ok(/Demo IRA stop 4\.2% below|stop 4\.2% below/.test(first.v7text) && /TINY \$40/.test(first.v7text), `held stop facts and the under-$100 footnote at ${width}: ${first.v7text.slice(0, 900)}`)
      assert.ok(/CIO view missing for \d+ of \d+ names/.test(first.v7text), `one CIO gap line at ${width}`)
      assert.ok(!/\bSH\b/.test(first.v7text.split('Diagnostics')[0]), `the inverse ETF is not in the names groups at ${width}`)
      assert.ok(!/risk score|budget risk budget/.test(first.v7text), `raw score and budget lines sit behind Diagnostics at ${width}`)
      assert.ok(/Diagnostics \(\d+ gaps?\)/i.test(first.v7text), `the diagnostics disclosure names its gap count at ${width}: ${first.v7text.slice(0, 600)}`)
      assert.ok(!/\bgap [A-Z]+\./.test(first.v7text), `no raw per-field gap line in the first view at ${width}`)
      assert.ok(!/trade time unverified/.test(first.v7text), `provenance sits behind Diagnostics at ${width}`)
      assert.ok(/exit \$50\.00/.test(first.v7text) && /now \$49\.87/.test(first.v7text), `a stopped row carries exit and now at ${width}: ${first.v7text.slice(0, 600)}`)
      assert.equal(first.overflow, false, `horizontal overflow in the first view at ${width}`)
      const at = id => first.order.indexOf(id)
      assert.ok(at('mr-positions-section') < at('mr-sectors-section') && at('mr-sectors-section') < at('mr-reentry-section')
        && at('mr-reentry-section') < at('home-v007') && at('home-v007') < at('v7-diagnostics'), `phone order positions → sectors → stopped-out → context → diagnostics at ${width}: ${first.order.join(',')}`)
    } catch (e) { process.exitCode = 1; throw e }
    await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true }))
    await page.waitForTimeout(100)
    const m = await page.evaluate(() => {
      const text = document.body.innerText || ''
      const taps = [...document.querySelectorAll('button,a,[role="button"],summary')].map(el => {
        const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), text: (el.textContent || '').slice(0, 24) }
      })
      return {
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        // Only what THIS component renders. Protect / Hedge / Rotate belong to ActionsTop, which the page
        // renders above the body (MarketRiskSummary / MarketRiskBanner) and this fixture does not mount — the
        // old checks passed only because a mislabelled section heading said "Protect · Hedge · Rotate".
        sections: {
          sectors: /Sectors vs SPY/i.test(text), reentry: /Since you were stopped out/i.test(text),
          positions: /Your positions in stressed groups/i.test(text), budgets: /Budget breaches/i.test(text),
          why: /Why this tier/i.test(text),
        },
        details: document.querySelectorAll('details').length,
        multiSegmentHeadings: (document.body.innerText.match(/Multi-segment issuer/gi) || []).length,
        gapGroups: [...document.querySelectorAll('[data-testid="v7-gap-group"]')].map(el => el.innerText),
        reentry: [...document.querySelectorAll('[data-testid="mr-reentry-row"]')].map(el => el.innerText),
        tableRows: document.querySelectorAll('[data-mr-actionable] tbody tr').length,
        smallTaps: taps.filter(x => (x.w > 0 || x.h > 0) && (x.w < 44 || x.h < 44)).length, taps: taps.filter(x => x.w > 0 || x.h > 0).length,
        smallDetail: taps.filter(x => (x.w > 0 || x.h > 0) && (x.w < 44 || x.h < 44)).slice(0, 4),
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        v7: !!document.querySelector('[data-testid="home-v007"]'),
        v7text: document.querySelector('[data-testid="home-v007"]')?.innerText || '',
        v7buttons: document.querySelectorAll('[data-testid="home-v007"] button').length,
        v7intentOpen: document.querySelectorAll('[data-testid="v7-intent-open"]').length,
        // Ask CIO only pre-fills the global Ask box; Explain opens a sheet; the gap line opens Diagnostics. None acts.
        v7askButtons: [...document.querySelectorAll('[data-testid="home-v007"] button')].filter(b => /^v8-ask-/.test(b.getAttribute('data-testid') || '')).map(b => b.textContent),
        v7otherButtons: [...document.querySelectorAll('[data-testid="home-v007"] button')].filter(b => !['v7-intent-open', 'mr-explain', 'v8-cio-gap-details'].includes(b.getAttribute('data-testid')) && !/^v8-ask-/.test(b.getAttribute('data-testid') || '')).map(b => b.getAttribute('data-testid') || b.textContent),
        caseLinks: [...document.querySelectorAll('[data-testid^="v8-case-"]')].map(a => a.getAttribute('href')),
        olderText: document.querySelector('[data-testid="v8-older"]')?.innerText || '',
      }
    })
    assert.deepEqual(t.pageErrors, [], `page errors at ${width}`)
    assert.deepEqual(t.external, [], `the card must not reach any external origin at ${width}: ${JSON.stringify(t.external)}`)
    try {
      assert.ok(Object.values(m.sections).every(Boolean), `a section is missing at ${width}: ${JSON.stringify(m.sections)}`)
      assert.equal(m.details, 8, `collapsible count at ${width} (six sections + older exits + Diagnostics)`)
      assert.equal(m.multiSegmentHeadings, 1, `"Multi-segment issuer" renders once at ${width}`)
      assert.ok(m.gapGroups.length >= 1 && m.gapGroups.every(g => /unavailable/.test(g)), `gaps render as grouped lines at ${width}: ${JSON.stringify(m.gapGroups)}`)
      for (const row of m.reentry) {
        assert.ok(!/0 of \d+ — waiting: all met/.test(row), `never "0 of N — waiting: all met" at ${width}: ${row}`)
        assert.ok(!(/STILL FALLING/.test(row) && /\+\d[\d.]*% vs exit/.test(row)), `never STILL FALLING above the exit at ${width}: ${row}`)
      }
      assert.equal(m.tableRows, 13, `sector row count at ${width}`)
      assert.equal(m.overflow, false, `horizontal overflow at ${width}`)
      assert.ok(m.smallTaps === 0, `taps under 44px at ${width}: ${JSON.stringify(m.smallDetail)}`)
      assert.ok(m.taps >= 20, `too few interactive targets measured at ${width}: ${m.taps}`)
      assert.ok(m.v7, `home_v007 section missing at ${width}`)
      assert.ok(m.v7text.includes('DEMO'), `v7 symbol missing at ${width}`)
      assert.ok(m.v7text.includes('$49.87'), `v7 price missing at ${width}`)
      assert.ok(/CIO stance · rationale unavailable for 1 symbol: DEMO — store does not expose it/.test(m.v7text), `the gap is grouped and names its symbol at ${width}: ${JSON.stringify(m.gapGroups)}`)
      assert.ok(/\$12\.5/.test(m.v7text) && /stale/.test(m.v7text) && /90m old/.test(m.v7text), `a measured-but-old quote must show its value, the word stale and its age at ${width}: ${m.v7text.slice(0,400)}`)
      assert.ok(/price unknown/.test(m.v7text) && /not measured/.test(m.v7text), `missing case not explicit at ${width}`)
      assert.ok(/fetched .*ET/.test(m.v7text) && /trade time unverified/.test(m.v7text), `the quote clock is labelled a fetch observation, not trade time, at ${width}: ${m.v7text.slice(0, 300)}`)
      // The producer's stale word carries no age: the flag alone must mark the price line.
      assert.ok(/\$7\.25 .*trade time unverified · stale/.test(m.v7text), `a stale-flagged quote says stale without an age at ${width}: ${m.v7text.slice(0, 600)}`)
      assert.ok(/intentional until/.test(m.v7text) && /breach still stands/.test(m.v7text), `an active decision reads back beside a breach that is still true at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/presentation/.test(m.v7text) && /src/.test(m.v7text), `both bindings are shown and kept distinct at ${width}`)
      assert.ok(/decision history is incomplete/.test(m.v7text), `a partial ledger says so at ${width}`)
      assert.ok(/inverse today: SH \+0\.58%/.test(m.v7text), `inverse moves render from the producer map at ${width}: ${m.v7text.slice(0, 400)}`)
      assert.ok(/next evaluation/.test(m.v7text), `a bare next-evaluation timestamp still renders at ${width}`)
      assert.ok(/since exit .*\$-?0\.1/.test(m.v7text), `a measured since-exit renders its value at ${width}: ${m.v7text.slice(0, 400)}`)
      // The recorded exit date is the fact-level `reference_as_of`; the card shows it rather than borrowing another fact.
      assert.ok(/exited 2026-10-30/.test(m.v7text), `the producer's reference_as_of renders as the exit date at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/to trigger invalidation_level -4\.80%/.test(m.v7text), `an analysis reference renders from the producer map at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/to trigger sma20 unknown/.test(m.v7text), `an unmeasured reference says unknown, not a blank level at ${width}: ${m.v7text.slice(0, 600)}`)
      // The producer's dual-mark conflict and its "source not recorded" refusal must both be named on the card.
      assert.ok(/conflicting observations: \$18\.04 \(market_quotes:alpaca\) vs \$18\.31 \(market_quotes\)/.test(m.v7text), `both conflict marks render at ${width}: ${m.v7text.slice(0, 800)}`)
      assert.ok(/not_recorded/.test(m.v7text), `an unrecorded quote source is named, not dressed in a source at ${width}: ${m.v7text.slice(0, 800)}`)
      // A carried category is unknown with the word that explains it, never an affirmative chip.
      assert.ok(/Volatility unknown — carried across a closure/.test(m.v7text), `a carried category says so at ${width}: ${m.v7text.slice(0, 800)}`)
      assert.ok(/Synthetic guarded headline · Nov 2 13:00 ET/.test(m.v7text), `a headline shows its own published clock at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/lagging sectors 4 of 10 sectors/.test(m.v7text), `the hedge trigger reads the producer unit at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/volume 1\.4× 20-day · observed session volume/.test(m.v7text), `the volume line carries the producer basis at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/budget unclocked budget: unknown — source clock unavailable/.test(m.v7text), `an unclocked budget says unknown and why at ${width}: ${m.v7text.slice(0, 500)}`)
      // The producer states unit "%" on risk-budget rows; a percentage rendered as dollars is a wrong number.
      // The producer's stale word must reach the budget line, and the score is a measurement with its own clock.
      assert.ok(/budget stale budget: \$9,000 of \$5,000 · breach .*· stale/.test(m.v7text), `a stale budget says stale at ${width}: ${m.v7text.slice(0, 900)}`)
      assert.ok(/risk score 61 · Nov 2 16:00 ET/.test(m.v7text), `the risk score shows its own clock at ${width}: ${m.v7text.slice(0, 900)}`)
      assert.ok(/budget risk budget: 52% of 35% · breach/.test(m.v7text), `a percent budget renders as a percent at ${width}: ${m.v7text.slice(0, 700)}`)
      assert.ok(!/\$52 of \$35/.test(m.v7text), `no percent budget may render as dollars at ${width}`)
      assert.ok(!/\$900/.test(m.v7text), `an unclocked budget must not publish its numbers at ${width}`)
      assert.ok(/intentional decision pending reviewed route \(pending_route\)/.test(m.v7text), `an unavailable decision states its remediation at ${width}`)
      assert.ok(/Nov 2 16:00 ET · market_data:daily_close/.test(m.v7text), `a fact with a clock and source shows both in ET at ${width}: ${m.v7text.slice(0, 500)}`)
      assert.ok(/Technology STRESS · Nov 2 16:00 ET · market_risk\.category\.tech/.test(m.v7text), `a risk category shows its own clock and source at ${width}: ${m.v7text.slice(0, 600)}`)
      assert.ok(/a size, an order or a stop level/.test(m.v7text), `advisory line missing at ${width}`)
      // The control is gated by the payload, not by a build constant: exactly the one row whose operator_decision is
      // `available` AND names a scope offers it; every other row stays read-only and shows its own unavailability.
      assert.equal(m.v7intentOpen, 1, `exactly one operator control (the intent control) at ${width}`)
      assert.deepEqual(m.v7otherButtons, [], `no other button may appear in the context at ${width}`)
      assert.deepEqual(m.v7askButtons, ['Ask CIO about AAA', 'Ask CIO about BBB', 'Ask CIO about DEMO', 'Ask CIO about CCC'], `Ask CIO per name at ${width}`)
      assert.deepEqual(m.caseLinks, ['/risk?tab=Recovery', '/risk?tab=Recovery'], `re-entry case links only on above/no-price rows at ${width}`)
      assert.ok(/Older exits on watch \(1\)/i.test(m.olderText) && /OLD1/.test(m.olderText) && /−10\.0% vs exit/.test(m.olderText), `older exits at ${width}: ${m.olderText}`)
      assert.ok(/intentional decision wire the reviewed subtype/.test(m.v7text), `the producer's own unavailable decision reason is shown at ${width}: ${m.v7text.slice(0, 600)}`)
    } catch (e) { process.exitCode = 1; throw e }
    const shot = path.join(out, `card-${width}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    results.push({ width, shot, firstView: first, measured: m, traffic: t })
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
    assert.deepEqual(t.external, [], `the unavailable block must not reach any external origin: ${JSON.stringify(t.external)}`)
    assert.ok(/unavailable/i.test(m.text), `the block says it is unavailable: ${m.text.slice(0, 300)}`)
    assert.ok(/could not be built \(TimeoutError\)/.test(m.text), `and states the producer's reason: ${m.text.slice(0, 300)}`)
    assert.ok(/Restore the additive context module/.test(m.text), `and its remediation: ${m.text.slice(0, 300)}`)
    assert.ok(/Diagnostics \(1 gap\)/i.test(m.text), `the failure's gaps sit in the Diagnostics disclosure: ${m.text.slice(0, 400)}`)
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
