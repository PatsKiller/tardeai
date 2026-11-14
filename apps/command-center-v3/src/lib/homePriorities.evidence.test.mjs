// Home v010 — "Today's priorities" population evidence (campaign Home item 4).
//
// The empty state "Nothing needs you today" is a claim over a population. The producer now sends, per input, whether
// it was read and how many rows it returned (`inputs`); this projection carries that as `evidence`, plus the body's
// own `served_at` so the card can age the ranking at render (item 1's rule) instead of implying it is current.
//   * an absent `inputs` (older server) yields evidence: null — the page then says only what `state` proves;
//   * a row count the server did not send is never invented ("read" without a number stays "read");
//   * a bad `served_at` is "no source time", never a guessed one.
// Synthetic fixtures only (no real accounts, symbols or values).
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
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

const { prioritiesView, PRIORITIES_API } = await import(compile(join(app, 'src/lib/homePriorities.ts')))
const AT = '2031-03-07T14:59:00Z'
const read = data => ({ state: 'OK', data, error: null, at: AT, source: PRIORITIES_API })
const SERVED = '2031-03-07T14:58:30Z'

let n = 0
function test(name, fn) { fn(); n += 1; console.log(`ok - ${name}`) }

// 1. The population reaches the page, per input, from the server's own array.
test('evidence names every input the ranking was read over, with its row count', () => {
  const v = prioritiesView(read({ state: 'OK', count: 0, items: [], unread: [], served_at: SERVED, inputs: [
    { input: 'incidents', read: true, rows: 12 }, { input: 'stop advice', read: true, rows: 3 }, { input: 'approvals', read: true, rows: 0 },
  ] }))
  assert.equal(v.state, 'OK')
  assert.equal(v.evidence, 'incidents 12 rows · stop advice 3 rows · approvals 0 rows')
  assert.equal(v.servedAt, SERVED)
})

// 2. An unread input is named as not read — and it changes the state, so the empty sentence cannot be claimed.
test('an unread input is named, never counted, and the state is PARTIAL', () => {
  const v = prioritiesView(read({ state: 'PARTIAL', count: 1, items: [{ id: 'a', kind: 'INCIDENT', title: 't', tier_label: 'P0' }], unread: [{ input: 'approvals', reason: 'approvals count not read' }],
    served_at: SERVED, inputs: [{ input: 'incidents', read: true, rows: 1 }, { input: 'stop advice', read: true, rows: 0 }, { input: 'approvals', read: false, rows: null, reason: 'approvals count not read' }] }))
  assert.equal(v.state, 'PARTIAL')
  assert.equal(v.evidence, 'incidents 1 row · stop advice 0 rows · approvals not read')
})

// 3. Backward compatible: an older server sends neither field and the page invents neither.
test('no inputs / no served_at -> null evidence and null source time (never a derived claim)', () => {
  const v = prioritiesView(read({ state: 'OK', count: 0, items: [], unread: [] }))
  assert.equal(v.evidence, null)
  assert.equal(v.servedAt, null)
  assert.equal(prioritiesView(undefined).servedAt, null)
  assert.equal(prioritiesView(undefined).evidence, null)
})

// 4. A row count that is missing or not a number is not invented, and a bad served_at is not a source time.
test('a missing count reads "read"; an unparseable served_at is null', () => {
  const v = prioritiesView(read({ state: 'OK', count: 0, items: [], unread: [], served_at: 'yesterday-ish', inputs: [
    { input: 'incidents', read: true }, { input: 'approvals', read: true, rows: 'many' },
  ] }))
  assert.equal(v.evidence, 'incidents read · approvals read')
  assert.equal(v.servedAt, null)
})

// 5. The UNKNOWN body still carries what it has (evidence of what failed), and the OK state is the only one that
//    can claim "nothing needs you" — pinned by the view, asserted here on the projection's state.
test('UNKNOWN keeps the evidence of the failed reads', () => {
  const v = prioritiesView(read({ state: 'UNKNOWN', count: 0, items: [], served_at: SERVED, unread: [{ input: 'incidents', reason: 'boom' }], inputs: [
    { input: 'incidents', read: false, rows: null, reason: 'boom' }, { input: 'stop advice', read: false, rows: null, reason: 'not read' },
  ] }))
  assert.equal(v.state, 'UNKNOWN')
  assert.equal(v.evidence, 'incidents not read · stop advice not read')
  assert.equal(v.servedAt, SERVED)
})

// 6. A1: an OK body whose own evidence names an unread input cannot claim the all-clear. The card would otherwise
//    print "every input was read · … approvals not read" in one sentence; the state is demoted to PARTIAL and the
//    note names exactly what was ranked without. (Defence in depth: the producer derives state from these inputs.)
test('an OK body with an unread input is demoted to PARTIAL, not printed as an all-clear', () => {
  const v = prioritiesView(read({ state: 'OK', count: 0, items: [], unread: [], served_at: SERVED, inputs: [
    { input: 'incidents', read: true, rows: 0 }, { input: 'approvals', read: false, rows: null },
  ] }))
  assert.equal(v.state, 'PARTIAL')
  assert.equal(v.evidence, 'incidents 0 rows · approvals not read')
  assert.equal(v.note, 'ranked without: approvals: not read')
})

// 7. The same body with every input read keeps its OK state: the guard fires on the evidence, not on the shape.
test('an OK body with every input read stays OK and carries no note', () => {
  const v = prioritiesView(read({ state: 'OK', count: 0, items: [], unread: [], served_at: SERVED, inputs: [
    { input: 'incidents', read: true, rows: 0 }, { input: 'approvals', read: true, rows: 0 },
  ] }))
  assert.equal(v.state, 'OK')
  assert.equal(v.note, null)
})

console.log(`homePriorities.evidence: ok (${n} cases)`)
