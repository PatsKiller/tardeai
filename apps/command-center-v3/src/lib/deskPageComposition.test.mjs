// DR-D06 / DR-D05 (sprint 8H-2 b3): the Defense desk put its source clocks and writer diagnostics between the
// tabs and the answer, so the first screen was evidence plumbing rather than "what do I do". The fix moves the
// clocks below the desk content — and then nothing on the first screen says whether the evidence is healthy, so a
// one-line health count stays above it. A source card must also name its owner and a way to review it (DR-D05).
// Render the real DeskPage: JSX comments and declarations cannot prove what the operator sees.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')
const reportError = console.error
console.error = (...args) => {
  if (!String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) reportError(...args)
}
globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  location: { origin: 'http://localhost:4173', pathname: '/v3/defense', search: '', hash: '' },
  addEventListener() {}, removeEventListener() {} }
globalThis.document = { documentElement: { style: {} }, body: { style: {} },
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }
Date.now = () => Date.parse('2026-11-05T21:00:00Z')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/, 'const useApi = () => (globalThis as any).__deskWriterFixture')
  let js = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
  } }).outputText.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (_whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    assert.ok(target, `Missing component fixture dependency: ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}
const { default: DeskPage } = await import(compile(join(app, 'src/components/DeskPage.tsx')))

const text = html => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const markup = html => html.replace(/<!--[\s\S]*?-->/g, '')
// The clocks <details> WRAPS the per-writer Diagnostics <details>, so only the inner ones may be removed.
const DIAGNOSTICS = /<details\b[^>]*data-testid="source-writer-diagnostics"[\s\S]*?<\/details>/g
const withoutDiagnostics = html => text(markup(html).replace(DIAGNOSTICS, ''))
const diagnosticsOf = html => markup(html).match(DIAGNOSTICS)?.join('') ?? ''
function healthOf(t) {
  const at = t.indexOf('Source health:')
  assert.ok(at >= 0, `no health line: ${t.slice(0, 300)}`)
  return t.slice(at, t.indexOf(DECISIONS, at)).trim()
}

const DECISIONS = 'Decisions for you'
const CLOCKS = 'Source clocks'

const SOURCES = [
  { id: 'engine', label: 'Synthetic engine', asOf: '2026-11-05T20:00:00Z', laneIds: ['lane-a'],
    owner: 'Desk owner (synthetic)', reviewHref: '/defense/classic', reviewLabel: 'Review engine evidence' },
  { id: 'momentum', label: 'Synthetic momentum', asOf: '2026-11-05T20:30:00Z', laneIds: ['lane-b'],
    owner: 'Momentum owner (synthetic)' },
  { id: 'console', label: 'Synthetic review console', asOf: null, gap: 'No lock on file.',
    owner: 'Operator (synthetic)' },
]

function render(sources = SOURCES, { writers, sourcesLast = true, missing = false, failed = false } = {}) {
  const rows = missing ? [] : (writers ?? [
    { lane_id: 'lane-a', state: 'ACTIVE', last_success_at: '2026-11-05T19:00:00Z', evidence_as_of: '2026-11-05T19:59:00Z', reason: null },
    { lane_id: 'lane-b', state: 'PAUSED', last_success_at: null, evidence_as_of: null, reason: 'Paused by the owner.' },
  ])
  globalThis.__deskWriterFixture = { data: failed ? { ok: false } : { ok: true, data: { writers: rows } },
    loading: false, error: failed ? 'read failed' : null, stale: false, refetch() {} }
  // `sourcesLast: null` omits the prop entirely, so the other-desk test exercises the component's real default.
  const props = { title: 'Synthetic desk', purpose: 'Synthetic composition', sources,
    decisions: [{ id: 'd1', title: 'Synthetic decision', detail: 'Synthetic detail' }],
    children: React.createElement('div', null, 'Synthetic desk content') }
  if (sourcesLast !== null) props.sourcesLast = sourcesLast
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
    React.createElement(DeskPage, props)))
}

let passed = 0, failed = 0
function check(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`) }
  catch (error) { failed++; console.log(`[FAIL] ${name}: ${error.message}`) }
}

