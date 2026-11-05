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

// Pagination-aware, because the decisive interaction happens on page 2: Beta is only on page 2, Alpha only on page 1.
// A constant fixture cannot show a selection that moved the operator to the wrong page — that was R2's whole point.
const pageOne = [cards[0], { symbol: 'ZZZ', company: 'Zeta Labs', trade_ai_state: 'WAIT', last: 5.5, day_change_pct: 0.4,
  decision: { category: 'review', category_label: 'Review', status: 'active' } }]
const pageTwo = [cards[1], { symbol: 'CCC', company: 'Corvus Energy', trade_ai_state: 'AVOID', last: 8.75,
  day_change_pct: -1.1, decision: { category: 'avoid', category_label: 'Avoid', status: 'active' } }]
// FQ-132 F2: the exact card cx-openai-3 replayed — a "High Conviction Opportunity" whose own status is expired and
// whose quote is STALE. Every number on it was true and the row still read as a live idea.
const stateCards = {
  3: [{ symbol: 'OLDY', company: 'Old Signal Corp', trade_ai_state: 'WAIT', last: 22.25, day_change_pct: -3.4,
    quote_freshness: 'STALE',
    decision: { category: 'high_conviction_opportunity', category_label: 'High Conviction Opportunity', status: 'expired' } }],
  4: [{ symbol: 'NEED', company: 'Needs Data Ltd', trade_ai_state: 'WAIT', last: 12, day_change_pct: 0.2,
    quote_freshness: 'CURRENT',
    decision: { category: 'high_conviction_opportunity', category_label: 'High Conviction Opportunity', status: 'needs_data' } }],
  5: [{ symbol: 'GONE', company: 'Invalidated Inc', trade_ai_state: 'AVOID', last: 9, day_change_pct: -2,
    quote_freshness: 'CURRENT', decision: { category: 'avoid', category_label: 'Avoid', status: 'invalidated' } }],
  6: [{ symbol: 'NOQT', company: 'No Quote Co', trade_ai_state: 'WAIT', last: 31, day_change_pct: 0.1,
    quote_freshness: 'DATA_UNAVAILABLE',
    decision: { category: 'review', category_label: 'Review', status: 'active' } }],
}
const requests = []

globalThis.__apiFixture = (url) => {
  if (url.includes('watch-intelligence')) {
    requests.push(url)
    const page = (url.match(/[?&]page=(\d+)/) || [])[1] || '1'
    const list = stateCards[page] || (page === '2' ? pageTwo : pageOne)
    return { data: { cards: list, summary: {}, counts: {}, data_quality: { status: 'OK' } }, loading: false, error: null }
  }
  if (url.includes('watch-filters')) return { data: { views: {}, trade_ai_states: ['WAIT', 'AVOID'] }, loading: false, error: null }
  if (url.includes('data-broker')) return { data: { projections: {} }, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))
const { withDetail } = await import(compile(join(app, 'src/lib/watchDetailEntry.ts')))

function render(path) {
  globalThis.__entry = path
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [path] }, React.createElement(Page)))
}

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('compact layout renders one scan row per name', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  const rows = html.match(/data-compact-row/g) || []
  assert.equal(rows.length, pageOne.length, `expected ${pageOne.length} compact rows, got ${rows.length}`)
  for (const c of pageOne) assert.ok(html.includes(c.symbol), `missing ${c.symbol}`)
})

check('the row carries the decision category and the money, not the long card sections', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  // The claim is about the ROW. Scoped to the list, not the page: the reading view beside it is allowed to have the
  // review boxes — that is what it is for.
  const list = html.slice(html.indexOf('data-compact-list'), html.indexOf('data-intelligence-inspector'))
  assert.match(list, /High Conviction Opportunity/)
  assert.match(list, /\$10\.50/)
  assert.doesNotMatch(list, /data-review-box/, 'the compact row rendered the review box')
})

// FQ-132 (cx-openai-3 at 234248492): the case here used to assert `role="button" … data-compact-row`, which passed
// while the rendered page had no reading view at all — a compact row selected a name and put nothing on the screen.
// These are rendered assertions: they read the markup that reaches the operator, and each one fails on the old page.
const inspector = (html) => {
  const at = html.indexOf('data-intelligence-inspector')
  return at === -1 ? '' : html.slice(at)
}

check('a compact row opens the reading view on the page', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact')
  assert.match(inspector(html), /WHAT THE COMPANY DOES/, 'compact rendered no reading view: no detail panel is on the page')
})

check('the reading view shows the chosen name, not the first card', () => {
  const html = render('/watch?tab=intelligence&view=top_ideas&layout=compact&detail=ZZZ')
  const panel = inspector(html)
  assert.match(panel, /Zeta Labs/, 'the selected row did not fill the reading view')
  assert.doesNotMatch(panel, /Alpha Holdings/, 'the reading view kept the first card instead of the selected one')
})

