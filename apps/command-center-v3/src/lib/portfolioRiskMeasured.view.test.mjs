// OP-023 PORTFOLIO-RISK-MEASURED (operator 2026-11-14 13:11:57 ET) — the Risk column is a MEASURED fact.
//
// What this pins, in the operator's words and the 13:16 ET amendment:
//   1. The composite risk score stays undecided: "Composite risk score: no approved methodology", no derived number.
//   2. "Hypothetical downside to stop (verified stop price)" = (mark − resting stop) × the quantity the stop covers.
//      It is a distance to a resting ORDER price: never a loss, an exit price, a guaranteed fill or P&L.
//   3. Covered and uncovered quantities are separate values. The uncovered quantity never carries a figure; its
//      state is the literal "uncovered: no stop".
//   4. An unknown cost basis blocks unrealized P&L ONLY. A valid mark + valid stop still produce the measure.
//   5. Stop/quote eligibility and staleness are the page's EXISTING rules (protectionFor/rowView + the R2 clock in
//      stopReadFreshness / STOP_READ_MAX_AGE_MS). This file also asserts no new constant exists in the module.
//   6. Table == drawer == CSV: one derivation, one clock, three renderings that must agree on value AND state.
//
// Synthetic fixtures only (the repository is public). The shared stop-verdict fixture
// tests/fixtures/portfolio_protection_books_lq2708.json is read as-is: its books carry no mark, so its PROTECTED
// rows must read MARK MISSING — the page never derives a mark from market_value / shares.
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

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
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
const {
  positionsFrom, protectionModel, p0Items, statusRows, measuresModel, sinceVisitModel, downsideToStop, downsideLine,
  holdingsCsv, fmtShares, fmtUsd, STOP_READ_MAX_AGE_MS, API,
} = lib

// A multi-check reporter: every failure is named, and a missing export is one failure rather than a crash, so the
// red-before run on the parent commit reports each behaviour that is absent instead of stopping at the first.
const failures = []
let checks = 0
function check(name, fn) {
  checks += 1
  try { fn() } catch (e) { failures.push(`${name}: ${e.message}`) }
}
function need(cond, msg) { assert.ok(cond, msg) }

const NOW = Date.parse('2031-03-07T15:00:00Z')   // Fri 10:00 ET — the regular session is OPEN
const NOW_CLOSED = Date.parse('2031-03-08T15:00:00Z') // Sat 10:00 ET — off-hours limits apply
const AT = '2031-03-07T14:59:00Z'                // one minute old at NOW
const AT_16H = '2031-03-06T23:00:00Z'            // 16 h old: stale in session, fresh off-hours

const ok = (source, data) => ({ state: 'OK', data, error: null, at: AT, source })
const noop = () => {}
const LAST_SEEN_UNKNOWN = { state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source: API.lastSeen }

/** One synthetic position. Defaults are a fully covered, fresh, measured row: 10 shares, mark 100, stop 90. */
const row = o => ({
  symbol: 'SYNA', account_id: 'acct-1', account_label: 'Broker A', broker: 'broker_a',
  shares: 10, market_value: 1000, price: 100, price_as_of: AT, price_stale: false, price_source: 'repricer',
  stop_price: 90, stop_qty: 10, stop_captured_at: AT, stop_source: 'broker_resting', stop_state: 'active',
  protection_state: 'PROTECTED', protection: { state: 'PROTECTED', source: 'broker_resting', as_of: AT, counted: true },
  ...o,
})
const wire = rows => ({ holdings: rows, total_value: 9999, today_change: 5, positions_as_of: AT, valuation_as_of: AT,
  quote_as_of: AT, position_counts: { agree: true } })
const positionsOf = (rows, now = NOW) => positionsFrom(wire(rows), now)
const one = (o, now = NOW) => { const ps = positionsOf([row(o)], now); return { p: ps[0], d: downsideToStop(ps[0], { nowMs: now }) } }

const dts = typeof downsideToStop === 'function'

// ── 1. The composite score is undecided and nothing derives one ─────────────────────────────────────
check('composite score is labelled with no approved methodology', () => {
  need(lib.RISK_SCORE.status === 'PENDING DECISION', `status ${lib.RISK_SCORE.status}`)
  need(/no approved methodology/.test(lib.RISK_SCORE.text) || /no number and no band/.test(lib.RISK_SCORE.text), 'RISK_SCORE.text lost its disclosure')
  const html = renderPage([row({})])
  need(html.includes('Composite risk score: no approved methodology'), 'the holdings block lost the composite label')
  need(!/Composite risk score[^<]*\d/.test(html), 'a digit follows the composite label')
})

