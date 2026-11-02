// Whole-Home capture-truth fixture. Real HomeHub + HomeDoNow + MetricStrip + risk/platform components,
// EVERY /api/* intercepted with synthetic data. No server, no port, no live 7777, no operator fields.
//
//   node e2e/home-capture-truth.fixture.mjs <output-directory>
//
// Seven captures at 1440 and 390 (baseline first): a dated-older briefing beside a current overview, a
// briefing clock missing and in the future, platform component counts that differ from the overall health
// findings, a date-only rotation reading, an unknown price-source word, and mixed Protect amount/pct bases.
// Console errors, page errors, failed and non-GET requests are recorded per capture. Captures are baseline
// evidence, not a claim that the page is correct or that the served runtime matches these sources.
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

const NOW = '2026-11-02T19:00:00Z'
const OLD = '2026-10-29T11:00:00Z'          // three days before the overview clock
const FUTURE = '2026-11-02T21:30:00Z'
const H = (n) => String(n).repeat(40)

const ACCOUNT = 'SYNTH_ACCOUNT_A'
const overview = (over = {}) => ({
  portfolio_value: 1000000, today_change: 1200, today_pct: 0.12, cash: 250000,
  as_of: NOW, data_as_of: NOW, cached_at: NOW, pending_approvals: 2,
  today_pnl: { session_date: '2026-11-02', funded_account_count: 1, represented_account_count: 1 },
  portfolio_aggregate: { portfolio_scope: 'ALL_ACCOUNTS', position_observation_newest: NOW, position_observation_oldest: NOW,
    position_observation_oldest_age_hours: 0, valuation_time: NOW, quote_observation_time: NOW, included_account_count: 1 },
  pricing: { last_repriced: NOW, reprice_source: 'schwab' },
  accounts: [{ account: ACCOUNT, label: 'Synthetic A', value: 1000000, cash: 250000 }],
  ...over,
})

