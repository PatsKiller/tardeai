// Parity-v2 §7A tests 1–7. Invented values, no server or live endpoint.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { adaptPerformance, performanceRead, selectPerformance, PERFORMANCE_PATH } from '../../src/pages/portfolio/performanceAdapter.ts'
import { createClient, HeavyReaderFromShell } from '../../src/api/client.ts'
import { READERS, specFor } from '../../src/api/readers.ts'

const router = createRequire(import.meta.url)('react-router-dom')
const NOW = Date.parse('2040-06-04T16:00:00Z'), OLD = '2040-06-01T16:00:00Z'
const PERIODS = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y']
const cell = (overrides = {}) => ({ change: 100, change_pct: 1, start_value: 10000, end_value: 10100,
  start_date: '2040-05-01', end_date: '2040-06-01', source: 'synthetic snapshots', quality: 'reliable', flags: [],
  observation_clock: { as_of: OLD, status: 'OK' }, ...overrides })
function body() {
  const account = (label, change) => ({ account_label: label, eligibility: { status: 'eligible', source: 'synthetic membership' },
    periods: Object.fromEntries(PERIODS.map(p => [p, cell({ change, change_pct: change / 100 })])) })
  return { periods: Object.fromEntries(PERIODS.map(p => [p, cell()])),
    accounts: { 'synthetic-account-a': account('Account A', 100), 'synthetic-account-b': account('Account B', -100) },
    today_pnl: { status: 'UNKNOWN', session_date: null, mark_session_date: '2040-06-01', observation_clock: { as_of: null, status: 'UNKNOWN' }, mark_batch_at: OLD, batch_built_at: OLD },
    market_session: { latest_open_session: '2040-06-04', as_of: '2040-06-04T16:00:00Z' },
    clock_provenance: { quote: { as_of: OLD, status: 'STALE' }, valuation: { as_of: OLD, status: 'OK' } },
    ytd_pin: { pin_date: '2040-06-01', end_snapshot: 'synthetic-snapshot-A', created_at: '2040-06-01T09:00:00', source: 'synthetic snapshots', pin_version: 'synthetic-v1' } }
}
const env = (data, extra = {}) => ({ ok: true, status: 200, data, error: null, fetchedAt: new Date(NOW).toISOString(), lastGood: data, lastGoodAt: OLD, lastGoodAgeSeconds: 30, timedOut: false, spec: specFor(PERFORMANCE_PATH), ...extra })
const adapt = (b = body(), key = null) => { const r = adaptPerformance(b, NOW, key); assert.ok(r.props, r.reason); return r.props }
const acct = (p, key = 'synthetic-account-a') => p.accounts.find(a => a.key === key)
const named = (name, fn) => test(`performance-adapter.test.mjs / ${name}`, fn)
const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..'), load = createRequire(import.meta.url)
let modules
function compiled() {
  if (modules) return modules
  const cache = path.join(APP, 'node_modules/.cache/wealth-gate-tests'); fs.mkdirSync(cache, { recursive: true })
  const out = fs.mkdtempSync(path.join(cache, 'performance-adapter-')), decl = path.join(out, 'css-modules.d.ts')
  fs.writeFileSync(decl, "declare module '*.css'\n")
  const args = ['--target', 'ES2020', '--module', 'commonjs', '--moduleResolution', 'node', '--strict', '--skipLibCheck', '--allowImportingTsExtensions', '--rewriteRelativeImportExtensions', '--jsx', 'react-jsx', '--typeRoots', path.join(APP, 'node_modules/@types'), '--types', 'node', '--outDir', out, path.join(APP, 'src/pages/portfolio/PerformanceLive.tsx'), decl]
  const r = spawnSync(process.execPath, [path.join(APP, 'node_modules/typescript/bin/tsc'), ...args], { encoding: 'utf8' })
  assert.equal(r.status, 0, `tsc rc ${r.status}: ${r.stdout}${r.stderr}`)
  fs.writeFileSync(path.join(out, 'package.json'), '{"type":"commonjs"}')
  fs.writeFileSync(path.join(out, 'pages/portfolio/semantic.css'), '')
  load.extensions['.css'] = () => {}
  process.once('exit', () => fs.rmSync(out, { recursive: true, force: true }))
  modules = { page: load(path.join(out, 'pages/portfolio/PerformancePage.js')).PerformancePage,
    live: load(path.join(out, 'pages/portfolio/PerformanceLive.js')).PerformanceLive, select: load(path.join(out, 'pages/portfolio/performanceScope.js')).PerformanceAccountSelect, client: load(path.join(out, 'api/client.js')) }
  return modules
}
const render = p => renderToStaticMarkup(React.createElement(compiled().page, p))
const accounts = html => html.split('<div data-performance-accounts="true">')[1] ?? ''
const household = html => html.split('<div data-performance-accounts="true">')[0]

