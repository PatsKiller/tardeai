// C-PERF-A: compile and render the actual page. Synthetic props only; no server or live data.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const APP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const GATE_CACHE = path.join(APP, 'node_modules/.cache/wealth-gate-tests')
let gateModules = null
function compileGateModules() {
  if (gateModules !== null) return gateModules
  fs.mkdirSync(GATE_CACHE, { recursive: true })
  const out = fs.mkdtempSync(path.join(GATE_CACHE, 'performance-'))
  const cssDecl = path.join(out, 'css-modules.d.ts')
  fs.writeFileSync(cssDecl, "declare module '*.css'\n")
  const args = [
    '--target', 'ES2020', '--module', 'commonjs', '--moduleResolution', 'node', '--strict', '--skipLibCheck',
    '--allowImportingTsExtensions', '--rewriteRelativeImportExtensions', '--jsx', 'react-jsx',
    '--typeRoots', path.join(APP, 'node_modules/@types'), '--types', 'node', '--outDir', out,
    path.join(APP, 'src/pages/portfolio/PerformancePage.tsx'),
    path.join(APP, 'src/pages/portfolio/performanceView.ts'), cssDecl,
  ]
  const r = spawnSync(process.execPath, [path.join(APP, 'node_modules/typescript/bin/tsc'), ...args], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error(`tsc could not compile performance gate modules (rc ${r.status}):\n${r.stdout ?? ''}${r.stderr ?? ''}`)
  fs.writeFileSync(path.join(out, 'package.json'), '{"type":"commonjs"}')
  process.once('exit', () => fs.rmSync(out, { recursive: true, force: true }))
  // Same asset loader as shell-logic.test.mjs: CSS is not bundled by tsc.
  const cssOut = path.join(out, 'pages/portfolio')
  fs.mkdirSync(cssOut, { recursive: true })
  fs.writeFileSync(path.join(cssOut, 'semantic.css'), '')
  const load = createRequire(import.meta.url)
  load.extensions['.css'] = () => {}
  gateModules = {
    page: load(path.join(out, 'pages/portfolio/PerformancePage.js')),
    view: load(path.join(out, 'pages/portfolio/performanceView.js')),
  }
  return gateModules
}

function fixture() { return structuredClone(compileGateModules().view.SYNTHETIC_PERFORMANCE_PROPS) }
function render(props = fixture()) {
  return renderToStaticMarkup(React.createElement(compileGateModules().page.PerformancePage, props))
}
function household(html) { return html.split('<div data-performance-accounts="true">')[0] }
function accounts(html) { return html.split('<div data-performance-accounts="true">')[1] ?? '' }
function justMeasure(measure) {
  const props = fixture()
  props.accounts = [{ key: 'synthetic-only', label: 'Account A', scopeNote: 'Synthetic', periods: {} }]
  props.household = { '1W': { observation: measure, estimate: null } }
  return household(render(props))
}

test('performance renders all seven literal windows, with no calendar-period substitutions', () => {
  const html = render()
  for (const label of ['Latest session', '1W', '1M', '3M', '6M', 'YTD', '1Y']) assert.ok(html.includes(`<h3>${label}</h3>`), label)
  assert.doesNotMatch(html, /\b(?:WTD|MTD|QTD)\b/)
})

test('performance null amount and percent show the specific history gap, never zero', () => {
  const measure = fixture().household['6M'].observation
  const html = justMeasure(measure)
  assert.match(html, /Unknown — insufficient history/)
  assert.doesNotMatch(html, /0\.00%|\$0\.00/)
  assert.match(html, /class="money-unknown">Unknown — insufficient history/)
})

test('performance numeric zero is a measured neutral 0.00%, including negative zero', () => {
  const measure = fixture().household['3M'].observation
  measure.percent.value = -0
  const html = justMeasure(measure)
  assert.match(html, /class="money-unknown">0\.00%/)
  assert.match(html, /class="money-unknown">\$0\.00/)
  assert.doesNotMatch(html, /class="(?:money-gain|money-loss)">|[-+]0\.00%/)
})

test('performance reliable positive and negative signs use the shared green and red classes', () => {
  const gain = fixture().household['1W'].observation
  const loss = fixture().household['1M'].observation
  gain.coverage = loss.coverage = { included: 3, total: 3 }
  assert.match(justMeasure(gain), /class="money-gain">\+2\.00%/)
  assert.match(justMeasure(loss), /class="money-loss">-1\.00%/)
})

for (const qualifier of ['partial', 'estimated', 'stale']) {
  test(`performance ${qualifier} is amber with a textual warning; zero and missing stay neutral`, () => {
    const measure = fixture().household['1W'].observation
    measure.qualifiers = [qualifier]
    measure.amount.value = 0
    let html = justMeasure(measure)
    assert.match(html, /class="text-warn">\+2\.00%/)
    assert.match(html, /class="money-unknown">\$0\.00/)
    assert.ok(html.includes(qualifier))
    measure.percent.value = null
    html = justMeasure(measure)
    assert.match(html, /class="money-unknown">Unknown/)
  })
}

test('performance household estimate is explicit, alongside raw NAV, and never repeated in account rows', () => {
  const html = render()
  assert.match(household(html), /Approximate household estimate/)
  assert.match(household(html), /Household only; not individual account profit/)
  assert.match(household(html), /Household residual approximation; external flows are not reconciled/)
  assert.match(household(html), /Raw NAV change — includes deposits\/withdrawals/)
  assert.doesNotMatch(accounts(html), /Approximate household estimate|household-estimate|Household residual/)
})

test('performance untyped household residual injected into an account is refused at render time', () => {
  const props = fixture()
  props.accounts[0].periods['1W'] = { ...props.household['1W'].estimate,
    amount: { value: 900, unknownReason: null }, percent: { value: 90, unknownReason: null } }
  const html = accounts(render(props))
  assert.match(html, /Unknown — account measure not served — owner: Performance source team/)
  assert.doesNotMatch(html, /900\.00|90\.00%|Approximate household estimate/)
})

test('performance coverage, scope, source, age, method and actual bounds render as supplied', () => {
  const html = justMeasure(fixture().household['1W'].observation)
  assert.match(html, /Coverage: 2 of 3 accounts/)
  assert.match(html, /Scope: Household/)
  assert.match(html, /Raw NAV change — includes deposits\/withdrawals/)
  assert.match(html, /Synthetic NAV observations · owner: Performance source team/)
  assert.match(html, /as of 2040-06-01T16:00:00Z · 60 s old/)
  assert.match(html, /Actual start: 2040-05-25T16:00:00Z · Actual end: 2040-06-01T16:00:00Z/)
})

test('performance missing attributed session is explicit even when a source clock exists', () => {
  const html = household(render())
  assert.match(html, /Estimated price movement of current holdings/)
  assert.match(html, /Attributed session unknown/)
  assert.doesNotMatch(html, /Attributed session: 2040-06-01/)
})

test('performance YTD retains its separate pin clock, age, source and calendar-year meaning', () => {
  const html = household(render())
  assert.match(html, /YTD pin:/)
  assert.match(html, /24\.0 h old/)
  assert.match(html, /Calendar year to date/)
  assert.match(html, /Synthetic pinned snapshot A; pin source: synthetic NAV observations/)
})

test('performance empty selection explains the next step and suppresses unrelated household values', () => {
  const props = fixture()
  props.accounts = []
  const html = render(props)
  assert.match(html, /data-performance-state="empty"/)
  assert.match(html, /No accounts in this view\. Choose an account scope with available history/)
  assert.doesNotMatch(html, /\+2\.00%|Approximate household estimate/)
})

test('performance all-unknown is distinct from empty and keeps every window and gap owner', () => {
  const props = fixture()
  props.household = {}
  props.accounts = [{ ...props.accounts[0], periods: {} }]
  const html = render(props)
  assert.match(html, /data-performance-state="unknown"/)
  assert.match(html, /All performance measures are unknown/)
  assert.match(html, /not served — owner: Performance source team/)
  assert.match(html, /<h3>1Y<\/h3>/)
  assert.doesNotMatch(html, /0\.00%/)
})

test('performance partial view explains qualifications without declaring reconciled profit', () => {
  const html = render()
  assert.match(html, /data-performance-state="partial"/)
  assert.match(html, /Partial performance view/)
  assert.match(html, /some measures are estimated, stale or unavailable/)
  assert.doesNotMatch(html, /verified return|verified daily|paid income/i)
})

test('performance amounts and percentages remain independently unknown; no back-solving', () => {
  const measure = fixture().household['1W'].observation
  measure.amount = { value: null, unknownReason: 'raw amount not served — owner: NAV source team' }
  let html = justMeasure(measure)
  assert.match(html, /Unknown — raw amount not served — owner: NAV source team/)
  assert.match(html, /\+2\.00%/)
  measure.amount.value = 100
  measure.percent = { value: null, unknownReason: 'opening value not served — owner: NAV source team' }
  html = justMeasure(measure)
  assert.match(html, /\+\$100\.00/)
  assert.match(html, /Unknown — opening value not served — owner: NAV source team/)
})

test('performance invalid numbers are unknown, not NaN, Infinity or numeric-string values', () => {
  for (const value of [NaN, Infinity, -Infinity, '2']) {
    const measure = fixture().household['1W'].observation
    measure.percent = { value, unknownReason: null }
    const html = justMeasure(measure)
    assert.match(html, /Unknown — not served — owner: Performance source team/)
    assert.doesNotMatch(html, /NaN%|Infinity%|\+2\.00%/)
  }
})

test('performance account display mapping never falls back to the raw key', () => {
  const props = fixture()
  props.accounts[0].key = 'synthetic-private-key'
  for (const label of [null, '', 'synthetic-private-key']) {
    props.accounts[0].label = label
    const html = accounts(render(props))
    assert.match(html, /Account label not served/)
    assert.doesNotMatch(html, /synthetic-private-key/)
  }
  props.accounts[0].label = 'Account A'
  assert.match(accounts(render(props)), /<h2>Account A<\/h2>/)
})

test('performance missing account period cannot inherit the household result or another window', () => {
  const props = fixture()
  props.accounts = [{ ...props.accounts[0], periods: {} }]
  const html = accounts(render(props))
  assert.match(html, /not served — owner: Performance source team/)
  assert.doesNotMatch(html, /\+2\.00%|\+\$200\.00|0\.00%/)
})

test('performance unproven clocks and coverage stay explicit and withdraw directional colour', () => {
  const measure = fixture().household['1W'].observation
  measure.clocks = []
  measure.coverage = { included: null, total: null }
  let html = justMeasure(measure)
  assert.match(html, /Source clock and age unknown — owner: Performance source team/)
  assert.match(html, /Account coverage unknown — owner: Performance source team/)
  assert.match(html, /class="text-warn">\+2\.00%/)
  measure.clocks = [{ label: 'NAV', asOf: null, ageSeconds: null, freshness: 'fresh' }]
  html = justMeasure(measure)
  assert.match(html, /age unknown/)
  assert.match(html, /freshness unknown/)
  assert.doesNotMatch(html, /source reports fresh/)
})

test('performance props render without a network request or automatic synthetic default', () => {
  const previous = globalThis.fetch
  let calls = 0
  globalThis.fetch = () => { calls++; throw new Error('Network forbidden in presentational page') }
  try {
    const html = render({ accounts: [], household: {}, gapOwner: 'Synthetic owner' })
    assert.equal(calls, 0)
    assert.doesNotMatch(html, /Synthetic NAV observations|Account A|2040-06-01/)
  } finally { globalThis.fetch = previous }
})


test('performance incomplete account coverage is amber even without an explicit partial qualifier', () => {
  const html = justMeasure(fixture().household['1W'].observation)
  assert.match(html, /class="text-warn">\+2\.00%/)
  assert.match(html, /! partial/)
})

test('performance invalid or unzoned source timestamps cannot claim fresh directional values', () => {
  for (const asOf of ['not-a-clock', '2040-06-01T16:00:00']) {
    const measure = fixture().household['1W'].observation
    measure.coverage = { included: 3, total: 3 }
    measure.clocks[0].asOf = asOf
    const html = justMeasure(measure)
    assert.match(html, /freshness unknown/)
    assert.match(html, /class="text-warn">\+2\.00%/)
    assert.doesNotMatch(html, /source reports fresh|class="money-gain">/)
  }
})

// C-PERF-B regressions: source selection on the actual presenter.
test('C-PERF-B leaves the single page H1 to the shell', () => {
  assert.doesNotMatch(render(), /<h1[ >]/)
})
test('C-PERF-B selected period renders only that interval with served choices', () => {
  const p = fixture()
  p.availablePeriods = ['1W', 'YTD']; p.selectedPeriod = '1W'
  const html = render(p)
  assert.match(html, /aria-label="Performance period"/)
  assert.match(html, /value="1W"/); assert.match(html, /value="YTD"/)
  assert.doesNotMatch(html, /value="1M"|<h3>YTD<\/h3>|<h3>Latest session<\/h3>/)
  assert.match(html, /<h3>1W<\/h3>/)
})
test('C-PERF-B places source provenance inside a closed evidence disclosure', () => {
  assert.match(render(), /<details><summary>Method &amp; interval details<\/summary><div class="performance-provenance"/)
})

test('C-PERF-B repeats an identical missing-number reason only once per measure', () => {
  const html = justMeasure(fixture().household['6M'].observation)
  assert.equal((html.match(/Unknown — insufficient history/g) ?? []).length, 1)
})
