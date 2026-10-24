/** Real W9 pages on synthetic GETs. Every request is intercepted; no local/live server. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
import {build} from 'esbuild'
import {chromium, expect} from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = process.argv[2]
assert(output, 'Explicit evidence directory required')
const clock = '2026-10-24T22:30:00Z'
const at = '2026-10-24T22:00:00Z'
const responses = {
  '/api/v2/research-intelligence/freshness': {topics: [], stats: {}},
  '/api/v2/research-intelligence/staged': {ideas: []},
  '/api/v2/hermes/discovery-inbox': {items: []},
  '/api/v2/hermes/research-links': {links: []},
  '/api/v2/risk-regime/latest': {regime_label: 'Neutral', as_of: at},
  '/api/v2/watch/alerts/list': {alerts: []},
  '/api/v3/data-broker/watch-filters': {views: ['top_ideas'], sectors: []},
  '/api/v3/data-broker': {projections: [], projection_count: 0},
  '/api/v3/data-broker/watch-intelligence': {
    items: [], cards: [], summary: {}, counts: {total_matched: 0},
    data_quality: {status: 'PARTIAL'}, provider_calls: 0,
    data_broker: {composes: ['quotes', 'profiles']},
  },
  '/api/v3/data-broker/watch-universe': {
    as_of: at, total: 1, universe: 1, page: 1, page_size: 100,
    items: [{symbol: 'SCHD', company: 'Fixture fund', rank: 1, conviction: 67, stance: 'WATCH',
      type: 'existing', stage: 'watching', position_state: 'held',
      risk_reward: {current_price: 27, risk_pct: 5, reward_pct: 10, rr: 2},
      held_accounts: [{account_id: 'schwab_roth_ira', account_label: 'Schwab Roth IRA'}]}],
  },
  '/api/v2/pro-analyst/pills': {pills: {}},
  '/api/v2/paper-status': {},
  '/api/v2/paper-proposals': {proposals: []},
  '/api/v2/broker-proposals/summary': {queue_summary: {total: 0}},
  '/api/v2/broker-proposals': {proposals: [], items: [], pagination: {total: 0}, queue_summary: {total: 0}},
  '/api/v2/paper-trade-readiness': {},
  '/api/v2/execution/current-state': {operator_live_via_2fa_allowed: false, live_unlocked: false},
  '/api/v2/rec-intel/outcomes': {},
  '/api/v2/finviz-strip-map': {},
  '/api/v2/pullback-macd/candidates': {candidates: []},
  '/api/v2/health/proposals': {},
  '/api/v2/broker-orders/drafts': {drafts: []},
  '/api/v2/broker-orders/activity': {activity: []},
  '/api/v2/watchlist/items': {items: []},
  '/api/v2/symbol-cards': {cards: []},
  '/api/v2/schwab/accounts-live': {accounts: []},
  '/api/v2/watchlist/summary': {},
  '/api/v2/entry-desk/automation': {},
}
const bundle = await build({metafile: true, stdin: {contents: `
import React,{useEffect} from 'react';import{createRoot}from'react-dom/client';
import{BrowserRouter,Routes,Route,useNavigate}from'react-router-dom';
import Research from './src/pages/ResearchIntelligenceHub';import Watch from './src/pages/WatchHub';
import Trading from './src/pages/TradingHub';import './src/styles/tokens.css';import './src/index.css';
function Fixture(){const navigate=useNavigate();useEffect(()=>{window.fixtureNavigate=navigate},[navigate]);
return <Routes><Route path="research-intelligence" element={<Research onDrill={()=>{}}/>}/>
<Route path="watch" element={<Watch onDrill={()=>{}}/>}/><Route path="trading" element={<Trading onDrill={()=>{}}/>}/></Routes>}
createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Fixture/></BrowserRouter>);
`, resolveDir: app, sourcefile: 'w9-fixture.tsx', loader: 'tsx'}, bundle: true, write: false,
  outfile: 'fixture.js', define: {'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false'}, logLevel: 'silent'})
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const source = Object.fromEntries(Object.keys(bundle.metafile.inputs).map(name => path.resolve(app, name))
  .filter(name => name.startsWith(path.join(app, 'src') + path.sep)).map(name => [path.relative(app, name), digest(name)]))
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
fs.mkdirSync(output, {recursive: true})
const browser = await chromium.launch({headless: true})
const cases = []
try {
  for (const width of [1440, 412]) {
    const context = await browser.newContext({viewport: {width, height: 1000}})
    const page = await context.newPage()
    const traffic = {reads: [], unexpected: [], external: [], mutations: [], errors: []}
    page.on('pageerror', error => traffic.errors.push(String(error)))
    await page.clock.install({time: new Date(clock)})
    await page.routeWebSocket('**/*', ws => {traffic.external.push(ws.url()); ws.close()})
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      if (url.origin !== 'http://w9-pages-fixture.test') {traffic.external.push(url.href); return route.abort()}
      if (req.method() !== 'GET') {traffic.mutations.push(req.method() + ' ' + url.pathname); return route.abort()}
      if (req.isNavigationRequest()) return route.fulfill({contentType: 'text/html', body:
        `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><style>${css}body{background:var(--bg-0);color:var(--text-0);margin:0}#root{padding:16px;min-width:0}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
      traffic.reads.push(url.pathname + url.search)
      let data = responses[url.pathname]
      if (url.pathname === '/api/v2/research-intelligence') {
        const empty = url.searchParams.get('q') === 'AXTI'
        data = {items: empty ? [] : [{id: 'fixture-stored-brief', symbol: 'SCHD', title: 'Fixture stored fund research',
          summary: 'Synthetic recorded research for the UI proof.', created_at: at, source_system: 'Fixture',
          research_type: 'stored_research', categories: [], freshness_tier: 'fresh'}],
          stats: {matched: empty ? 0 : 1, universe: 42, by_category: {}, by_freshness: {fresh: 1}}, taxonomy: {categories: []}}
      }
      if (data === undefined) {traffic.unexpected.push(url.pathname); data = {}}
      return route.fulfill({contentType: 'application/json', body: JSON.stringify({ok: true, data})})
    })
    const shot = async state => {
      await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
      await page.screenshot({path: path.join(output, `impl-w9-${state}-${width}.png`), fullPage: true, animations: 'disabled'})
    }
    await page.goto('http://w9-pages-fixture.test/v3/research-intelligence?symbol=AXTI&source=fixture')
    const search = page.getByPlaceholder('Search briefs — Roth, IRMAA, SCHD, Fed, thesis…')
    await expect(search).toHaveValue('AXTI')
    await expect(page.getByText('No stories match these filters', {exact: true})).toBeVisible()
    await page.clock.runFor(300_100)
    await expect(search).toHaveValue('AXTI')
    const emptyReads = traffic.reads.filter(url => new URL(url, 'http://fixture').pathname === '/api/v2/research-intelligence')
    assert(emptyReads.length >= 2, 'Empty search must survive a poll')
    assert(emptyReads.every(url => new URL(url, 'http://fixture').searchParams.get('q') === 'AXTI'), 'No automatic widening of empty search')
    await shot('research-empty-filter')
    await page.evaluate(() => window.fixtureNavigate('/research-intelligence?symbol=SCHD&source=fixture'))
    await expect(search).toHaveValue('SCHD')
    await expect(page.getByText('Fixture stored fund research').first()).toBeVisible()
    await shot('research-same-page-link')
    await page.getByRole('button', {name: 'Clear all filters', exact: true}).click()
    await expect(search).toHaveValue('')
    assert.equal(new URL(page.url()).searchParams.get('symbol'), null)
    assert.equal(new URL(page.url()).searchParams.get('source'), 'fixture')
    await page.goBack()
    await expect(search).toHaveValue('SCHD')
    await page.goto('http://w9-pages-fixture.test/v3/watch?tab=intelligence')
    await expect(page.locator('[data-watch-intelligence-primary]')).toBeVisible()
    await page.getByText('Discovery & Administration', {exact: false}).click()
    await expect(page.getByRole('link', {name: 'Previous Watch layout'})).toHaveAttribute('href', '/v3/watch-legacy?legacy=1')
    await shot('watch-classic')
    await page.getByTestId('watch-tab-opportunities').click()
    await expect(page.locator('[data-opportunity-row="SCHD"]')).toBeVisible()
    await shot('watch-full-universe')
    await page.goto('http://w9-pages-fixture.test/v3/trading?tab=Proposals')
    await expect(page.getByTestId('proposals-section-path-b')).toHaveText('Broker proposals')
    await expect(page.getByTestId('proposals-section-path-a')).toHaveText('Manual Entry Desk')
    await shot('trading-proposals')
    await page.getByTestId('proposals-section-path-a').click()
    await expect(page.getByText('Manual Thinkorswim entries.', {exact: false})).toBeVisible()
    await shot('trading-manual-entry')
    assert.deepEqual({...traffic, reads: []}, {reads: [], unexpected: [], external: [], mutations: [], errors: []}, JSON.stringify(traffic))
    cases.push({width, empty_filter_polls: emptyReads, same_route_query: true, clear_and_back: true, classic_link: true, traffic})
    await context.close()
  }
} finally {await browser.close()}
for (const [file, sha] of Object.entries(source)) assert.equal(digest(path.join(app, file)), sha, `Source changed during proof: ${file}`)
fs.writeFileSync(path.join(output, 'w9-page-receipts.json'), JSON.stringify({fixture: true, clock,
  head: execFileSync('git', ['rev-parse', 'HEAD'], {cwd: app, encoding: 'utf8'}).trim(),
  patch_sha256: crypto.createHash('sha256').update(execFileSync('git', ['diff', 'HEAD'], {cwd: app})).digest('hex'),
  source_sha256: source, cases}, null, 2) + '\n')
console.log(`W9 actual-component proof: ${cases.length} widths × 6 states; no external or mutating traffic`)
