// FQ-034 — on a phone the Defense page leads with the decision, not with writer diagnostics.
//
// Live at 390 px on release 105df180e, /v3/defense opened: tab bar → a long "Source clocks" block (Writer ACTIVE ·
// "Last successful run: not measured" × 5 sources) → then the tab's own content. The operator's question is "how exposed
// am I and what is pending", and it sat below the plumbing.
//
// Red-first: at the parent DeskPage both controls fail — the clocks section is always first and never collapsed.
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

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

let PHONE = true
globalThis.window = globalThis.window || {}
globalThis.window.matchMedia = (q) => ({ matches: PHONE && String(q).includes('820'), media: q,
  addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
globalThis.window.location = globalThis.window.location || { origin: 'http://localhost:4173', pathname: '/v3/defense', search: '', hash: '' }
globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
globalThis.document = globalThis.document || { documentElement: { style: {} }, body: { style: {} },
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (String(_args[0] ?? "").includes("desk-sources") && (globalThis as any).__deskWriterFixture) ? { data: (globalThis as any).__deskWriterFixture, loading: false, error: null } : { data: null, loading: false, error: null }',
  )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (spec.endsWith('.css')) return 'from "data:text/javascript,export default {}"'
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { default: DeskPage } = await import(compile(join(app, 'src/components/DeskPage.tsx')))

const SOURCES = [{ id: 'a', label: 'Sector posture', asOf: '2026-11-03T17:26:00Z', laneIds: ['sector-posture'] }]
const DECISIONS = [{ id: 'd1', title: 'Decide: re-hedge the book', detail: 'Coverage fell below the floor.' }]

function render(phone) {
  PHONE = phone
  const props = {
    title: 'Defense', purpose: 'How exposed is the book if the market turns?',
    tabs: [{ id: 'act', label: 'Where to act' }, { id: 'log', label: 'Review log' }], defaultTab: 'act',
    sources: SOURCES, decisions: DECISIONS,
    children: React.createElement('div', { 'data-testid': 'defense-content' }, 'Where to act: hedge now'),
  }
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
    React.createElement(DeskPage, props)))
}

const text = (m) => m.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
function idx(haystack, needle) { const i = haystack.indexOf(needle); assert.ok(i >= 0, `missing ${needle}`); return i }

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('a phone leads with the pending decision, before the clocks', () => {
  const t = text(render(true))
  assert.ok(idx(t, 'Decide: re-hedge') < idx(t, 'Source clocks'), 'the decision is below the source clocks')
})

check('a phone puts the tab content before the clocks too', () => {
  const t = text(render(true))
  assert.ok(idx(t, 'Where to act: hedge now') < idx(t, 'Source clocks'), 'the content is below the source clocks')
})

check('the clocks are a closed disclosure on a phone, and still on the page', () => {
  const html = render(true)
  const details = html.match(/<details[^>]*data-testid="desk-source-clocks"[\s\S]*?<\/details>/)
  assert.ok(details, 'no disclosure around the source clocks')
  const openingTag = details[0].match(/^<details\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/)?.[0]
  assert.ok(openingTag, 'no opening tag for the source clocks disclosure')
  // Attribute values can say "open" without opening the disclosure; attribute order cannot change its state.
  const attributes = openingTag.replace(/"[^"]*"|'[^']*'/g, '')
  assert.doesNotMatch(attributes, /\sopen(?=[\s=/>])/i, 'the disclosure is open by default')
  assert.match(text(details[0]), /Sector posture/, 'the clock content was removed instead of collapsed')
})

check('desktop is unchanged: clocks first, no disclosure', () => {
  const html = render(false)
  const t = text(html)
  assert.ok(idx(t, 'Source clocks') < idx(t, 'Decide: re-hedge'), 'desktop order changed')
  assert.ok(!html.includes('data-testid="desk-source-clocks"'), 'desktop grew a disclosure')
})

// FQ-023 — the source clocks speak in the operator's words, not the writer's.
check('writer jargon is gone and the lane is named in words', () => {
  // render with a populated writer so the block is exercised (fixture hook covers the desk-sources call)
  globalThis.__deskWriterFixture = { ok: true, data: { writers: [{ lane_id: 'schwab-position-sync', state: 'ACTIVE',
    last_success_at: null, evidence_as_of: null, reason: 'No successful run is recorded in the available execution evidence.' }] } }
  PHONE = false
  const props = { title: 'Defense', purpose: 'p', tabs: [], sources: [{ id: 'holdings', label: 'Holdings', laneIds: ['schwab-position-sync'] }],
    children: React.createElement('div', null, 'x') }
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] }, React.createElement(DeskPage, props)))
  const t = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  assert.doesNotMatch(t, /Writer ACTIVE/, 'raw writer state is still the label')
  assert.doesNotMatch(t, /Last successful run:/, 'raw writer label is still printed')
  assert.match(t, /Schwab position sync is enabled/, 'the lane is not named in words')
  // ACTIVE is a registry enablement flag. This fixture carries no run evidence at all, so "running" would be a claim
  // the record does not make — and the suite must catch the old word if it comes back.
  assert.doesNotMatch(t, /Schwab position sync is running/, 'a registry flag was rendered as runtime liveness')
  assert.match(t, /cannot be confirmed current/, 'the consequence is not stated')
  assert.match(html, /title="schwab-position-sync"/, 'the raw lane id is not kept')
})
check('a past success does not suppress why the writer is not current now', () => {
  // The producer's reason was rendered only when `last_success_at` was null, so a lane that is NOT SET UP but ran in
  // the past printed "is not set up · last succeeded 7h ago" and never said why it is not set up.
  globalThis.__deskWriterFixture = { ok: true, data: { writers: [{ lane_id: 'schwab-position-sync', state: 'NONE',
    last_success_at: '2026-11-05T09:30:00Z', evidence_as_of: null, reason: 'No scheduled writer is registered for this source.' }] } }
  PHONE = false
  const props = { title: 'Defense', purpose: 'p', tabs: [], sources: [{ id: 'holdings', label: 'Holdings', laneIds: ['schwab-position-sync'] }],
    children: React.createElement('div', null, 'x') }
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] }, React.createElement(DeskPage, props)))
  const t = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  assert.match(t, /Schwab position sync is not set up/, 'the state is not stated')
  assert.match(t, /last succeeded/, 'the past run is hidden')
  assert.match(t, /No scheduled writer is registered for this source/, 'a past success suppressed the reason')
})
check('an enabled writer with no run does not repeat the same sentence twice', () => {
  globalThis.__deskWriterFixture = { ok: true, data: { writers: [{ lane_id: 'schwab-position-sync', state: 'ACTIVE',
    last_success_at: null, evidence_as_of: null, reason: 'No successful run is recorded in the available execution evidence.' }] } }
  PHONE = false
  const props = { title: 'Defense', purpose: 'p', tabs: [], sources: [{ id: 'holdings', label: 'Holdings', laneIds: ['schwab-position-sync'] }],
    children: React.createElement('div', null, 'x') }
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] }, React.createElement(DeskPage, props)))
  const t = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  const occurrences = (t.match(/No successful run is recorded/g) || []).length
  assert.equal(occurrences, 1, `the no-run sentence is printed ${occurrences} times: ${t}`)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