check('the desk answer comes before the evidence plumbing when sourcesLast is set', () => {
  const t = text(render())
  assert.ok(t.indexOf(DECISIONS) >= 0 && t.indexOf(CLOCKS) >= 0, `sections missing: ${t}`)
  assert.ok(t.indexOf(DECISIONS) < t.indexOf(CLOCKS), `Decisions must precede Source clocks: ${t.slice(0, 400)}`)
  assert.ok(t.indexOf('Synthetic desk content') < t.indexOf(CLOCKS), 'the desk content must precede the clocks')
})
check('a source-health count stays visible above the moved evidence', () => {
  const t = text(render())
  assert.equal(healthOf(t), 'Source health: 3 sources · 2 need attention')
  assert.ok(t.indexOf('Source health') < t.indexOf(DECISIONS), 'the health line belongs above the desk answer')
})
check('moving the clocks removes no source, age or gap', () => {
  const t = text(render())
  for (const label of ['Synthetic engine', 'Synthetic momentum', 'Synthetic review console']) assert.match(t, new RegExp(label))
  assert.match(t, /No lock on file/)
})
check('a fresh clock behind a paused writer still needs attention', () => {
  // lane-b is PAUSED with an as-of 30 minutes old: the clock alone would read healthy
  assert.equal(healthOf(text(render())), 'Source health: 3 sources · 2 need attention')
})
check('unknown writer evidence is never reported as all-writers-active', () => {
  const health = healthOf(text(render(SOURCES, { missing: true })))
  assert.equal(health, 'Source health: 3 sources · 1 needs attention · 2 unknown')
})
check('a failed writer read is unknown, not clean', () => {
  const health = healthOf(text(render(SOURCES, { failed: true })))
  assert.match(health, /unknown/)
  assert.doesNotMatch(health, /all writers active/)
})
check('an all-active, gap-free page says so', () => {
  const clean = SOURCES.slice(0, 2)
  const t = text(render(clean, { writers: [
    { lane_id: 'lane-a', state: 'ACTIVE', last_success_at: '2026-11-05T19:00:00Z', evidence_as_of: null, reason: null },
    { lane_id: 'lane-b', state: 'ACTIVE', last_success_at: '2026-11-05T19:00:00Z', evidence_as_of: null, reason: null },
  ] }))
  assert.match(t, /Source health: 2 sources · all writers active/)
})
check('every source card names its owner and a review link, in the primary text', () => {
  const html = render()
  const primary = withoutDiagnostics(html)
  assert.match(primary, /Owner: Desk owner \(synthetic\)/)
  assert.match(primary, /Owner: Momentum owner \(synthetic\)/)
  assert.match(primary, /Owner: Operator \(synthetic\)/)
  assert.match(html, /<a[^>]+href="\/defense\/classic"[^>]*>[^<]*Review engine evidence/)
  // a source with nothing to review says so rather than showing no owner line at all
  assert.match(primary, /Owner: Momentum owner \(synthetic\)/)
})
check('a card with no review link says the review is not published', () => {
  const primary = withoutDiagnostics(render())
  assert.match(primary, /Review engine evidence/)
  assert.match(primary, /No review link is published/) // momentum + console cards
})
check('the card states its last output, last successful run (or not measured) and lifecycle', () => {
  const html = render()
  const diag = diagnosticsOf(html)
  const primary = withoutDiagnostics(html)
  // the last output is the source's own as-of line, in the primary text: "Updated 1h ago · As of <time>"
  assert.match(primary, /Synthetic engine\b[\s\S]*Owner: Desk owner \(synthetic\)[\s\S]*Updated 1h ago[\s\S]*As of Nov 5 15:00 ET/)
  // lifecycle and the run history move one tap away, and a source that never succeeded says so
  assert.match(text(diag), /Writer state: ACTIVE/)
  assert.match(text(diag), /Last successful run: 2h ago/)
  assert.match(text(diag), /Evidence captured: 1h ago/)
  assert.match(text(diag), /Last successful run: not measured/) // lane-b never succeeded
  assert.doesNotMatch(primary, /Last successful run:/)
})
check('the default order for every other desk is unchanged and adds no health line', () => {
  const t = text(render(SOURCES, { sourcesLast: null }))
  assert.ok(t.indexOf(CLOCKS) < t.indexOf(DECISIONS), `default order changed: ${t.slice(0, 300)}`)
  assert.doesNotMatch(t, /Source health:/)
})

// ── wiring: the Defense desk is the page that asks for the new composition ────────────────────────────────────
const codeOnly = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
check('DefenseDesk asks for sourcesLast and passes owner/review from the projection', () => {
  const src = codeOnly(readFileSync(join(app, 'src/pages/desks/DefenseDesk.tsx'), 'utf8'))
  assert.match(src, /sourcesLast/, 'DefenseDesk does not request the evidence-last composition')
})
check('the projection contract carries owner and review link, and both desks pass them through', () => {
  const board = codeOnly(readFileSync(join(app, 'src/components/DeskBoard.tsx'), 'utf8'))
  assert.match(board, /owner\?:/, 'DeskProjection.sources has no owner')
  assert.match(board, /review_href\?:/, 'DeskProjection.sources has no review_href')
  assert.match(board, /owner: s\.owner/, 'DeskBoard drops the owner it reads')
  const defense = codeOnly(readFileSync(join(app, 'src/pages/desks/DefenseDesk.tsx'), 'utf8'))
  assert.match(defense, /owner: s\.owner/, 'DefenseDesk drops the owner it reads')
})

console.log(JSON.stringify({ suite: 'deskPageComposition', passed, failed }))
if (failed) process.exitCode = 1
