/** Batch 31 (operator 2026-10-25): Watch "Ask the CIO" on the actual My Watchlist and Prospects pages at phone widths.
 *  A missing CIO view is not a conflict, every CIO step is actionable from the row and the record, and the request's
 *  recorded state (blocked by acquisition, queued) is visible. Synthetic rows; every request intercepted; no live POST.
 *
 *    node e2e/watch-cio-review.fixture.mjs <evidence-dir>
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {build} from 'esbuild'
import {chromium, expect} from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'), output = process.argv[2]
assert(output, 'Explicit evidence directory required')
const clock = '2026-10-25T14:00:00Z'
const bundle = await build({stdin: {contents: `
import React from'react';import{createRoot}from'react-dom/client';import{BrowserRouter,Routes,Route}from'react-router-dom';
import Mine from'./src/pages/WatchMyList';import Prospects from'./src/pages/WatchProspects';
import'./src/styles/tokens.css';import'./src/index.css';
createRoot(document.getElementById('root')).render(<BrowserRouter basename="/v3"><Routes><Route path="mine" element={<Mine/>}/><Route path="prospects" element={<Prospects/>}/></Routes></BrowserRouter>);
`, resolveDir: app, loader: 'tsx', sourcefile: 'watch-cio-review-fixture.tsx'}, bundle: true, write: false, outfile: 'fixture.js',
  define: {'process.env.NODE_ENV': '"production"', 'import.meta.env.DEV': 'false'}, logLevel: 'silent'})
const js = bundle.outputFiles.find(f => f.path.endsWith('.js')).text.replace(/<\/script/gi, '<\\/script'), css = bundle.outputFiles.find(f => f.path.endsWith('.css'))?.text || ''
const GAP = 'CIO stance or conviction unavailable for this security GUID'
const BLOCKED = {schema: 'ReviewRequestState@v1', symbol: 'FATN', status: 'blocked', open: true,
  label: 'Blocked: waiting for evidence — no contradicting evidence on file yet (5 new items awaiting curation)',
  queued_at: '2026-10-24T04:54:05+00:00', expires_at: '2026-10-31T04:54:05+00:00', attempts_since_request: 5,
  last_attempt: {status: 'BLOCKED', at: '2026-10-25T08:25:03+00:00', block_reason: 'BLOCKED_PENDING_ACQUISITION_AND_CURATION'}}
const QUEUED = {schema: 'ReviewRequestState@v1', symbol: 'QUE', status: 'queued', open: true, label: 'Queued for the CIO',
  queued_at: clock, expires_at: '2026-11-01T14:00:00+00:00', attempts_since_request: 0, last_attempt: null}
fs.mkdirSync(output, {recursive: true})
const browser = await chromium.launch({headless: true}), cases = []
try {
  for (const width of [412, 390]) for (const surface of ['mine', 'prospects']) {
    const height = width === 412 ? 915 : 844
    const context = await browser.newContext({viewport: {width, height}, hasTouch: true}), page = await context.newPage()
    const traffic = {reads: [], posts: [], external: [], unexpected: [], mutations: [], errors: []}
    let queState = null
    const row = (symbol, extra) => ({symbol, company: 'Fixture company', security_guid: 'fixture-' + symbol, identity_status: 'CONFIRMED',
      lane: 'forming', stage: 'forming', why: 'Recorded fixture evidence', summary: 'Fixture record summary', conviction: null,
      conviction_components: [], conviction_missing: [], conviction_source: 'cio_truth', conviction_as_of: null, conviction_stale: true,
      stance: null, whats_missing: [GAP], conflicts: [], conflict_section: {findings: [], headline: null, gap: null},
      next_trigger: {label: 'Watch recorded levels', level_ref: null, inside: false, distance_pct: null, observed_by: 'Fixture'},
      next_action: {kind: 'cio_missing', label: 'Ask the CIO for a view', reason: GAP, gap: {reason: GAP}},
      price: 10, price_as_of: clock, rsi: null, held: false, position_state: 'never_held', surfaces: [], evidence_at: clock, expires_at: null,
      stale: false, mine: true, starred: true, membership: [], review_state: null, ...extra})
    const rows = () => [
      row('FATN', {review_state: BLOCKED}),
      row('QUE', {review_state: queState}),
      row('NAVN', {stance: 'WATCH', conviction: 60, whats_missing: [],
        conflicts: [{kind: 'trade_ai_block', summary: 'Trade AI deterministic fail', a: {value: 'FAIL', source: 'trade_ai', at: clock}, b: {value: 'RE_ENTER', source: 'cio', at: clock}}],
        conflict_section: {findings: [], headline: null, gap: {reason: 'conflict ledger not yet produced'}},
        next_action: {kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'Two inputs disagree.'}}),
      row('CLEAN', {stance: 'WATCH', conviction: 70, whats_missing: [], next_action: {kind: 'none', label: '—', reason: 'Nothing to act on.'}}),
    ]
    page.on('pageerror', e => traffic.errors.push(String(e)))
    await page.clock.install({time: new Date(clock)})
    await page.routeWebSocket('**/*', ws => { traffic.external.push(ws.url()); ws.close() })
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      if (url.origin !== 'http://watch-cio-fixture.test') { traffic.external.push(url.href); return route.abort() }
      const json = (data, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)})
      const m = url.pathname.match(/^\/api\/v3\/opportunities\/([A-Z]+)\/review-request$/)
      if (req.method() === 'POST' && m) {
        traffic.posts.push({path: url.pathname, body: req.postDataJSON()})
        if (m[1] === 'FATN') return json({ok: true, already_open: true, symbol: 'FATN', review: {open: true}, review_state: BLOCKED})
        queState = QUEUED
        return json({ok: true, already_open: false, symbol: m[1], request_id: 'rr_fixture', review: {open: true}, review_state: {...QUEUED, symbol: m[1]}})
      }
      if (req.method() !== 'GET') { traffic.mutations.push(req.method() + ' ' + url.pathname); return route.abort() }
      if (req.isNavigationRequest()) return route.fulfill({contentType: 'text/html', body: `<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}body{margin:0;background:var(--bg-0);color:var(--text-0)}#root{padding:16px;min-width:0}</style></head><body><div id="root"></div><script>${js}</script></body></html>`})
      traffic.reads.push(url.pathname + url.search)
      const items = rows()
      if (url.pathname === '/api/v3/data-broker/watch-curation')
        return json({ok: true, data: {my_watchlist: {rows: items, count: items.length, unfiltered_count: items.length, starred: items.length, kind_counts: {all: items.length}, sources: {}}}})
      if (url.pathname === '/api/v3/data-broker/watch-prospects')
        return json({ok: true, data: {schema: 'WatchProspects@v1', source: 'fixture', interim: false, generated_at: clock, source_label: 'Fixture record', sources: {},
          counts: {prospects: items.length, conflicts: 1}, curation: {one_membership: true, caps: {}, sort_order: 'Fixture order', expiry: 'Fixture'},
          lanes: ['actionable', 'forming', 'reentry', 'manage', 'expired'].map(id => ({id, label: id === 'forming' ? 'Forming' : id, hint: 'Fixture lane',
            count: id === 'forming' ? items.length : 0, cap: 25, items: id === 'forming' ? items : [], overflow: []}))}})
      if (url.pathname === '/api/v2/watch/alerts/list') return json({ok: true, data: {alerts: []}})
      traffic.unexpected.push(url.pathname); return route.abort()
    })
    const tap = async loc => { await loc.scrollIntoViewIfNeeded(); const b = await loc.boundingBox(); assert(b && b.width >= 44 && b.height >= 44, '44px tap target ' + JSON.stringify(b)); await loc.tap() }
    const inView = async loc => { await expect(loc).toBeVisible(); const b = await loc.boundingBox(); assert(b && b.x >= -1 && b.x + b.width <= width + 1, 'Horizontal viewport ' + JSON.stringify(b)) }
    const noHorizontal = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal page scroll')
    const sheetName = s => surface === 'mine' ? `${s} · watch record` : `${s} · prospect record`
    await page.goto(`http://watch-cio-fixture.test/v3/${surface}?source=fixture${surface === 'prospects' ? '&lane=forming' : ''}`)
    await expect(page.getByTestId('watch-row')).toHaveCount(4)
    const card = s => page.getByTestId('watch-row').filter({has: page.locator(`[title="Open the ${s} record"]`)})
    // A missing CIO view is never presented as a conflict; the row step is actionable everywhere the CIO is needed.
    await expect(page.locator('body')).not.toContainText('Resolve conflict')
    for (const s of ['FATN', 'QUE', 'NAVN']) await expect(card(s).getByTestId('watch-step')).toHaveText('Ask the CIO to review')
    await expect(card('CLEAN').getByRole('button', {name: 'No action', exact: true})).toBeDisabled()
    await expect(card('FATN').getByTestId('watch-row-review-state')).toContainText('Blocked: waiting for evidence — no contradicting evidence on file yet')
    await expect(card('QUE').getByTestId('watch-row-review-state')).toHaveCount(0)
    await noHorizontal()
    await page.screenshot({path: path.join(output, `watch-cio-${surface}-rows-${width}.png`), animations: 'disabled'})

    // FATN: already asked → the row opens the full-screen record with Back and the blocked state; no duplicate POST.
    await tap(card('FATN').getByTestId('watch-step'))
    let dialog = page.getByRole('dialog', {name: sheetName('FATN')})
    await inView(dialog); await inView(dialog.getByRole('button', {name: '← Back'}))
    const state = dialog.getByTestId('watch-review-state')
    await state.scrollIntoViewIfNeeded(); await inView(state)
    await expect(state).toContainText('Blocked: waiting for evidence'); await expect(state).toHaveAttribute('data-status', 'blocked')
    await expect(dialog.getByTestId('watch-cio-review')).toContainText('BLOCKED_PENDING_ACQUISITION_AND_CURATION · 5 runs since you asked')
    assert.equal(traffic.posts.length, 0, 'An open request is shown, not re-posted')
    const ask = dialog.getByTestId('watch-ask-cio')
    await expect(ask).toHaveCount(1); await expect(ask).toHaveText('Ask the CIO to review')
    await page.screenshot({path: path.join(output, `watch-cio-${surface}-blocked-sheet-${width}.png`), animations: 'disabled'})
    await tap(ask)
    await expect(dialog.getByTestId('watch-cio-message')).toContainText('Already asked — Blocked: waiting for evidence')
    assert.equal(traffic.posts.length, 1); assert.match(traffic.posts[0].body.note, /no CIO view/)
    await tap(dialog.getByRole('button', {name: '← Back'})); await expect(page.getByRole('dialog')).toHaveCount(0)

    // QUE: never asked → one tap on the row asks and the record shows "Queued".
    await tap(card('QUE').getByTestId('watch-step'))
    dialog = page.getByRole('dialog', {name: sheetName('QUE')})
    await inView(dialog); await inView(dialog.getByRole('button', {name: '← Back'}))
    await expect(dialog.getByTestId('watch-cio-message')).toHaveText('CIO review queued.')
    await expect(dialog.getByTestId('watch-review-state')).toContainText('Queued for the CIO')
    assert.equal(traffic.posts.length, 2); assert.equal(traffic.posts[1].path, '/api/v3/opportunities/QUE/review-request')
    await page.screenshot({path: path.join(output, `watch-cio-${surface}-queued-sheet-${width}.png`), animations: 'disabled'})
    await tap(dialog.getByRole('button', {name: '← Back'})); await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(card('QUE').getByTestId('watch-row-review-state')).toContainText('Queued for the CIO')

    // NAVN: a Watch flag with no engine section → flags and exactly one actionable ask button in the record.
    await tap(card('NAVN').getByTestId('watch-step'))
    dialog = page.getByRole('dialog', {name: sheetName('NAVN')})
    await inView(dialog)
    await expect(dialog.getByTestId('watch-detail-conflicts')).toContainText('Trade AI deterministic fail')
    await expect(dialog.getByTestId('watch-ask-cio')).toHaveCount(1)
    await expect(dialog.getByTestId('watch-detail-conflicts').getByTestId('watch-cio-message')).toHaveText('CIO review queued.')
    assert.equal(traffic.posts.length, 3); assert.match(traffic.posts[2].body.note, /Trade AI deterministic fail/)
    await noHorizontal()
    await page.screenshot({path: path.join(output, `watch-cio-${surface}-flag-sheet-${width}.png`), animations: 'disabled'})
    await tap(dialog.getByRole('button', {name: '← Back'}))
    assert.deepEqual({external: traffic.external, unexpected: traffic.unexpected, mutations: traffic.mutations, errors: traffic.errors},
      {external: [], unexpected: [], mutations: [], errors: []})
    cases.push({surface, width, height, no_false_conflict: true, row_ask_actionable: true, full_screen_sheet_back: true,
      blocked_state_visible: true, open_request_not_reposted: true, queued_state_visible: true, legacy_flags_single_button: true,
      posts: traffic.posts.length})
    await context.close()
  }
} finally { await browser.close() }
fs.writeFileSync(path.join(output, 'watch-cio-review-receipts.json'), JSON.stringify({scope: 'Actual Watch pages with synthetic rows; all traffic intercepted; no live POST', cases}, null, 2) + '\n')
console.log('Watch Ask the CIO at 412/390 on My Watchlist and Prospects: no false conflict, row ask → full-screen record with Back and request state, blocked/queued visible')
