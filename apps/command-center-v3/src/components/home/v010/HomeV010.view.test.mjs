// Home v010 (design/pages/home/v010, operator-approved 2026-11-11) — the page model and its rendering.
//
// Engineering Constitution: unknown beats wrong. These cases pin the four promises the page makes:
//   1. the Trade-ready chip shows the SERVER verdict from /api/v2/home/status (YES / NO / UNKNOWN + cause); with the
//      endpoint absent (404) or unread it is UNKNOWN, never YES/NO from the client;
//   2. a failed read is UNKNOWN / TIMED OUT, never OK and never "clear";
//   3. trading gates come from the same read with state + age; with no read they say "not available", never "0";
//   4. when every source was read and nothing needs action, Action Required collapses to one line.
// Synthetic fixtures only (public repo): placeholder symbols / accounts, no real values.
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

const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const FAILED = {
  sinceClose: fail(API.sinceClose, 'TIMED OUT'),
  approvals: fail(API.approvals),
  incidents: fail(API.incidents),
  lastSeen: fail(API.lastSeen),
}
const http404 = source => ({ state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source })
const gate = (id, state, extra = {}) => ({ id, label: id, required: true, state, source_id: `src_${id}`, as_of: '2031-03-07T14:50:00Z', age_s: 600, threshold_s: 900, reason: null, needs_backend: false, ...extra })
// computed_at is required by the F-1 guard (REVIEW-2446): a served YES older than YES_MAX_AGE_MS is not shown.
const STATUS_YES = { schema: 'HomeStatus@v1', verdict: 'YES', trade_ready: { verdict: 'YES', cause: 'every required input read OK and nothing blocks trading', computed_at: '2031-03-07T14:59:30Z' },
  gates: ['p0', 'p1_blocking', 'gates', 'portfolio', 'orders', 'data'].map(id => gate(id, 'OK')), blockers: [], unknown_inputs: [] }
const STATUS_NO = { schema: 'HomeStatus@v1', verdict: 'NO', trade_ready: { verdict: 'NO', cause: 'Synthetic Kill: synthetic kill' },
  gates: [gate('p0', 'WARN', { value: 1 }), gate('orders', 'UNKNOWN', { as_of: null, age_s: null, needs_backend: true, reason: 'NEEDS BACKEND: no heartbeat' })],
  blockers: [{ category: 'Synthetic Kill', cause: 'synthetic kill', count: 1, goto: '#card-action' }],
  unknown_inputs: [{ input: 'orders', state: 'UNKNOWN', reason: 'NEEDS BACKEND: no heartbeat', needs_backend: true }] }
const STATUS_UNKNOWN = { schema: 'HomeStatus@v1', verdict: 'UNKNOWN', trade_ready: { verdict: 'UNKNOWN', cause: 'data: quote store unreadable' },
  gates: [gate('p0', 'OK'), gate('data', 'UNKNOWN', { reason: 'quote store unreadable' })], blockers: [],
  unknown_inputs: [{ input: 'data', state: 'UNKNOWN', reason: 'quote store unreadable' }] }
const render = model => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model, nowIso: new Date(NOW).toISOString(), onOpenWhy() {}, onOpenDiag() {} })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }

await test('no status read / 404 -> chip UNKNOWN "not served" with NEEDS BACKEND, in every state', () => {
  for (const inp of [CLEAR, FAILED, { ...CLEAR, status: http404(API.status) }]) {
    const m = buildModel(inp, NOW)
    assert.equal(m.tradeReadyServed, false)
    assert.match(m.tradeReadyCause, /not served/)
    assert.equal(m.tradeReady, 'UNKNOWN')
    const t = text(render(m))
    assert.match(t, /Trade-ready: UNKNOWN/)
    assert.doesNotMatch(t, /Trade-ready: (YES|NO)/)
    assert.match(t, /NEEDS BACKEND/)
  }
})

await test('failed fetch -> UNKNOWN / TIMED OUT, never OK, never clear', () => {
  const m = buildModel(FAILED, NOW)
  for (const r of m.status) assert.notEqual(r.state, 'OK', `${r.name} must not be OK on a failed read`)
  assert.equal(m.status.find(r => r.name === 'Orders').state, 'TIMED OUT')
  assert.equal(m.status.find(r => r.name === 'Alerts').state, 'UNKNOWN')
  assert.equal(m.actionEmpty, false)
  const t = text(render(m))
  assert.doesNotMatch(t, /Nothing needs action/)
  assert.match(t, /UNKNOWN — could not read incidents/)
  assert.match(t, /TIMED OUT — could not read stop advice/)
  assert.match(t, /Cause: .* · Source: .* · Owner: /)
  // the body of a 200 that itself says UNKNOWN is also UNKNOWN
  const m2 = buildModel({ ...CLEAR, incidents: ok(API.incidents, { state: 'UNKNOWN', items: null, counts: null }) }, NOW)
  assert.equal(m2.status.find(r => r.name === 'Alerts').state, 'UNKNOWN')
  assert.equal(m2.actionEmpty, false)
})