named('parity 1: seven windows, raw NAV includes flows, actual bounds and calendar YTD pin', () => {
  const b = body(); b.periods['1W'] = cell({ change: 300, change_pct: 3, flags: ['includes_transfers'] })
  const p = adapt({ ok: true, data: b }), html = render(p)
  assert.equal(p.household['1W'].observation.amount.value, 300)
  for (const label of ['Latest session', '1W', '1M', '3M', '6M', 'YTD', '1Y']) assert.ok(html.includes(`<h3>${label}</h3>`))
  assert.match(html, /Raw NAV change — includes deposits\/withdrawals/); assert.doesNotMatch(html, /\b(?:WTD|MTD|QTD)\b/)
  assert.match(html, /Actual start: 2040-05-01 · Actual end: 2040-06-01/)
  assert.equal((household(html).match(/Calendar year to date/g) ?? []).length, 1)
  assert.match(html, /YTD pin date: 2040-06-01; snapshot: synthetic-snapshot-A; source: synthetic snapshots/)
})
named('parity 2: account display-only fields and allocated flow never become raw NAV', () => {
  const b = body(), c = b.accounts['synthetic-account-a'].periods['1W']; delete c.change; delete c.change_pct
  Object.assign(c, { display_change: 900, display_change_pct: 9, estimated_net_flow: 800, adjustment_note: 'Invented deposit 800' })
  const p = adapt(b), m = acct(p).periods['1W']
  assert.equal(m.amount.value, null); assert.equal(m.percent.value, null); assert.match(m.amount.unknownReason, /not served or invalid.*owner/)
  assert.doesNotMatch(accounts(render(p)), /900\.00|800\.00|Invented deposit|estimated_net_flow/)
})
named('parity 2: opposite display/raw signs use only eligible raw change', () => {
  const b = body(); Object.assign(b.accounts['synthetic-account-a'].periods['1W'], { change: -200, change_pct: -2, display_change: 900, display_change_pct: 9 })
  const p = adapt(b); assert.equal(acct(p).periods['1W'].amount.value, -200); assert.equal(acct(p).periods['1W'].percent.value, -2)
  const html = accounts(render(p)); assert.match(html, /-\$200\.00/); assert.doesNotMatch(html, /\+\$900\.00/)
})
for (const marker of [{ adjustment_method: 'household_residual_live_end' }, { provenance_note: 'rewritten opening anchor' }, { linked_start_value: 1000 }, { economic_start_value: 1000 }, { rewrote_extreme_nav: true }]) {
  named(`parity 2: account guard refuses ${Object.keys(marker)[0]}`, () => {
    const b = body(); Object.assign(b.accounts['synthetic-account-a'].periods['1W'], marker)
    const m = acct(adapt(b)).periods['1W']; assert.equal(m.amount.value, null); assert.equal(m.percent.value, null); assert.match(m.amount.unknownReason, /residual|anchor/)
  })
}
named('parity 3: external household flow qualifications stay beside raw NAV, not in account returns', () => {
  const b = body(); Object.assign(b.periods['1W'], { nav_change: 500, nav_change_pct: 5, display_change: 100, display_change_pct: 1,
    display_label: 'synthetic residual with external flow ambiguity', nav_is_not_market_only: true, quality: 'includes_transfers', flags: ['external_flow_not_reconciled'] })
  const p = adapt(b), h = p.household['1W'], html = render(p)
  assert.equal(h.observation.amount.value, 500); assert.equal(h.estimate.amount.value, 100)
  assert.match(h.estimate.methodNote, /synthetic residual with external flow ambiguity/); assert.match(h.estimate.methodNote, /nav_is_not_market_only: true; quality: includes_transfers/)
  assert.match(household(html), /Approximate household estimate/); assert.match(household(html), /external flows are not reconciled/)
  assert.equal(acct(p).periods['1W'].percent.value, 1); assert.equal(acct(p, 'synthetic-account-b').periods['1W'].percent.value, -1)
  assert.equal(h.estimate.startAt, '2040-05-01'); assert.doesNotMatch(accounts(html), /household-estimate|external_flow_not_reconciled/)
})
named('parity 3: synthesized display sum is not independently served raw household NAV', () => {
  const b = body(); b.periods['1W'] = cell({ source: 'sum_accounts', display_change: 100, display_change_pct: 1 })
  const h = adapt(b).household['1W']; assert.equal(h.observation.amount.value, null); assert.match(h.observation.amount.unknownReason, /raw household NAV not served/); assert.equal(h.estimate.amount.value, 100)
})
named('parity 4: missing account period and unknown eligibility never inherit values', () => {
  const b = body(); delete b.accounts['synthetic-account-a'].periods['1M']; delete b.accounts['synthetic-account-b'].eligibility
  const p = adapt(b); assert.equal(acct(p).periods['1M'].amount.value, null); assert.equal(acct(p).periods['1W'].amount.value, 100)
  assert.equal(acct(p, 'synthetic-account-b').periods['1W'].amount.value, null); assert.match(acct(p, 'synthetic-account-b').scopeNote, /eligibility unknown/)
  const missing = adaptPerformance(b, NOW, 'synthetic-no-match'); assert.equal(missing.props, null); assert.match(missing.reason, /no matching account rows.*fallback withheld/)
})
named('parity 4: filtered account cannot inherit household totals/proxy alpha/NAV drawdown', () => {
  const b = body(); b.benchmarks = { alpha: { change_pct: 900 } }; b.max_drawdown_pct = -99
  const p = adapt(b, 'synthetic-account-a'); assert.equal(p.accounts.length, 1); assert.deepEqual(p.household, {})
  const html = render(p); assert.doesNotMatch(html, /900\.00%|-99\.00%/); assert.match(household(html), /Unknown — not served/)
})
named('parity 5: missing/null/invalid amount and percent stay independent, numeric zero survives', () => {
  for (const invalid of [null, undefined, NaN, Infinity, '100', false]) {
    const b = body(); b.periods['1W'] = cell({ change: invalid, change_pct: 0 }); let m = adapt(b).household['1W'].observation
    assert.equal(m.amount.value, null); assert.equal(m.percent.value, 0)
    b.periods['1W'] = cell({ change: 0, change_pct: invalid }); m = adapt(b).household['1W'].observation
    assert.equal(m.amount.value, 0); assert.equal(m.percent.value, null)
  }
  const b = body(); b.periods['1W'] = cell({ change: 0, change_pct: 0 }); assert.match(household(render(adapt(b))), /class="money-unknown">0\.00%/)
})
named('parity 5: household 1D retains snapshot_replaced and is a price-move estimate', () => {
  const b = body(); b.periods['1D'] = cell({ snapshot_replaced: true }); const p = adapt(b), m = p.household['Latest session'].observation
  assert.equal(m.method, 'holdings-price-move'); assert.match(m.note, /Snapshot replaced: true/); assert.match(household(render(p)), /Estimated price movement of current holdings/)
})
named('parity 6: old/weekend marks and current reference session cannot attribute latest session', () => {
  const b = body(), m = adapt(b).household['Latest session'].observation; assert.equal(m.attributedSession, null)
  assert.match(m.note, /Marks observed calendar date .*2040-06-01.*reference session .*2040-06-04/)
  const marks = m.clocks.find(c => c.label.startsWith('Holdings marks')); assert.equal(marks.asOf, '2040-06-01T16:00:00.000Z'); assert.equal(marks.ageSeconds, 259200)
  delete b.today_pnl; delete b.market_session; assert.equal(adapt(b).household['Latest session'].observation.attributedSession, null); assert.match(render(adapt(b)), /Attributed session unknown/)
})
named('parity 6: naive pin creation has zone unknown; zoned offset normalizes explicitly', () => {
  const m = adapt().household.YTD.observation, c = m.clocks.find(c => c.label.startsWith('YTD pin'))
  assert.equal(c.asOf, null); assert.equal(c.ageSeconds, null); assert.match(m.note, /created: 2040-06-01T09:00:00 \(zone unknown; not a UTC observation\)/); assert.doesNotMatch(m.note, /09:00:00Z/)
  const b = body(); b.periods['1W'].observation_clock.as_of = '2040-06-01T12:00:00-04:00'; assert.equal(adapt(b).household['1W'].observation.clocks[0].asOf, '2040-06-01T16:00:00.000Z')
})
named('parity 7: HTTP failure preserves original source age/status, distinct from cache receipt age', () => {
  const b = body(), original = structuredClone(b), r = performanceRead(env(null, { ok: false, status: 503, error: 'HTTP 503', lastGood: b }), NOW)
  assert.equal(r.state, 'last-available'); assert.match(r.notice, /Last available response.*cache receipt age: 30 seconds/)
  const m = r.props.household['1W'].observation; assert.equal(m.clocks[0].ageSeconds, 259200); assert.equal(m.clocks[0].freshness, 'unknown'); assert.match(m.clocks[0].label, /source status: OK/); assert.ok(m.qualifiers.includes('stale')); assert.deepEqual(b, original)
  const older = performanceRead(env(null, { ok: false, lastGood: b }), NOW + 3600000); assert.equal(older.props.household['1W'].observation.clocks[0].ageSeconds, 262800)
})
named('parity 7: missing body, nested unknown and unavailable cells never use fixtures', () => {
  for (const b of [null, [], 'invalid', { ok: false }, { ok: true, data: null }, { ok: true, data: { status: 'UNKNOWN', accounts: {} } }, { accounts: [] }]) {
    const r = adaptPerformance(b, NOW); assert.equal(r.props, null); assert.match(r.reason, /Unknown.*owner/)
  }
  const b = body(); b.periods['1W'].status = 'UNKNOWN'; assert.equal(adapt(b).household['1W'].observation.amount.value, null)
  assert.equal(performanceRead(null, NOW).state, 'loading'); assert.equal(performanceRead(env(null, { ok: false, lastGood: null, error: 'offline' }), NOW).state, 'unavailable')
})
named('parity 7: one clock-none page-only reader, synthetic client never makes a shell fetch', async () => {
  const rows = READERS.filter(s => s.path === PERFORMANCE_PATH); assert.equal(rows.length, 1); assert.equal(rows[0].heavy, true); assert.equal(rows[0].clock, 'none'); assert.equal(rows[0].asOfAt, undefined)
  let calls = 0
  const c = createClient({ fetchImpl: async () => { calls++; return new Response(JSON.stringify({ ok: true, data: body() }), { headers: { 'content-type': 'application/json' } }) } })
  assert.throws(() => c.get(PERFORMANCE_PATH, { from: 'shell' }), HeavyReaderFromShell); assert.equal(calls, 0)
  const response = await c.get(PERFORMANCE_PATH, { from: 'page' }); assert.equal(calls, 1); assert.equal(performanceRead(response, NOW).state, 'served')
})
named('adapter never throws on malformed shapes and never mutates source data', () => {
  for (const b of [0, true, {}, { accounts: { 'fake-key': null } }, { accounts: {}, periods: 3 }, { accounts: {}, periods: { YTD: [] } }]) assert.doesNotThrow(() => adaptPerformance(b, NOW))
  const b = body(), original = structuredClone(b); render(adapt(b)); assert.deepEqual(b, original)
  assert.equal(adaptPerformance(new Proxy({}, { get() { throw Error('not JSON') } }), NOW).props, null)
})
named('raw account keys never render; coverage comes only from an explicit served count contract', () => {
  const b = body(); delete b.accounts['synthetic-account-a'].account_label; b.periods['1W'].coverage = { included: 2, total: 3 }
  const p = adapt(b), html = render(p); assert.match(html, /Account 1 · label not served/); assert.doesNotMatch(html, /synthetic-account-a|synthetic-account-b/)
  assert.match(household(html), /Coverage: 2 of 3 accounts/); assert.deepEqual(p.household['1M'].observation.coverage, { included: null, total: null })
})

