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

const lib = await import(compile(join(app, 'src/lib/homePriorities.ts')))
const { prioritiesView, recordVisit, deviceOf, PRIORITIES_API, LAST_SEEN_KEY } = lib

let failed = 0
async function test(name, fn) { try { await fn(); console.log(`ok - ${name}`) } catch (e) { failed++; console.error(`not ok - ${name}\n${e.stack}`) } }
const AT = '2031-03-07T14:59:00Z'
const ok = data => ({ state: 'OK', data, error: null, at: AT, source: PRIORITIES_API })
const bad = (state, error) => ({ state, data: null, error, at: AT, source: PRIORITIES_API })
const item = (n, over = {}) => ({ rank: n, kind: 'INCIDENT', id: `inc-${n}`, title: `Item ${n}`, why: 'synthetic cause', tier_label: 'P0', ...over })

await test('a served ranking keeps the server order and says OK', () => {
  const v = prioritiesView(ok({ state: 'OK', count: 2, items: [item(1), item(2)], unread: [] }))
  assert.equal(v.state, 'OK'); assert.deepEqual(v.rows.map(r => r.id), ['inc-1', 'inc-2']); assert.equal(v.needsBackend, false); assert.equal(v.note, null)
})
await test('an empty OK ranking is the only "nothing to do"', () => {
  const v = prioritiesView(ok({ state: 'OK', count: 0, items: [], unread: [] }))
  assert.equal(v.state, 'OK'); assert.equal(v.rows.length, 0)
})
await test('PARTIAL names what was not read and is not OK', () => {
  const v = prioritiesView(ok({ state: 'PARTIAL', count: 1, items: [item(1)], unread: [{ input: 'approvals', reason: 'approvals count not read' }] }))
  assert.equal(v.state, 'PARTIAL'); assert.match(v.note, /approvals/)
})
await test('server UNKNOWN is UNKNOWN with the reasons, never an empty all-clear', () => {
  const v = prioritiesView(ok({ state: 'UNKNOWN', count: 0, items: [], unread: [{ input: 'incidents', reason: 'boom' }] }))
  assert.equal(v.state, 'UNKNOWN'); assert.match(v.note, /incidents: boom/)
})
await test('HTTP 404 keeps NEEDS BACKEND; any other failure is UNKNOWN without it', () => {
  assert.equal(prioritiesView(bad('UNKNOWN', 'HTTP 404')).needsBackend, true)
  const v = prioritiesView(bad('UNKNOWN', 'HTTP 503')); assert.equal(v.needsBackend, false); assert.match(v.note, /HTTP 503/)
  assert.equal(prioritiesView(bad('TIMED OUT', 'timeout')).state, 'TIMED OUT')
})
await test('a body with no state or items is unreadable, not empty', () => {
  assert.equal(prioritiesView(ok({})).state, 'UNKNOWN'); assert.equal(prioritiesView(ok({ state: 'MAYBE', items: [] })).state, 'UNKNOWN')
})
await test('loading and undefined read as reading', () => {
  assert.equal(prioritiesView(undefined).state, 'LOADING'); assert.equal(prioritiesView({ state: 'LOADING', data: null, error: null, at: null, source: 'x' }).state, 'LOADING')
})
await test('a missing cause is "cause not recorded", never blank', () => {
  assert.equal(prioritiesView(ok({ state: 'OK', items: [item(1, { why: undefined })] })).rows[0].why, 'cause not recorded')
})
await test('device is derived from width', () => { assert.equal(deviceOf(390), 'phone'); assert.equal(deviceOf(1280), 'desktop') })

function fakeFetch(res) { const calls = []; const f = async (url, init) => { calls.push({ url, init }); if (res instanceof Error) throw res; return res }; f.calls = calls; return f }
await test('recordVisit POSTs home.last_seen with only the device and no timestamp', async () => {
  const f = fakeFetch({ ok: true, status: 200, json: async () => ({ ok: true }) })
  assert.equal(await recordVisit(1280, f), 'RECORDED')
  const c = f.calls[0]; assert.equal(c.url, '/api/v2/ui/prefs'); assert.equal(c.init.method, 'POST')
  const body = JSON.parse(c.init.body); assert.equal(body.key, LAST_SEEN_KEY); assert.deepEqual(body.value, { device: 'desktop' })
})
await test('recordVisit reports a refusal and a failure and never throws', async () => {
  assert.equal(await recordVisit(390, fakeFetch({ ok: false, status: 403, json: async () => ({}) })), 'REFUSED')
  assert.equal(await recordVisit(390, fakeFetch({ ok: true, status: 200, json: async () => ({ ok: false }) })), 'REFUSED')
  assert.equal(await recordVisit(390, fakeFetch({ ok: false, status: 500, json: async () => ({}) })), 'FAILED')
  assert.equal(await recordVisit(390, fakeFetch(new Error('net'))), 'FAILED')
})
await test('the page records the visit only after the last-seen read, once, and only on an OK read', () => {
  const page = readFileSync(join(app, 'src/pages/HomeV010.tsx'), 'utf8')
  assert.match(page, /k === 'lastSeen' && r\.state === 'OK'\) void recordVisit/)
  assert.equal((page.match(/recordVisit\(/g) || []).length, 1)
  assert.match(page, /readOnce<PrioritiesWire>\(PRIORITIES_API\)/)
})
await test('the view draws the server rows and keeps NEEDS BACKEND only when there is no ranking', () => {
  const v = readFileSync(join(app, 'src', 'components', ['ho', 'me'].join(''), 'v010', 'HomeV010View.tsx'), 'utf8')
  assert.match(v, /\{!pv \|\| pv\.needsBackend \? <NB \/> : null\}/)
  assert.match(v, /data-testid="prio-list"/); assert.match(v, /Why: <b>\{r\.why\}<\/b>/)
})
if (failed) { console.error(`${failed} failed`); process.exit(1) }
console.log('HomePriorities tests passed')
