// LQ-20261107-2993a: Watch v002 Overview rendering. A chip that cannot prove freshness never renders green; the
// classic link stays; every gate shows state + age + limit + owner.
// Synthetic fixtures only (public repo).
import assert from 'node:assert/strict'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (existsSync(target) && statSync(target).isDirectory()) target = ['index.ts', 'index.tsx'].map(s => join(target, s)).find(existsSync)
    else if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const model = await import(compile(join(app, 'src/lib/watchV002.ts')))
const page = await import(compile(join(app, 'src/pages/WatchV002.tsx')))
const { buildWatchStatus } = model
const { WatchV002View, WatchWhySheet, classicTarget, default: WatchV002 } = page

const NOW = Date.parse('2031-03-07T15:00:00Z')
const iso = s => new Date(NOW - s * 1000).toISOString()
const inp = (id, o = {}) => ({ id, label: id, required: true, state: 'OK', source_id: `src_${id}`, owner: `own_${id}`, as_of: iso(60), threshold_s: 1800, ...o })
const IDS = ['my_list', 'prospects', 'alerts', 'regime']
const body = (inputs = IDS.map(i => inp(i)), o = {}) => ({ schema: 'WatchStatus@v1', verdict: 'OK', computed_at: iso(10), session: 'RTH', required_inputs: IDS, inputs, ...o })
const ok = d => ({ state: 'OK', data: d, error: null, at: iso(10), source: '/api/v2/watch/status' })
const noop = () => {}
const LV = { recorded: false, status: 'NOT_RECORDED', startMs: NOW - 24 * 3600_000, label: 'last 24 h — your last visit is not recorded', seenAt: null }
const ov = (o = {}) => ({ actions: [], since: [], lastVisit: LV, unread: [], loading: false, statusState: 'OK', statusAt: iso(10), readFrom: 'computed_on_request', session: 'rth', ...o })
const html = (m, o = {}) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WatchV002View, { m, checkedLabel: 'checked', ov: ov(o), onOpenWhy: noop, onOpenDiag: noop, onRecheck: noop })))
/** The Action/Triggers card's meta span (the one next to its heading). */
const metaOf = h => (h.match(/data-testid="ov-actions"[\s\S]*?<span class="v010-meta">([^<]*)<\/span>/) || [null, ''])[1]
const chip = h => (h.match(/data-testid="watch-data-chip"[^>]*>/) || [''])[0]

