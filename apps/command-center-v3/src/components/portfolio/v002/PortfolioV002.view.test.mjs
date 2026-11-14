// Portfolio v002 (design/pages/portfolio/v002, operator-approved 2026-11-11) — what the page draws.
// Pins: UNKNOWN rows never read NO STOP; a failed/timed-out read shows TIMED OUT / UNKNOWN and "review count ?", never "0 positions";
// gates are NEEDS BACKEND, never "0 open"; a fully protected book collapses Action·Protection to CLEAR.
// 2026-11-14 campaign: the four measures come only from PortfolioMeasures@v1 (measure 4 UNKNOWN with its cause, the
// Finviz mark a separate estimate beside the anchor), stop coverage is drawn in its six categories with resting vs
// held shares, the stop link carries full identity, the risk score is an isolated pending decision, and the six
// subnav desks keep their deep links.
// Synthetic fixtures only (public repo). Same harness as the Home v010 view test.
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
  // The sheets' `import '../../home/v010'` is a side-effect CSS load; the shell markup is local. Drop it so the
  // harness never has to resolve a directory index.
  js = js.replace(/import\s+['"][^'"]*home\/v010['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
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

const lib = await import(compile(join(app, 'src/lib/portfolioV002.ts')))
const { default: View } = await import(compile(join(app, 'src/components/portfolio/v002/PortfolioV002View.tsx')))
const sheets = await import(compile(join(app, 'src/components/portfolio/v002/PortfolioSheets.tsx')))
const { positionsFrom, protectionModel, p0Items, statusRows, measuresModel, sinceVisitModel, STOP_READ_MAX_AGE_MS, API, filterPositions, exclusiveCoverage } = lib

const NOW = Date.parse('2031-03-07T15:00:00Z')
const AT = '2031-03-07T14:59:00Z'
const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const fail = (source, state = 'UNKNOWN') => ({ state, data: null, error: 'HTTP 503', at: AT, source })
const row = o => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', broker: 'broker_a', shares: 10, market_value: 1000,
  price: 100, price_as_of: AT, protection_state: 'PROTECTED', protection: { state: 'PROTECTED', source: 'stop store', as_of: AT, counted: true },
  stop_price: 90, stop_qty: 10, ...o })
const wire = (rows, extra = {}) => ({ holdings: rows, total_value: 9999, today_change: 5, positions_as_of: AT, valuation_as_of: AT, quote_as_of: AT,
  position_counts: { agree: true }, ...extra })
const noop = () => {}
const LAST_SEEN_UNKNOWN = { state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source: API.lastSeen }

const MEASURES = {
  contract_version: 'PortfolioMeasures@v1', materialized: true, as_of: AT, generated_at: AT,
  basis: { applied: 'broker_positions_store', why: 'broker values are the accounting anchor' },
  finviz_estimates_are_separate: true,
  measures: {
    account_value: { label: 'Account value', value: 1252980.85, status: 'MEASURED', as_of: AT, rows: 31,
      finviz_estimate: { label: 'Finviz mark estimate', value: 1255586.37, delta: -2605.52, marks_at: AT, note: 'a mark difference is not a move and not P&L' } },
    price_move_estimate: { label: 'Estimated price movement of current holdings', value: -1836.58, status: 'PARTIAL', as_of: AT,
      coverage: { measured_rows: 28, unknown_rows: 1, row_count: 29 }, gap: { reason: 'one row has no prior-close baseline' } },
    account_value_change_1d: { label: 'Account value change since prior close', value: -5020.07, status: 'MEASURED', as_of: AT,
      start: { equity_usd: 1258000.92, as_of: AT }, end: { equity_usd: 1252980.85, as_of: AT },
      drill_down: { price_move_estimate: -4467.14, closed_today_trade_effect: -552.93, fees_today: 0.47, income_today: 0, external_flows_today: 0, reconciles: true } },
    verified_daily_pnl: { label: 'Verified daily P&L', value: null, status: 'UNKNOWN', candidate: -5020.07,
      gap: { reason: 'no stored verified reconciliation exists', requires: 'stored signed per-account reconciliation' },
      known_components: { price_move_estimate: -4467.14, closed_today_trade_effect: -552.93, fees_today: 0.47, income_today: null, external_flows_today: null } },
  },
}

function render(holdings, incidents = ok(API.incidents, { counts: { P0: 0, P1: 0 }, served_at: AT }), lastSeen = LAST_SEEN_UNKNOWN, shownCount = 25) {
  // The harness pins one clock (NOW); the page itself passes the wall clock, which is correct in production.
  const positions = holdings.state === 'OK' ? positionsFrom(holdings.data, NOW) : []
  const prot = protectionModel(holdings, positions)
  const props = { holdings, positions, prot, p0: p0Items(holdings, prot), status: statusRows(holdings, incidents, positions, NOW),
    measures: measuresModel(holdings), sinceVisit: sinceVisitModel(lastSeen), visitRecord: 'PENDING',
    nowIso: new Date(NOW).toISOString(), filter: 'all', account: 'all', shownCount, showAllAction: false,
    onFilter: noop, onAccount: noop, onShowMore: noop, onShowAllAction: noop, onOpenWhy: noop, onOpenDiag: noop, onOpenAudit: noop,
    onOpenPosition: noop, onOpenMeasures: noop, onOpenMeasure: noop, onOpenGates: noop, onOpenSince: noop, onOpenSync: noop,
    onOpenRisk: noop, onExportCsv: noop }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(View, props)))
}
const sheet = (Comp, props) => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Comp, { open: true, onClose: noop, ...props })))
const chipP0 = html => {
  const m = html.match(/<button[^>]*data-testid="chip-p0"[^>]*>([^<]*)</) || html.match(/data-testid="chip-p0">([^<]*)</)
  return m ? m[1] : undefined
}
const section = (html, id) => { const i = html.indexOf(`data-testid="${id}"`); assert.ok(i >= 0, `missing ${id}`); return html.slice(i, html.indexOf('</section>', i)) }
const measureRows = html => section(html, 'card-status').split('data-testid="measure-row"').slice(1)

// 1. UNKNOWN rows render UNKNOWN with their cause; only a GAP row reads NO STOP.
const gapHtml = render(ok(API.holdings, wire([
  row({ symbol: 'UNK', market_value: 5000, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null, stop_qty: null }),
  row({ symbol: 'GAPX', market_value: 2000, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: null }),
  row({ symbol: 'SAFE', market_value: 3000 }),
])))
const protect = section(gapHtml, 'card-protect')
const rowsHtml = protect.split('data-testid="prot-row"').slice(1)
const unkRow = rowsHtml.find(r => r.includes('UNK<') || r.includes('>UNK'))
const gapRow = rowsHtml.find(r => r.includes('GAPX'))
assert.ok(unkRow && gapRow, 'both non-protected rows listed')
assert.doesNotMatch(unkRow, /NO STOP/); assert.match(unkRow, /UNKNOWN/); assert.match(unkRow, /No Stop Read/)
assert.match(gapRow, /NO STOP/)
assert.equal(chipP0(gapHtml), '1 position needs stop review')
assert.match(section(gapHtml, 'card-gates'), /NEEDS BACKEND/); assert.doesNotMatch(section(gapHtml, 'card-gates'), /\b0 open\b/)
assert.match(gapHtml, /Retired/)