// FQ-132 R2 (cx-openai-3 at c3ea49812): selecting a row used the FILTER setter, which resets `page` to 1 for every key
// but `page`. From page 2 that sent the page to `page=1&detail=BBB`, page 1 does not contain BBB, and the inspector fell
// back to its first card: the operator clicked Beta and read Alpha. This runs the page's OWN callback, extracted from
// the source and evaluated with the real rule for the filter setter, then renders the URL it produces.
const pageSource = readFileSync(join(app, 'src/pages/WatchIntelligenceUnified.tsx'), 'utf8')
function chooseRow(sp, symbol) {
  const line = (pageSource.match(/const setSelected = [^\n]*/) || [])[0]
  assert.ok(line, 'the selection callback is gone from the page')
  const compiled = ts.transpileModule(line, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  const navigations = []
  const setSp = (params) => navigations.push(new URLSearchParams(params))
  const phone = { mobile: false, id: null, open() {}, close() {} }
  // The real filter setter's rule, verbatim: change one key, and reset the page unless that key was `page`.
  const setParam = (key, value) => {
    const next = new URLSearchParams(sp)
    if (!value) next.delete(key)
    else next.set(key, value)
    if (key !== 'page') next.set('page', '1')
    setSp(next)
  }
  const run = new Function('phone', 'setSp', 'sp', 'withDetail', 'setParam', `${compiled}\nreturn setSelected`)
  run(phone, setSp, sp, withDetail, setParam)(symbol)
  assert.equal(navigations.length, 1, 'the row click did not navigate')
  return navigations[0]
}

const startOnPageTwo = () => new URLSearchParams('tab=intelligence&view=top_ideas&layout=compact&page=2')

check('choosing a row keeps the page the operator was on', () => {
  const target = chooseRow(startOnPageTwo(), 'BBB')
  assert.equal(target.get('page'), '2', 'selecting a name reset the page')
  assert.equal(target.get('detail'), 'BBB')
})

check('the row the operator chose is the one that renders, on the page they were on', () => {
  const target = chooseRow(startOnPageTwo(), 'BBB')
  requests.length = 0
  const html = render(`/watch?${target.toString()}`)
  assert.ok(requests.some(u => /[?&]page=2(&|$)/.test(u)), `the page did not request page 2 after a selection: ${requests[0] || 'no request'}`)
  const panel = inspector(html)
  assert.match(panel, /Beta Industrials/, 'the reading view did not show the name the operator clicked')
  assert.doesNotMatch(panel, /Alpha Holdings/, 'the reading view fell back to page 1\'s first card')
})

// FQ-132 F2 (cx-openai-3 at c3ea49812): the compact row rendered the historical CATEGORY and the money while the
// decision's own status and the quote's state were invisible — and the opened sheet carried neither. These cases read
// the visible words in the row and in the reading view, and the counter-case keeps a healthy row one line short.
const rowOf = (html) => html.slice(html.indexOf('data-compact-row'), html.indexOf('data-intelligence-inspector'))

check('an expired decision with a STALE quote says so, next to its category, in the row', () => {
  const row = rowOf(render('/watch?tab=intelligence&view=top_ideas&layout=compact&page=3'))
  assert.match(row, /Signal expired/, 'the row still hides an expired decision behind its category')
  assert.match(row, /Quote stale/, 'the row still hides a stale quote')
  assert.match(row, /High Conviction Opportunity/, 'the category was replaced instead of annotated')
  assert.match(row, /\$22\.25/, 'the price disappeared')
})

for (const [page, words] of [['4', 'Needs fresh analysis'], ['5', 'Invalidated'], ['6', 'Quote unavailable']]) {
  check(`a non-current state on page ${page} is spelled out: ${words}`, () => {
    const row = rowOf(render(`/watch?tab=intelligence&view=top_ideas&layout=compact&page=${page}`))
    assert.ok(row.includes(words), `the row does not say "${words}"`)
  })
}

check('a current card keeps one short line and no warning text', () => {
  const row = rowOf(render('/watch?tab=intelligence&view=top_ideas&layout=compact'))
  assert.doesNotMatch(row, /data-compact-row-state/, 'a healthy row grew a warning line')
  assert.doesNotMatch(row, /Signal expired|Quote stale|Needs fresh analysis|Invalidated/)
})

check('the reading view carries the same state the row does', () => {
  const panel = inspector(render('/watch?tab=intelligence&view=top_ideas&layout=compact&page=3&detail=OLDY'))
  assert.match(panel, /Old Signal Corp/, 'the selected name did not open')
  assert.match(panel, /Signal expired/, 'the sheet/inspector hides an expired decision')
  assert.match(panel, /Quote stale/, 'the sheet/inspector hides a stale quote')
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