// ── 2. MEASURED: (mark − stop) × covered qty, and the wording is a hypothetical ─────────────────────
check('a covered row measures (mark − stop) × covered qty', () => {
  need(dts, 'downsideToStop is not exported')
  const { d } = one({})
  need(d.state === 'MEASURED', `state ${d.state}`)
  need(d.usd === 100, `usd ${d.usd}`)
  need(Math.abs(d.pct - 10) < 1e-9, `pct ${d.pct}`)
  need(d.coveredQty === 10 && d.uncoveredQty === 0, `covered ${d.coveredQty} uncovered ${d.uncoveredQty}`)
  need(d.cell === '$100', `cell ${d.cell}`)
  need(d.formula === '(mark $100 − stop $90) × 10 covered shares = $100', `formula ${d.formula}`)
  need(d.reason.includes('Hypothetical downside to stop (verified stop price)'), 'the reason lost the mandated label')
  need(/resting order price, not an executed price/.test(d.reason), 'the stop-is-not-a-fill sentence is missing')
  for (const bad of ['loss', 'exit price', 'guaranteed', 'will fill']) need(!d.reason.toLowerCase().includes(bad), `the reason says "${bad}"`)
  // The LINE is a surface of its own: it must carry the mandated label and none of the banned words.
  need(downsideLine(d).startsWith('hypothetical downside to stop $100 (10.0% below the mark)'), `the line reads "${downsideLine(d)}"`)
  for (const bad of ['loss', 'exit price', 'guaranteed', 'will fill']) need(!downsideLine(d).toLowerCase().includes(bad), `the line says "${bad}"`)
})

check('the standalone formula holds for a second, non-round row', () => {
  const { d } = one({ price: 123.45, stop_price: 101.01, shares: 7, stop_qty: 7, market_value: 864.15 })
  need(d.state === 'MEASURED', `state ${d.state}`)
  need(d.usd === Math.round((123.45 - 101.01) * 7 * 100) / 100, `usd ${d.usd}`)
})

// ── 3. PARTIAL: covered and uncovered are separate; the uncovered qty gets NO figure ────────────────
check('partial coverage measures over the covered qty and names the uncovered qty', () => {
  const { d } = one({ shares: 100.7963, stop_qty: 100, price: 425.76, stop_price: 406.94, market_value: 42915.9 })
  need(d.state === 'PARTIAL', `state ${d.state}`)
  need(d.coveredQty === 100, `covered ${d.coveredQty}`)
  need(d.uncoveredQty === 0.7963, `uncovered ${d.uncoveredQty}`)
  need(d.uncoveredState === 'uncovered: no stop', `uncoveredState ${d.uncoveredState}`)
  need(d.usd === 1882, `usd ${d.usd}`)
  need(d.uncoveredQty !== null && d.usd === Math.round((425.76 - 406.94) * 100 * 100) / 100, 'the figure is not over the covered qty only')
  need(downsideLine(d).includes(`${fmtShares(0.7963)} uncovered: no stop`), `line ${downsideLine(d)}`)
})

// ── 4. Every non-measured state is explicit: never a blank, never a false 0 ─────────────────────────
const STATED = [
  ['cash row is exempt', { is_cash: true, asset_type: 'cash', shares: 0, market_value: 500, price: null, price_as_of: null,
    stop_price: null, stop_qty: null, stop_captured_at: null, protection_state: 'EXEMPT',
    protection: { state: 'EXEMPT', source: 'policy', as_of: null, counted: false } }, 'EXEMPT'],
  ['a good read with no resting stop is uncovered, not a zero', { stop_price: null, stop_qty: null, stop_captured_at: null,
    protection_state: 'GAP', protection: { state: 'GAP', source: 'broker_resting', as_of: AT, counted: true } }, 'UNCOVERED'],
  ['a planned level is never a verified stop price', { stop_source: 'planned', stop_state: 'none', stop_price: 63.66, stop_qty: null,
    stop_captured_at: AT, protection_state: 'GAP',
    protection: { state: 'GAP', source: 'planned', as_of: AT, counted: true } }, 'PLANNED_ONLY'],
  ['an expired stop is its own state off-hours', { stop_price: 90, stop_qty: 10, stop_source: 'broker_resting', stop_state: 'expired',
    protection_state: 'GAP', protection: { state: 'GAP', expired_stop: true, source: 'broker_resting', as_of: AT, counted: true } }, 'EXPIRED', NOW_CLOSED],
  ['an expired stop in session reads UNKNOWN, not EXPIRED (R1)', { stop_price: 90, stop_qty: 10, stop_source: 'broker_resting', stop_state: 'expired',
    protection_state: 'GAP', protection: { state: 'GAP', expired_stop: true, source: 'broker_resting', as_of: AT, counted: true } }, 'UNVERIFIABLE'],
  ['an unread book is never measured from a last-known level', { protection_state: 'UNKNOWN',
    protection: { state: 'UNKNOWN', cause: 'No Stop Read', source: 'stop store', as_of: null, counted: true } }, 'UNVERIFIABLE'],
  ['a stop without a verified price is stated', { stop_price: null }, 'STOP_PRICE_MISSING'],
  ['a stop without a published quantity is not measured over the whole holding', { stop_qty: null }, 'STOP_QTY_MISSING'],
  ['a missing mark is stated', { price: null, price_as_of: null }, 'MARK_MISSING'],
  ['a stale mark is stated', { price_stale: true }, 'MARK_STALE'],
  ['a stop read older than the session limit is stated', { stop_captured_at: '2031-03-07T14:00:00Z',
    protection: { state: 'PROTECTED', source: 'broker_resting', as_of: '2031-03-07T14:00:00Z', counted: true } }, 'STOP_STALE'],
  ['a stop read with no clock is stated', { stop_captured_at: null, protection: { state: 'PROTECTED', source: 'stop store', as_of: null, counted: true } }, 'STOP_UNDATED'],
  ['a mark at or below the stop has no distance to measure', { price: 90, stop_price: 95 }, 'AT_OR_BELOW_STOP'],
]
for (const [name, o, want, at] of STATED) {
  check(name, () => {
    need(dts, 'downsideToStop is not exported')
    const { d } = one(o, at ?? NOW)
    need(d.state === want, `state ${d.state} (want ${want})`)
    need(d.usd === null && d.pct === null, `a figure was drawn: usd ${d.usd} pct ${d.pct}`)
    need(d.cell.length > 0 && d.cell !== '0' && d.cell !== '$0', `cell is blank or a false zero: "${d.cell}"`)
    need(!downsideLine(d).includes('$0'), `the line carries a false zero: ${downsideLine(d)}`)
    need(d.reason.length > 0, 'no reason is drawn')
  })
}

