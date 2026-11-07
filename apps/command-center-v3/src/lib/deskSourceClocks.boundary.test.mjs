// Render the real DeskPage: declarations and JSX comments cannot prove what the operator sees.
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
export const text = html => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
export const markup = html => html.replace(/<!--[\s\S]*?-->/g, '')
export function diagnosticsOf(html) {
  return markup(html).match(/<details\b[^>]*data-testid="source-writer-diagnostics"[\s\S]*?<\/details>/)?.[0] ?? ''
}
export function primaryOf(html) {
  return text(markup(html).match(/<div\b[^>]*data-testid="source-writer-state"[^>]*>([\s\S]*?)<\/div>/)?.[1] ?? '')
}
export function renderWriter(state, { loading = false, lastSuccess = null, reason = 'No successful run is recorded in the available execution evidence.', missing = false, asOf = '2026-11-05T20:58:00Z', fallback = false, gap } = {}) {
  const writers = missing ? [] : [{ lane_id: 'synthetic-source-lane', state, last_success_at: lastSuccess,
    evidence_as_of: '2026-11-05T20:59:00Z', reason }]
  globalThis.__deskWriterFixture = { data: { ok: true, data: { writers } }, loading, error: null, stale: false, refetch() {} }
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
    React.createElement(DeskPage, { title: 'Synthetic desk', purpose: 'Synthetic source evidence',
      sources: [{ id: 'fixture', label: 'Synthetic source', asOf, laneIds: ['synthetic-source-lane'], writerClockFallback: fallback, gap }],
      children: React.createElement('div', null, 'Synthetic desk content') })))
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let passed = 0, failed = 0
  function check(name, fn) {
    try { fn(); passed++; console.log(`[PASS] ${name}`) }
    catch (error) { failed++; console.log(`[FAIL] ${name}: ${error.message}`) }
  }
  const html = renderWriter('ACTIVE', { lastSuccess: '2026-11-05T19:00:00Z', reason: 'Synthetic current qualification.' })
  const diag = diagnosticsOf(html)
  const primary = text(markup(html).replace(/<details\b[\s\S]*?<\/details>/g, ''))
  check('fixture renders a nonempty real source and desk', () => assert.match(primary, /Synthetic source.*Synthetic desk content/))
  check('Diagnostics is a real closed disclosure', () => {
    assert.ok(diag, 'Diagnostics disclosure missing')
    const tag = diag.match(/^<details\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/)?.[0]
    assert.ok(tag, 'Diagnostics opening tag missing')
    assert.doesNotMatch(tag.replace(/"[^"]*"|'[^']*'/g, ''), /\sopen(?=[\s=/>])/i)
    assert.match(text(diag), /Diagnostics/)
  })
  check('last successful run remains inside Diagnostics', () => { assert.match(text(diag), /Last successful run:/); assert.doesNotMatch(primary, /Last successful run:/) })
  check('evidence capture remains inside Diagnostics', () => { assert.match(text(diag), /Evidence captured:/); assert.doesNotMatch(primary, /Evidence captured:/) })
  check('raw state remains inside Diagnostics', () => { assert.match(text(diag), /Writer state: ACTIVE/); assert.doesNotMatch(primary, /Writer state:/) })
  check('current reason survives alongside an older success', () => assert.match(text(diag), /Synthetic current qualification\./))
  check('paused consequence is primary text', () => assert.equal(primaryOf(renderWriter('PAUSED')), 'Paused — not refreshing this source'))
  check('missing writer stays unavailable with evidence explanation', () => {
    const missing = renderWriter(null, { missing: true })
    assert.equal(primaryOf(missing), 'State unavailable')
    assert.match(text(diagnosticsOf(missing)), /Execution evidence is unavailable for this writer\./)
  })
  console.log(JSON.stringify({ suite: 'deskSourceClocks.boundary', passed, failed }))
  if (failed) process.exitCode = 1
}
