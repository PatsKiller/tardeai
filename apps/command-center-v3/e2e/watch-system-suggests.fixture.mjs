/** Synthetic, fully intercepted System Suggests phone/desktop proof. No live server. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium, expect} from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = process.argv[2]
assert(output, 'Explicit private evidence directory required')
const clock = '2026-10-27T18:00:00Z'
const bundle = await build({stdin: {contents: `
import React from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';
import Suggests from './src/pages/WatchSuggests';import './src/styles/tokens.css';import './src/index.css';
createRoot(document.getElementById('root')).render(<BrowserRouter><Suggests/></BrowserRouter>);
`, resolveDir: app, loader: 'tsx', sourcefile: 'watch-system-suggests-fixture.tsx'}, bundle: true, write: false,
outfile: 'fixture.js', define: {'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false',
  '__ANALYST_UI_VERSION__': '"synthetic-old"', '__BUILD_DATE__': '"2026-10-26"', '__CC_BUNDLE_SOURCE_SHA__': JSON.stringify('a'.repeat(40))},
logLevel: 'silent'})
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script')
const css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
const field = value => ({value, source: 'stored synthetic fixture', observed_at: clock})
const facts = symbol => ({schema: 'CIOCompanyFacts@v1', symbol, status: 'AVAILABLE', assembled_at: clock,
  company: field('Fictional Instruments'), description: field('Builds fictional testing instruments.'),
  sector: field('Synthetic sector'), industry: field('Synthetic industry'), conflicts: [],
  catalyst: {status: 'CURRENT', headline: 'Fictional company scheduled product event', event_at: '2026-11-02T14:00:00Z',
    date: '2026-11-02', source_label: 'Stored house calendar', source: 'synthetic calendar', catalyst_class: 'UPCOMING_EVENT'}})
const baseRow = symbol => ({symbol, company: 'Fictional Instruments', security_guid: `synthetic-${symbol}`, identity_status: 'CONFIRMED',
  lane: 'forming', stage: 'forming', why: 'Ranked research suggestion', summary: 'Synthetic evidence summary',
  company_facts: facts(symbol), conviction: null, conviction_components: [], conviction_missing: [],
  conviction_source: 'cio_truth', conviction_as_of: null, conviction_stale: true, stance: null,
  whats_missing: ['CIO record needed'], conflicts: [], conflict_section: {findings: [], headline: null, gap: null},
  next_trigger: {label: 'Zone not measured', level_ref: null, inside: false, distance_pct: null, observed_by: null},
  next_action: {kind: 'cio_missing', label: 'Ask the CIO for a view', reason: 'CIO record needed'},
  levels_ref: {}, price: null, price_as_of: null, rsi: null, held: false, surfaces: [], evidence_at: clock,
  expires_at: null, mine: false, starred: false, membership: [], position_state: 'never_held', review_state: null,
  suggestion: {status: 'listed', reason: 'Ranked research', universe_rank: 1, top_factor: null}})
const queued = {status: 'queued', label: 'Queued for the CIO', open: true, request_id: 'rr_synthetic',
  queued_at: clock, updated_at: clock, next_run: 'Synthetic scheduled run', last_attempt: null}
fs.mkdirSync(output, {recursive: true})
const browser = await chromium.launch({headless: true})
const results = []
try {
  for (const width of [1440, 412, 390]) {
    const context = await browser.newContext({viewport: {width, height: 915}, hasTouch: width < 821})
    const page = await context.newPage()
    const traffic = {posts: [], external: [], unexpected: [], errors: []}
    let state = null, polls = 0
    const rows = () => [
      {...baseRow('ZZAA'), ...(state?.publication_verified ? {
        conviction: 76, conviction_as_of: '2026-10-27T18:00:20Z', conviction_stale: false, stance: 'WATCH',
        whats_missing: [], next_action: {kind: 'set_alert', label: 'Set alert', reason: 'Watch the recorded trigger'},
      } : {}), review_state: state},
      {...baseRow('ZZBB'), company_facts: {...facts('ZZBB'),
        industry: {...field(null), missing_reason: 'profile_industry_not_recorded'},
        catalyst: {status: 'NONE_ON_FILE', reason: 'No dated issuer event on file'}}},
      {...baseRow('ZZCC'), review_state: {status: 'answered', open: false, publication_verified: false,
        label: 'Previous research published 2026-10-09 · 18 d ago — current CIO linkage unavailable; refresh'}},
    ]
    page.on('pageerror', error => traffic.errors.push(String(error)))
    await page.clock.install({time: new Date(clock)})
    await page.routeWebSocket('**/*', ws => {traffic.external.push(ws.url()); ws.close()})
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      const json = (data, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)})
      if (url.origin !== 'http://watch-suggests-fixture.test') {traffic.external.push(url.href); return route.abort()}
      if (req.isNavigationRequest()) return route.fulfill({contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:12px;min-width:0}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
      const match = url.pathname.match(/^\/api\/v3\/opportunities\/(ZZ[A-Z]+)\/review-request$/)
      if (req.method() === 'POST' && match) {
        traffic.posts.push({path: url.pathname, body: req.postDataJSON()})
        if (match[1] === 'ZZBB') return json({ok: false, error: 'PROCESS_CAP: synthetic daily request limit'}, 429)
        state = {...queued}
        return json({ok: true, request_id: queued.request_id, review_state: state, review: {next_run: queued.next_run}})
      }
      if (req.method() !== 'GET') {traffic.unexpected.push(req.method() + ' ' + url.pathname); return route.abort()}
      if (url.pathname === '/v3/build-meta.json') return json({ui_version: 'synthetic-new', git_sha: 'b'.repeat(40), source_sha: 'b'.repeat(40)})
      if (url.pathname === '/api/v2/watch/alerts/list') return json({ok: true, data: {alerts: []}})
      if (url.pathname === '/api/v3/data-broker/watch-curation' && url.searchParams.get('review_status') === '1') {
        polls++
        if (polls === 2) state = {...queued, status: 'researching', label: 'Researching stored evidence', updated_at: '2026-10-27T18:00:10Z'}
        if (polls >= 3) state = {...queued, open: false, status: 'answered', label: 'Answered — linked CIO record available',
          updated_at: '2026-10-27T18:00:20Z', publication_verified: true, research_id: 'research_synthetic',
          answer_summary: 'Stored evidence reviewed; monitor the fictional product event.'}
        return json({ok: true, schema: 'WatchReviewStatus@v1', rows: {ZZAA: state}})
      }
      if (url.pathname === '/api/v3/data-broker/watch-curation') return json({ok: true, data: {
        ranking: {label: 'Synthetic full universe', as_of: clock}, my_watchlist: {rows: []},
        suggests: {n: 3, eligible: 3, ranked: 3, rows: rows(), skipped: {}, rotation: {available: false, unavailable_reason: 'First synthetic run'},
          universe_note: 'Ranked research universe; fixtures only', pagination: {total: 3, offset: 0, limit: 10, has_more: false}}}})
      traffic.unexpected.push(url.pathname); return route.abort()
    })
    const tap = async loc => {
      await loc.scrollIntoViewIfNeeded(); const box = await loc.boundingBox()
      assert(box && box.width >= 44 && box.height >= 44, '44px action ' + JSON.stringify(box))
      if (width < 821) await loc.tap(); else await loc.click()
    }
    await page.goto('http://watch-suggests-fixture.test/v3/watch?tab=suggests')
    await expect(page.getByTestId('suggest-row')).toHaveCount(3)
    await expect(page.getByTestId('watch-reload-notice')).toBeVisible()
    await expect(page.getByTestId('watch-suggests')).toContainText('Fictional Instruments')
    await expect(page.getByTestId('watch-suggests')).toContainText('18 d ago')
    await expect(page.getByTestId('watch-company-missing')).toContainText('industry: profile industry not recorded')
    await expect(page.getByTestId('watch-suggests')).not.toContainText('cio record missing')
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No sideways page scroll')
    await page.screenshot({path: path.join(output, `suggests-rows-${width}.png`), fullPage: true, animations: 'disabled'})
    await tap(page.locator('[data-symbol="ZZAA"]').getByTestId('watch-step'))
    const record = width < 821 ? page.getByRole('dialog', {name: 'ZZAA · suggestion record'}) : page.getByRole('complementary', {name: 'Record'})
    await expect(record.getByTestId('watch-cio-request')).toContainText('rr_synthetic')
    await expect(record.getByTestId('watch-review-state')).toContainText('Queued')
    if (width < 821) {
      const box = await record.boundingBox(); assert(box && box.y <= 1 && box.height >= 900, 'Full screen phone sheet')
    }
    await page.screenshot({path: path.join(output, `suggests-queued-${width}.png`), animations: 'disabled'})
    await page.clock.fastForward(10_000)
    await expect(record.getByTestId('watch-review-state')).toContainText('Researching')
    await page.clock.fastForward(10_000)
    await expect(record.getByTestId('watch-cio-answer')).toContainText('fictional product event')
    await expect(record).not.toContainText('CIO record needed')
    assert.equal(traffic.posts.length, 1, 'One tap queues once; progress never posts')
    await page.screenshot({path: path.join(output, `suggests-answered-${width}.png`), animations: 'disabled'})
    await tap(record.getByRole('button', {name: width < 821 ? '← Back' : 'Back to list', exact: true}))
    await tap(page.locator('[data-symbol="ZZBB"]').getByTestId('watch-step'))
    const refused = width < 821 ? page.getByRole('dialog', {name: 'ZZBB · suggestion record'}) : page.getByRole('complementary', {name: 'Record'})
    await expect(refused.getByTestId('watch-cio-message')).toContainText('PROCESS_CAP')
    await page.screenshot({path: path.join(output, `suggests-limit-${width}.png`), animations: 'disabled'})
    assert.equal(traffic.posts.length, 2)
    assert.deepEqual(traffic.external, []); assert.deepEqual(traffic.unexpected, []); assert.deepEqual(traffic.errors, [])
    results.push({width, status: 'PASS', polls, posts: traffic.posts.length, screenshots: 4})
    await context.close()
  }
} finally {await browser.close()}
fs.writeFileSync(path.join(output, 'fixture-results.json'), JSON.stringify({synthetic: true, live_traffic: false, results}, null, 2) + '\n')
console.log(JSON.stringify(results))