check('uncovered rows carry the literal uncovered state and no figure on the uncovered qty', () => {
  const { d } = one({ stop_price: null, stop_qty: null, stop_captured_at: null, protection_state: 'GAP',
    protection: { state: 'GAP', source: 'broker_resting', as_of: AT, counted: true } })
  need(d.uncoveredQty === 10, `uncoveredQty ${d.uncoveredQty}`)
  need(d.uncoveredState === 'uncovered: no stop', `uncoveredState ${d.uncoveredState}`)
})

// ── 5. The existing clock decides staleness; no new rule is introduced ──────────────────────────────
check('the off-hours limit applies to the same read off-hours', () => {
  const { d } = one({ stop_captured_at: AT_16H, protection: { state: 'PROTECTED', source: 'broker_resting', as_of: AT_16H, counted: true } }, NOW_CLOSED)
  need(d.stop.freshness === 'fresh', `freshness ${d.stop.freshness}`)
  need(d.state === 'MEASURED' && d.usd === 100, `state ${d.state} usd ${d.usd}`)
})
check('the session limit applies to the same read in session', () => {
  const { d } = one({ stop_captured_at: AT_16H, protection: { state: 'PROTECTED', source: 'broker_resting', as_of: AT_16H, counted: true } }, NOW)
  need(d.state === 'STOP_STALE', `state ${d.state}`)
})
check('no new staleness constant is added to the module', () => {
  const src = readFileSync(join(app, 'src/lib/portfolioV002.ts'), 'utf8')
  const consts = [...src.matchAll(/^export const (\w*(?:AGE|STALE|TTL|MAX|LIMIT)\w*)\s*=/gmi)].map(m => m[1])
  assert.deepEqual([...new Set(consts)].sort(), ['LIMITS', 'STOP_READ_MAX_AGE_MS'])
  need(STOP_READ_MAX_AGE_MS.session === 900_000 && STOP_READ_MAX_AGE_MS.offHours === 72 * 3_600_000, 'the shared limits changed')
  // The measure reads the shared rule, not a copy of it: its only freshness source is stopReadFreshness.
  const fn = src.slice(src.indexOf('export function downsideToStop'), src.indexOf('export function downsideLine'))
  need(fn.includes('stopReadFreshness('), 'the measure does not call stopReadFreshness')
  need(!/STOP_READ_MAX_AGE_MS\./.test(fn), 'the measure reads the limit constants directly instead of the shared rule')
})

// ── 6. Unknown cost basis blocks unrealized P&L ONLY (amendment 3) ──────────────────────────────────
check('an unknown basis never blanks the price-to-stop measure', () => {
  const { p, d } = one({ basis_status: 'missing_basis', basis_truth: { status: 'unknown', cost_basis_usd: null, gap: { reason: 'no lot record for this position' } } })
  need(d.state === 'MEASURED' && d.usd === 100, `state ${d.state} usd ${d.usd}`)
  need(d.basis.status === 'UNKNOWN', `basis ${d.basis.status}`)
  need(p.basis.pnlUsd === null, 'the fixture did not withhold P&L')
})

// ── 7. The shared stop-verdict fixture: no mark is ever derived ─────────────────────────────────────
check('the shared lq2708 books never invent a mark', () => {
  const doc = JSON.parse(readFileSync(join(app, '../../tests/fixtures/portfolio_protection_books_lq2708.json'), 'utf8'))
  const nowMs = Date.parse(doc.now)
  let rows = 0
  for (const b of doc.books) {
    for (const p of positionsFrom({ holdings: b.wire, position_counts: b.position_counts ?? { agree: true } }, nowMs)) {
      rows += 1
      const d = downsideToStop(p, { nowMs })
      need(d.usd === null, `${b.name}/${p.symbol}: a figure was derived without a published mark`)
      const allowed = ['EXEMPT', 'UNCOVERED', 'EXPIRED', 'UNVERIFIABLE', 'PLANNED_ONLY', 'MARK_MISSING', 'STOP_UNDATED', 'STOP_STALE', 'STOP_PRICE_MISSING', 'STOP_QTY_MISSING']
      need(allowed.includes(d.state), `${b.name}/${p.symbol}: unexpected state ${d.state}`)
    }
  }
  need(rows >= 9, `only ${rows} fixture rows walked`)
})

