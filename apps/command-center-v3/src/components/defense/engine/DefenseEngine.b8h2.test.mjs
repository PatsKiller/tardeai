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
function projection(exposure) {
  return {
    schema: 'DefenseProjection@v1', generated_at: AT,
    tier: { tier: 'YELLOW', score: 41.8, as_of: AT, ladder: [], history: [] },
    exposure, stops: {}, hedge_readiness: {}, sector_posture: {}, cash_alternatives: {},
    base_rates: {}, watch_next: {}, playbook: {}, sources: [], source_summary: null,
    narrative: { headline: 'synthetic headline', where_we_stand: [], what_to_do: [] },
  }
}

const renderView = p => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
  React.createElement(View, { p, onOpen() {} })))
const renderSheet = (p, sheet) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/v3/defense'] },
  React.createElement(EngineSheetBody, { p, sheet })))

const text = html => html.replace(/<[^>]+>/g, ' ').replace(/&[a-z#0-9]+;/gi, "'").replace(/\s+/g, ' ').trim()
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

// ── Operator directive 09:30 ET (item A): journey proof, hermetic ────────────────────────────────────────────
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

console.log(`${n} passed, ${failures.length} failed`)
if (failures.length) { console.error(failures.map(f => `${f.name}: ${f.e.stack}`).join('\n\n')); process.exit(1) }