// 1. all fresh = OK, four gates, classic link present
{
  const h = html(buildWatchStatus(ok(body()), NOW))
  assert.match(chip(h), /data-state="OK"/)
  for (const id of IDS) assert.ok(h.includes(`data-testid="watch-gate-${id}"`), `gate ${id}`)
  assert.ok(h.includes('data-testid="watch-classic-link"') && h.includes('href="/watch-classic"'), 'classic link')
  assert.match(h, /own_my_list/); assert.match(h, /src_alerts/); assert.match(h, /limit 30 m/)
}
// 2. unread / timed out / loading are never OK
for (const [read, st] of [[undefined, 'LOADING'], [{ state: 'TIMED OUT', data: null, error: 'timed out', at: null, source: 'x' }, 'TIMED OUT'],
  [{ state: 'UNKNOWN', data: null, error: 'HTTP 503', at: null, source: 'x' }, 'UNKNOWN']]) {
  const h = html(buildWatchStatus(read, NOW))
  assert.ok(chip(h).includes(`data-state="${st}"`), st)
  assert.ok(!chip(h).includes('data-state="OK"') && !/v010-pill ok/.test(h.slice(h.indexOf('watch-data-chip'), h.indexOf('watch-data-chip') + 200)), `${st} not green`)
  assert.ok(h.includes('watch-gates-none'), `${st}: no invented gates`)
  assert.ok(h.includes('data-testid="watch-classic-link"'))
}
// 3. one stale input = STALE chip with that gate named and its age
{
  const h = html(buildWatchStatus(ok(body([inp('my_list', { as_of: iso(5000) }), ...IDS.slice(1).map(i => inp(i))])), NOW))
  assert.match(chip(h), /data-state="STALE"/)
  assert.match(h, /data-testid="watch-gate-my_list" data-state="STALE"/)
  assert.match(h, /data-testid="watch-gate-alerts" data-state="OK"/)
}
// 4. a missing input renders UNKNOWN on its gate
{
  const h = html(buildWatchStatus(ok(body(['my_list', 'prospects', 'regime'].map(i => inp(i)))), NOW))
  assert.match(chip(h), /data-state="UNKNOWN"/); assert.match(h, /data-testid="watch-gate-alerts" data-state="UNKNOWN"/)
}
// 5. Why sheet: names the state and the blocking input with age, limit and owner; closed = nothing
{
  const m = buildWatchStatus(ok(body([inp('alerts', { as_of: iso(9000) }), ...['my_list', 'prospects', 'regime'].map(i => inp(i))])), NOW)
  const s = renderToStaticMarkup(React.createElement(WatchWhySheet, { open: true, onClose: noop, state: m.chip.state, cause: m.cause, blockers: m.blockers }))
  assert.match(s, /Watch data: STALE/); assert.match(s, /alerts/); assert.match(s, /limit 30 m/); assert.match(s, /owner own_alerts/)
  assert.equal(renderToStaticMarkup(React.createElement(WatchWhySheet, { open: false, onClose: noop, state: 'OK', cause: '', blockers: [] })), '')
}
// LQ-2993 / completion-matrix W-04 (lead 00:47 ET): the sub-nav makes Watch one surface. On /watch the current tab is a
// span with aria-current (never a link to itself); every tab links to its OWN v002 view; NO tab points at the classic hub.
{
  const at = path => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [path] },
    React.createElement(WatchV002View, { m: buildWatchStatus(ok(body()), NOW), checkedLabel: 'checked', ov: ov(), onOpenWhy: noop, onOpenDiag: noop, onRecheck: noop })))
  const h = at('/watch')
  assert.ok(h.includes('data-testid="watch-subnav"'), 'the sub-nav renders on Overview')
  const full = k => (h.match(new RegExp(`<(?:a|span)[^>]*data-testid="watch-subnav-${k}"[^>]*>`)) || [''])[0]
  const hrefOf = k => (full(k).match(/href="([^"]+)"/) || [])[1]
  assert.match(full('overview'), /^<span/, 'Overview is the current page, not a link to itself')
  assert.match(full('overview'), /aria-current="page"/)
  const owns = { mine: '/watch-lists?list=mine', suggests: '/watch-lists?list=suggests', prospects: '/watch-lists?list=prospects', setups: '/watch-setups', sectors: '/watch-setups?tab=sectors', discover: '/watch-setups?tab=discover', alerts: '/watch-setups?tab=alerts', pullback: '/watch-setups?tab=pullback' }
  for (const [k, to] of Object.entries(owns)) {
    assert.match(full(k), /^<a/, `${k} is a link`)
    assert.equal(hrefOf(k), to, `${k} goes to its own v002 view`)
  }
  const nav = (h.match(/<nav[^>]*data-testid="watch-subnav"[^>]*>[\s\S]*?<\/nav>/) || [''])[0]
  assert.ok(nav && !nav.includes('/watch-classic'), 'no sub-nav tab points at the classic hub')
  assert.ok(!h.includes('data-classic') && !h.includes('· classic'), 'no classic-only item or suffix is left')
  assert.equal((nav.match(/<a /g) || []).length, 8, 'eight links plus the current span = nine tabs')
  // The current tab follows the route it renders on: on the Lists route Suggestions is current and Overview is a link.
  const hs = at('/watch-lists?list=suggests')
  const fs = k => (hs.match(new RegExp(`<(?:a|span)[^>]*data-testid="watch-subnav-${k}"[^>]*>`)) || [''])[0]
  assert.match(fs('suggests'), /^<span/); assert.match(fs('suggests'), /aria-current="page"/)
  assert.match(fs('overview'), /^<a/); assert.equal((fs('overview').match(/href="([^"]+)"/) || [])[1], '/watch')
}

