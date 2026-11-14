// Sprint 8H-2 slice S4, batch b1 — two Defense findings, synthetic fixtures only (the repo is public).
//
//  DR-D10  The tier chip is a dotted `Term` (a <button>) and it sat INSIDE the ladder-opening <button>: a nested
//          interactive control. The fix keeps both controls, as siblings, and this test fails if any button is
//          ever rendered inside another.
//  DR-D01  "Book in stressed groups" printed money(stressed_usd) · pct(stressed_pct_invested) from a projection
//          that publishes no status and no coverage. A missing look-through and a genuine zero therefore printed
//          the same reassurance ("$0 · 0.0% of invested"). The view now refuses to call an unmeasured book calm:
//          it prints Unknown + the coverage it does have, and only a projection that says `coverage_status:
//          'measured'` may print a measured zero — with the positions it covers.
//
// Run: node src/components/defense/engine/DefenseEngine.b8h2.test.mjs
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
  // Anchored on the import statement (identifiers such as `p.served.served_from` contain the word "from",
  // and an unanchored `from "..."` regex rewrites halves of template literals instead of module specifiers).
  js = js.replace(/^(?:import|export)[^;]*?from\s*(["'])([^"']+)\1;?/gm, (whole, quote, spec) => {
    let specifier
    if (!spec.startsWith('.')) specifier = pathToFileURL(require.resolve(spec)).href
    else {
      let target = resolve(dirname(path), spec)
      if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      specifier = compile(target)
    }
    return whole.replace(`${quote}${spec}${quote}`, JSON.stringify(specifier))
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { default: View } = await import(compile(join(app, 'src/components/defense/engine/DefenseEngine.tsx')))
const { EngineSheetBody, SHEET_TITLES } = await import(compile(join(app, 'src/components/defense/engine/DefenseEngine.tsx')))
const { defenseLines, exposureCoverage, money } = await import(compile(join(app, 'src/lib/defenseEngine.ts')))

const AT = '2031-03-07T14:59:00Z'

/** A projection with nothing but the facts each assertion needs; every other section is empty on purpose. */
function projection(exposure, extra = {}) {
  return {
    schema: 'DefenseProjection@v1', generated_at: AT,
    tier: { tier: 'YELLOW', score: 41.8, as_of: AT, ladder: [], history: [] },
    exposure, stops: {}, hedge_readiness: {}, sector_posture: {}, cash_alternatives: {},
    base_rates: {}, watch_next: {}, playbook: {}, sources: [], source_summary: null,
    narrative: { headline: 'synthetic headline', where_we_stand: [], what_to_do: [] },
    ...extra,
  }
}

const renderView = p => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
  React.createElement(View, { p, onOpen() {} })))
const renderSheet = (p, sheet) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
  React.createElement(EngineSheetBody, { p, sheet })))