// 2. A timed-out holdings read: TIMED OUT, P0 unknown, no value, no CLEAR.
const toHtml = render(fail(API.holdings, 'TIMED OUT'))
assert.match(toHtml, /TIMED OUT/); assert.equal(chipP0(toHtml), 'review count ?')
assert.match(toHtml, /value UNKNOWN/); assert.doesNotMatch(toHtml, />CLEAR</)

// 3. A failed (non-timeout) read is UNKNOWN, never CLEAR.
const failHtml = render(fail(API.holdings))
assert.match(section(failHtml, 'card-protect'), /UNKNOWN/); assert.doesNotMatch(failHtml, />CLEAR</)
// A8 (REVIEW-CAMPAIGN8H-item1-fix): on an unreadable read the header's title names the read error (the value itself
// stays UNKNOWN and no number is drawn); the dead "unreadable store total" branch is gone.
const failHdr = failHtml.match(/data-testid="hdr-value"[^>]*>([^<]*)</) || []
assert.match(failHdr[1], /value UNKNOWN/)
assert.match(failHdr[0], /HTTP 503; no account value was published/is)
assert.doesNotMatch(failHdr[0], /store total/)

// 4. Every counted row protected: Action·Protection collapses to CLEAR, 0 P0.
const okHtml = render(ok(API.holdings, wire([row({ symbol: 'ONE' }), row({ symbol: 'TWO', stop_state: 'pending_activation' })])))
assert.match(okHtml, />CLEAR</); assert.equal(chipP0(okHtml), '0 positions need stop review'); assert.doesNotMatch(okHtml, /NO STOP/)

// F5: the CLEAR line names the brokers it covered, not "N of N brokers".
assert.doesNotMatch(okHtml, /(\d+) of \1 brokers/); assert.match(okHtml, /1 broker with counted positions/)

// 5. LQ-2460 F1 (REVIEW-2448): an unpriced GAP (counted:false, no value) is a GAP row and a P0, never CLEAR.
const unpricedHtml = render(ok(API.holdings, wire([row({ symbol: 'SAFE' }),
  row({ symbol: 'NOPX', market_value: null, price: null, protection_state: 'GAP', protection: { state: 'GAP', counted: false }, stop_price: null, stop_qty: null })])))
assert.doesNotMatch(unpricedHtml, />CLEAR</); assert.equal(chipP0(unpricedHtml), '1 position needs stop review')
assert.match(section(unpricedHtml, 'card-protect').split('data-testid="prot-row"').find(r => r.includes('NOPX')) || '', /NO STOP/)

// 6. LQ-2460 F2: a cash-only book (zero counted positions, count not confirmed) is UNKNOWN, never CLEAR.
const cashHtml = render(ok(API.holdings, wire([row({ symbol: 'CASH', is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })])))
assert.doesNotMatch(cashHtml, />CLEAR</); assert.match(cashHtml, /Protection: UNKNOWN/)
assert.match(section(cashHtml, 'card-protect'), /Protection UNKNOWN: No counted position, and the position count does not confirm zero/)

// 7. LQ-2752 (operator order 2026-11-12 21:56 ET): until v002 is validated the page carries a visible link to the
// classic Portfolio page, like Home's "Classic Home". It sits in the header, ahead of every card, in every read state,
// so a long holdings list at 390/412 px never pushes it off the first screen.
{
  const many = Array.from({ length: 40 }, (_, i) => row({ symbol: `S${i}`, market_value: 1000 + i }))
  const states = {
    ok: render(ok(API.holdings, wire(many))),
    loading: render({ state: 'LOADING', data: null, error: null, at: null, source: API.holdings }),
    unknown: render(fail(API.holdings)),
    timedOut: render(fail(API.holdings, 'TIMED OUT')),
  }
  for (const [name, html] of Object.entries(states)) {
    const link = html.match(/<a[^>]*data-testid="classic-portfolio-link"[^>]*>([^<]*)</)
    assert.ok(link, `${name}: no classic Portfolio link`)
    assert.match(link[0], /href="\/portfolio-classic"/, `${name}: classic link target`)
    assert.equal(link[1], 'Classic Portfolio', `${name}: classic link label`)
    const at = html.indexOf('data-testid="classic-portfolio-link"')
    assert.ok(at < html.indexOf('</header>'), `${name}: classic link is not in the header`)
    assert.ok(at < html.indexOf('data-testid="card-protect"'), `${name}: classic link is below the first card`)
  }
  // The Details row stays as a second way in.
  assert.match(section(states.ok, 'card-details'), /data-testid="classic-link"/)
  // Phone: nothing hides the link, and it is a 44 px tap target.
  const css = readFileSync(join(app, 'src/components/portfolio/v002/PortfolioV002.css'), 'utf8')
  const rule = (css.match(/\.pv2-classic\s*\{([^}]*)\}/) || [])[1] || ''
  assert.match(rule, /min-height:\s*44px/, '.pv2-classic is not a 44 px tap target')
  assert.doesNotMatch(css, /\.pv2-classic[^{]*\{[^}]*(display:\s*none|visibility:\s*hidden)/, '.pv2-classic is hidden somewhere')
}

// 8. Measures absent: four UNKNOWN rows carrying the writer's reason; no page-side number, no UNVERIFIED claim
// (there is nothing to call verified), and the header is the store total, labelled as not reconciled.
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'ONE' })])))
  const mrows = measureRows(html)
  assert.equal(mrows.length, 4, 'four measure rows')
  for (const m of mrows) assert.match(m, /UNKNOWN/)
  assert.match(section(html, 'card-status'), /the writer must run once before the four measures are published/)
  const hdr = html.match(/data-testid="hdr-value"[^>]*>([^<]*)</) || []
  assert.match(hdr[1], /\$9,999/, 'store total drawn with its label')
  // C3 (REVIEW-CAMPAIGN8H-item1 F1): the qualification is VISIBLE text beside the figure at 390/412 — never only a
  // title= a phone cannot hover. The title now names the state it was taken in (C2, F2).
  const mark = (html.match(/data-testid="hdr-mark"[^>]*>([^<]*)</) || [])[1] || ''
  assert.match(mark, /store total · not reconciled/, 'the unreconciled qualification is drawn as text')
  assert.match(hdr[0], /not materialized in this read/)
  assert.doesNotMatch(html, /data-testid="chip-unverified"/)
}

// 8b. C1 (REVIEW F3): a statusless value is not a figure — it is never drawn in its measure row nor promoted to the
// header. The header falls back to the store total, visibly marked unreconciled.
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'ONE' })], { measures: { materialized: true, measures: { account_value: { value: 777777 } } }, total_value: 888888 })))
  const hdr = html.match(/data-testid="hdr-value"[^>]*>([^<]*)</) || []
  assert.match(hdr[1], /\$888,888/, 'the store total, not the statusless number')
  assert.doesNotMatch(html, /777,777/, 'a statusless value appears nowhere in the markup')
  assert.match(measureRows(html)[0], /status not published — not a figure/)
  const mark = (html.match(/data-testid="hdr-mark"[^>]*>([^<]*)</) || [])[1] || ''
  assert.match(mark, /store total · not reconciled/)
}