// W-04 (lead 00:47 ET): the Overview is ordered Action/Triggers -> Validation Gates -> Since Last Visit -> Watch Status
// -> Details, and each section draws only what it could read.
{
  const acts = [
    { id: 'trigger-AAA', kind: 'trigger', symbol: 'AAA', href: '/watch/intelligence/AAA', text: 'Pullback/MACD trigger · score 82', detail: 'entry 10 · stop 9 · target 12 · proposal in queue', tone: 'ok' },
    { id: 'alert-BBB', kind: 'alert', symbol: 'BBB', href: '/watch/intelligence/BBB', text: 'Alert: BBB rsi above 70', detail: 'fired Nov 12, 1:00 PM ET', tone: 'warn' },
  ]
  const since = [{ id: 'since-alert-BBB', kind: 'alert', symbol: 'BBB', text: 'BBB alert fired: rsi above 70', at: iso(600), atText: 'Nov 12, 1:00 PM ET' }]
  const h = html(buildWatchStatus(ok(body()), NOW), { actions: acts, since })
  const order = ['ov-actions', 'ov-gates', 'ov-since', 'ov-status', 'ov-details'].map(id => h.indexOf(`data-testid="${id}"`))
  assert.ok(order.every((v, i) => v > 0 && (i === 0 || v > order[i - 1])), `section order ${order}`)
  assert.match(h, /Action \/ Triggers/); assert.match(h, /Validation Gates/); assert.match(h, /Since Last Visit/)
  assert.match(h, /Watch Status/); assert.match(h, /<h2[^>]*>Details<\/h2>/)
  assert.match(h, /data-testid="action-trigger-AAA"/); assert.match(h, /data-testid="action-alert-BBB"/)
  assert.match(h, /data-testid="since-alert-BBB"/); assert.match(h, /href="\/watch\/intelligence\/AAA"/)
  for (const id of IDS) assert.ok(h.includes(`data-testid="detail-${id}"`), `details lists ${id}`)
  assert.match((h.match(/data-testid="ov-status-row"[^>]*>/) || [''])[0], /data-state="OK"/)
}
// A source that could not be read is never "nothing needs action", and no empty-success line is drawn.
{
  const h = html(buildWatchStatus(ok(body()), NOW), { unread: ['alert list', 'pullback candidates'] })
  assert.match(h, /data-testid="ov-actions-unread"/); assert.ok(!h.includes('ov-actions-none'))
  assert.match(h, /Could not be read: alert list, pullback candidates/)
  assert.match(h, /data-testid="ov-since-unread"/); assert.ok(!h.includes('ov-since-none'))
  // W-04 review C2: the headline must not state a total while a source is unread.
  assert.match(metaOf(h), /incomplete — a source could not be read/)
  assert.doesNotMatch(metaOf(h), /\d+ to look at/, 'no count over an unread source')
  assert.match(metaOf(html(buildWatchStatus(ok(body()), NOW))), /0 to look at/, 'complete reads still state the count')
  assert.match(metaOf(html(buildWatchStatus(ok(body()), NOW), { loading: true })), /reading…/)
}
// The fallback window says it is a fallback; a recorded visit says since when and draws no fallback line.
{
  const h = html(buildWatchStatus(ok(body()), NOW))
  assert.match(h, /data-testid="ov-since-window" data-recorded="0"/)
  assert.match(h, /your last visit is not recorded/)
  const h2 = html(buildWatchStatus(ok(body()), NOW), { lastVisit: { recorded: true, status: 'RECORDED', startMs: NOW - 3600_000, label: 'since Nov 12, 1:00 PM ET', seenAt: iso(3600) } })
  assert.ok(!h2.includes('data-testid="ov-since-window"'), 'a recorded visit draws no fallback line')
  assert.match(h2, /since Nov 12, 1:00 PM ET/)
}
// An empty, fully-read section says so plainly.
{
  const h = html(buildWatchStatus(ok(body()), NOW))
  assert.match(h, /data-testid="ov-actions-none"/); assert.match(h, /data-testid="ov-since-none"/)
}
// A visit that could not be stamped is said out loud (the anchor does not advance), never swallowed.
{
  const h = html(buildWatchStatus(ok(body()), NOW), { visitError: 'HTTP 403' })
  assert.match(h, /data-testid="ov-visit-unrecorded"/)
  assert.match(h, /could not be recorded \(HTTP 403\)/)
  assert.ok(!html(buildWatchStatus(ok(body()), NOW)).includes('ov-visit-unrecorded'), 'a stamped visit draws no such line')
}
// W-04 review C1: the stamp is classified from the response BODY. HTTP 200 with no server `seen_at` is NOT a stamp
// (today's unregistered-key branch), so the line is drawn; a stamped body draws nothing. recordVisit is exercised with a
// stubbed fetch/window, so this is the same code path the page runs.
{
  const calls = []
  const realWin = globalThis.window, realFetch = globalThis.fetch
  globalThis.window = { innerWidth: 390 }
  const run = async (impl) => {
    calls.length = 0
    globalThis.fetch = impl
    await page.recordVisit(m => calls.push(m))
    return calls.slice()
  }
  try {
    const res = (ok, status, payload) => async () => ({ ok, status, json: async () => payload })
    assert.deepEqual(await run(res(true, 200, { ok: true, key: 'watch.last_seen' })),
      ['the server did not stamp a visit'], '200 {ok,key} draws the line')
    assert.deepEqual(await run(res(true, 200, { ok: true, key: 'watch.last_seen', value: { device: 'phone' } })),
      ['the server did not stamp a visit'], '200 with a value but no seen_at draws the line')
    assert.deepEqual(await run(res(true, 200, { ok: true, key: 'watch.last_seen', value: { device: 'phone', seen_at: iso(0) } })),
      [], 'a stamped body draws no line')
    assert.deepEqual(await run(res(false, 403, {})), ['HTTP 403'], 'a refused POST still names the status')
    assert.deepEqual(await run(async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad json') } })),
      ['the server did not confirm the visit'], 'an unreadable body is not a stamp')
  } finally {
    globalThis.window = realWin
    globalThis.fetch = realFetch
  }
}
console.log('WatchV002.view: ok')

// LQ-3012: the body the backend really serves (generated by watch_status_live.compute with stub rows), sent through the
// real /api/v2 envelope and readOnce, then built and rendered. Alerts has no run record, Prospects is 3 h old.
{
  const { readOnce } = await import(compile(join(app, 'src/lib/homeV010.ts')))
  const served = {"schema":"WatchStatus@v1","verdict":"UNKNOWN","cause":"Alerts: no evaluator run record: watch_alerts_eval has no heartbeat or run table yet (W-06 / WV-07); last_fired_at is not liveness","computed_at":"2031-03-07T15:00:00+00:00","session":"rth","read_from":"computed_on_request","required_inputs":["my_list","prospects","alerts","regime"],"inputs":[
    {"id":"my_list","label":"My List","required":true,"state":"OK","source_id":"watchlist_items","owner":"watch curation","as_of":"2031-03-07T14:56:00+00:00","age_s":240,"threshold_s":1800,"reason":null,"needs_backend":false,"timed_out":false},
    {"id":"prospects","label":"Prospects","required":true,"state":"STALE","source_id":"cio_prospect","owner":"cio","as_of":"2031-03-07T12:00:00+00:00","age_s":10800,"threshold_s":1800,"reason":"last write 10800 s ago, limit 1800 s","needs_backend":false,"timed_out":false},
    {"id":"alerts","label":"Alerts","required":true,"state":"UNKNOWN","source_id":"watch_alerts_eval_runs","owner":"watch alerts","as_of":null,"age_s":null,"threshold_s":1200,"reason":"no evaluator run record: watch_alerts_eval has no heartbeat or run table yet (W-06 / WV-07); last_fired_at is not liveness","needs_backend":true,"timed_out":false},
    {"id":"regime","label":"Regime","required":true,"state":"OK","source_id":"market_regime_snapshots","owner":"market regime","as_of":"2031-03-07T13:00:00+00:00","age_s":7200,"threshold_s":93600,"reason":null,"needs_backend":false,"timed_out":false}]}
  const fetchOf = body => async () => ({ ok: true, status: 200, json: async () => body })
  const read = await readOnce('/api/v2/watch/status', 1000, fetchOf({ ok: true, data: served }))
  assert.equal(read.state, 'OK'); assert.equal(read.data.verdict, 'UNKNOWN', 'envelope unwrapped to data.verdict')
  const h = html(buildWatchStatus(read, NOW))
  assert.match(chip(h), /data-state="UNKNOWN"/, 'UNKNOWN verdict is the chip, never green')
  const gate = id => (h.match(new RegExp(`data-testid="watch-gate-${id}"[^>]*>`)) || [''])[0]
  assert.match(gate('my_list'), /data-state="OK"/); assert.match(gate('prospects'), /data-state="STALE"/)
  assert.match(gate('alerts'), /data-state="UNKNOWN"/); assert.match(gate('regime'), /data-state="OK"/)
  assert.ok(h.includes('NEEDS BACKEND') && h.includes('3 h 0 m old · limit 30 m'), 'needs-backend flag and the stale age are visible')
  // an envelope carrying ok:false is a failed read, not a body
  const bad = await readOnce('/api/v2/watch/status', 1000, fetchOf({ ok: false, reason: 'db down' }))
  const hb = html(buildWatchStatus(bad, NOW))
  assert.match(chip(hb), /data-state="UNKNOWN"/); assert.ok(hb.includes('watch-gates-none') && hb.includes('db down'))
  // a server that drops one required input never reads OK even when the rest are fresh
  const miss = await readOnce('/api/v2/watch/status', 1000, fetchOf({ ok: true, data: { ...body(IDS.slice(1).map(i => inp(i))), verdict: 'OK' } }))
  const hm = html(buildWatchStatus(miss, NOW))
  assert.match(chip(hm), /data-state="UNKNOWN"/); assert.match((hm.match(/data-testid="watch-gate-my_list"[^>]*>/) || [''])[0], /data-state="UNKNOWN"/)
}
// LQ-2993r R1/R2: legacy deep links keep working. Any query is handed to the classic hub unchanged; no query = Overview.
{
  const links = ['?tab=Suggests', '?symbol=AXTI', '?conflict=abc-123', '?symbol=AXTI&review=1', '?view=intelligence', '?mine=1&conv=high']
  for (const q of links) assert.equal(classicTarget(q), `/watch-classic${q}`, q)
  assert.equal(classicTarget(''), null)
  assert.equal(classicTarget('?'), null)
  const at = search => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [`/watch${search}`] },
    React.createElement(page.default)))
  assert.ok(at('').includes('data-testid="watch-v002"'), 'no query renders the Overview')
  for (const q of links) assert.ok(!at(q).includes('data-testid="watch-v002"'), `${q} must redirect, not render the Overview`)
}
console.log('deep-link redirect checks passed')

