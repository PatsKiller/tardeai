// Home v010 — the "Today's priorities" card (campaign Home item 4, with item 1's timing rule).
//
// The card is only allowed to say "Nothing needs you today" over a population it can name, and the ranking it draws
// is aged at render from the server's own `served_at` — never presented as current without a source time, and never
// aged from a stored relative string.
// Synthetic fixtures only (no real accounts, symbols or values).
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

const { buildModel, API } = await import(compile(join(app, 'src/lib/homeV010.ts')))
const { prioritiesView, PRIORITIES_API } = await import(compile(join(app, 'src/lib/homePriorities.ts')))
const { default: View } = await import(compile(join(app, 'src/components/home', 'v010/HomeV010View.tsx')))

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const SERVED = '2031-03-07T14:58:30Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })

const CLEAR = {
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: ok(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } }),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
}
const view = { state: 'OK', data: null, error: null, at: AT, source: PRIORITIES_API }
const render = (prio, now = NOW) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model: buildModel(CLEAR, now), nowIso: new Date(now).toISOString(), onOpenPriorities: undefined,
    onOpenWhy() {}, onOpenDiag() {}, priorities: prioritiesView(prio) })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const section = html => html.match(/<section[^>]*id="card-priorities"[\s\S]*?<\/section>/)
const cardText = (prio, now) => text(section(render(prio, now))[0])
const prio = (over = {}) => ({ ...view, data: { state: 'OK', count: 0, items: [], unread: [], served_at: SERVED,
  inputs: [{ input: 'incidents', read: true, rows: 12 }, { input: 'stop advice', read: true, rows: 3 }, { input: 'approvals', read: true, rows: 0 }], ...over } })

let n = 0
function test(name, fn) { fn(); n += 1; console.log(`ok - ${name}`) }

// 1. The empty state names the population it is claimed over and the ranking's own source time.
test('empty state: population evidence + source time, aged at render', () => {
  const t = cardText(prio())
  assert.match(t, /Nothing needs you today: every input was read and none has an open item\./)
  assert.match(t, /incidents 12 rows · stop advice 3 rows · approvals 0 rows/)
  assert.match(t, /as of \w{3} 9:58 AM ET · 1 m old/)
})

// 2. The age is recomputed from the client clock: the same payload one hour later is one hour older.
test('the same body ages when the client clock moves; no stored relative wording', () => {
  const later = cardText(prio(), NOW + 3_600_000)
  assert.match(later, /as of \w{3} 9:58 AM ET · 1 h 1 m old/)
  assert.doesNotMatch(later, /just now/i)
})

// 3. A ranking with no source time says so instead of looking current.
test('no served_at -> "source time not published", never an implied "as of now"', () => {
  const t = cardText(prio({ served_at: null }))
  assert.match(t, /source time not published/)
  assert.doesNotMatch(t, /as of/)
})

// 4. An older server (no inputs) keeps the old sentence and invents no population.
test('no inputs -> the sentence stands alone; no invented counts', () => {
  const t = cardText(prio({ inputs: undefined, served_at: null }))
  assert.match(t, /Nothing needs you today: every input was read and none has an open item\./)
  assert.doesNotMatch(t, /rows/)
})

// 5. A PARTIAL ranking never claims "nothing needs you"; the unread input is named and the population still shown.
test('PARTIAL with rows: population line under the list, no "Nothing needs you"', () => {
  const t = cardText(prio({ state: 'PARTIAL', count: 1, items: [{ id: 'a', rank: 1, kind: 'INCIDENT', title: 'Synthetic item', why: 'cause', tier_label: 'P0' }],
    unread: [{ input: 'approvals', reason: 'approvals count not read' }],
    inputs: [{ input: 'incidents', read: true, rows: 1 }, { input: 'approvals', read: false, rows: null }] }))
  assert.doesNotMatch(t, /Nothing needs you/)
  assert.match(t, /read: incidents 1 row · approvals not read/)
  assert.match(t, /ranked without: approvals/)
})

// 6. The empty state is only ever OK: a PARTIAL with no rows shows the note, not the all-clear sentence.
test('PARTIAL with no rows: the note, never the all-clear', () => {
  const t = cardText(prio({ state: 'PARTIAL', count: 0, unread: [{ input: 'approvals', reason: 'approvals count not read' }] }))
  assert.doesNotMatch(t, /Nothing needs you today/)
  assert.match(t, /ranked without: approvals/)
})

// 7. A1: with the body saying OK but its evidence naming an unread input, the card must not claim "every input was
//    read" (or "nothing needs you") in the same breath as printing "not read". The PARTIAL note carries it instead.
test('OK body with an unread input: no all-clear sentence; the unread input is named', () => {
  const t = cardText(prio({ inputs: [{ input: 'incidents', read: true, rows: 0 }, { input: 'approvals', read: false, rows: null }] }))
  assert.doesNotMatch(t, /Nothing needs you today/)
  assert.doesNotMatch(t, /every input was read/)
  assert.match(t, /ranked without: approvals/)
  assert.match(t, /PARTIAL/)
})

console.log(`HomeV010.prioPopulation: ${n} passed`)
