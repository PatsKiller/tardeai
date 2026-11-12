// Home v010 — REVIEW-20261107-2446 F-1: a served YES must not sit beside a page that contradicts it.
//
// Engineering Constitution: UI may not contradict reality; unknown beats wrong. These cases pin the client guard:
//   * YES is shown only when every required gate is OK, no page read failed, no P0 is on this page, and the
//     verdict's computed_at is within YES_MAX_AGE_MS of the page's own clock;
//   * each of those contradictions demotes YES to UNKNOWN with the reason, and the reason reaches the Why sheet;
//   * NO is never softened and UNKNOWN is never upgraded.
// Synthetic fixtures only (public repo): placeholder symbols / accounts, no real values.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')

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
const { buildModel, statusFrom, YES_MAX_AGE_MS, API } = lib

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
const gate = (id, state, extra = {}) => ({ id, label: id, required: true, state, source_id: `src_${id}`, as_of: '2031-03-07T14:58:00Z', age_s: 120, threshold_s: 900, reason: null, needs_backend: false, ...extra })
const yesBody = (over = {}) => ({ schema: 'HomeStatus@v1', verdict: 'YES',
  trade_ready: { verdict: 'YES', cause: 'every required input read OK and nothing blocks trading', computed_at: '2031-03-07T14:59:30Z' },
  gates: ['p0', 'p1_blocking', 'gates', 'portfolio', 'orders', 'data'].map(id => gate(id, 'OK')),
  blockers: [], unknown_inputs: [], ...over })
const noBody = { schema: 'HomeStatus@v1', verdict: 'NO',
  trade_ready: { verdict: 'NO', cause: 'Synthetic Kill: synthetic kill', computed_at: '2031-03-07T14:59:30Z' },
  gates: [gate('p0', 'WARN', { value: 1 }), gate('portfolio', 'OK')],
  blockers: [{ category: 'Synthetic Kill', cause: 'synthetic kill', count: 1 }], unknown_inputs: [] }
const withStatus = body => ({ ...CLEAR, status: ok(API.status, body) })

let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }

await test('a served YES the page agrees with stays YES, and YES_MAX_AGE_MS is 2 minutes', () => {
  const m = buildModel(withStatus(yesBody()), NOW)
  assert.equal(YES_MAX_AGE_MS, 120_000)
  assert.equal(m.tradeReady, 'YES')
  assert.equal(m.tradeReadyServed, true)
  assert.equal(m.unread.length, 0)
  assert.equal(m.p0.length, 0)
})

await test('a required gate that is not OK demotes YES to UNKNOWN with the gate named', () => {
  const m = buildModel(withStatus(yesBody({ gates: [...yesBody().gates, gate('data', 'UNKNOWN', { reason: 'quote store unreadable' })] })), NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.equal(m.tradeReadyServed, true)  // the endpoint was served; the claim was not shown
  assert.match(m.tradeReadyCause, /required gate not OK: data UNKNOWN/)
  assert.equal(m.why.blockers[0].category, 'Trade-ready YES not shown')
  assert.match(m.why.blockers[0].detail, /required gate not OK/)
})

await test('a failed page read demotes YES to UNKNOWN and names the unread source', () => {
  const m = buildModel({ ...withStatus(yesBody()), incidents: fail(API.incidents) }, NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.match(m.tradeReadyCause, /1 page read unread: incidents/)
})

await test('an open P0 on this page demotes YES to UNKNOWN', () => {
  const incidents = ok(API.incidents, { state: 'OK', counts: { P0: 1, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 },
    items: [{ incident_id: 'i1', priority: 'P0', category: 'Synthetic Kill', symbol: 'AAA' }] })
  const m = buildModel({ ...withStatus(yesBody()), incidents }, NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.match(m.tradeReadyCause, /open P0 on this page/)
})

await test('a YES older than the bound demotes (a tab left open cannot keep it)', () => {
  const old = yesBody({ trade_ready: { verdict: 'YES', computed_at: '2031-03-07T14:55:00Z' } })
  const m = buildModel(withStatus(old), NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.match(m.tradeReadyCause, /computed 5 m ago \(limit 2 m\)/)
})

await test('a YES with no readable computed_at, or no gate list, demotes', () => {
  const noStamp = buildModel(withStatus(yesBody({ trade_ready: { verdict: 'YES' } })), NOW)
  assert.equal(noStamp.tradeReady, 'UNKNOWN')
  assert.match(noStamp.tradeReadyCause, /no readable computed_at/)

  const noGates = buildModel(withStatus(yesBody({ gates: null })), NOW)
  assert.equal(noGates.tradeReady, 'UNKNOWN')
  assert.match(noGates.tradeReadyCause, /no gate list/)
})

await test('NO is never softened, even with unread reads and an old verdict', () => {
  const m = buildModel({ ...withStatus(noBody), incidents: fail(API.incidents), approvals: fail(API.approvals) }, NOW)
  assert.equal(m.tradeReady, 'NO')
  assert.equal(m.tradeReadyCause, 'Synthetic Kill: synthetic kill')
})

await test('UNKNOWN stays UNKNOWN', () => {
  const body = { schema: 'HomeStatus@v1', verdict: 'UNKNOWN', trade_ready: { verdict: 'UNKNOWN', cause: 'data: quote store unreadable', computed_at: '2031-03-07T14:59:30Z' },
    gates: [gate('data', 'UNKNOWN')], blockers: [], unknown_inputs: [{ input: 'data', state: 'UNKNOWN', reason: 'quote store unreadable' }] }
  const m = buildModel(withStatus(body), NOW)
  assert.equal(m.tradeReady, 'UNKNOWN')
  assert.equal(m.tradeReadyCause, 'data: quote store unreadable')
})

await test('a served YES with no cause says "cause not recorded", never a claim', () => {
  const st = statusFrom(ok(API.status, { schema: 'HomeStatus@v1', verdict: 'YES', trade_ready: { verdict: 'YES', computed_at: '2031-03-07T14:59:30Z' }, gates: [gate('p0', 'OK')] }), NOW)
  assert.equal(st.verdict, 'YES')
  assert.equal(st.cause, 'cause not recorded')
})

console.log(`# ${n} passed`)
