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
const { positionsFrom, protectionModel, p0Items, statusRows, measuresModel, sinceVisitModel, STOP_READ_MAX_AGE_MS, API, filterPositions } = lib

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
  assert.match(section(html, 'card-protect'), /Coverage: <b>1<\/b> covered · <b>1<\/b> partial · <b>1<\/b> uncovered · <b>1<\/b> planned-only/)
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
  const gh = sheet(sheets.GateEvidenceSheet, { prot, measures, positions: pos })
  assert.match(gh, /No gate store is served/); assert.match(gh, /NOT AVAILABLE/)
  for (const h of gh.match(/data-testid="gate-item"/g) || []) assert.ok(h)
  assert.doesNotMatch(gh, /\b0 open\b/)
  const sh = sheet(sheets.SinceLastVisitSheet, { since, visitRecord: 'RECORDED' })
  assert.match(sh, /Since your last visit/); assert.match(sh, /Server-stamped/); assert.match(sh, /change store \(LQ-2143\)/)
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

// 14. Risk: the row and the Details entry say pending decision; no score band or number is drawn.
{
  const statusHtml = section(okHtml, 'card-status')
  assert.match(statusHtml, /PENDING DECISION|PENDING/)
  assert.match(statusHtml, /RISK-SCORE-SPEC-20261111 is PROPOSED/)
  assert.match(statusHtml, /data-testid="risk-why"/)
  assert.doesNotMatch(okHtml, /data-testid="row-risk"[\s\S]{0,300}score \d/)
  assert.match(section(okHtml, 'card-details'), /Risk score · pending decision/)
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
  assert.match(g, /holdings\.all_rows scope counts 1; this read drew 1 row; they match/)
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

console.log('PortfolioV002.view.test.mjs: ok')