// ── 8. Table == drawer == CSV on one fixture, one clock ─────────────────────────────────────────────
const BOOK = [
  row({ symbol: 'SYNA', account_label: 'Broker A' }),
  row({ symbol: 'SYNB', shares: 100.7963, stop_qty: 100, price: 425.76, stop_price: 406.94, market_value: 42915.9 }),
  row({ symbol: 'SYNC', stop_price: null, stop_qty: null, stop_captured_at: null, protection_state: 'GAP',
    protection: { state: 'GAP', source: 'broker_resting', as_of: AT, counted: true } }),
  row({ symbol: 'SYND', basis_status: 'missing_basis', basis_truth: { status: 'unknown', cost_basis_usd: null } }),
  row({ symbol: 'SYNE', is_cash: true, asset_type: 'cash', shares: 0, market_value: 500, price: null, price_as_of: null,
    price_stale: null, stop_price: null, stop_qty: null, stop_captured_at: null, protection_state: 'EXEMPT',
    protection: { state: 'EXEMPT', source: 'policy', as_of: null, counted: false } }),
]
const SNAP = { snapshotId: 'snap-op023-synthetic', observedAt: AT }

function csvRows(text) {
  const lines = text.split('\r\n')
  const head = parseLine(lines[0])
  return lines.slice(1).map(l => Object.fromEntries(parseLine(l).map((v, i) => [head[i], v])))
}
function parseLine(line) {
  const out = []
  let cur = '', q = false
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i]
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i += 1 }
      else if (c === '"') q = false
      else cur += c
    } else if (c === '"') q = true
    else if (c === ',') { out.push(cur); cur = '' }
    else cur += c
  }
  out.push(cur)
  return out
}

function renderPage(rows) {
  const holdings = ok(API.holdings, wire(rows))
  const positions = positionsFrom(holdings.data, NOW)
  const prot = protectionModel(holdings, positions)
  const props = {
    holdings, positions, prot, p0: p0Items(holdings, prot),
    status: statusRows(holdings, ok(API.incidents, { counts: { P0: 0, P1: 0 }, served_at: AT }), positions, NOW),
    measures: measuresModel(holdings), sinceVisit: sinceVisitModel(LAST_SEEN_UNKNOWN), visitRecord: 'PENDING',
    nowIso: new Date(NOW).toISOString(), filter: 'all', account: 'all', shownCount: 25, showAllAction: false,
    onFilter: noop, onAccount: noop, onShowMore: noop, onShowAllAction: noop, onOpenWhy: noop, onOpenDiag: noop,
    onOpenAudit: noop, onOpenPosition: noop, onOpenMeasures: noop, onOpenMeasure: noop, onOpenGates: noop,
    onOpenSince: noop, onOpenSync: noop, onOpenRisk: noop, onExportCsv: noop,
  }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(View, props)))
}
const renderSheet = props => renderToStaticMarkup(React.createElement(MemoryRouter, null,
  React.createElement(sheets.RiskSheet, { open: true, onClose: noop, ...props })))

check('the table draws the exact figure and state for every row', () => {
  need(dts, 'downsideToStop is not exported')
  const html = renderPage(BOOK)
  const positions = positionsOf(BOOK)
  need(html.includes('data-testid="row-risk"'), 'the Risk column has no cell')
  need(!/data-testid="row-risk"[^>]*>—</.test(html), 'a Risk cell is still a blank dash')
  const facts = [...html.matchAll(/data-testid="row-downside"[^>]*>([^<]*)</g)].map(m => m[1])
  need(facts.length === BOOK.length, `draws ${facts.length} downside lines for ${BOOK.length} rows`)
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    need(facts.includes(downsideLine(d)), `${p.symbol}: the row does not draw "${downsideLine(d)}"`)
  }
  const cells = [...html.matchAll(/data-testid="row-risk"[^>]*data-state="([^"]+)"[^>]*>([^<]*)/g)]
  need(cells.length === BOOK.length, `draws ${cells.length} Risk cells`)
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    const cell = cells.find(c => c[1] === d.state)
    need(cell, `${p.symbol}: no cell in state ${d.state}`)
    need(cell[2].startsWith(d.cell), `${p.symbol}: cell "${cell[2]}" does not start with "${d.cell}"`)
  }
})

check('the drawer draws the same line, value, inputs and arithmetic', () => {
  need(dts, 'downsideToStop is not exported')
  const positions = positionsOf(BOOK)
  const html = renderSheet({ rows: positions, nowMs: NOW })
  need(html.includes('Composite risk score: no approved methodology'), 'the sheet lost the composite label')
  need(html.includes('Hypothetical downside to stop (verified stop price)'), 'the sheet lost the mandated label')
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    need(html.includes(`data-testid="risk-line">${escapeHtml(downsideLine(d))}<`), `${p.symbol}: drawer line differs`)
    need(html.includes(`data-testid="risk-mark">mark ${escapeHtml(fmtUsd(d.mark.value))}`), `${p.symbol}: mark input missing`)
    need(html.includes(`data-testid="risk-stop">stop ${escapeHtml(d.stop.value == null ? 'not published' : fmtUsd(d.stop.value))}`), `${p.symbol}: stop input missing`)
    if (d.usd != null) need(html.includes(`data-testid="risk-arithmetic">${escapeHtml(d.formula)}<`), `${p.symbol}: arithmetic missing`)
    need(html.includes(`data-testid="risk-basis">cost basis ${d.basis.status === 'RECORDED' ? 'recorded' : 'unknown'}`), `${p.symbol}: basis line missing`)
  }
})