await test('readOnce: non-200 is UNKNOWN, a 30 s stall is TIMED OUT', async () => {
  const r1 = await readOnce('/api/x', 1000, async () => ({ ok: false, status: 500, json: async () => ({}) }))
  assert.equal(r1.state, 'UNKNOWN')
  const stall = (_u, init) => new Promise((_res, rej) => init.signal.addEventListener('abort', () => rej(new Error('aborted'))))
  const r2 = await readOnce('/api/x', 5, stall)
  assert.equal(r2.state, 'TIMED OUT')
})

await test('served YES -> chip YES, gates listed with state + age, no NEEDS BACKEND on the chip', () => {
  const m = buildModel({ ...CLEAR, status: ok(API.status, STATUS_YES) }, NOW)
  assert.equal(m.tradeReady, 'YES')
  assert.equal(m.tradeReadyServed, true)
  assert.equal(m.gates.length, 6)
  const html = render(m)
  const t = text(html)
  assert.match(t, /Trade-ready: YES/)
  const head = text(html.match(/<header[\s\S]*?<\/header>/)[0])
  assert.doesNotMatch(head, /NEEDS BACKEND/)
  const gates = text(html.match(/<section[^>]*id="card-gates"[\s\S]*?<\/section>/)[0])
  assert.equal((html.match(/data-testid="gate-row"/g) || []).length, 6)
  assert.match(gates, /portfolio OK as of .* · 10 m old/)
  assert.equal(m.status.find(r => r.name === 'Portfolio').state, 'OK')
})

await test('served NO -> chip NO with the blocker as cause; an unread gate stays UNKNOWN + NEEDS BACKEND', () => {
  const m = buildModel({ ...CLEAR, status: ok(API.status, STATUS_NO) }, NOW)
  assert.equal(m.tradeReady, 'NO')
  assert.match(m.tradeReadyCause, /^Synthetic Kill/)
  assert.ok(m.why.blockers.some(b => b.category === 'Synthetic Kill' && b.targetId === 'card-action'))
  assert.ok(m.why.blockers.some(b => b.category === 'Could not read: orders' && b.needsBackend))
  const html = render(m)
  assert.match(text(html), /Trade-ready: NO/)
  assert.match(text(html), /Synthetic Kill: synthetic kill/)
  const gates = text(html.match(/<section[^>]*id="card-gates"[\s\S]*?<\/section>/)[0])
  assert.match(gates, /orders UNKNOWN no as-of NEEDS BACKEND/)
  assert.match(gates, /Why: NEEDS BACKEND: no heartbeat · Source: src_orders/)
})