// 8c. C2 (REVIEW F2): with the block MATERIALIZED but no account_value figure published, the fallback must not claim
// the measures are not materialized (the card beside it reads MEASURED), and the unreconciled mark stays visible.
{
  const noFigure = { ...MEASURES, measures: { ...MEASURES.measures, account_value: { label: 'Account value', value: null, status: 'MEASURED', as_of: AT } } }
  const html = render(ok(API.holdings, wire([row({ symbol: 'ONE' })], { measures: noFigure, total_value: 7654321 })))
  const hdr = html.match(/data-testid="hdr-value"[^>]*>([^<]*)</) || []
  assert.match(hdr[1], /\$7,654,321/)
  assert.doesNotMatch(hdr[0], /not materialized/, 'the block IS materialized; the reason must not say otherwise')
  assert.match(hdr[0], /did not publish an account value/i)
  const mark = (html.match(/data-testid="hdr-mark"[^>]*>([^<]*)</) || [])[1] || ''
  assert.match(mark, /store total · not reconciled/)
  assert.match(measureRows(html)[0], /MEASURED/)   // the header fallback does not contradict the card
}

// 8d. C4 (REVIEW, mutants M3/M5): the status card has no Value/Today row, today_change never reaches the markup, and
// the store total is drawn only in the header fallback. (M3 — coverage PARTIAL rolling up as GAP — is pinned in the
// model test: a PROTECTED/PARTIAL-only book reads OK, counted 1.)
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'ONE' })], { total_value: 7654321, today_change: 4321 })))
  assert.doesNotMatch(html, /today_change/)
  const stNames = [...html.matchAll(/data-testid="(row-[a-z]+)"><div class="s1"><span class="n">([^<]*)</g)].map(m => m[2])
  assert.ok(stNames.length > 0, 'status rows are rendered')
  for (const n of stNames) assert.doesNotMatch(n, /^(value|today)\b/i, `status row named ${n}`)
  assert.equal(html.split('7,654,321').length - 1, 1, 'the store total is drawn exactly once — in the header')
  assert.match(html, /data-testid="hdr-value"/)
}

// 9. Measures present: the anchor and the four measures come from the projection; measure 4 is UNKNOWN with its
// candidate; the Finviz mark is separate and labelled; the page never shows a computed "today".
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'ONE' })], { measures: MEASURES })))
  const hdr = html.match(/data-testid="hdr-value"[^>]*>([^<]*)</) || []
  assert.match(hdr[1], /1,252,981/, 'header is the broker anchor')
  assert.doesNotMatch(hdr[1], /1,255,586/, 'the Finviz estimate is not the header figure')
  assert.match(html, /data-testid="chip-unverified"/)
  const mrows = measureRows(html)
  assert.match(mrows[0], /MEASURED/); assert.match(mrows[0], /1,252,981/)
  assert.match(mrows[0], /Finviz estimate \$1,255,586.*separate/)
  assert.match(mrows[1], /PARTIAL/); assert.match(mrows[1], /1,837/)
  assert.match(mrows[2], /MEASURED/); assert.match(mrows[2], /5,020/)
  assert.match(mrows[3], /UNKNOWN/); assert.match(mrows[3], /candidate .*5,020.*not verified/)
  assert.doesNotMatch(mrows[3], /VERIFIED</, 'measure 4 is never drawn verified without a stored reconciliation')
  assert.match(section(html, 'card-status'), /never added to a “today” figure/)
}

// 10. Coverage categories in the rows and the coverage line; resting vs held; the stop link carries identity.
{
  const html = render(ok(API.holdings, wire([
    row({ symbol: 'FULL', shares: 300, stop_qty: 300 }),
    row({ symbol: 'HALF', shares: 300, stop_qty: 200 }),
    row({ symbol: 'PLAN', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_source: 'planned', stop_price: null, stop_qty: null }),
    row({ symbol: 'NONE', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: null }),
  ])))
  const holdings = section(html, 'card-holdings')
  const half = holdings.split('data-testid="holding-row"').find(r => r.includes('HALF')) || ''
  assert.match(half, /PARTIAL 200\/300/)
  const plan = holdings.split('data-testid="holding-row"').find(r => r.includes('PLAN<')) || ''
  assert.match(plan, /PLANNED ONLY/)
  const none = holdings.split('data-testid="holding-row"').find(r => r.includes('NONE')) || ''
  assert.match(none, /NO STOP/)
  // R5b #2 (2026-11-14): the coverage categories count every drawn row and the tiles count the counted rows. The
  // line names both populations and how they relate; the tiles-sum names its own scope. Here all four rows count.
  const protect = section(html, 'card-protect')
  assert.match(protect, /Coverage · all 4 rows drawn · 4 counted \(the tiles\): <b>1<\/b> covered · <b>1<\/b> partial · <b>1<\/b> uncovered · <b>1<\/b> planned-only/)
  assert.match(protect, /4 of 4 counted positions \(non-cash, at or above \$100\)/)
  // F4 (REVIEW advisory): PLAN/NONE publish no resting quantity, so the totals are a partial sum and the line says
  // "published" instead of presenting 500/620 as the book's totals.
  assert.match(section(html, 'card-protect'), /resting <b>500<\/b> of <b>620<\/b> published held shares/)
  // ...and when every eligible row publishes both quantities, the line reads as the plain totals.
  const completeHtml = render(ok(API.holdings, wire([
    row({ symbol: 'FULL', shares: 300, stop_qty: 300 }),
    row({ symbol: 'GAPY', shares: 300, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: 0 }),
  ])))
  assert.match(section(completeHtml, 'card-protect'), /resting <b>300<\/b> of <b>600<\/b> held shares/)
  const hrefs = [...html.matchAll(/href="([^"]*portfolio-classic\?tab=Stop\+Management[^"]*)"/g)].map(m => m[1])
  assert.ok(hrefs.length >= 1, 'stop desk link')
  const decoded = hrefs.map(h => decodeURIComponent(h.replace(/\+/g, ' '))).find(d => /symbol=NONE/.test(d)) || ''
  assert.ok(decoded, 'the uncovered row carries a stop desk link')
  assert.match(decoded, /account=acct-1/); assert.match(decoded, /broker=broker_a/); assert.match(decoded, /position=acct-1:NONE/)
}