check('the CSV carries the same values, states and formula', () => {
  need(dts, 'downsideToStop is not exported')
  const positions = positionsOf(BOOK)
  const csv = csvRows(holdingsCsv(positions, SNAP, NOW))
  need(csv.length === BOOK.length, `CSV has ${csv.length} rows`)
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    const r = csv.find(x => x.symbol === p.symbol)
    need(r, `${p.symbol}: missing from the CSV`)
    need(r.downside_state === d.state, `${p.symbol}: csv state ${r.downside_state} vs ${d.state}`)
    need(r.hypothetical_downside_to_stop_usd === (d.usd == null ? '' : String(d.usd)), `${p.symbol}: csv usd ${r.hypothetical_downside_to_stop_usd} vs ${d.usd}`)
    need(r.downside_covered_qty === (d.coveredQty == null ? '' : String(d.coveredQty)), `${p.symbol}: csv covered ${r.downside_covered_qty}`)
    need(r.downside_uncovered_qty === (d.uncoveredQty == null ? '' : String(d.uncoveredQty)), `${p.symbol}: csv uncovered ${r.downside_uncovered_qty}`)
    need(r.downside_uncovered_state === (d.uncoveredState ?? ''), `${p.symbol}: csv uncovered state ${r.downside_uncovered_state}`)
    need(r.downside_formula === d.formula, `${p.symbol}: csv formula differs`)
    need(r.downside_reason === d.reason, `${p.symbol}: csv reason differs`)
    if (d.usd != null) need(Number(r.hypothetical_downside_to_stop_pct_of_mark) === Number(d.pct.toFixed(2)), `${p.symbol}: csv pct ${r.hypothetical_downside_to_stop_pct_of_mark}`)
  }
  // The unknown-basis row keeps its measure AND withholds the P&L (amendment 3), in the file itself.
  const d4 = csv.find(x => x.symbol === 'SYND')
  need(d4.hypothetical_downside_to_stop_usd === '100', `SYND csv usd ${d4.hypothetical_downside_to_stop_usd}`)
  need(d4.unrealized_pnl_usd === '', `SYND csv drew a P&L: ${d4.unrealized_pnl_usd}`)
  need(d4.basis_status === 'UNKNOWN', `SYND basis ${d4.basis_status}`)
  // The uncovered row has no figure anywhere.
  const c3 = csv.find(x => x.symbol === 'SYNC')
  need(c3.hypothetical_downside_to_stop_usd === '' && c3.hypothetical_downside_to_stop_pct_of_mark === '', 'SYNC exported a figure')
  need(c3.downside_uncovered_state === 'uncovered: no stop', `SYNC uncovered state ${c3.downside_uncovered_state}`)
})

check('the three surfaces agree row-for-row', () => {
  need(dts, 'downsideToStop is not exported')
  const positions = positionsOf(BOOK)
  const html = renderPage(BOOK)
  const drawer = renderSheet({ rows: positions, nowMs: NOW })
  const csv = csvRows(holdingsCsv(positions, SNAP, NOW))
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    const inTable = html.includes(escapeHtml(downsideLine(d)))
    const inDrawer = drawer.includes(`data-testid="risk-line">${escapeHtml(downsideLine(d))}<`)
    const inCsv = csv.find(x => x.symbol === p.symbol).downside_state === d.state
    need(inTable && inDrawer && inCsv, `${p.symbol}: table ${inTable}, drawer ${inDrawer}, csv ${inCsv}`)
  }
})

check('the CSV header is served labels only, and the new block is additive', () => {
  const head = holdingsCsv([], null, NOW).split('\r\n')[0].split(',')
  for (const c of ['symbol', 'coverage', 'protection', 'stop_price', 'verified_at',
    'hypothetical_downside_to_stop_usd', 'hypothetical_downside_to_stop_pct_of_mark', 'downside_state', 'downside_coverage',
    'downside_covered_qty', 'downside_uncovered_qty', 'downside_uncovered_state', 'downside_reason', 'downside_formula']) {
    need(head.includes(c), `missing CSV column ${c}`)
  }
  need(head.indexOf('snapshot_id') === head.length - 2, 'the identity columns are no longer last')
})

// ── 9. The page says what the column is, in the operator's words ────────────────────────────────────
check('the table states the label and the composite decision', () => {
  const html = renderPage([row({})])
  need(html.includes('Hypothetical downside to stop (verified stop price)'), 'the header/title lost the label')
  // N1 (review cc-deepseek-4, 19:05Z): pin the COLUMN HEADER CELL itself, not just "the label appears somewhere".
  // Before this line the row titles satisfied the check above, so a header-only regression (its mutant M8 turned the
  // cell into "Loss to stop") stayed green. This is the one label the operator reads as the column name.
  need(/class="risk-h" title="Hypothetical downside to stop \(verified stop price\)">Risk</.test(html),
    'the Risk column header lost its mandated title or visible name')
  need(html.includes('Composite risk score: no approved methodology'), 'the composite decision is missing')
  need(/not a loss/.test(html), 'the page no longer says the figure is not a loss')
})