const baseApi = {
  '/api/v2/overview': overview(),
  '/api/v2/portfolio/performance': { as_of: NOW, accounts: [{ account: ACCOUNT, label: 'Synthetic A', value: 1000000, ytd_pct: 4.2 }], ytd_pct: 4.2 },
  '/api/v2/home/do-now': {
    schema: 'HomeDoNow@v1', as_of: NOW, all_sources_answered: true,
    items: [{ id: 'decide:synthetic', category: 'decide', severity: 'P2', title: 'Synthetic decision', why: 'fixture only',
      action: { label: 'Open', where: '/approvals' }, sources: ['overview'], money_at_risk_usd: 1500, money_basis: 'amount at risk' }],
    sources: { overview: { status: 'OK', as_of: NOW } },
    rolled_up: { raw_items: 1, after_dedupe: 1, inbox_total: 1, needs_action_total: 1 },
    numbers: { unprotected_positions: 1, unprotected_value_usd: 12500 },
  },
  '/api/v2/cio/pages': {
    positions: { source: 'CIO categorized positions', as_of: NOW, rows: [
      { symbol: 'SYN1', account_key: ACCOUNT, account_label: 'Synthetic A', market_value: 12500,
        stop_category: 'none', stop_reason: 'no stop on file', stop_captured_at: NOW },
      { symbol: 'SYN2', account_key: ACCOUNT, account_label: 'Synthetic A', market_value: 8000,
        stop_category: 'below', stop_reason: 'trading below stop', stop_captured_at: NOW },
    ], unprotected_value_usd: 12500 },
    stops: { as_of: NOW, last_broker_read_at: NOW, unprotected_count: 1, stale: false },
  },
  '/api/v2/risk-regime/latest': { regime_label: 'risk on trend', confidence: 0.3, trend_state: 'bullish', breadth_state: 'broad', volatility_state: 'low_vol' },
  '/api/v2/trade-ai/summary': { run_date: '2026-11-02', run_label: '0900', cached_at: NOW, run_finished_at: NOW, stale: false,
    vix: 15.1, vix_source: 'fixture', vix_observation_time: NOW,
    setup_run_summary: { run_id: '2026-11-02::0900', run_label: '0900', run_date: '2026-11-02', run_timestamp: NOW,
      scanned_count: 20, classified_count: 10, go_count: 3, wait_count: 4, nogo_count: 3, review_count: 0,
      excluded_count: 0, error_count: 0, unclassified_count: 0, count_integrity: 'RECONCILED', freshness_status: 'OK' } },
  '/api/v2/defense/posture': { as_of: NOW, rotation_plan_counts: { plans: 2 } },
  '/api/v3/opportunities?preset=top5': { as_of: NOW, items: [] },
  '/api/v2/system/platform-health': { status: 'OK', as_of: NOW, items: [
    { id: 'api', group: 'runtime', label: 'API', status: 'OK', as_of: NOW, value: 'up' },
    { id: 'db', group: 'runtime', label: 'Database', status: 'OK', as_of: NOW, value: 'up' },
    { id: 'n8n', group: 'lane', label: 'n8n', status: 'WARN', as_of: NOW, value: 'lag', reason: 'queue lag' },
  ] },
  '/api/v2/ops/deploys': { as_of: NOW, status: 'OK', open: [], stop: { state: 'RUNNING', effective_stop: false } },
  // Both shapes: `llm` is what the pre-f94 Home reads; `llm_intelligence` is the f94 object shape.
  '/api/v2/command': { as_of: NOW, llm: { generated_at: NOW, portfolio_risk: 'Synthetic morning briefing text for the fixture.' },
    llm_intelligence: { portfolio_risk: { content: 'Synthetic morning briefing text for the fixture.', generated_at: NOW } },
    executive_brief: null },
  '/api/v2/health': { as_of: NOW, findings: [
    ...Array.from({ length: 4 }, () => ({ severity: 'critical', code: 'synthetic' })),
    ...Array.from({ length: 113 }, () => ({ severity: 'warning', code: 'synthetic' })),
  ] },
  '/api/v2/health/proposals': { as_of: NOW, proposals: [] },
  '/api/v2/hermes/health': { as_of: NOW, ok: true, lanes: [] },
  '/api/v2/needs-action': { as_of: NOW, items: [] },
  '/api/v2/paper-proposals': { as_of: NOW, proposals: [] },
  '/api/v2/paper-trade-readiness': { closed_usable: 0, win_rate: null },
  '/api/v2/risk': { as_of: NOW, positions: [] },
  '/api/v2/market-risk/latest': { as_of: NOW, regime: 'neutral' },
  '/api/v2/system/metrics-history': { as_of: NOW, series: [] },
  '/api/v2/hermes/runtime': { as_of: NOW, lanes: [] },
}

// Each case patches the synthetic API; nothing else differs.
const CASES = {
  baseline: {},
  'briefing-older-than-overview': {
    '/api/v2/command': { as_of: OLD, llm: { generated_at: OLD, portfolio_risk: 'Briefing written three days ago but shown with no date.' },
      llm_intelligence: { portfolio_risk: { content: 'Briefing written three days ago but shown with no date.', generated_at: OLD } } },
  },
  'briefing-clock-missing-and-future': {
    '/api/v2/command': { as_of: FUTURE, llm: { generated_at: FUTURE, portfolio_risk: 'Briefing clock is ahead of the page clock.' },
      llm_intelligence: { portfolio_risk: { content: 'Briefing clock is ahead of the page clock.', generated_at: FUTURE } } },
  },
  'briefing-clock-missing': {
    '/api/v2/command': { llm: { portfolio_risk: 'Briefing with no clock at all.' },
      llm_intelligence: { portfolio_risk: { content: 'Briefing with no clock at all.' } } },
  },
  'platform-counts-vs-health-findings': {
    '/api/v2/system/platform-health': (() => {
      const items = []
      for (let i = 0; i < 21; i++) items.push({ id: `p${i}`, group: 'runtime', label: `Probe ${i}`, status: 'OK', as_of: NOW, value: 'up' })
      items.push({ id: 'p21', group: 'runtime', label: 'Probe 21', status: 'WARN', as_of: NOW, value: 'lag', reason: 'lag' })
      items.push({ id: 'p22', group: 'runtime', label: 'Probe 22', status: 'WARN', as_of: NOW, value: 'lag', reason: 'lag' })
      return { status: 'OK', as_of: NOW, items }
    })(),
  },
  'rotation-date-only': {
    '/api/v2/defense/posture': { as_of: '2026-11-02', rotation_plan_counts: { plans: 2 }, rotation_as_of: '2026-11-02' },
  },
  'unknown-extended-session': {
    '/api/v2/overview': overview({ pricing: { last_repriced: NOW, reprice_source: 'extended' } }),
  },
  'protect-mixed-bases': {
    '/api/v2/cio/pages': {
      positions: { source: 'CIO categorized positions', as_of: NOW, rows: [
        { symbol: 'SYN1', account_key: ACCOUNT, account_label: 'Synthetic A', market_value: 12500, stop_category: 'none', stop_reason: 'no stop on file', stop_captured_at: NOW },
        { symbol: 'SYN2', account_key: ACCOUNT, account_label: 'Synthetic A', market_value: 8000, stop_category: 'below', stop_reason: 'trading below stop', stop_captured_at: NOW },
      ], unprotected_value_usd: 12500, unprotected_pct: 1.25 },
      stops: { as_of: NOW, last_broker_read_at: NOW, unprotected_count: 1, stale: false, coverage_pct: 66.7 },
    },
  },
}