// Drive the actual compiled wrapper with stubbed React hooks/client. No renderer server or network.
async function liveHarness(result, reject = false, overview = env({ ok: true, data: {} })) {
  const { live, client } = compiled(), saved = { useState: React.useState, useMemo: React.useMemo, useEffect: React.useEffect, useContext: React.useContext, useSearchParams: router.useSearchParams, getJson: client.getJson, now: Date.now }
  const state = [], effects = [], calls = [], signals = []; let cursor = 0
  const publication = { accounts: null, reason: null, publish(accounts, reason) { this.accounts = accounts; this.reason = reason } }
  publication.publish = publication.publish.bind(publication)
  React.useState = initial => { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial; return [state[i], v => { state[i] = v }] }
  React.useContext = () => publication; router.useSearchParams = () => [new URLSearchParams(), () => {}]
  React.useMemo = fn => fn(); React.useEffect = fn => { effects.push(fn) }; Date.now = () => NOW
  client.getJson = (url, s) => {
    calls.push(url); signals.push(s)
    if (url === PERFORMANCE_PATH) return reject ? Promise.reject(new Error('synthetic offline')) : Promise.resolve(result)
    assert.equal(url, '/api/v2/overview')
    return overview instanceof Error ? Promise.reject(overview) : Promise.resolve(overview)
  }
  try {
    cursor = 0; const initial = renderToStaticMarkup(live()), cleanup = effects[0]()
    await new Promise(resolve => setImmediate(resolve))
    cursor = 0; const final = renderToStaticMarkup(live()); effects[effects.length - 2]()
    const picker = renderToStaticMarkup(React.createElement(compiled().select))
    assert.deepEqual(calls.sort(), ['/api/v2/overview', PERFORMANCE_PATH].sort()); cleanup(); assert.ok(signals.every(s => s.aborted))
    return { initial, final, picker }
  } finally { Object.assign(React, { useState: saved.useState, useMemo: saved.useMemo, useEffect: saved.useEffect, useContext: saved.useContext }); router.useSearchParams = saved.useSearchParams; client.getJson = saved.getJson; Date.now = saved.now }
}
named('live wrapper reads once, renders adapted data, and aborts on unmount', async () => {
  const { initial, final } = await liveHarness(env({ ok: true, data: body() })); assert.match(initial, /Reading Performance source/); assert.match(final, /Account A/); assert.match(final, /Source-supplied|eligible/)
})
named('live wrapper HTTP failure displays cached values and their old source ages', async () => {
  const { final } = await liveHarness(env(null, { ok: false, status: 503, error: 'HTTP 503', lastGood: body() })); assert.match(final, /Last available response/); assert.match(final, /3\.0 d old/); assert.match(final, /HTTP 503/)
})
named('live wrapper rejected read renders failure and no sample values', async () => {
  const { final } = await liveHarness(null, true); assert.match(final, /synthetic offline/); assert.doesNotMatch(final, /Account A|\$100/)
})