// ── 10. DRAWER-CSV-RISK-PARITY (operator on R8b 331b658c1, 2026-11-14 20:59Z assignment) ─────────────
// The row drew the measured downside while the position DRAWER (positionFields → PositionSheet) printed only
// "PENDING DECISION / G7". The drawer now draws the SAME `downsideToStop` derivation at the SAME clock, and the CSV
// states the coverage word beside it. The composite score keeps its exact undecided statement in its own field.
// Synthetic fixtures only (the repository is public).
const S_COVERED = row({ symbol: 'SYNP' })                                          // stop for all 10 shares
const S_PARTIAL = row({ symbol: 'SYNQ', shares: 10, stop_qty: 4 })                 // stop for 4 of 10
const S_UNCOVERED = row({ symbol: 'SYNR', stop_price: null, stop_qty: null, stop_captured_at: null,
  protection_state: 'GAP', protection: { state: 'GAP', source: 'broker_resting', as_of: AT, counted: true } })
const S_STATED = row({ symbol: 'SYNS', stop_price: null })                          // PROTECTED, no verified stop price
// F1 (REVIEW 2148Z): a resting quantity for 4 of 10 shares with the stop price unverified. The measure withholds the
// split there, so the drawer must not read it as full coverage — this is the state the operator's drawer opens on.
const S_PARTSTALE = row({ symbol: 'SYNV', shares: 10, stop_qty: 4, stop_price: null })
const S_UNVERIF = row({ symbol: 'SYNT', protection_state: 'UNKNOWN',
  protection: { state: 'UNKNOWN', cause: 'No Stop Read', source: 'stop store', as_of: null, counted: true } })
const S_ATBELOW = row({ symbol: 'SYNU', price: 90, stop_price: 95 })                 // mark at/below the stop
const PARITY = [S_COVERED, S_PARTIAL, S_UNCOVERED, S_STATED, S_PARTSTALE, S_UNVERIF, S_ATBELOW]

function positionDrawer(p, rows) {
  return renderToStaticMarkup(React.createElement(MemoryRouter, null,
    React.createElement(sheets.PositionSheet, { pos: p, onClose: noop, holdings: wire(rows), nowIso: new Date(NOW).toISOString() })))
}
const riskField = (p, rows) => lib.positionFields(p, wire(rows), NOW).find(f => f.field === 'Risk')
const drawerValue = d => (d.usd != null ? `${fmtUsd(d.usd)} · ${d.pct.toFixed(1)}% below the mark` : d.cell)

check('the position drawer draws the row\'s measured figure, and the composite stays undecided', () => {
  need(typeof lib.positionFields === 'function', 'positionFields is not exported')
  const positions = positionsOf(BOOK)
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    const fields = lib.positionFields(p, wire(BOOK), NOW)
    const f = fields.find(x => x.field === 'Risk')
    // The mutant that DROPS the drawer field dies here (and again in the rendered assertion below).
    need(f, `${p.symbol}: the drawer has no Risk field`)
    need(f.value === drawerValue(d), `${p.symbol}: drawer Risk "${f.value}" vs the row's "${drawerValue(d)}"`)
    need(f.provenance.startsWith(`${downsideLine(d)}.`), `${p.symbol}: drawer provenance does not open with the row's facts line: ${f.provenance}`)
    const comp = fields.find(x => x.field === 'Composite risk score')
    need(comp, `${p.symbol}: the composite field disappeared`)
    need(comp.value === 'PENDING DECISION', `${p.symbol}: the composite changed to "${comp.value}"`)
    need(comp.provenance === 'no approved risk-score definition (G7); nothing is scored here', `${p.symbol}: the composite provenance changed`)
  }
  // Rendered: the drawer markup itself carries the figure, and the composite sentinel appears exactly once.
  const p0 = positions[0]
  const d0 = downsideToStop(p0, { nowMs: NOW })
  const html = positionDrawer(p0, BOOK)
  need(html.includes(`<span class="f">Risk</span><span class="v">${escapeHtml(drawerValue(d0))}</span>`),
    `the rendered drawer does not print Risk "${drawerValue(d0)}"`)
  need(html.includes('<span class="f">Composite risk score</span><span class="v">PENDING DECISION</span>'),
    'the rendered drawer lost the composite statement')
  need((html.match(/PENDING DECISION/g) || []).length === 1, 'the drawer prints the composite sentinel more than once')
})