await test('served UNKNOWN -> chip UNKNOWN with the unread input named, never YES', () => {
  const m = buildModel({ ...CLEAR, status: ok(API.status, STATUS_UNKNOWN) }, NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.equal(m.tradeReadyServed, true)
  assert.match(text(render(m)), /data: quote store unreadable/)
  // a 200 with no verdict word, a 500 and a timeout are all UNKNOWN, never YES
  for (const r of [ok(API.status, { gates: [] }), fail(API.status), fail(API.status, 'TIMED OUT')]) {
    const m2 = buildModel({ ...CLEAR, status: r }, NOW)
    assert.equal(m2.tradeReady, 'UNKNOWN')
    assert.equal(m2.gates, null)
  }
  assert.match(buildModel({ ...CLEAR, status: fail(API.status, 'TIMED OUT') }, NOW).tradeReadyCause, /timed out/)
})

await test('trading gates show "not available", never a zero count, when not served', () => {
  const html = render(buildModel(CLEAR, NOW))
  const gates = text(html.match(/<section[^>]*id="card-gates"[\s\S]*?<\/section>/)[0])
  assert.match(gates, /Trading gates: not available/)
  assert.match(gates, /NEEDS BACKEND/)
  assert.doesNotMatch(gates, /\d/, 'the gates block must carry no count at all')
})

await test('empty action area collapses to one "Nothing needs action" line', () => {
  const m = buildModel(CLEAR, NOW)
  assert.equal(m.actionEmpty, true)
  const html = render(m)
  assert.equal((html.match(/data-testid="action-clear"/g) || []).length, 1)
  assert.match(text(html), /Nothing needs action · checked/)
  assert.match(text(html), /last 24 h — last visit not recorded/)
})

await test('P0 overflow: first 3 shown, then "+N more P0 items"', () => {
  const items = Array.from({ length: 5 }, (_, i) => ({ incident_id: i, priority: 'P0', category: 'Unprotected Position', symbol: `SYM${i}`, first_seen_at: AT, owner: 'UNREGISTERED' }))
  const m = buildModel({ ...CLEAR, incidents: ok(API.incidents, { state: 'OK', items, data_integrity_24h: { state: 'OK', value: { events: 0 } } }) }, NOW)
  const t = text(render(m))
  assert.equal((t.match(/P0 · UNPROTECTED POSITION/g) || []).length, 3)
  assert.match(t, /\+2 more P0 items/)
  assert.equal(m.status.find(r => r.name === 'Alerts').state, 'WARN')
  assert.equal(m.tradeReady, 'UNKNOWN')
})

// Every /api/v2 route wraps its payload as { ok, data }; readOnce unwraps it (live P0 2026-11-12: the page read the
// envelope as the payload and showed every source as unreadable). Synthetic bodies only.
const stub = body => async () => ({ ok: true, status: 200, json: async () => body })
await test('readOnce: an enveloped status body is unwrapped and the server verdict NO is read', async () => {
  const r = await readOnce(API.status, 1000, stub({ ok: true, data: STATUS_NO }))
  assert.equal(r.state, 'OK')
  assert.equal(r.data.verdict, 'NO')
  const m = buildModel({ ...CLEAR, status: r }, NOW)
  assert.equal(m.tradeReady, 'NO')
  assert.equal(m.tradeReadyServed, true)
  assert.doesNotMatch(m.tradeReadyCause, /unreadable/)
})
await test('readOnce: enveloped incidents and since-close read OK; enveloped approvals + last-seen are read', async () => {
  const inc = await readOnce(API.incidents, 1000, stub({ ok: true, data: { schema: 'HomeIncidents@v1', state: 'OK', counts: { P0: 0, P1: 0 }, items: [], data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } }))
  const sc = await readOnce(API.sinceClose, 1000, stub({ ok: true, data: { status: 'ok', schema: 'since_close_card.v1', cio_brief: { status: 'available', stop_advice: [] } } }))
  const ap = await readOnce(API.approvals, 1000, stub({ ok: true, data: { count: 2, urgent_count: 0, as_of: AT } }))
  const ls = await readOnce(API.lastSeen, 1000, stub({ ok: true, data: { ok: true, key: 'home.last_seen', value: null, read: { status: 'NOT_RECORDED', seen_at: null } } }))
  for (const r of [inc, sc, ap, ls]) assert.equal(r.state, 'OK')
  const m = buildModel({ ...CLEAR, incidents: inc, sinceClose: sc, approvals: ap, lastSeen: ls, status: ok(API.status, STATUS_NO) }, NOW)
  assert.deepEqual(m.unread, [])
  assert.equal(m.status.find(r => r.name === 'Alerts').state, 'OK')
  assert.equal(m.approvalsCount, 2)
  assert.equal(m.since.state, 'OK')
  assert.match(m.since.header, /last visit not recorded/)
  const t = text(render(m))
  assert.doesNotMatch(t, /could not read incidents/)
  assert.doesNotMatch(t, /could not read stop advice/)
})
await test('readOnce: ok:false is UNKNOWN with the reason, never OK; the verdict stays UNKNOWN', async () => {
  const r1 = await readOnce(API.status, 1000, stub({ ok: false, reason: 'synthetic store down' }))
  assert.equal(r1.state, 'UNKNOWN'); assert.equal(r1.data, null); assert.equal(r1.error, 'synthetic store down')
  const r2 = await readOnce(API.approvals, 1000, stub({ ok: false, code: 'SYNTHETIC_REFUSED' }))
  assert.equal(r2.state, 'UNKNOWN'); assert.equal(r2.error, 'SYNTHETIC_REFUSED')
  const r3 = await readOnce(API.incidents, 1000, stub({ ok: false }))
  assert.equal(r3.error, 'ok:false')
  const m = buildModel({ ...CLEAR, status: r1, approvals: r2, incidents: r3 }, NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.match(m.tradeReadyCause, /synthetic store down/)
  assert.equal(m.approvalsCount, null)
  assert.ok(m.unread.some(u => u.label === 'approvals') && m.unread.some(u => u.label === 'incidents'))
  // an envelope with ok:true but no object payload is not unwrapped and carries no verdict -> UNKNOWN, never YES
  const r4 = await readOnce(API.status, 1000, stub({ ok: true, data: null }))
  assert.equal(buildModel({ ...CLEAR, status: r4 }, NOW).tradeReady, 'UNKNOWN')
})
await test('readOnce: an un-enveloped body still works (raw payload passes through)', async () => {
  const r = await readOnce(API.status, 1000, stub(STATUS_NO))
  assert.equal(r.state, 'OK'); assert.equal(r.data.verdict, 'NO')
  assert.equal(buildModel({ ...CLEAR, status: r }, NOW).tradeReady, 'NO')
  const inc = await readOnce(API.incidents, 1000, stub({ state: 'OK', items: [], data_integrity_24h: { state: 'OK', value: { events: 0 } } }))
  assert.equal(buildModel({ ...CLEAR, incidents: inc }, NOW).status.find(x => x.name === 'Alerts').state, 'OK')
  // the legacy nested approvals shape is still read
  assert.equal(buildModel(CLEAR, NOW).approvalsCount, 0)
})

console.log(`HomeV010.view: ${n} passed`)