named('legacy shape has no account eligibility, display labels, coverage or unified period clock', () => {
  const b = body()
  for (const a of Object.values(b.accounts)) { delete a.eligibility; delete a.account_label }
  for (const c of Object.values(b.periods)) delete c.observation_clock
  const p = adapt(b)
  for (const a of p.accounts) for (const m of Object.values(a.periods)) { assert.equal(m.amount.value, null); assert.match(m.amount.unknownReason, /eligibility unknown/) }
  assert.equal(p.household['1W'].observation.amount.value, 100)
  assert.equal(p.household['1W'].observation.clocks[0].ageSeconds, null)
  assert.deepEqual(p.household['1W'].observation.coverage, { included: null, total: null })
  assert.match(render(p), /Account 1 · label not served/)
})
named('clock OK alone is not freshness; invalid calendar dates never become source instants', () => {
  const b = body()
  let c = adapt(b).household['1W'].observation.clocks[0]
  assert.equal(c.freshness, 'unknown'); assert.match(c.label, /source status: OK/)
  b.periods['1W'].observation_clock.as_of = '2040-02-31T16:00:00Z'
  c = adapt(b).household['1W'].observation.clocks[0]
  assert.equal(c.asOf, null); assert.equal(c.ageSeconds, null)
})

named('parity 7: nested UNKNOWN with evidence withholds values but preserves source clocks and status', () => {
  const b = body(); b.status = 'UNKNOWN'
  const r = performanceRead(env({ ok: true, data: b }), NOW)
  assert.equal(r.state, 'unavailable'); assert.ok(r.props); assert.match(r.notice, /status UNKNOWN.*values withheld.*clocks retained/)
  const m = r.props.household['1W'].observation
  assert.equal(m.amount.value, null); assert.equal(m.percent.value, null)
  assert.equal(m.clocks[0].ageSeconds, 259200); assert.match(m.clocks[0].label, /source status: OK/)
  assert.match(render(r.props), /All performance measures are unknown/)
})