check('row, drawer and CSV agree on a covered, a partial, an uncovered and a stated row', () => {
  need(dts, 'downsideToStop is not exported')
  const expect = { SYNP: 'covered', SYNQ: 'partial', SYNR: 'uncovered', SYNS: 'unknown', SYNV: 'unknown', SYNT: 'unknown', SYNU: 'covered' }
  const html = renderPage(PARITY)
  const positions = positionsOf(PARITY)
  const csv = csvRows(holdingsCsv(positions, SNAP, NOW))
  need(positions.length === PARITY.length, `positions ${positions.length} of ${PARITY.length}`)
  for (const p of positions) {
    const d = downsideToStop(p, { nowMs: NOW })
    const cov = lib.downsideCoverage(d)
    need(cov === expect[p.symbol], `${p.symbol}: coverage "${cov}", expected "${expect[p.symbol]}" (state ${d.state})`)
    // ROW: the facts line the row draws is the one derived here.
    need(html.includes(escapeHtml(downsideLine(d))), `${p.symbol}: the row does not draw "${downsideLine(d)}"`)
    // DRAWER: the same figure, never a recomputed one.
    const f = riskField(p, PARITY)
    need(f, `${p.symbol}: the drawer has no Risk field`)
    need(f.value === drawerValue(d), `${p.symbol}: drawer "${f.value}" vs row "${drawerValue(d)}"`)
    // F2 (REVIEW 2148Z): the composed sentence must not end a sentence twice ("…held shares.. No figure is drawn.").
    need(!f.provenance.includes('..'), `${p.symbol}: doubled full stop in the drawer provenance: ${f.provenance}`)
    // CSV: the same figure, the same state and the same coverage word.
    const r = csv.find(x => x.symbol === p.symbol)
    need(r, `${p.symbol}: missing from the CSV`)
    need(r.downside_coverage === cov, `${p.symbol}: csv coverage "${r.downside_coverage}" vs "${cov}"`)
    need(r.downside_state === d.state, `${p.symbol}: csv state "${r.downside_state}" vs "${d.state}"`)
    need((r.hypothetical_downside_to_stop_usd || '') === (d.usd == null ? '' : String(d.usd)), `${p.symbol}: csv usd "${r.hypothetical_downside_to_stop_usd}" vs ${d.usd}`)
    need((r.hypothetical_downside_to_stop_pct_of_mark || '') === (d.pct == null ? '' : String(Number(d.pct.toFixed(2)))), `${p.symbol}: csv pct "${r.hypothetical_downside_to_stop_pct_of_mark}" vs ${d.pct}`)
  }
  // PARTIAL: 4 of 10 covered — the uncovered leg is named in words in the drawer and as its own state in the CSV.
  const q = positions.find(p => p.symbol === 'SYNQ')
  const dq = downsideToStop(q, { nowMs: NOW })
  need(dq.state === 'PARTIAL' && dq.coveredQty === 4 && dq.uncoveredQty === 6, `partial ${dq.state} ${dq.coveredQty}/${dq.uncoveredQty}`)
  const fq = riskField(q, PARITY)
  need(/The resting stop covers 4 of 10 held shares; 6 carry no resting order \(uncovered: no stop\)\./.test(fq.provenance),
    `the partial row's drawer does not name the uncovered leg: ${fq.provenance}`)
  const rq = csv.find(x => x.symbol === 'SYNQ')
  need(rq.downside_uncovered_qty === '6' && rq.downside_uncovered_state === 'uncovered: no stop', `partial csv uncovered "${rq.downside_uncovered_qty}" / "${rq.downside_uncovered_state}"`)
  // UNCOVERED: no figure anywhere — row state, drawer state, CSV state.
  const u = positions.find(p => p.symbol === 'SYNR')
  const du = downsideToStop(u, { nowMs: NOW })
  need(du.usd == null && du.state === 'UNCOVERED', `uncovered state ${du.state} usd ${du.usd}`)
  const fu = riskField(u, PARITY)
  need(fu.value === du.cell && !fu.value.includes('$'), `the uncovered drawer prints a figure: "${fu.value}"`)
  need(/No resting order covers this position \(uncovered: no stop\)\./.test(fu.provenance), `the uncovered drawer lost its words: ${fu.provenance}`)
  const ru = csv.find(x => x.symbol === 'SYNR')
  need(ru.hypothetical_downside_to_stop_usd === '' && ru.hypothetical_downside_to_stop_pct_of_mark === '', 'the uncovered CSV row exported a figure')
  // STATED (PROTECTED, no verified stop price): the drawer states the state, never a number or a zero.
  const s = positions.find(p => p.symbol === 'SYNS')
  const ds = downsideToStop(s, { nowMs: NOW })
  need(ds.state === 'STOP_PRICE_MISSING', `stated state ${ds.state}`)
  const fs_ = riskField(s, PARITY)
  need(fs_.value === ds.cell && !fs_.value.includes('$'), `the stated drawer prints a figure: "${fs_.value}"`)
  need(fs_.needsBackend === true, 'the stated drawer does not ask for the missing backend input')
  need(!/covers all/i.test(fs_.provenance), `the stated drawer (unverified stop level) claims full coverage: ${fs_.provenance}`)
  // UNVERIFIABLE: a failed read establishes nothing — not the distance, not the coverage. It must never claim
  // "N shares uncovered: no stop" (that is a statement about a book the read could not open), and the coverage
  // word must be unknown, not partial.
  const t = positions.find(p => p.symbol === 'SYNT')
  const dt = downsideToStop(t, { nowMs: NOW })
  need(dt.state === 'UNVERIFIABLE' && dt.usd == null, `unread book ${dt.state} usd ${dt.usd}`)
  need(dt.uncoveredQty == null && dt.uncoveredState == null, `an unread book published an uncovered claim: ${dt.uncoveredQty} / ${dt.uncoveredState}`)
  need(lib.downsideCoverage(dt) === 'unknown', `unread book coverage "${lib.downsideCoverage(dt)}"`)
  const ft = riskField(t, PARITY)
  need(ft.value === dt.cell, `unread book drawer "${ft.value}" vs "${dt.cell}"`)
  need(/Coverage cannot be established from this read/.test(ft.provenance), `unread book drawer lost its words: ${ft.provenance}`)
  const rt = csv.find(x => x.symbol === 'SYNT')
  need(rt.downside_coverage === 'unknown' && rt.downside_uncovered_qty === '' && rt.downside_uncovered_state === '', `unread book csv "${rt.downside_coverage}" / "${rt.downside_uncovered_qty}" / "${rt.downside_uncovered_state}"`)
  // AT/BELOW THE STOP: both quantities ARE published, so the coverage word is established even with no distance.
  const a = positions.find(p => p.symbol === 'SYNU')
  const da = downsideToStop(a, { nowMs: NOW })
  need(da.state === 'AT_OR_BELOW_STOP' && da.coveredQty === 10 && da.uncoveredQty === 0, `at/below ${da.state} ${da.coveredQty}/${da.uncoveredQty}`)
  need(riskField(a, PARITY).value === da.cell, 'the at/below drawer draws something other than its state')
  need(csv.find(x => x.symbol === 'SYNU').downside_coverage === 'covered', 'the at/below CSV row lost its coverage word')
})