// 10b. R5b #2 (2026-11-14): the two coverage denominators are named, on the page and in the sheet, from one model.
// Live shape it reproduces: 30 rows drawn, 11 counted, 19 not counted (14 under $100 + 5 exempt); here 6/3/3.
{
  const rows = [
    row({ symbol: 'BIG1', shares: 300, stop_qty: 300 }),
    row({ symbol: 'BIG2', protection_state: 'GAP', protection: { state: 'GAP', counted: true, as_of: AT }, stop_price: null }),
    row({ symbol: 'BIG3', protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true, as_of: AT }, stop_price: null }),
    row({ symbol: 'SML1', market_value: 50, protection_state: 'GAP', protection: { state: 'GAP', counted: false, as_of: AT }, stop_price: null }),
    row({ symbol: 'SML2', market_value: 40, protection_state: 'GAP', protection: { state: 'GAP', counted: false, as_of: AT }, stop_price: null }),
    row({ symbol: 'CASHX', is_cash: true, market_value: 900, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } }),
  ]
  const html = render(ok(API.holdings, wire(rows)))
  const protect = section(html, 'card-protect')
  // The categories count all six rows; the line says so and says how the counted rows relate to them.
  assert.match(protect, /Coverage · all 6 rows drawn · 3 counted \(the tiles\) · 3 not counted: 2 under \$100, listed only · 1 exempt:/)
  assert.match(protect, /<b>1<\/b> covered · <b>0<\/b> partial · <b>3<\/b> uncovered · <b>0<\/b> planned-only · <b>1<\/b> exempt · <b>1<\/b> unverifiable/)
  // The tiles count only the three counted rows and name their own scope.
  assert.match(protect, /3 of 3 counted positions \(non-cash, at or above \$100\)/)
  // The sheet's coverage block names the same population (not the counted one) from the same model.
  const pos = positionsFrom(wire(rows), NOW)
  const holdings = ok(API.holdings, wire(rows))
  const why = sheet(sheets.ProtectionWhySheet, { prot: protectionModel(holdings, pos), positions: pos, nowIso: new Date(NOW).toISOString(), onGoTo: noop })
  assert.match(why, /data-testid="why-coverage">all 6 rows drawn · 3 counted \(the tiles\) · 3 not counted: 2 under \$100, listed only · 1 exempt:/)
}

// 11. The sheets: reconciliation and UNVERIFIED, gate evidence with no served gate, the last-visit window, the
// pending risk decision (no score anywhere).
{
  const pos = positionsFrom(wire([row({ symbol: 'HALF', shares: 300, stop_qty: 200 })]), NOW)
  const holdings = ok(API.holdings, wire([row({})], { measures: MEASURES }))
  const measures = measuresModel(holdings)
  const prot = protectionModel(holdings, positionsFrom(holdings.data, NOW))
  const since = sinceVisitModel(ok(API.lastSeen, { read: { status: 'RECORDED', window_basis: 'last_visit', seen_at: AT, age_sec: 60, device: 'phone' } }))
  const mh = sheet(sheets.MeasuresSheet, { measures, nowIso: new Date(NOW).toISOString() })
  assert.match(mh, /DAY FIGURES UNVERIFIED/); assert.match(mh, /UNVERIFIED\./); assert.match(mh, /candidate/)
  assert.match(mh, /COMPONENTS RECONCILE/)
  assert.match(mh, /Finviz mark estimate/); assert.match(mh, /never added to any “today” measure/)
  // PR-004: the sheet now renders the SERVED gate projection. With no answer (route not wired / read failed) it shows
  // an honest UNAVAILABLE and says why — never the old "NOT AVAILABLE" constant and never "0 open".
  const gh = sheet(sheets.GateEvidenceSheet, { prot, measures, positions: pos })
  assert.match(gh, /the gate store read has not answered yet/)
  assert.match(gh, /data-testid="gate-store-unavailable"/)
  assert.match(gh, /UNAVAILABLE/)
  assert.match(gh, /Store: the gate store could not be read; no gate verdict is shown/)
  assert.equal((gh.match(/data-testid="gate-item"/g) || []).length, 4)
  assert.doesNotMatch(gh, /No gate store is served/)
  assert.doesNotMatch(gh, /\b0 open\b/)
  assert.doesNotMatch(gh, /NOT AVAILABLE/)

  // The served projection: one closed gate, its clock named as a closure, its NULL blocks_trading counted as unknown.
  const servedPayload = {
    schema: lib.GATES_SCHEMA, served_at: AT, state: 'OK', reason: null,
    scope: { categories: ['Order protection'], gates: 1 },
    snapshot: { computed_at: '2031-03-06T15:00:00Z', age_s: 86400, threshold_s: 900, basis: 'closed_gates' },
    writer: { lane_id: 'validation-gates-sync', last_ok_at: AT, receipt: 'data/runtime/validation-gates-sync_last.json' },
    counts: { rows: 1, failed: 0, overdue: 0, open: 0, closed: 1, blocks_trading: 0, blocks_trading_unknown: 1, never_evaluated: 0 },
    items: [{ gate_id: 'VG-PORT-COUNT-AGREES', title: 'Position count agrees', status: 'PASSED', blocks_trading: null,
      owner: 'position sync lane', label_text: 'FIXED · UNPROVEN OVER TIME',
      last_eval: { result: 'PASS', at: '2031-03-06T15:00:00Z', detail: '7 rows = 7 rows' },
      clock: { state: 'closed', at: '2031-03-06T15:00:00Z', age_s: 86400, threshold_s: 900, text: 'closed at its last evaluation (24.0 h ago)' },
      window: { end: '2031-03-09T15:00:00Z', days_remaining: 2 },
      next_action: 'No action unless it regresses: proving over the window to 2031-03-09', decl_path: 'config/x.json' }],
  }
  const gs = sheet(sheets.GateEvidenceSheet, { prot, measures, positions: pos, gatesRead: ok(API.gates, servedPayload), nowMs: NOW })
  assert.match(gs, /data-testid="gate-served-row"/)
  assert.match(gs, /Position count agrees · VG-PORT-COUNT-AGREES/)
  assert.match(gs, /closed at its last evaluation \(24.0 h ago\)/)
  assert.match(gs, /Blocks trading: not declared \(unknown\)/)
  assert.match(gs, /data-testid="gate-next-action"/)
  assert.match(gs, /FIXED · UNPROVEN OVER TIME/)
  assert.match(gs, /1 gate in scope · 0 open · 1 closed/)
  assert.match(gs, /closure clock/)
  assert.match(gs, /do not declare whether they block trading/)
  // The expectation with a served row is GATED; the other three say ungated, which is not a pass.
  assert.match(gs, /data-testid="gate-served-text">Store: PASSED · last result PASS at/)
  assert.equal((gs.match(/ungated, which is not a pass/g) || []).length, 3)

  // An empty scope after a good read is still not a pass, and the sheet says so in words.
  const ge = sheet(sheets.GateEvidenceSheet, { prot, measures, positions: pos, nowMs: NOW,
    gatesRead: ok(API.gates, { ...servedPayload, state: 'UNKNOWN', counts: null, items: [],
      reason: 'no portfolio gate is declared for scope [&apos;Order protection&apos;]' }) })
  assert.match(ge, /data-testid="gate-store-empty"|data-testid="gate-store-headline"/)
  assert.match(ge, /no gate verdict: no portfolio gate is declared/)
  assert.doesNotMatch(ge, /\b0 open\b/)
  const sh = sheet(sheets.SinceLastVisitSheet, { since, visitRecord: 'RECORDED' })
  assert.match(sh, /Since your last visit/); assert.match(sh, /Server-stamped/)
  assert.match(sh, /The change list was not read on this page load/)

  // PR-005: the served change list. Each event keeps its OWN time; a measured zero says so; a failed read is an honest
  // UNAVAILABLE and never "no changes".
  const chPayload = { schema: lib.CHANGES_SCHEMA, served_at: AT, state: 'OK', reason: null,
    window: { basis: 'last_visit', since: '2031-03-06T14:00:00Z', until: AT }, count: 1,
    latest_at: '2031-03-07T13:04:54Z', may_be_truncated: false,
    outside_window: { before: 0, after: 0, unreadable: 0, out_of_scope: 8 },
    items: [{ event_id: 41, source_kind: 'gate', source_id: 'VG-R3-STOP-COVERAGE-HEARTBEAT', category: 'Order protection',
      transition: 'passed', label: 'FIXED_UNPROVEN', label_text: 'FIXED · UNPROVEN OVER TIME',
      occurred_at: '2031-03-07T13:04:54Z', detected_at: '2031-03-07T13:04:58Z',
      summary: 'Stop-coverage producer heartbeat is fresh: passed', owner: 'platform' }] }
  const chs = sheet(sheets.SinceLastVisitSheet, { since, visitRecord: 'RECORDED', changesRead: ok(API.changes, chPayload) })
  assert.match(chs, /data-testid="changes-state"/); assert.match(chs, /1 change since your last visit/)
  assert.match(chs, /data-testid="change-row"/)
  assert.match(chs, /passed · FIXED · UNPROVEN OVER TIME — VG-R3-STOP-COVERAGE-HEARTBEAT/)
  assert.match(chs, /Fri 8:04 AM/)                  // the event's own time, not the page clock
  assert.match(chs, /8 events on this store belong to another page/)
  assert.match(chs, /PortfolioChanges@v1/)
  const chz = sheet(sheets.SinceLastVisitSheet, { since, visitRecord: 'RECORDED',
    changesRead: ok(API.changes, { ...chPayload, count: 0, items: [], latest_at: null }) })
  assert.match(chz, /NO CHANGES/); assert.match(chz, /measured zero/)
  assert.doesNotMatch(chz, /data-testid="change-row"/)
  const chu = sheet(sheets.SinceLastVisitSheet, { since, visitRecord: 'RECORDED',
    changesRead: { state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source: API.changes } })
  assert.match(chu, /UNAVAILABLE/); assert.match(chu, /data-testid="changes-unavailable"/)
  assert.doesNotMatch(chu, /measured zero/)
  const rh = sheet(sheets.RiskSheet, {})
  assert.match(rh, /PENDING DECISION/); assert.match(rh, /RISK-SCORE-SPEC-20261111/); assert.match(rh, /no number and no band/)
}