named('C-PERF-B exposes only actual served period keys, never invented windows', () => {
  const b = body(); b.periods = { '1W': cell(), 'YTD': cell() }
  for (const a of Object.values(b.accounts)) a.periods = { '1W': cell() }
  assert.deepEqual(adapt(b).availablePeriods, ['1W', 'YTD'])
})
named('C-PERF-B canonical label join changes no eligibility or monetary evidence', () => {
  const b = body(); delete b.accounts['synthetic-account-a'].eligibility; delete b.accounts['synthetic-account-a'].account_label
  const p = adaptPerformance(b, NOW, null, new Map([['synthetic-account-a', 'Canonical account A']])).props
  assert.equal(acct(p).label, 'Canonical account A')
  assert.equal(acct(p).periods['1W'].amount.value, null)
  assert.match(acct(p).periods['1W'].amount.unknownReason, /eligibility unknown/)
})

named('C-PERF-B scoped period choices and measures share source membership', () => {
  const b = body(); b.accounts['synthetic-account-a'].periods = { '1W': cell() }
  const p = adapt(b), original = structuredClone(p)
  const selected = selectPerformance(p, 'synthetic-account-a', 'YTD')
  assert.equal(selected.props.accounts.length, 1)
  assert.equal(selected.props.accounts[0].key, 'synthetic-account-a')
  assert.deepEqual(selected.props.household, {})
  assert.equal(selected.props.showHousehold, false)
  assert.deepEqual(selected.props.availablePeriods, ['1W'])
  assert.equal(selected.props.selectedPeriod, '1W')
  assert.match(selected.notice, /not served for this scope/)
  assert.deepEqual(p, original)
  const html = render(selected.props)
  assert.doesNotMatch(html, /<h2>Household<\/h2>|<h2>Account B<\/h2>|<h3>YTD<\/h3>/)
})
named('C-PERF-B unknown account URL never silently falls back to household', () => {
  const selected = selectPerformance(adapt(), 'synthetic-missing', '1W')
  assert.deepEqual(selected.props.accounts, [])
  assert.deepEqual(selected.props.household, {})
  assert.deepEqual(selected.props.availablePeriods, [])
  assert.equal(selected.props.selectedPeriod, null)
  assert.match(selected.notice, /account is not served.*fallback withheld/)
  assert.doesNotMatch(render(selected.props), /\+\$100\.00|<h2>Household<\/h2>/)
})
named('C-PERF-B literal 1D URL selects Latest session; calendar aliases do not relabel rolling windows', () => {
  assert.equal(selectPerformance(adapt(), null, '1D').props.selectedPeriod, 'Latest session')
  for (const period of ['1W', '1M', '3M']) assert.equal(selectPerformance(adapt(), null, period).props.selectedPeriod, period)
  for (const period of ['WTD', 'MTD', 'QTD', 'broken']) {
    const selected = selectPerformance(adapt(), null, period)
    assert.equal(selected.props.selectedPeriod, 'YTD')
    assert.match(selected.notice, /Requested period is not served/)
  }
})
named('C-PERF-B no served period keys produces an explicit unavailable selector', () => {
  const b = body(); b.periods = {}; for (const a of Object.values(b.accounts)) a.periods = {}
  const selected = selectPerformance(adapt(b), null, null)
  assert.equal(selected.props.selectedPeriod, null)
  assert.match(render(selected.props), /No periods served/)
  assert.match(selected.notice, /No periods served/)
})