check('a partial resting quantity with an unverified stop never reads as full coverage (F1)', () => {
  // 10 held, a resting order recorded for 4, no verified stop price. The measure withholds the split (uncoveredQty
  // null) and the CSV word is therefore `unknown`; the drawer's sentence must agree and must never say "all".
  const p = positionsOf([S_PARTSTALE])[0]
  const d = downsideToStop(p, { nowMs: NOW })
  need(d.state === 'STOP_PRICE_MISSING', `fixture state ${d.state}`)
  need(d.coveredQty === 4 && d.uncoveredQty == null, `fixture covered ${d.coveredQty} uncovered ${d.uncoveredQty}`)
  const f = riskField(p, [S_PARTSTALE])
  need(f, 'the drawer has no Risk field')
  need(!/covers all/i.test(f.provenance), `the drawer claims full coverage for a 4-of-10 position: ${f.provenance}`)
  need(/recorded against 4 of 10 held shares/.test(f.provenance), `the drawer does not name the recorded quantity: ${f.provenance}`)
  need(/6 carry no resting order recorded/.test(f.provenance), `the drawer does not name the uncovered quantity: ${f.provenance}`)
  need(f.provenance.includes('coverage is not established (unknown)'), `the drawer does not carry the coverage word: ${f.provenance}`)
  need(!f.provenance.includes('..'), `doubled full stop: ${f.provenance}`)
  const r = csvRows(holdingsCsv(positionsOf([S_PARTSTALE]), SNAP, NOW)).find(x => x.symbol === 'SYNV')
  need(r, 'the row is missing from the CSV')
  need(r.downside_coverage === lib.downsideCoverage(d), `drawer word vs csv word: "${r.downside_coverage}"`)
  need(r.downside_coverage === 'unknown', `csv coverage "${r.downside_coverage}"`)
  need(r.downside_uncovered_qty === '' && r.downside_uncovered_state === '', `the withheld split leaked into the CSV: "${r.downside_uncovered_qty}" / "${r.downside_uncovered_state}"`)
})

check('the drawer Risk field is unique and the CSV header states its units', () => {
  for (const p of positionsOf(BOOK)) {
    const names = lib.positionFields(p, wire(BOOK), NOW).map(f => f.field)
    need(new Set(names).size === names.length, `duplicate drawer field names (React keys): ${names.join(' / ')}`)
    const sentinels = lib.positionFields(p, wire(BOOK), NOW).filter(f => f.value === 'PENDING DECISION')
    need(sentinels.length === 1 && sentinels[0].field === 'Composite risk score',
      `${p.symbol}: the composite sentinel ${sentinels.length === 1 ? `sits on "${sentinels[0].field}"` : `appears ${sentinels.length}×`}`)
  }
  const head = holdingsCsv([], null, NOW).split('\r\n')[0].split(',')
  need(head.includes('hypothetical_downside_to_stop_usd'), 'the dollar column does not state its unit')
  need(head.includes('hypothetical_downside_to_stop_pct_of_mark'), 'the percent column does not state its unit (of the mark)')
  need(!head.includes('hypothetical_downside_to_stop_pct'), 'the unitless percent header survived')
  need(head.includes('downside_coverage'), 'the coverage column is missing')
})

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

// ── report ──────────────────────────────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error(`${failures.length} failed / ${checks - failures.length} passed`)
  for (const f of failures) console.error(`  ✗ ${f}`)
  process.exit(1)
}
console.log(`portfolioRiskMeasured: ${checks} checks passed`)