// WL-01/WL-06 (sprint 8H-2 b1): the verdict states its own scope, and the cause is rendered exactly once.
{
  const m = buildWatchStatus(ok(body([...IDS.map(i => inp(i)), inp('x_optional', { required: false })])), NOW)
  const h = html(m)
  const scope = (h.match(/data-testid="ov-status-scope"[^>]*>([^<]*)</) || [null, ''])[1]
  assert.equal(scope, 'computed over 4 required inputs · 1 optional input not in the verdict', 'the verdict names the inputs it covers')
  assert.match((h.match(/data-testid="detail-my_list-scope"[^>]*>([^<]*)</) || [null, ''])[1], /^required$/)
  assert.match((h.match(/data-testid="detail-x_optional-scope"[^>]*>([^<]*)</) || [null, ''])[1], /^optional$/, 'an optional input is not part of the verdict')
  assert.ok(h.includes('5 inputs · 4 required'), 'the Details meta separates the total from the required set')
  assert.equal(h.split('All required Watch inputs are within their thresholds').length - 1, 1, 'the cause is rendered once, not in both Gates and Watch Status')
  // every input required: no optional disclosure is invented
  const all = html(buildWatchStatus(ok(body()), NOW))
  assert.equal((all.match(/data-testid="ov-status-scope"[^>]*>([^<]*)</) || [null, ''])[1], 'computed over 4 required inputs')
  assert.ok(!all.includes('optional input not in the verdict'))
}
console.log('WL-01/WL-06 scope checks passed')