// 12. Pagination: 40 rows, 25 shown, a "show more" control; the count is exact.
{
  const many = Array.from({ length: 40 }, (_, i) => row({ symbol: `S${i}`, market_value: 1000 + i }))
  const html = render(ok(API.holdings, wire(many)), undefined, undefined, 25)
  assert.match(html, /Showing 25 of 40 · show 15 more/)
  assert.match(html, /data-testid="show-more"/)
  const all = render(ok(API.holdings, wire(many)), undefined, undefined, 40)
  assert.doesNotMatch(all, /data-testid="show-more"/)
}

// 13. The six subnav desks keep their deep links.
{
  const d = section(okHtml, 'card-details')
  for (const [id, href] of [['lnk-retirement', '/retirement'], ['lnk-risk', '/risk'], ['lnk-defense', '/defense'],
    ['lnk-reentry', '/portfolio/re-entry'], ['lnk-rotation', '/rotation'], ['lnk-redeploy', '/redeploy']]) {
    assert.ok(d.includes(`data-testid="${id}" href="${href}"`), `missing or wrong link ${id}`)
  }
}

// 14. Risk: the composite score is undecided; the column is a measured hypothetical, never a score.
{
  const statusHtml = section(okHtml, 'card-status')
  assert.match(statusHtml, /PENDING DECISION|PENDING/)
  assert.match(statusHtml, /RISK-SCORE-SPEC-20261111 is PROPOSED/)
  assert.match(statusHtml, /data-testid="risk-why"/)
  assert.doesNotMatch(okHtml, /data-testid="row-risk"[\s\S]{0,300}score \d/)
  assert.match(section(okHtml, 'card-details'), /Risk · measured downside to stop/)
  assert.match(section(okHtml, 'card-holdings'), /Composite risk score: no approved methodology/)
}

