// FQ-073 — the phone watchlist opens on compact scan rows; the full reading view is one tap away.
//
// The audit: each name rendered evidence, ownership and review sections before the next name, so the list needed
// substantial scrolling to scan. This pins the compact layout (reachable by ?layout=compact and the phone default):
// one 48 px row per name with the symbol, the decision category, the price and the day move — and none of the card's
// long sections, which remain in the full-screen sheet the row opens.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

// Server rendering of this page emits a React warning with a multi-megabyte stack trace per render; the warning is
// about a client-only layout effect and is not what this test measures. Suppress exactly that one message.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

// The page touches window at module scope (FQDN, the mobile media query). Server rendering has none.
globalThis.window = globalThis.window || {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  location: { origin: 'http://localhost:4173', pathname: '/v3/watch', search: '', hash: '', href: 'http://localhost:4173/v3/watch' },
  addEventListener() {}, removeEventListener() {}, scrollTo() {},
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
}
globalThis.document = globalThis.document || { documentElement: { style: {} }, addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__apiFixture(String(_args[0] ?? \'\'), _args)',
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

const cards = [
  { symbol: 'AAA', company: 'Alpha Holdings', trade_ai_state: 'WAIT', street_rating: 'HOLD', last: 10.5,
    day_change_pct: 1.2, held: true, decision: { category: 'high_conviction_opportunity', category_label: 'High Conviction Opportunity', status: 'active', priority: 'high', actionable: true, action_hint: 'Review entry' } },
  { symbol: 'BBB', company: 'Beta Industrials', trade_ai_state: 'AVOID', street_rating: 'SELL', last: 22.25,
    day_change_pct: -3.4, decision: { category: 'avoid', category_label: 'Avoid', status: 'active' } },
]

globalThis.__apiFixture = (url) => {
  if (url.includes('watch-intelligence')) return { data: { cards, summary: {}, counts: {}, data_quality: { status: 'OK' } }, loading: false, error: null }
  if (url.includes('watch-filters')) return { data: { views: {}, trade_ai_states: ['WAIT', 'AVOID'] }, loading: false, error: null }
  if (url.includes('data-broker')) return { data: { projections: {} }, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

function render(path) {
  globalThis.__entry = path
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [path] }, React.createElement(Page)))
}

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('compact layout renders one scan row per name', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  const rows = html.match(/data-compact-row/g) || []
  assert.equal(rows.length, cards.length, `expected ${cards.length} compact rows, got ${rows.length}`)
  for (const s of ['AAA', 'BBB']) assert.ok(html.includes(s), `missing ${s}`)
})

check('the row carries the decision category and the money, not the long card sections', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  assert.match(html, /High Conviction Opportunity/)
  assert.match(html, /\$10\.50/)
  assert.doesNotMatch(html, /data-review-box/, 'the compact row rendered the review box')
})

check('the row opens the full reading view', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  assert.match(html, /role="button"[^>]*data-compact-row/)
})

check('the raw Trade AI code is not the row text — it is the tooltip', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  const row = (html.match(/<span title="Trade AI state: WAIT"[^>]*>[^<]*</) || [''])[0]
  assert.ok(row.length > 0, 'the state is not carried as a tooltip')
})

check('grid is still the desktop default', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas')
  assert.equal(html.match(/data-compact-row/g), null, 'grid fell through to compact')
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)
