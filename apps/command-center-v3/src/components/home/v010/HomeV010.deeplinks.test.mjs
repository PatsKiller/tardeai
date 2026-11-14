// LQ-20261107-2992b: priority deep links, Watch/Details blocks, '+N more gates', blocks_trading tri-state. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
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
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const lib = await import(compile(join(app, 'src/lib/homeV010.ts')))
const { default: View } = await import(compile(join(app, 'src/components/home', 'v010', 'HomeV010View.tsx')))
const { buildModel, readOnce, API } = lib

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const fail = (source, state = 'UNKNOWN') => ({ state, data: null, error: 'HTTP 503', at: AT, source })
const dest = await import(compile(join(app, 'src/lib/homeDestinations.ts')))
const { prioritiesView } = await import(compile(join(app, 'src/lib/homePriorities.ts')))
const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const gate = (id, state, extra = {}) => ({ id, label: id, required: true, state, source_id: `src_${id}`, as_of: '2031-03-07T14:50:00Z', age_s: 600, threshold_s: 900, reason: state === 'OK' ? null : 'synthetic', needs_backend: false, ...extra })
const wire = gates => ({ schema: 'HomeStatus@v1', verdict: 'NO', trade_ready: { verdict: 'NO', cause: 'synthetic', computed_at: '2031-03-07T14:59:30Z' }, gates, blockers: [], unknown_inputs: [] })
const model = gates => buildModel({ ...CLEAR, status: ok(API.status, wire(gates)) }, NOW)
const render = (m, priorities) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model: m, nowIso: new Date(NOW).toISOString(), onOpenWhy() {}, onOpenDiag() {}, priorities })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }
const count = (h, re) => (h.match(re) || []).length
const prio = items => prioritiesView({ state: 'OK', data: { state: 'OK', items, count: items.length }, error: null, at: AT, source: 'p' })
const item = (kind, id) => ({ id, kind, title: `t-${id}`, why: 'w', rank: 1 })

await test('each priority kind links to its real page', () => {
  assert.equal(dest.priorityDestination('INCIDENT').to, '/ops/incidents')
  assert.equal(dest.priorityDestination('APPROVALS').to, '/approvals')
  assert.equal(dest.priorityDestination('STOP').to, '/home-classic')
  assert.equal(dest.priorityDestination('MYSTERY'), null)
  assert.equal(dest.priorityDestination(null), null)
})
await test('every destination is a route that exists in App.tsx', () => {
  const app_ = readFileSync(join(app, 'src/App.tsx'), 'utf8')
  const routes = new Set([...app_.matchAll(/<Route path="([^"]+)"/g)].map(m => '/' + m[1]))
  for (const d of dest.DETAILS) assert.ok(routes.has(d.to), d.to)
  for (const k of ['INCIDENT', 'APPROVALS', 'STOP']) assert.ok(routes.has(dest.priorityDestination(k).to), k)
})
await test('priority rows render a link, and an unknown kind says no destination (not a guessed link)', () => {
  const h = render(model([gate('p0', 'OK')]), prio([item('INCIDENT', 'a'), item('APPROVALS', 'b'), item('ZZZ', 'c')]))
  assert.equal(count(h, /data-testid="prio-link"/g), 2)
  assert.match(h, /href="\/ops\/incidents"/); assert.match(h, /href="\/approvals"/)
  assert.equal(count(h, /data-testid="prio-nolink"/g), 1)
})
await test('Watch block is an honest NEEDS BACKEND with the real Watch link; Details lists every destination', () => {
  const h = render(model([gate('p0', 'OK')]))
  const w = h.slice(h.indexOf('id="card-watch"'), h.indexOf('id="card-details"'))
  assert.match(w, /UNKNOWN — Home reads no watch-item source/); assert.doesNotMatch(w, /NEEDS BACKEND|No source yet/); assert.match(w, /href="\/watch"/)
  assert.doesNotMatch(text(w), /\d+ (items?|symbols?)/)
  assert.equal(count(h, /data-testid="details-link"/g), dest.DETAILS.length)
  assert.match(h, /href="\/home-classic"/)
})
const many = k => Array.from({ length: k }, (_, i) => gate(`g${i}`, 'OK'))
await test('+N more gates: 8 OK gates -> 5 shown and "+3 more gates"; toggle target present', () => {
  const h = render(model(many(8)))
  assert.equal(count(h, /data-testid="gate-row"/g), 5)
  assert.match(text(h), /\+3 more gates/)
})
await test('+N more gates never hides a non-OK gate', () => {
  const g = many(8); g[6] = gate('g6', 'STALE'); g[7] = gate('g7', 'UNKNOWN')
  const h = render(model(g))
  assert.equal(count(h, /data-testid="gate-row"/g), 7)
  assert.match(h, /id="gate-g6"/); assert.match(h, /id="gate-g7"/)
  assert.match(text(h), /\+1 more gates/)
})
await test('5 or fewer gates -> no overflow control; all-bad list -> no hiding', () => {
  assert.doesNotMatch(render(model(many(5))), /gates-more/)
  const bad = Array.from({ length: 8 }, (_, i) => gate(`b${i}`, 'WARN'))
  const h = render(model(bad)); assert.equal(count(h, /data-testid="gate-row"/g), 8); assert.doesNotMatch(h, /gates-more/)
})
await test('blocks_trading null/absent renders "classification pending (UNKNOWN)", never non-blocking', () => {
  const h = render(model([gate('a', 'WARN'), gate('b', 'WARN', { blocks_trading: null }), gate('c', 'WARN', { blocks_trading: false }), gate('d', 'WARN', { blocks_trading: true })]))
  assert.equal(count(h, /classification pending \(UNKNOWN\)/g), 2)
  assert.equal(count(h, /does not block trading/g), 1); assert.equal(count(h, /blocks trading/g), 1)
  assert.equal(dest.blocksText(undefined), 'classification pending (UNKNOWN)')
})
console.log(`HomeV010.deeplinks: ${n} passed`)