const bundled = await build({
  stdin: {
    contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom';
      import {OpportunityModalProvider} from './src/components/opportunity/OpportunityContext';
      import HomeHub from './src/pages/HomeHub'; import MetricStrip from './src/components/MetricStrip';
      import PlatformHealthPanel from './src/components/PlatformHealthPanel';
      import {AiIntelligenceBriefing} from './src/components/home/HomeTrustRender';
      import './src/index.css'; import './src/pages/OpsEvidencePages.css';
      const F = (globalThis).__FIXTURES__ || {};
      createRoot(document.getElementById('root')).render(
        <MemoryRouter><OpportunityModalProvider>
          <div className="ops-evidence-page" data-testid="synthetic-home"
            style={{background:'var(--bg0)',color:'var(--text0)',minHeight:'100vh',padding:8}}>
            <div style={{fontSize:11,opacity:0.7}}>SYNTHETIC HOME FIXTURE — no live data, no broker, no network</div>
            <section data-testid="case-strip"><MetricStrip onDrill={() => {}} /></section>
            <section data-testid="case-briefings">
              <AiIntelligenceBriefing llm={F.briefOld} />
              <AiIntelligenceBriefing llm={F.briefFuture} />
              <AiIntelligenceBriefing llm={F.briefMissing} />
            </section>
            <section data-testid="case-platform"><PlatformHealthPanel compact /></section>
            <section data-testid="case-home"><HomeHub onDrill={() => {}} /></section>
          </div>
        </OpportunityModalProvider></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'home-fixture.tsx',
  },
  bundle: true, write: false, outfile: 'fixture.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css')).text
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head>
  <body><main id="root"></main><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  for (const [name, patch] of Object.entries(CASES)) {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
      const page = await context.newPage()
      await page.clock.setFixedTime(new Date(NOW))
      const api = { ...baseApi, ...Object.fromEntries(Object.entries(patch).filter(([k]) => k.startsWith('/'))) }
      const traffic = { api: [], external: [], mutations: [], unexpected: [], consoleErrors: [], pageErrors: [], failed: [] }
      page.on('pageerror', e => traffic.pageErrors.push(String(e.message || e)))
      page.on('console', m => { if (m.type() === 'error') traffic.consoleErrors.push(m.text().slice(0, 300)) })
      page.on('requestfailed', r => traffic.failed.push(`${r.method()} ${new URL(r.url()).pathname} ${r.failure()?.errorText ?? ''}`.trim()))
      await context.addInitScript((f) => { (globalThis).__FIXTURES__ = f }, {
        briefOld: { generated_at: OLD, as_of: OLD, portfolio_risk: 'Briefing written three days ago but shown with no date.' },
        briefFuture: { generated_at: FUTURE, as_of: FUTURE, portfolio_risk: 'Briefing clock is ahead of the page clock.' },
        briefMissing: { portfolio_risk: 'Briefing with no clock at all.' },
      })
      await page.route('**/*', async route => {
        const req = route.request(); const url = new URL(req.url())
        if (url.origin !== 'http://home-fixture.test') { traffic.external.push(req.url()); return route.abort() }
        if (req.method() !== 'GET') { traffic.mutations.push(`${req.method()} ${url.pathname}`); return route.abort() }
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
        const key = Object.keys(api).find(k => k.split('?')[0] === url.pathname)
        if (key) { traffic.api.push(url.pathname); return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: api[key] }) }) }
        traffic.unexpected.push(url.pathname)
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture: unmapped path' }) })
      })
      await page.goto('http://home-fixture.test/')
      await page.waitForSelector('[data-testid="synthetic-home"]', { timeout: 20_000 })
      await page.evaluate(() => new Promise(r => setTimeout(r, 900)))
      const m = await page.evaluate(() => {
        const text = (document.body.innerText || '').replace(/\s+/g, ' ')
        const near = (label, span = 260) => {
          const i = text.indexOf(label)
          return i < 0 ? null : text.slice(i, i + span)
        }
        return {
          width: innerWidth, pageScrollWidth: document.documentElement.scrollWidth, text,
          briefing: near('AI Intelligence Briefing', 700),
          platform: near('Platform', 240),
          system: near('System pulse', 240),
          prices: near('Prices', 160),
          protect: near('Protect', 240),
        }
      })
      assert.ok(m.pageScrollWidth <= m.width + 1, `${name}@${width}: horizontal overflow ${m.pageScrollWidth} > ${m.width}`)
      assert.deepEqual(traffic.external, [], `${name}@${width}: external request attempted`)
      assert.deepEqual(traffic.mutations, [], `${name}@${width}: a mutation was attempted`)
      assert.deepEqual(traffic.pageErrors, [], `${name}@${width}: page error`)
      // Desired truths, asserted only where the surface exists today. Everything else is recorded as a
      // baseline observation so the audit can diff it against the fixed source later.
      if (name === 'unknown-extended-session' && width > 820) {
        const priceText = (m.prices ?? '') || m.text
        assert.ok(priceText.includes('extended'), `${name}@${width}: the unknown source word is shown as itself`)
        assert.ok(!priceText.includes('after-hours'), `${name}@${width}: an unknown word is never relabelled after-hours`)
      }
      if (name === 'platform-counts-vs-health-findings') {
        assert.ok((m.platform ?? '').includes('21 OK'), `${name}@${width}: platform counts come from platform probes`)
      }
      const text = m.text
      const observations = {
        briefingHasVisibleClock: /\b(?:Nov|Oct|Sep|Aug|Jul|Jun|May|Apr|Mar|Feb|Jan)\b|\d{4}-\d{2}-\d{2}T/.test(m.briefing ?? ''),
        briefingAgeShown: /\b(?:\d+\s*(?:s|m|h|d)\s*ago|in the future|time is in the future|time unknown|not recorded)\b/i.test(m.briefing ?? ''),
        platformScopeExplained: /component checks|different populations|counts critical and warning findings/i.test(text),
        platformCountsShown: /\d+\s+(?:OK|WARN|CRIT|STALE|UNKNOWN)/.test(m.platform ?? ''),
        healthFindingsInText: /\bcritical\b/i.test(text),
        rotationRenderedOnHome: /rotation/i.test(text),
        completedCloseShown: /completed close/i.test(text),
        afterHoursShown: /after-hours/i.test(text),
        protectAmountShown: /at risk/i.test(m.protect ?? ''),
        protectPctShown: /%\s*(?:at risk|unprotected|protected)/i.test(text),
        priceStampRendered: (m.prices ?? '') !== '' && (m.prices ?? '') !== null,
      }
      const file = path.join(out, `${name}-${width}.png`)
      await page.screenshot({ path: file, fullPage: true })
      results.push({ case: name, width, clock: NOW, screenshot: file,
        measured: { width: m.width, pageScrollWidth: m.pageScrollWidth, briefing: m.briefing, platform: m.platform,
          system: m.system, prices: m.prices, protect: m.protect, textSample: m.text.slice(0, 4000) },
        observations, traffic })
      await context.close()
    }
  }
} finally {
  await browser.close()
}
fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify({ fixture: 'home-capture-truth', generated_for: 'source-only baseline', results }, null, 2))
for (const r of results) console.log(`  [CAPTURE] ${r.case}@${r.width} · ${r.traffic.api.length} API · consoleErrors=${r.traffic.consoleErrors.length} failed=${r.traffic.failed.length}`)
console.log(`home-capture-truth: ${results.length} captures`)
