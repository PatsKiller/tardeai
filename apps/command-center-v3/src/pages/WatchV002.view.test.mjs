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
const html = m => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(WatchV002View, { m, checkedLabel: 'checked', onOpenWhy: noop, onOpenDiag: noop, onRecheck: noop })))
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