// 15. Export: a CSV control in the holdings block, disabled state is not the default; the file name carries no symbol.
{
  const html = render(ok(API.holdings, wire([row({})])))
  assert.match(section(html, 'card-holdings'), /data-testid="export-csv"/)
  assert.match(section(html, 'card-holdings'), /Export the filtered holdings as CSV/)
  const page = readFileSync(join(app, 'src/pages/PortfolioV002.tsx'), 'utf8')
  assert.match(page, /portfolio-holdings-\$\{new Date\(\)\.toISOString\(\)\.slice\(0, 10\)\}\.csv/)
  assert.doesNotMatch(page, /\.csv`?.*symbol/i)
}

// 16. Validation gates: the four named gates with their evidence, an unticked box each, no count and no verdict.
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'AAA' }), row({ symbol: 'BBB', price_stale: true })])))
  const g = section(html, 'card-gates')
  assert.equal((g.match(/data-testid="gate-row"/g) || []).length, 4)
  assert.match(g, /Stop read covers every broker/)
  assert.match(g, /Price check · 5 sessions clean/)
  assert.match(g, /Position count agrees/)
  assert.match(g, /Value reconciles to the accounting anchor/)
  assert.match(g, /In this read: 1 stale of 2 priced rows in this read; one read cannot show a five-session window/)
  assert.match(g, /BLOCKS TRADING/)
  assert.match(g, /data-testid="open-gates"/)
  assert.equal((g.match(/class="pv2-gbox"/g) || []).length, 4)
  assert.doesNotMatch(g, /\b(PASS|FAIL|OPEN|CLOSED|0 open)\b/)
  assert.doesNotMatch(g, /✓|✔/)
  // The header never counts gates: the chip says NEEDS BACKEND, the block age says the result is unavailable.
  assert.match(section(html, 'card-gates'), /result not available/)
  assert.doesNotMatch(section(okHtml, 'card-gates'), /Gates \d/)
}

// 16b. C5/C6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2) at the rendered level: the served count block's cross-scope
// `agree:false` is not a mismatch and not a P0 — the gate speaks the like-for-like row count, and a healthy,
// fully protected book draws "0 P0".
{
  const SERVED_COUNTS = {
    contract_version: 'PositionCountAuthority@v1', primary_scope: 'holdings.non_cash_over_100', agree: false,
    position_count: 11, held_count: 28, all_rows: 1, cash_rows: 0, non_cash_rows: 1, below_100: 0,
    distinct_values: [0, 1, 11, 28],
    scopes: { 'holdings.all_rows': 1, 'holdings.cash': 0, 'holdings.non_cash': 1, 'holdings.non_cash_over_100': 1 },
    summary: '1 position at or above $100', findings: [],
  }
  const html = render(ok(API.holdings, wire([row({ symbol: 'SAFE' })], { position_counts: SERVED_COUNTS })))
  const g = section(html, 'card-gates')
  assert.match(g, /holdings\.all_rows scope counts 1; this read parsed 1 normalised row; they match/)
  assert.match(g, /headline 11 is its holdings\.non_cash_over_100 scope/)
  assert.match(g, /its own summary: 1 position at or above \$100/)
  assert.doesNotMatch(g, /disagree/i)
  assert.doesNotMatch(g, /summary 11 vs/)
  assert.equal(chipP0(html), '0 positions need stop review', 'a healthy book draws no review population')
  // ...and a published finding still raises exactly one P0, with its detail on the page.
  const withFinding = render(ok(API.holdings, wire([row({ symbol: 'SAFE' })], { position_counts: { ...SERVED_COUNTS, findings: [{ code: 'LIVE_MARK_COUNT_DIFFERS', detail: 'the live re-mark counts 12 instruments at or above $100 where the positions store counts 11' }] } })))
  assert.equal(chipP0(withFinding), '0 positions need stop review', 'a count-mismatch finding is not a position: the badge counts positions')
  assert.match(withFinding, /data-testid="chip-count-mismatch"/, 'the finding keeps its own labelled chip')
  assert.doesNotMatch(html, /chip-count-mismatch/, 'no mismatch chip on a book without one')
}

// 17. A status row opens the measures sheet at its own measure (drawn first, marked); the other three stay.
{
  const measures = measuresModel(ok(API.holdings, wire([row({})], { measures: MEASURES })))
  const mh = sheet(sheets.MeasuresSheet, { measures, nowIso: new Date(NOW).toISOString(), focus: 'verified_daily_pnl' })
  const blocks = mh.split('data-testid="measure-detail"').slice(1)
  assert.equal(blocks.length, 4)
  assert.match(blocks[0], /data-focus="true"/)
  assert.match(blocks[0], /Verified daily P&amp;L/)
  assert.equal((mh.match(/data-focus="true"/g) || []).length, 1)
  // The page wires the row to the focused sheet, and the Details entry opens it unfocused.
  const page = readFileSync(join(app, 'src/pages/PortfolioV002.tsx'), 'utf8')
  assert.match(page, /onOpenMeasure=\{k => \{ setMeasureFocus\(k\); setMeasuresOpen\(true\) \}\}/)
  assert.match(page, /onOpenMeasures=\{\(\) => \{ setMeasureFocus\(null\); setMeasuresOpen\(true\) \}\}/)
}

// 18. Since your last visit: the anchor, device and previous visit when recorded; an explicit reason when not.
{
  const r = ok(API.lastSeen, { read: { status: 'RECORDED', window_basis: 'last_visit', seen_at: AT,
    previous_seen_at: '2031-03-01T15:00:00Z', age_sec: 60, device: 'phone' } })
  const s = section(render(ok(API.holdings, wire([row({})])), undefined, r), 'card-since')
  assert.match(s, /Last visit /); assert.match(s, /phone/); assert.match(s, /previous /)
  assert.match(s, /data-testid="since-window"/)
  const unknown = section(okHtml, 'card-since')
  assert.match(unknown, /data-testid="since-detail"/)
  assert.doesNotMatch(unknown, /Last visit \d/, 'no visit time is drawn when the record is missing')
}

// 19. PR-001 (S8H-2 S3): the headline tiles are MUTUALLY EXCLUSIVE counted-position states that add to the counted
// population, and each one opens exactly the rows it counts. A partially covered position is Partial only — it is
// never counted in Fully covered, which is what the old "Protected 8" tile did.
{
  const html = render(ok(API.holdings, wire([
    row({ symbol: 'FULL', market_value: 5000 }),
    row({ symbol: 'PART', market_value: 4000, shares: 300, stop_qty: 200 }),
    row({ symbol: 'GONE', market_value: 3000, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: null }),
    row({ symbol: 'UNK', market_value: 2000, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null, stop_qty: null }),
    row({ symbol: 'CASH', is_cash: true, market_value: 900, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } }),
  ])))
  const protectSec = section(html, 'card-protect')
  const tile = label => {
    const m = protectSec.match(new RegExp(`<button[^>]*><span class="k">${label}</span><span class="n">(\\d+)</span></button>`))
    assert.ok(m, `missing tile ${label}`)
    return Number(m[1])
  }
  const got = { covered: tile('Fully covered'), partial: tile('Partial'), noStop: tile('No broker stop'), unknown: tile('Unknown') }
  assert.deepEqual(got, { covered: 1, partial: 1, noStop: 1, unknown: 1 }, 'tiles are exclusive')
  assert.equal(got.covered + got.partial + got.noStop + got.unknown, 4, 'tiles add to the counted population')
  assert.match(protectSec, /4 of 4 counted positions/)
  assert.doesNotMatch(protectSec, />Protected</, 'no tile calls a partial position fully protected')
  // The tile filters are exclusive too: every counted row lands in exactly one of the four.
  const ps = positionsFrom(ok(API.holdings, wire([
    row({ symbol: 'FULL' }), row({ symbol: 'PART', shares: 300, stop_qty: 200 }),
    row({ symbol: 'GONE', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: null }),
    row({ symbol: 'UNK', protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null, stop_qty: null }),
  ])).data, NOW)
  const counted = ps.filter(p => p.counted).length
  const union = ['covered', 'partial', 'unprotected', 'unknown'].map(f => filterPositions(ps, f, 'all'))
  assert.equal(union.reduce((n, rows) => n + rows.length, 0), counted, 'filter populations partition the counted rows')
  const keys = union.flat().map(p => p.key)
  assert.equal(new Set(keys).size, keys.length, 'no row matches two of the four filters')
}

// 20. PR-003: a verification time later than the capture clock is unverified evidence, not a successful read; and a
// row with no published read time says so rather than "never" (which read as "a read happened and found nothing").
{
  const future = new Date(Date.parse(AT) + 12 * 3600_000).toISOString()
  const hold = ok(API.holdings, wire([
    row({ symbol: 'AMNX', protection_state: 'PROTECTED', protection: { state: 'PROTECTED', as_of: future, counted: true } }),
    row({ symbol: 'NOC', market_value: 800, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null, stop_qty: null, stop_captured_at: null }),
  ]))
  const html = render(hold)
  const rows = section(html, 'card-protect').split('data-testid="prot-row"').slice(1)
  const amnx = rows.find(r => r.includes('AMNX'))
  const noc = rows.find(r => r.includes('NOC'))
  assert.ok(amnx && noc, 'both rows drawn')
  assert.match(amnx, /UNKNOWN/, 'a future verification is not evidence of protection')
  // The row line carries the state; the sentence is drawn in the position sheet, so assert it on the model both draw from.
  assert.match(positionsFrom(hold.data, NOW).find(p => p.symbol === 'AMNX').reason, /later than the capture clock/)
  assert.match(amnx, /read time invalid · not verified/)
  assert.doesNotMatch(amnx, /STOP \$/, 'no stop chip is drawn from an impossible time')
  assert.match(noc, /NO STOP/)
  assert.match(noc, /no read time published/)
  assert.doesNotMatch(noc, /· never/, '"never" is not drawn as read evidence')
}

// 21. PR-017: a planned level is its own fact beside the broker-evidence state. AMANX reads UNKNOWN *and* shows its
// plan; it is not counted as "No broker stop" (a plan is not coverage) and the Planned filter counts the facet.
{
  const html = render(ok(API.holdings, wire([
    row({ symbol: 'AMNX', market_value: 4000, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true },
      stop_price: 63.66, stop_qty: 100, stop_source: 'planned', stop_state: 'planned' }),
  ])))
  const protectSec = section(html, 'card-protect')
  const amnx = protectSec.split('data-testid="prot-row"').slice(1).find(r => r.includes('AMNX'))
  assert.match(amnx, /UNKNOWN/, 'broker evidence stays UNKNOWN')
  assert.match(amnx, /plan \$63\.66 \(not rested\)/, 'the plan is visible as a separate fact')
  // The filter chips live in the holdings list, not in the protection card; they read the same counts.
  assert.match(html, /Planned 1</, 'the Planned filter counts the facet')
  assert.match(html, /No broker stop 0</, 'a plan is not counted as no-broker-stop coverage')
  assert.match(protectSec, /1 positions with unverifiable protection/, 'the row is counted UNKNOWN, not unprotected')
}

// 22. PR-002: one Scope line names every denominator the page uses — source rows, cash/non-cash/unpriced, quoteable,
// drawn/filtered/rendered, the page's counted population and the count block's own headline scope — and names the fact
// the read does not publish (the snapshot id) instead of omitting it or inventing one.
{
  const counts = { contract_version: 'PositionCountAuthority@v1', primary_scope: 'holdings.non_cash_over_100', agree: false,
    position_count: 1, held_count: 2, all_rows: 3, cash_rows: 1, non_cash_rows: 2, below_100: 0,
    scopes: { 'holdings.all_rows': 3, 'holdings.cash': 1, 'holdings.non_cash': 2, 'holdings.non_cash_over_100': 1, 'holdings.unpriced': 1 },
    summary: '1 position at or above $100', findings: [] }
  const rows = [row({ symbol: 'AAA' }), row({ symbol: 'BBB', market_value: 900 }),
    row({ symbol: 'CASH', market_value: 500, is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false }, stop_price: null, stop_qty: null })]
  const html = render(ok(API.holdings, wire(rows, { position_counts: counts })))
  const line = (html.match(/data-testid="scope-line">([\s\S]*?)<\/p>/) || [])[1] || ''
  for (const t of ['all accounts (1)', 'source rows 3', 'cash 1', 'non-cash 2', 'unpriced 1', 'quoteable 2',
    'drawn 3', 'after filter 3', 'rendered 3', 'counted here 2', 'count block 1 (holdings.non_cash_over_100)']) {
    assert.ok(line.includes(t), `scope line names "${t}"`)
  }
  // R5c (b6): the snapshot identity is ONE sentence from the shared accessor Risk calls too — the id is named as
  // not published, the read clock is the served one, and the account scope is this page's own filter.
  assert.match(line, /data-testid="snapshot-line">snapshot id not published · positions read Fri 9:59 AM ET · all accounts \(1\)</)
  assert.doesNotMatch(line, /differs:/, 'published denominators agree here')
  assert.match(line, /data-testid="scope-diag"/, 'the line routes to Diagnostics')
  // A disagreement between two published denominators is named, never silently reconciled.
  const off = render(ok(API.holdings, wire(rows, { position_counts: { ...counts, all_rows: 2 } })))
  assert.match(off, /differs: the count block&#x27;s all-rows scope counts 2; this read parsed 3 rows/)
  // When the wire publishes a snapshot id, the line prints it and stops calling it missing.
  const snap = render(ok(API.holdings, wire(rows, { position_counts: counts, snapshot_id: 'snap-20310307-1' })))
  assert.match(snap, /snapshot snap-20310307-1/)
  assert.doesNotMatch(snap, /not published: snapshot id/)
  // REVIEW O1 (cc-deepseek-4): the account count is over the account KEY on both pages (Risk passes
  // `account_id ?? account`). A display label that changes must not invent a second account.
  const relabelled = render(ok(API.holdings, wire([
    row({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01' }),
    row({ symbol: 'BBB', account_id: 'acct-1', account_label: 'Broker A ··rekeyed', market_value: 900 }),
  ])))
  assert.match(relabelled, /data-testid="snapshot-line">[^<]*all accounts \(1\)/)
  assert.doesNotMatch(relabelled, /all accounts \(2\)/)
}

// 23. PR-006: the incidents badge names its entity and scope (open lifecycle incidents, all pages) and opens the
// evidence set it counts. It is not the position review population and says so in the row.
{
  const html = render(ok(API.holdings, wire([row({ symbol: 'AAA' })])), ok(API.incidents, { counts: { P0: 1, P1: 16 }, served_at: AT }))
  const line = section(html, 'card-status').split('data-testid="row-alerts"').slice(1)[0] || ''
  assert.match(line, /Incidents · all pages/, 'the row names the entity and the scope')
  assert.match(line, /1 P0 · 16 P1 open lifecycle incidents/)
  assert.match(line, /not the position review count/, 'the two populations are distinguished in words')
  assert.match(line, /data-testid="row-alerts-evidence"/, 'the count has a destination')
  assert.match(line, /href="\/ops\/incidents"/)
}

// 24. C1 (REVIEW-S2-portfolio-risk-b1 §5): a GAP row whose stop-read time is later than the capture clock was drawn
// NO STOP while its own sentence said the read could not be trusted. It now reads UNKNOWN with its cause, through both
// carriers of the read time, and it is not part of the No broker stop population the tiles and filters count.
for (const carrier of ['as_of', 'stop_captured_at']) {
  const future = new Date(Date.parse(AT) + 12 * 3600_000).toISOString()
  const gap = { state: 'GAP', counted: true }
  const h = row({ symbol: 'FUTG', protection_state: 'GAP', stop_price: null, stop_qty: null, stop_captured_at: null,
    protection: carrier === 'as_of' ? { ...gap, as_of: future } : gap, ...(carrier === 'stop_captured_at' ? { stop_captured_at: future } : {}) })
  const hold = ok(API.holdings, wire([h]))
  const html = render(hold)
  const line = section(html, 'card-protect').split('data-testid="prot-row"').slice(1).find(r => r.includes('FUTG'))
  assert.ok(line, `${carrier}: the row is drawn`)
  assert.match(line, /UNKNOWN/, `${carrier}: an impossible read time is UNKNOWN`)
  assert.doesNotMatch(line, /NO STOP/, `${carrier}: it is not asserted as a successful negative read`)
  const m = positionsFrom(hold.data, NOW)[0]
  assert.equal(m.cause, 'Invalid Stop Read Time', `${carrier}: cause`)
  assert.match(m.reason, /later than the capture clock/)
  assert.equal(exclusiveCoverage(positionsFrom(hold.data, NOW)).noStop, 0, `${carrier}: zero in No broker stop`)
}

console.log('PortfolioV002.view.test.mjs: ok')

// 25. OBS-P1 (operator 2026-11-14 11:15 ET): the live row read Symbol/Shares/Value/Protection/Risk plus an UNLABELED %.
// The row now draws, in the row itself: the mark with its source and read clock, the session PRICE MOVE in $ and %
// (never called P&L), the weight (or that it is not published), and unrealized P&L ONLY on a recorded basis with the
// read's own reason otherwise. The row markup is width-independent and no rule hides these facts at 390/412 px, so the
// phone card and the desktop table draw the same labelled facts — nothing here is drawer-only.
const obsp1 = render(ok(API.holdings, wire([
  row({ symbol: 'NOB', shares: 100, price: 186.64, market_value: 18664, price_source: 'finviz', price_as_of: AT,
    prior_close: 188.98, day_change: -234, day_change_pct: -1.24 }),
  row({ symbol: 'RECD', shares: 50, price: 200, market_value: 10000, price_source: 'schwab', price_as_of: AT,
    day_change: 120, day_change_pct: 1.2, cost_basis: 9000,
    basis_truth: { cost_basis_usd: 9000, unrealized_pl_usd: 1000, unrealized_pl_pct: 11.11, source: 'broker_api', status: 'recorded', gap: null } }),
])))
const obRows = section(obsp1, 'card-holdings').split('data-testid="holding-row"').slice(1)
const nob = obRows.find(r => r.includes('>NOB<')) || ''
const recd = obRows.find(r => r.includes('>RECD<')) || ''
assert.ok(nob && recd, 'both OBS-P1 rows are drawn')
// Mark: the price, its source and the clock it was observed at — one sentence, in the row.
assert.match(nob, /data-testid="row-quote">mark \$186\.64 · finviz · quote read Fri 9:59 AM ET</)
// The session move is labelled a PRICE MOVE and carries both figures; the word P&L is not on it.
assert.match(nob, /data-testid="row-move">price move today −1\.2% · −\$234</)
assert.doesNotMatch(nob.slice(nob.indexOf('data-testid="row-move"'), nob.indexOf('data-testid="row-pnl"')), /P&amp;L|P&L/)
// No recorded basis: the reason is printed, and a zero is nowhere near it.
assert.match(nob, /data-testid="row-pnl">unrealized P&amp;L not shown — cost basis not reported by the broker read</)
assert.doesNotMatch(nob, /\$0\b/)
// Weight is not published by this read: the row says so instead of dividing two numbers itself.
assert.match(nob, /data-testid="row-weight">weight not published in this read</)
// A recorded basis: the served P&L with its own pct and the basis source.
assert.match(recd, /data-testid="row-pnl">\+\$1,000 \(\+11\.1%\) on recorded basis · broker_api</)
assert.match(recd, /data-testid="row-move">price move today \+1\.2% · \+\$120</)
// The header states how much of the book's unrealized P&L can be drawn at all.
assert.match(section(obsp1, 'card-holdings'),
  /data-testid="basis-coverage">cost basis recorded for 1 of 2 non-cash positions \(1 without a usable basis — their unrealized P&amp;L is not drawn\)/)
// The row's financial facts are never hidden by a breakpoint rule.
const css = readFileSync(join(app, 'src/components/portfolio/v002/PortfolioV002.css'), 'utf8')
assert.doesNotMatch(css, /\.pv2-hrow\s+\.facts[^{]*\{[^}]*display:\s*none/)

// 26. OP-026 (2026-11-14): the primary row draws its WEIGHTED REMAINING BASIS and per-share average, from the same
// row the drawer reads, and a missing basis says "basis not recorded" while the mark, value and price move stay on
// the row (missing basis blocks unrealized P&L, never a current-price fact). Fail-before: no row-basis fact existed.
const op26Wire = wire([
  row({ symbol: 'WK1', account_id: 'acct-a', account_label: 'Broker A ··01', shares: 600, price: 139.11, market_value: 83466,
    price_source: 'finviz', price_as_of: AT, day_change: -495.36, day_change_pct: -0.59, cost_basis: 79620,
    basis_truth: { cost_basis_usd: 79620, unrealized_pl_usd: 3846, unrealized_pl_pct: 4.83, source: 'broker_api', status: 'recorded', gap: null, conflicts: [] } }),
  row({ symbol: 'NOPX', account_id: 'acct-c', account_label: 'Broker C ··03', shares: 10, price: 50, market_value: 500,
    price_source: 'finviz', price_as_of: AT, day_change: -2.5, day_change_pct: -0.5, cost_basis: null,
    basis_truth: { cost_basis_usd: null, unrealized_pl_usd: null, unrealized_pl_pct: null, source: null, status: 'unknown',
      gap: { reason: 'basis unknown — no recorded acquisition cost' }, conflicts: [] } }),
])
const op26 = render(ok(API.holdings, op26Wire))
const op26Rows = section(op26, 'card-holdings').split('data-testid="holding-row"').slice(1)
const wk1 = op26Rows.find(r => r.includes('>WK1<')) || ''
const nopx = op26Rows.find(r => r.includes('>NOPX<')) || ''
assert.ok(wk1 && nopx, 'both OP-026 rows are drawn')
// Recorded basis: the basis total and the per-share average, in the row.
assert.match(wk1, /data-testid="row-basis">basis \$79,620 · avg entry \$132\.70</)
// The fact sits in the row's full-width facts line, which no breakpoint hides (the phone and desktop draw it).
assert.ok(wk1.indexOf('class="facts"') >= 0 && wk1.indexOf('data-testid="row-basis"') > wk1.indexOf('class="facts"'))
// Missing basis: named exactly, with the read's own reason — and the mark, value and move are still drawn.
assert.match(nopx, /data-testid="row-basis">basis not recorded — basis unknown — no recorded acquisition cost</)
assert.match(nopx, /data-testid="row-quote">mark \$50\.00 · finviz · /)
assert.match(nopx, /data-testid="row-move">price move today −0\.5% · −\$3</)
assert.match(nopx, /<span class="num">\$500<\/span>/)
// The drawer prints the same two numbers, from the same row.
const op26Positions = positionsFrom(op26Wire, NOW)
const wk1Model = op26Positions.find(p => p.symbol === 'WK1')
const drawFields = lib.positionFields(wk1Model, op26Wire, NOW)
assert.equal(drawFields.find(f => f.field === 'Cost basis').value, '$79,620')
assert.equal(drawFields.find(f => f.field === 'Avg entry').value, '$132.70')
assert.match(wk1, /basis \$79,620 · avg entry \$132\.70/)
