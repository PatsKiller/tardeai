// LQ-20261113-3100 (A06): the CIO card's catalyst row is never blank and never invented. Render test (SSR, no DOM).
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

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = globalThis.window || {}
globalThis.window.matchMedia = globalThis.window.matchMedia || (q => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
globalThis.window.location = globalThis.window.location || { origin: 'http://localhost:4173', pathname: '/v3/home', search: '', hash: '' }
globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
globalThis.document = globalThis.document || { documentElement: { style: {} }, body: { style: {} },
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (spec.endsWith('.css')) return 'from "data:text/javascript,export default {}"'
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

const T = '2031-03-13T20:00:00Z'
const fact = (value) => ({ value, source_id: 'synthetic', as_of: T })
const { default: Card } = await import(compile(join(app, 'src/components/home/CioCardV5.tsx')))
const NOW = Date.parse('2031-03-13T21:00:00Z')
const render = (card) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/home'] },
  React.createElement(Card, { card: { tier: fact('YELLOW'), score: fact(40), ...card }, adviceOk: true, nowMs: NOW })))
const text = (s) => s.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')
const row = (html) => (html.split('data-testid="cio5-catalyst"')[1] || '').split('data-testid=')[0]

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('the live record (no label) names the event, date and time; the row is not blank', () => {
  const r = text(row(render({ catalyst: { event: 'Advance Retail Sales', date: '2031-03-17', time_et: '08:30', source_id: 'cio_synopsis:x', as_of: T } })))
  assert.match(r, /Next catalyst: Advance Retail Sales · 2031-03-17 08:30 ET/)
  assert.doesNotMatch(r, /Next catalyst:\s*(T|$)/)
})
check('no event, none qualified: the row says none scheduled with the reason and as-of', () => {
  const html = render({ catalyst_state: { state: 'NONE', reason: 'no macro event is dated today or later', as_of: T } })
  const r = text(row(html))
  assert.match(r, /none scheduled/)
  assert.match(r, /no macro event is dated today or later/)
  assert.match(r, /as of/)
  assert.ok(html.includes('data-catalyst-state="NONE"'))
})
check('calendar unreadable: UNKNOWN with the reason', () => {
  const html = render({ catalyst_state: { state: 'UNKNOWN', reason: 'the synopsis carries no macro calendar', as_of: T } })
  assert.match(text(row(html)), /UNKNOWN.*no macro calendar/)
  assert.ok(html.includes('data-catalyst-state="UNKNOWN"'))
})
check('an older server with neither field still draws an UNKNOWN row, never nothing', () => {
  const html = render({})
  assert.ok(html.includes('data-testid="cio5-catalyst"'))
  assert.match(text(row(html)), /UNKNOWN/)
})

let failed = 0
for (const c of cases) {
  try { await c.fn(); console.log(`  [PASS] ${c.name}`) } catch (e) { failed++; console.log(`  [FAIL] ${c.name}\n    ${e.message}`) }
}
console.log(`cioCatalystRow.view.test.mjs: ${cases.length - failed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
