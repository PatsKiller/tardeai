// LQ-20261113-3078 (A08): the lifecycle footnote and the Watch card are not placeholder controls.
// Lifecycle labels: UNKNOWN with a count and a reason when rows carry none (nothing when all do); Watch: UNKNOWN + reason,
// never "No source yet" and never a NEEDS BACKEND tag. Synthetic fixtures only.
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
const { buildModel, lifecycleNote, API } = lib

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const inc = items => ok(API.incidents, { state: 'OK', items, counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } })
const base = items => ({
  sinceClose: ok(API.sinceClose, { status: 'ok', cio_brief: { status: 'available', stop_advice: [] } }),
  approvals: ok(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } }),
  incidents: inc(items),
  lastSeen: ok(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } }),
})
const item = (n, label) => ({ incident_id: n, priority: 'P1', category: 'Synthetic Alert', symbol: `SYM${n}`, first_seen_at: AT, owner: 'UNREGISTERED', ...(label ? { validation_label: label } : {}) })
const render = model => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/'] },
  React.createElement(View, { model, nowIso: new Date(NOW).toISOString(), onOpenWhy() {}, onOpenDiag() {} })))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const card = (html, id) => html.match(new RegExp(`<section[^>]*id="${id}"[\\s\\S]*?</section>`))[0]

let n = 0
async function test(name, fn) { await fn(); n += 1; console.log(`ok - ${name}`) }

await test('unlabelled incident rows: the lifecycle line is UNKNOWN with a count and a reason, no NEEDS BACKEND tag', () => {
  const html = render(buildModel(base([item(1), item(2, 'MONITORING')]), NOW))
  const since = card(html, 'card-since')
  const t = text(since)
  assert.match(t, /Lifecycle UNKNOWN for 1 of 2 incidents/)
  assert.match(t, /carries no FIXED \/ UNPROVEN \/ MONITORING label/)
  assert.match(since, /data-testid="since-lifecycle"/)
  assert.doesNotMatch(since, /NEEDS BACKEND/)
  assert.doesNotMatch(since, /labels\s*<span/)
})

await test('every row labelled, or no rows, or an unread feed: no lifecycle line at all', () => {
  assert.equal(lifecycleNote([{ id: 'a', label: 'FIXED', text: 't', time: 'x' }], 'OK'), null)
  assert.equal(lifecycleNote([], 'OK'), null)
  assert.equal(lifecycleNote([{ id: 'a', label: null, text: 't', time: 'x' }], 'UNKNOWN'), null)
  const html = render(buildModel(base([item(1, 'FIXED'), item(2, 'MONITORING')]), NOW))
  assert.doesNotMatch(card(html, 'card-since'), /since-lifecycle|Lifecycle UNKNOWN/)
  const unread = render(buildModel({ ...base([]), incidents: { state: 'TIMED OUT', data: null, error: 'timeout', at: AT, source: API.incidents } }, NOW))
  assert.match(text(card(unread, 'card-since')), /TIMED OUT — could not read incidents/)
  assert.doesNotMatch(card(unread, 'card-since'), /Lifecycle UNKNOWN/)
})

await test('the singular case reads "1 of 1 incident"', () => {
  assert.equal(lifecycleNote([{ id: 'a', label: null, text: 't', time: 'x' }], 'OK')?.startsWith('Lifecycle UNKNOWN for 1 of 1 incident:'), true)
})

await test('Watch card: UNKNOWN with a reason, no placeholder sentence, no NEEDS BACKEND, link kept', () => {
  const html = render(buildModel(base([]), NOW))
  const watch = card(html, 'card-watch')
  const t = text(watch)
  assert.match(t, /^\s*Watch\s+UNKNOWN — Home reads no watch-item source/)
  assert.match(watch, /data-testid="watch-unknown"/)
  assert.doesNotMatch(watch, /No source yet|watch-na|NEEDS BACKEND|Watch today|Watch tonight/)
  assert.match(watch, /data-testid="watch-link"/)
  assert.equal(buildModel(base([]), NOW).watch.state, 'UNKNOWN')
})

console.log(`${n} passed`)
