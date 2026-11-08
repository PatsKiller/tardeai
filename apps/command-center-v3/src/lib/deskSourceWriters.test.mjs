// LQ-20261107-529: seven /v3 source cards said "Writer not identified for this source." Each card now either names
// its real writer lane (which must be registered and ACTIVE) or states why no scheduled writer exists. No writer is
// invented. This suite renders the real DeskPage for the stated-reason path and checks every listed page's sources.
// Synthetic fixtures only.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const repo = resolve(app, '../..')
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
Date.now = () => Date.parse('2026-11-07T21:00:00Z')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = () => ({ data: { ok: true, data: { writers: [] } }, loading: false, error: null, stale: false, refetch() {} })')
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
const markup = html => html.replace(/<!--[\s\S]*?-->/g, '')
const text = html => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const renderSources = sources => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
  React.createElement(DeskPage, { title: 'Synthetic desk', purpose: 'Synthetic source evidence', sources,
    children: React.createElement('div', null, 'Synthetic desk content') })))

let passed = 0, failed = 0
function check(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`) }
  catch (error) { failed++; console.log(`[FAIL] ${name}: ${error.message}`) }
}
const MISSING = 'Writer not identified for this source.'
const read = rel => readFileSync(join(app, rel), 'utf8')
const registry = new Map(JSON.parse(readFileSync(join(repo, 'config/lane_registry.json'), 'utf8')).lanes.map(l => [l.lane_id, l]))

// The object literal that declares one source, found by its id and read to its matching brace.
function sourceLiteral(src, id) {
  const at = src.search(new RegExp(`\\{\\s*id:\\s*'${id}'`))
  assert.ok(at >= 0, `source '${id}' not found`)
  let depth = 0
  for (let i = at; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}' && --depth === 0) return src.slice(at, i + 1)
  }
  throw new Error(`source '${id}' literal not closed`)
}
function lanesOf(literal) {
  const m = literal.match(/laneIds:\s*\[([^\]]*)\]/)
  return m ? [...m[1].matchAll(/'([^']+)'/g)].map(x => x[1]) : []
}

const PAGES = [
  ['src/components/OpsDeskFrame.tsx', 'watchers', 'Incident watchers'],
  ['src/components/OpsDeskFrame.tsx', 'supervisor', 'Incident supervisor'],
  ['src/pages/ConflictRules.tsx', 'rulebook', 'Conflict rulebook'],
  ['src/pages/ConflictRules.tsx', 'ledger', 'Conflict ledger'],
  ['src/pages/ApprovalsHub.tsx', 'approvals', 'Approval queue'],
  ['src/pages/CioHub.tsx', 'cio-status', 'CIO evaluations'],
]
for (const [file, id, label] of PAGES) {
  check(`${label} names a registered ACTIVE writer or states why none exists`, () => {
    const literal = sourceLiteral(read(file), id)
    const lanes = lanesOf(literal)
    if (lanes.length) {
      for (const lane of lanes) {
        assert.ok(registry.has(lane), `${lane} is not in config/lane_registry.json`)
        assert.equal(registry.get(lane).state, 'ACTIVE', `${lane} is not ACTIVE`)
      }
    } else {
      assert.match(literal, /writerNote:\s*'[^']{20,}'/, `${label} has no writer lane and no writerNote`)
    }
  })
}
check('incident timers map to their registered lanes', () => {
  const ops = read('src/components/OpsDeskFrame.tsx')
  assert.deepEqual(lanesOf(sourceLiteral(ops, 'watchers')), ['tradeai-incident-watchers'])
  assert.deepEqual(lanesOf(sourceLiteral(ops, 'supervisor')), ['tradeai-incident-supervisor'])
})
check('conflict ledger maps to the lane that appends it', () =>
  assert.deepEqual(lanesOf(sourceLiteral(read('src/pages/ConflictRules.tsx'), 'ledger')), ['conflict-resolver']))
check('server projections carry writer_note through to the card', () => {
  for (const file of ['src/components/DeskBoard.tsx', 'src/pages/desks/DefenseDesk.tsx'])
    assert.match(read(file), /writerNote:\s*s\.writer_note/, `${file} drops writer_note`)
})

const noted = renderSources([{ id: 'n', label: 'Synthetic noted source', writerNote: 'Synthetic: built on request; no scheduled job writes it.' }])
check('a stated reason replaces the missing-writer warning', () => {
  assert.match(text(markup(noted)), /Synthetic: built on request; no scheduled job writes it\./)
  assert.ok(!text(markup(noted)).includes(MISSING))
  assert.match(markup(noted), /data-testid="desk-source-writer-note"/)
})
const bare = renderSources([{ id: 'b', label: 'Synthetic bare source' }])
check('a source with neither lane nor reason still says the writer is not identified', () =>
  assert.ok(text(markup(bare)).includes(MISSING)))

console.log(JSON.stringify({ suite: 'deskSourceWriters', passed, failed }))
if (failed) process.exitCode = 1