const text = html => html.replace(/<[^>]+>/g, ' ').replace(/&[a-z#0-9]+;/gi, "'").replace(/\s+/g, ' ').trim()
/** From a testid to the end of the markup — for the last card in the document, whose own rows carry testids. */
const card = (html, testid) => {
  const i = html.indexOf(`data-testid="${testid}"`)
  if (i < 0) throw new Error(`no ${testid} in the rendered markup`)
  return html.slice(i)
}
/** From a testid up to the next testid (a row/block slice, for structures that are not a single button). */
const separator = (html, testid) => {
  const i = html.indexOf(`data-testid="${testid}"`)
  if (i < 0) throw new Error(`no ${testid} in the rendered markup`)
  const j = html.indexOf('data-testid=', i + 12)
  return html.slice(i, j < 0 ? undefined : j)
}
const segment = (html, testid) => {
  const i = html.indexOf(`data-testid="${testid}"`)
  if (i < 0) throw new Error(`no ${testid} in the rendered markup`)
  const end = html.indexOf('</button>', i)
  return html.slice(i, end < 0 ? undefined : end)
}

/** The deepest nesting of <button> inside <button> in a markup string; 1 means "no nesting". */
function buttonDepth(html) {
  let depth = 0, max = 0
  for (const m of html.matchAll(/<(\/?)button\b/g)) {
    depth += m[1] ? -1 : 1
    max = Math.max(max, depth)
  }
  return max
}

let n = 0
const failures = []
async function test(name, fn) {
  try { await fn(); n += 1; console.log(`ok - ${name}`) } catch (e) {
    failures.push({ name, e }); console.log(`FAIL - ${name}: ${String(e.message).split('\n')[0]}`)
  }
}

// ── DR-D10 ───────────────────────────────────────────────────────────────────────────────────────────────────
const plain = { as_of: AT, coverage_status: 'measured', positions_count: 6, mapped_count: 6, unmapped_count: 0, unmapped_usd: 0, invested_usd: 100000, stressed_usd: 0, stressed_pct_invested: 0, rows: [], unmapped: [] }

await test('DR-D10: no interactive control is rendered inside another button', () => {
  const html = renderView(projection(plain))
  assert.equal(buttonDepth(html), 1, `a <button> is nested inside another: depth ${buttonDepth(html)}`)
})

await test('DR-D10: the tier chip and the ladder opener are still both there, by name', () => {
  const html = renderView(projection(plain))
  assert.match(html, /aria-label="Open the tier ladder"/, 'the ladder opener lost its accessible name')
  assert.match(html, /aria-label="tier: definition"/, 'the tier definition control disappeared')
  // the definition control must not be a descendant of the opener
  const op = segment(html, 'defense-engine-hero')
  const opener = op.slice(op.indexOf('aria-label="Open the tier ladder"'))
  assert.ok(!/<button[^>]*aria-label="tier: definition"/.test(opener.slice(0, opener.indexOf('</div>'))),
    'the definition button still ships inside the ladder-opening button')
})

// ── DR-D01: the saved shape (no coverage published) may not read as calm ────────────────────────────────────
const saved = {
  as_of: AT, invested_usd: 100000, stressed_usd: 0, stressed_pct_invested: 0, rows: [],
  unmapped: [{ symbol: 'ZZZ', account_label: 'Acct A', usd: 40000, reason: 'not in the engine look-through' }],
}

await test('DR-D01: a projection with no coverage says Unknown, never "$0 · 0.0% of invested"', () => {
  const html = renderView(projection(saved))
  const book = text(segment(html, 'defense-line-book'))
  assert.match(book, /Unknown/, `the book line reads as a measured figure: "${book}"`)
  assert.doesNotMatch(book, /\$0/, `the book line prints a zero it cannot measure: "${book}"`)
})

await test('DR-D01: an unmapped book names what is not counted, and never sums a capped list', () => {
  // the legacy payload lists ONE unmapped position and no aggregate: the count is honest, a dollar total
  // summed from that list would not be (the server caps the list at max_rows).
  const legacy = exposureCoverage(saved)
  assert.equal(legacy.state, 'unknown')
  assert.match(legacy.detail, /1 position not mapped/, legacy.detail)
  assert.doesNotMatch(legacy.detail, /\$40/, `dollars summed from a capped list: "${legacy.detail}"`)
  // with the projection's own total, the dollars are published and printed
  const withTotal = exposureCoverage({ ...saved, unmapped_count: 3, unmapped_usd: 92500 })
  assert.match(withTotal.detail, /\$92\.5K not mapped/, withTotal.detail)
})

await test('DR-D01: a measured zero prints the coverage it rests on', () => {
  const html = renderView(projection(plain))
  const book = text(segment(html, 'defense-line-book'))
  assert.match(book, /\$0/, `measured zero should print $0: "${book}"`)
  assert.match(book, /6 of 6 positions mapped/, `measured zero must name its coverage: "${book}"`)
})

await test('DR-D01: partial coverage is not a measured zero', () => {
  const partial = { ...saved, coverage_status: 'partial', positions_count: 6, mapped_count: 4, unmapped_count: 2, unmapped_usd: 40000, look_through_basis: ['fund_holdings'] }
  const book = text(segment(renderView(projection(partial)), 'defense-line-book'))
  assert.match(book, /Unknown/, `partial coverage prints as a number: "${book}"`)
  assert.match(book, /4 of 6 positions mapped/, `partial coverage must name what it covers: "${book}"`)
  assert.doesNotMatch(book, /\$0(?!\d)/, `partial coverage prints a zero: "${book}"`)
})

await test('DR-D01 sheet: the unknown book carries a Verify exposure route, not a figure', () => {
  const html = renderSheet(projection(saved), 'exposure')
  const body = text(html)
  assert.match(body, /Unknown/, `the sheet prints a figure it cannot measure: "${body}"`)
  assert.match(body, /Verify exposure/, `the sheet offers no way to check the evidence: "${body}"`)
  assert.match(html, /\?detail=engine:sources/, 'the Verify exposure control does not open the sources sheet')
  assert.doesNotMatch(body, /\$0 · 0\.0% of invested/, `the sheet still prints the reassurance: "${body}"`)
})

await test('DR-D01 sheet: the measured book names coverage, basis and clock', () => {
  const measured = { ...plain, look_through_basis: ['fund_holdings', 'stock_sector'] }
  const body = text(renderSheet(projection(measured), 'exposure'))
  assert.match(body, /6 of 6 positions mapped/, body)
  assert.match(body, /fund_holdings, stock_sector/, `the basis is not named: "${body}"`)
  assert.match(body, /As of/, `no section clock: "${body}"`)
  assert.doesNotMatch(body, /Verify exposure/, 'a measured book should not ask to verify itself')
})

// ── F1/F2 (REVIEW-S2-defense-reentry-b1-cc-deepseek-3): an unpriced position is named, and the two Unknowns differ
await test('F1: a position with no value is named, and never counted as measured coverage', () => {
  const unpriced = { ...saved, coverage_status: 'partial', positions_count: 1, mapped_count: 1, unmapped_count: 0,
    unpriced_count: 1, unpriced_symbols: ['ZZPP'], look_through_basis: ['fund_holdings'] }
  const cov = exposureCoverage(unpriced)
  assert.equal(cov.state, 'unknown', 'an unpriced position was promoted to a measured figure')
  assert.match(cov.detail, /1 position with no value/, `the unpriced position is not named: "${cov.detail}"`)
  assert.doesNotMatch(cov.detail, /0 positions not mapped/, `an unknown value is printed as a measured zero: "${cov.detail}"`)
})

await test('F2: an empty book and an unpublished coverage are two different sentences', () => {
  const empty = exposureCoverage({ as_of: AT, coverage_status: 'unknown', positions_count: 0, mapped_count: 0,
    unmapped_count: 0, unpriced_count: 0, rows: [], unmapped: [] })
  assert.equal(empty.state, 'unknown')
  assert.match(empty.detail, /no non-cash position is on file/, `the empty book is not distinguished: "${empty.detail}"`)
  // the saved shape publishes no coverage field at all — that is a different fact, and says so
  const stale = exposureCoverage(saved)
  assert.match(stale.detail, /exposure coverage not published/, stale.detail)
  assert.doesNotMatch(stale.detail, /no non-cash position is on file/,
    `an unreadable book claims it has no positions: "${stale.detail}"`)
  // no coverage field AND no position count at all: the empty-book sentence would be a claim nothing published
  const bare = exposureCoverage({ as_of: AT })
  assert.match(bare.detail, /exposure coverage not published/, bare.detail)
  assert.doesNotMatch(bare.detail, /no non-cash position is on file/, `invented an empty book: "${bare.detail}"`)
})


// The Defense page is read-only: a journey has no persisted result, its "action" is the route-backed sheet
// (?detail=engine:<sheet>) and its "readback" is the sheet body. These pin that every action the view offers
// lands on a titled sheet that renders, that the failure state names its cause, and that the view prints the
// projection's figure rather than recomputing one (directive B: no page-specific financial recalculation).

await test('journey J1: every control the view offers opens a sheet that exists and renders', () => {
  const p = projection(plain)
  const lines = defenseLines(p)
  // the line rows and the hero are the page's actions; their targets are the SHEET_TITLES keys
  for (const l of lines) assert.ok(SHEET_TITLES[l.sheet], `line ${l.id} opens "${l.sheet}", which has no title`)
  assert.ok(SHEET_TITLES.tier, 'the ladder opener opens "tier", which has no title')
  assert.match(renderView(p), /aria-label="Open the tier ladder"/, 'no control opens the tier sheet')
  // and each targeted sheet renders content, so the action never lands on an empty screen
  for (const sheet of ['tier', 'exposure', 'sources']) {
    assert.ok(text(renderSheet(p, sheet)).length > 20, `sheet ${sheet} renders nothing`)
  }
})

await test('journey J2 (failure): a broken exposure read names its cause and is never a calm Unknown', () => {
  const broken = { as_of: null, stale_reason: 'book exposure is not joined (holdings store unreadable)', coverage_status: 'unknown', rows: [], unmapped: [] }
  const html = renderView(projection(broken))
  const book = text(segment(html, 'defense-line-book'))
  assert.match(book, /Unknown/, book)
  assert.match(book, /holdings store unreadable/, `the failure state does not name its cause: "${book}"`)
  assert.match(text(renderSheet(projection(broken), 'exposure')), /Verify exposure/, 'no recovery route from the failure state')
})

await test('journey J3: the view prints the projection figure and recomputes nothing', () => {
  // rows that sum to something else entirely: the printed figure must still be the projection's own field
  const p = projection({ ...plain, stressed_usd: 12000, stressed_pct_invested: 12, rows: [{ symbol: 'ZZAA', usd_exposed: 999999 }] })
  const book = text(segment(renderView(p), 'defense-line-book'))
  assert.match(book, new RegExp(money(12000).replace('$', '\\$')), `not the projection's figure: "${book}"`)
  assert.doesNotMatch(book, /\$1\.0M/, `the view recomputed from the rows: "${book}"`)
})

// ── DR-D03: both hedge conditions beside the verdict, and Unknown is not "Not met" ──────────────────────────
// The payload has always carried both conditions (`hedge_readiness.triggers[2]`), but the page printed only the
// first one's sentence in the line's sub, so the verdict looked like it rested on one condition. The matrix names
// condition, observed value, rule, result, source and clock, and renders an unevaluated condition as Unknown.
const HEDGE = {
  as_of: AT, readiness: 'UNKNOWN', met_count: 1, of: 2,
  triggers: [
    { id: 'exposure', label: 'Stressed groups ≥ 10% of invested', value: 3.2, threshold: 10, unit: '% of invested', met: false, detail: 'Now 3.2% (Semis, look-through)', when: 'stressed groups reach 10% of invested' },
    { id: 'breadth', label: '4 or more of 11 sectors lagging, or the shock is SYSTEMIC', value: null, threshold: 4, unit: 'sectors', met: null, detail: 'lagging count not on file', when: 'the shock turns systemic or 4 or more sectors lag' },
  ],
  inverse_triggers: { SPY: { inverse: 'SH', trigger: false, exposure_pct: 3.2 }, PSQ: { inverse: 'PSQ', trigger: null, exposure_pct: null, reason: 'trigger unknown: threshold or stressed share not on file' } },
  thesis_light: { state: 'GREEN', label: 'no thesis', as_of: AT, stale_reason: null },
  put_protection: { qqq_atm_iv: 18.4, as_of: AT, structures: 0, lifecycle: { state: 'paused', as_of: AT, stale_reason: null } },
}

await test('DR-D03: the matrix renders both conditions with their result, rule and clock', () => {
  const html = renderView(projection(plain, { hedge_readiness: HEDGE }))
  const body = text(html)
  assert.match(body, /Hedge conditions/, 'no condition matrix beside the verdict')
  const first = text(separator(html, 'hedge-condition-exposure'))
  assert.match(first, /Not met/, `an evaluated false condition must say Not met: "${first}"`)
  assert.match(first, /10% of invested/, `the rule is not named: "${first}"`)
  assert.match(first, /3\.2/, `the observed value is not shown: "${first}"`)
  const second = text(separator(html, 'hedge-condition-breadth'))
  assert.match(second, /Unknown/, `an unevaluated condition must say Unknown: "${second}"`)
  assert.doesNotMatch(second, /Not met/, `Unknown printed as Not met: "${second}"`)
  assert.match(second, /not on file/, `the reason it is unknown is not shown: "${second}"`)
})

await test('DR-D03: the verdict counts the unknowns it has, at the verdict and in the matrix', () => {
  const html = renderView(projection(plain, { hedge_readiness: HEDGE }))
  assert.match(text(segment(html, 'defense-line-hedge')), /1 of 2 met · 1 unknown/, 'the verdict hides its unknown')
  assert.match(text(card(html, 'defense-hedge-conditions')), /1 of 2 met · 1 unknown/, 'the matrix hides its unknown')
})

await test('DR-D03: inverse gates and options availability are separate evidence, each with its own state', () => {
  const body = text(card(renderView(projection(plain, { hedge_readiness: HEDGE })), 'defense-hedge-conditions'))
  assert.match(body, /SPY → SH: thesis off/, `the index gate result is missing: "${body}"`)
  assert.match(body, /PSQ → PSQ: Unknown/, `an unevaluated gate must read Unknown: "${body}"`)
  assert.match(body, /threshold or stressed share not on file/, `the gate's unknown reason is missing: "${body}"`)
  assert.match(body, /Options lifecycle: paused/, `options availability is not reported separately: "${body}"`)
})

await test('DR-D03: a stale hedge section says so in the matrix and offers the evidence route', () => {
  const stale = { ...HEDGE, as_of: null, stale_reason: 'the engine projection carries no hedge block', readiness: 'UNKNOWN' }
  const html = card(renderView(projection(plain, { hedge_readiness: stale })), 'defense-hedge-conditions')
  assert.match(text(html), /carries no hedge block/, 'a stale section renders without its reason')
  assert.match(html, /aria-label="Review hedge evidence"/, 'no action to review the hedge evidence')
})

// ── DR-D02: the protection total is decomposed, never asserted as one merged truth ─────────────────────────
// Defense printed "3 without a broker stop" (no stop + a planned level, merged), Portfolio called two
// unprotected, Risk distinguished two no-stop positions from one planned-only one. Those reconcile only if the
// total is decomposed by state; a merged label asserts one truth where the sources answer three questions. An
// unproven position (AMANX-like) is not "unprotected" either: it is unknown, and it gets a verify action.
const STOPS = {
  as_of: AT, no_stop: { count: 3, value_usd: 5000 }, planned_only: 1,
  pending: { count: 5, value_usd: 10000 }, active: 3, filled: { count: 0 }, unknown: { count: 1 },
  gaps: [{ symbol: 'NOSTOP1', account_label: 'Acct A', value_usd: 1200, state: 'no stop' }],
  near: [], near_threshold_pct: 5,
  reconciliation: {
    counted_positions: 12,
    by_state: {
      active: { count: 3, value_usd: 3000 }, pending_activation: { count: 5, value_usd: 10000 },
      planned_only: { count: 1, value_usd: 3000 }, no_stop: { count: 2, value_usd: 2000 },
      unknown: { count: 1, value_usd: 5500 }, filled: { count: 0, value_usd: 0 },
    },
    no_resting_order: { count: 3, value_usd: 5000, definition: 'no stop plus a planned level only' },
    resting_or_pending: { count: 8, value_usd: 13000 },
    excluded: { count: 2, value_usd: 942, by_reason: null, note: 'the exclusion reason is not published in the stop rows' },
    partial_quantities: { known: false, reason: 'the stops slice carries no resting-stop quantity' },
    coverage: 'measured',
  },
  unknown_rows: [{ symbol: 'FUNDX', account_label: 'Acct B', value_usd: 5500, state: 'UNKNOWN', cause: 'No Stop Read',
    reason: 'No stop read source for this broker; protection cannot be verified' }],
}

await test('DR-D02: the stop line decomposes the total instead of merging no-stop with planned-only', () => {
  const html = renderView(projection(plain, { stops: STOPS }))
  const sub = text(segment(html, 'defense-line-stops'))
  assert.match(sub, /2 no stop/, `the definite no-stop count is missing: "${sub}"`)
  assert.match(sub, /1 planned only/, `the planned-only position is merged away: "${sub}"`)
  assert.match(sub, /8 resting or pending/, `the resting/pending population is missing: "${sub}"`)
  assert.match(sub, /12 counted/, `the reconciliation has no denominator: "${sub}"`)
})

await test('DR-D02 sheet: the reconciliation names every state, the exclusions and the unknown position', () => {
  const html = renderSheet(projection(plain, { stops: STOPS }), 'stops')
  const body = text(html)
  assert.match(body, /Protection reconciliation/, 'no reconciliation block')
  assert.match(body, /12 counted positions/, `no denominator: "${body}"`)
  assert.match(body, /8 resting or pending/, 'the resting/pending population is missing')
  assert.match(body, /3 no resting broker order/, 'the merged figure is not named for what it is')
  assert.match(body, /1 planned level only/, 'a planned level is not kept as its own field')
  assert.match(body, /2 excluded from the count/, 'the under-$100/policy exclusions are invisible')
  assert.match(body, /\$942/, 'the excluded value is missing')
  assert.match(body, /not published/, 'partial quantities are silently omitted')
  assert.match(body, /FUNDX/, 'the unproven position is not listed')
  assert.match(body, /No Stop Read/, 'the unproven position prints without its cause')
  assert.match(body, /Verify broker evidence/, 'the unproven position has no way to verify it')
  assert.match(html, /\?detail=engine:sources/, 'Verify broker evidence does not open the sources sheet')
})

await test('DR-D02 sheet: a resting pending stop is never described as active', () => {
  const body = text(renderSheet(projection(plain, { stops: STOPS }), 'stops'))
  assert.match(body, /Pending activation/, 'the pending population is not named')
  assert.doesNotMatch(body, /5 active/, `a pending stop is described as active: "${body}"`)
})

console.log(`${n} passed, ${failures.length} failed`)
if (failures.length) { console.error(failures.map(f => `${f.name}: ${f.e.stack}`).join('\n\n')); process.exit(1) }