named('C-PERF-B selected account status does not count a suppressed household as a missing measure', () => {
  const b = body(); b.accounts['synthetic-account-a'].periods['1W'] = cell({coverage:{included:1,total:1},observation_clock:{as_of:OLD,freshness:'fresh'}})
  const selected = selectPerformance(adapt(b), 'synthetic-account-a', '1W')
  assert.match(render(selected.props), /data-performance-state="available"/)
})

const fiveUnlabeled = () => {
  const b = body()
  b.accounts = Object.fromEntries(Array.from({ length: 5 }, (_, i) => [`synthetic-key-${i}`, { periods: { '1W': cell() } }]))
  return b
}
const optionTexts = html => Array.from(html.matchAll(/<option[^>]*>(.*?)<\/option>/g), m => m[1]).slice(1)
named('C-PERF-B labels: five missing labels have distinct safe text and stable filtered identity', async () => {
  const b = fiveUnlabeled(), { final, picker } = await liveHarness(env({ ok: true, data: b }))
  assert.deepEqual(optionTexts(picker), Array.from({ length: 5 }, (_, i) => `Account ${i + 1} · label not served`))
  assert.doesNotMatch(optionTexts(picker).join(' '), /synthetic-key/)
  assert.doesNotMatch(final, /synthetic-key/)
  assert.match(render(adaptPerformance(b, NOW, 'synthetic-key-3').props), /Account 4 · label not served/)
})
named('C-PERF-B labels: actual wrapper joins both canonical overview label shapes without money or clock inference', async () => {
  const b = fiveUnlabeled()
  const labels = { account_labels: Object.fromEntries([0, 1, 2].map(i => [`synthetic-key-${i}`, `Canonical synthetic ${i + 1}`])),
    portfolio_aggregate: { accounts: [3, 4].map(i => ({ account_id: `synthetic-key-${i}`, account_label: `Canonical synthetic ${i + 1}` })) },
    clock_provenance: { quote: { as_of: new Date(NOW).toISOString(), freshness: 'fresh' } } }
  const { final, picker } = await liveHarness(env({ ok: true, data: b }), false, env({ ok: true, data: labels }))
  assert.deepEqual(optionTexts(picker), Array.from({ length: 5 }, (_, i) => `Canonical synthetic ${i + 1}`))
  assert.doesNotMatch(final, /label not served/)
  assert.match(final, /eligibility unknown/); assert.match(final, /3\.0 d old/)
  assert.doesNotMatch(accounts(final), /\+\$100\.00|\+1\.00%/)
})
named('C-PERF-B labels: label failures preserve Performance values, old clocks and safe placeholders', async () => {
  for (const overview of [new Error('synthetic label offline'), env(null, { ok: false, status: 503 }), env({ ok: false, error: 'synthetic nested failure', data: { account_labels: { 'synthetic-key-0': 'Rejected label' } } })]) {
    const { final, picker } = await liveHarness(env({ ok: true, data: fiveUnlabeled() }), false, overview)
    assert.equal(new Set(optionTexts(picker)).size, 5)
    assert.match(final, /Account labels unavailable/); assert.match(final, /3\.0 d old/)
    assert.match(household(final), /\+\$100\.00/)
    assert.doesNotMatch(final, /Rejected label/)
  }
})
