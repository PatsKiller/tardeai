// Portfolio v002 page model (design/pages/portfolio/v002, approved 2026-11-11). Unknown beats wrong:
// UNKNOWN is never drawn as NO STOP, a failed read is never OK or "0", a pending-activation GTC stop counts.
// Synthetic fixtures only (public repo): placeholder symbols, accounts and values.
import assert from 'node:assert/strict'
import {
  readOnce, positionsFrom, protectionModel, p0Items, statusRows, filterPositions, rowProtection, auditCategories, sessionOpenET,
  measuresModel, coverageCounts, coverageOf, holdingsCsv, CSV_COLUMNS, stopDeskHref, sinceVisitModel, gateEvidence, RISK_SCORE,
  MEASURES_ABSENT_REASON, MEASURE_KEYS,
  type HoldingWire, type HoldingsWire, type Read, type IncidentsWire, type LastSeenWire, type MeasuresBlockWire,
} from './portfolioV002.ts'

const AT = '2031-03-07T14:59:00Z'
const NOW = Date.parse('2031-03-07T15:00:00Z')
const ok = <T,>(data: T, source = '/api/v2/portfolio/holdings'): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })
const row = (o: Partial<HoldingWire>): HoldingWire => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', broker: 'broker_a',
  shares: 10, market_value: 1000, price: 100, price_as_of: AT, protection_state: 'PROTECTED',
  protection: { state: 'PROTECTED', reason: 'Resting stop', source: 'stop store', as_of: AT, counted: true }, stop_price: 90, ...o })
const wire = (rows: HoldingWire[], o: Partial<HoldingsWire> = {}): HoldingsWire => ({ holdings: rows, total_value: 5000, today_change: 12,
  positions_as_of: AT, valuation_as_of: AT, quote_as_of: AT, position_counts: { agree: true }, ...o })
/** The SHAPE the served contract emits (scripts/lib/position_count_authority.py counts_for_rows → PositionCountAuthority@v1):
 *  named scopes, `agree` = "every scope has the same value" (false on every real book: cash/under-$100/unpriced rows
 *  are different populations), findings [] unless the contract found something. C5/C6 fixtures use this, not invented shapes. */
type ServedCounts = NonNullable<HoldingsWire['position_counts']>
const servedCounts = (o: Partial<ServedCounts> = {}): ServedCounts => ({
  contract_version: 'PositionCountAuthority@v1', primary_scope: 'holdings.non_cash_over_100',
  agree: false, position_count: 11, held_count: 28, all_rows: 33, cash_rows: 5, non_cash_rows: 28, below_100: 14,
  distinct_values: [3, 5, 11, 14, 25, 28, 33],
  scopes: { 'holdings.all_rows': 33, 'holdings.cash': 5, 'holdings.non_cash': 28, 'holdings.non_cash_over_100': 11,
    'holdings.held_under_100': 14, 'holdings.unpriced': 3, 'holdings.position': 28 },
  summary: '11 positions at or above $100 · 14 held under $100 · 3 unpriced lots excluded',
  findings: [], ...o,
})

// 1. UNKNOWN is never NO STOP: every UNKNOWN cause keeps the UNKNOWN chip.
for (const cause of ['No Stop Read', 'Stop Read Failed', 'Stop State Unproven']) {
  const r = rowProtection(row({ protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause, counted: true }, stop_price: null }))
  assert.equal(r.protection, 'UNKNOWN'); assert.equal(r.chip, 'UNKNOWN'); assert.equal(r.cause, cause)
  assert.notEqual(r.chip, 'NO STOP')
}
// A row without a backend verdict is UNKNOWN, never guessed from the stop fields (I1/I2).
const bare = rowProtection(row({ protection_state: null, protection: null, stop_price: null, stop_state: null }))
assert.equal(bare.protection, 'UNKNOWN'); assert.equal(bare.cause, 'No Protection Verdict')

// 2. A pending-activation GTC stop the backend calls PROTECTED gives OK (fail-before: storedStops dropped it).
const pend = positionsFrom(wire([row({ symbol: 'BBB', stop_state: 'pending_activation' }), row({ symbol: 'CCC', market_value: 2000 })]))
const pm = protectionModel(ok(wire([])), pend)
assert.equal(pm.verdict, 'OK'); assert.equal(pm.counted, 2); assert.equal(pm.protectedN, 2); assert.equal(pm.action.length, 0)

// 3. D1: an expired stop after the close is WARN, never OK; GAP outranks UNKNOWN outranks WARN (LQ-2460 F3).
const CLOSED = Date.parse('2031-03-08T15:00:00Z')   // Saturday
const exp = rowProtection(row({ protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_state: 'expired' }), { nowMs: CLOSED })
assert.equal(exp.protection, 'WARN'); assert.equal(exp.chip, 'EXPIRED')
const mixed = positionsFrom(wire([
  row({ symbol: 'UUU', market_value: 9000, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true } }),
  row({ symbol: 'EEE', market_value: 3000, protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_state: 'expired' }),
  row({ symbol: 'GGG', market_value: 500, protection_state: 'GAP', protection: { state: 'GAP', counted: true } }),
  row({ symbol: 'PPP', market_value: 4000 }),
  row({ symbol: 'TINY', market_value: 40, protection_state: 'GAP', protection: { state: 'GAP', counted: false } }),
  row({ symbol: 'CASH', market_value: 700, is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } }),
  row({ symbol: 'SMOL', market_value: 40 , protection: { state: 'PROTECTED', as_of: AT, counted: false } }),
]), CLOSED)
const mm = protectionModel(ok(wire([])), mixed)
assert.equal(mm.verdict, 'GAP')
// GAP, then UNKNOWN, then WARN (backend order) — not by value. TINY is a KNOWN $40 GAP: listed, not counted (DECISIONS).
assert.deepEqual(mm.action.map(p => p.symbol), ['GGG', 'UUU', 'EEE'])
assert.equal(mm.counted, 4); assert.equal(mm.listedNotCounted, 2); assert.equal(mm.exempt, 1)
assert.equal(mm.gap, 1); assert.equal(mm.warn, 1); assert.equal(mm.unknown, 1)
const onlyUnk = protectionModel(ok(wire([])), mixed.filter(p => p.symbol === 'UUU' || p.symbol === 'PPP'))
assert.equal(onlyUnk.verdict, 'UNKNOWN')   // an unread stop never rolls up to OK
assert.equal(onlyUnk.brokers[0].state, 'UNKNOWN')

// 4. P0 counts GAP rows and a count-block FINDING; it is null (never 0) when the read failed.
// C6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): `agree:false` is the cross-scope flag — every real book with a
// cash row or an under-$100 row sets it — so it is NEVER a P0. Only a published finding is.
const healthyRead = ok(wire([row({ symbol: 'SAFE' })], { position_counts: servedCounts() }))
assert.deepEqual(p0Items(healthyRead, protectionModel(healthyRead, positionsFrom(healthyRead.data, NOW))), [])
// The same healthy block with one published finding yields exactly one P0 carrying that finding's detail.
const findingRead = ok(wire([row({ symbol: 'SAFE' })], { position_counts: servedCounts({ findings: [{ code: 'LIVE_MARK_COUNT_DIFFERS', detail: 'the live re-mark counts 13 instruments at or above $100 where the positions store counts 11' }] }) }))
const findingP0 = p0Items(findingRead, protectionModel(findingRead, positionsFrom(findingRead.data, NOW)))!
assert.deepEqual(findingP0.map(x => x.category), ['Position Count Mismatch'])
assert.match(findingP0[0].detail, /13 instruments/)
const gapP0 = p0Items(ok(wire([])), mm)!
assert.deepEqual(gapP0.map(x => x.category), ['Unprotected Position'])
const p0 = gapP0   // later cases read the P0 list of the mixed book
const failed: Read<HoldingsWire> = { state: 'UNKNOWN', data: null, error: 'HTTP 503', at: AT, source: '/api/v2/portfolio/holdings' }
assert.equal(p0Items(failed, protectionModel(failed, [])), null)

// 5. Failed / empty / timed-out reads are never OK.
assert.equal(protectionModel(failed, []).verdict, 'UNKNOWN')
assert.equal(protectionModel(ok(wire([])), []).verdict, 'UNKNOWN')
const timedOut: Read<HoldingsWire> = { ...failed, state: 'TIMED OUT' }
assert.equal(protectionModel(timedOut, []).verdict, 'TIMED OUT')

// 6. readOnce: a hung fetch becomes TIMED OUT; HTTP errors become UNKNOWN; {ok,data} is unwrapped. Never throws.
const hung = ((_: string, init?: RequestInit) => new Promise((_r, rej) => {
  init?.signal?.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' })))
})) as unknown as typeof fetch
assert.equal((await readOnce('/api/x', 20, hung)).state, 'TIMED OUT')
const http503 = (async () => new Response('no', { status: 503 })) as unknown as typeof fetch
assert.equal((await readOnce('/api/x', 1000, http503)).state, 'UNKNOWN')
const wrapped = (async () => new Response(JSON.stringify({ ok: true, data: { total_value: 1 } }), { status: 200 })) as unknown as typeof fetch
const wr = await readOnce<HoldingsWire>('/api/x', 1000, wrapped)
assert.equal(wr.state, 'OK'); assert.equal(wr.data?.total_value, 1)

// 7. Status rows: Risk is UNKNOWN + NEEDS BACKEND; a failed incidents read is not "0 alerts".
const inc: Read<IncidentsWire> = { state: 'UNKNOWN', data: null, error: 'HTTP 500', at: AT, source: '/api/v2/home/incidents' }
const rows = statusRows(ok(wire([])), inc, mixed, NOW)
const risk = rows.find(r => r.id === 'row-risk')!; assert.equal(risk.state, 'UNKNOWN'); assert.equal(risk.needsBackend, true)
const alerts = rows.find(r => r.id === 'row-alerts')!; assert.notEqual(alerts.state, 'OK'); assert.doesNotMatch(alerts.text, /^0\b/)

// 8. Filters: unprotected = counted GAP + WARN; unknown = UNKNOWN; under $100 = known value under the floor, any state.
assert.deepEqual(filterPositions(mixed, 'unprotected', 'all').map(p => p.symbol).sort(), ['EEE', 'GGG'])
assert.deepEqual(filterPositions(mixed, 'unknown', 'all').map(p => p.symbol), ['UUU'])
assert.deepEqual(filterPositions(mixed, 'under100', 'all').map(p => p.symbol).sort(), ['SMOL', 'TINY'])
assert.equal(mixed.find(p => p.symbol === 'TINY')!.protection, 'GAP')   // listed with its real state, not hidden

// 9. Audit categories come from the same model (no second source of truth).
assert.ok(auditCategories(mm, p0).some(c => c.category.includes('Unprotected')))

// 10. LQ-20261107-2460 (REVIEW-2448 F1-F4): the client verdict errs to UNKNOWN, never to OK.
const gapRow = (o: Partial<HoldingWire> = {}, p: Record<string, unknown> = {}) =>
  row({ symbol: 'GAP1', protection_state: 'GAP', stop_price: null, protection: { state: 'GAP', counted: true, as_of: AT, ...p }, ...o })
const okRow = (sym: string) => row({ symbol: sym, market_value: 5000 })
const verdictOf = (rows: HoldingWire[], nowMs = NOW, o: Partial<HoldingsWire> = {}) => protectionModel(ok(wire(rows, o)), positionsFrom(wire(rows, o), nowMs))

// F1: an unpriced GAP (backend counted:false, no market value, no price) stays a GAP; the page cannot read OK.
const unpriced = gapRow({ market_value: null, price: null }, { counted: false })
const f1 = verdictOf([okRow('PPP'), unpriced])
assert.equal(f1.verdict, 'GAP'); assert.equal(f1.gap, 1); assert.equal(f1.counted, 2); assert.equal(f1.listedNotCounted, 0)
assert.deepEqual(p0Items(ok(wire([])), f1)!.map(x => x.category), ['Unprotected Position'])
// ...and an unpriced UNKNOWN row is not hidden either.
const unpricedUnk = row({ symbol: 'UNP', market_value: null, price: null, protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: false } })
assert.equal(verdictOf([okRow('PPP'), unpricedUnk]).verdict, 'UNKNOWN')
// The floor drops a row with a KNOWN value under $100 from the count, whatever its state (DECISIONS-20261111).
const small = positionsFrom(wire([row({ symbol: 'SML', market_value: 50, protection: { state: 'PROTECTED', as_of: AT, counted: false } })]), NOW)[0]
assert.equal(small.counted, false); assert.equal(small.underFloor, true)

// LQ-2469 (folded, cc-sonnet-1 tests 3b): an unknown value is never small.
const unp = positionsFrom(wire([
  row({ symbol: 'NOPX', market_value: null, price: null, protection_state: 'GAP', protection: { state: 'GAP', counted: false } }),
  row({ symbol: 'PPP', market_value: 4000 }),
]), NOW)
const unpModel = protectionModel(ok(wire([])), unp)
assert.equal(unp.find(p => p.symbol === 'NOPX')!.counted, true); assert.equal(unp.find(p => p.symbol === 'NOPX')!.unpriced, true)
assert.equal(unpModel.verdict, 'GAP'); assert.equal(unpModel.gap, 1); assert.equal(unpModel.listedNotCounted, 0)
assert.deepEqual(unpModel.action.map(p => p.symbol), ['NOPX'])
assert.equal(protectionModel(ok(wire([])), unp.filter(p => p.symbol === 'NOPX')).verdict, 'GAP')
// an unpriced PROTECTED row is counted too (never silently small)
const unpProt = positionsFrom(wire([row({ symbol: 'NOPX', market_value: null, protection: { state: 'PROTECTED', as_of: AT, counted: false } })]), NOW)
assert.equal(unpProt[0].counted, true); assert.equal(protectionModel(ok(wire([])), unpProt).verdict, 'OK')
// the served price_missing flag counts the row even if a stale market_value rides along
const pm2 = positionsFrom(wire([row({ market_value: 0, protection_state: 'GAP', protection: { state: 'GAP', counted: false, price_missing: true } })]), NOW)[0]
assert.equal(pm2.counted, true); assert.equal(pm2.underFloor, false)
// a KNOWN $40 GAP is listed, not counted; an unpriced cash/exempt row is not counted and not 'unpriced'
const g40 = positionsFrom(wire([row({ market_value: 40, protection_state: 'GAP', protection: { state: 'GAP', counted: false } })]), NOW)[0]
assert.equal(g40.counted, false); assert.equal(g40.underFloor, true); assert.equal(g40.protection, 'GAP')
const ucash = positionsFrom(wire([row({ market_value: null, is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })]), NOW)[0]
assert.equal(ucash.counted, false); assert.equal(ucash.unpriced, false); assert.equal(ucash.underFloor, false)

// F2: zero counted positions is UNKNOWN unless the position count confirms zero.
const cashOnly = [row({ symbol: 'CASH', is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })]
const f2 = verdictOf(cashOnly)
assert.equal(f2.verdict, 'UNKNOWN'); assert.equal(f2.counted, 0); assert.ok(f2.cause)
// LQ-2469 3c: cash plus a known $40 PROTECTED row is still zero counted -> UNKNOWN, never CLEAR.
assert.equal(verdictOf([...cashOnly, row({ symbol: 'TINY', market_value: 40, protection: { state: 'PROTECTED', as_of: AT, counted: false } })]).verdict, 'UNKNOWN')
assert.equal(verdictOf(cashOnly, NOW, { position_counts: { agree: false, position_count: 0 } }).verdict, 'UNKNOWN')
assert.equal(verdictOf(cashOnly, NOW, { position_counts: { agree: true, position_count: 0 } }).verdict, 'OK')
assert.equal(verdictOf(cashOnly, NOW, { position_counts: { agree: true, position_count: 3 } }).verdict, 'UNKNOWN')

// F3: GAP > UNKNOWN > WARN > OK, for the book and for each broker.
const expRow = (sym: string) => gapRow({ symbol: sym }, { expired_stop: true })
const unkRow = row({ symbol: 'UUU', protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true } })
const f3 = verdictOf([expRow('EEE'), unkRow], CLOSED)
assert.equal(f3.warn, 1); assert.equal(f3.unknown, 1)
assert.equal(f3.verdict, 'UNKNOWN'); assert.equal(f3.brokers[0].state, 'UNKNOWN')
assert.deepEqual(f3.action.map(p => p.symbol), ['UUU', 'EEE'])
const f3g = verdictOf([unkRow, gapRow()])
assert.equal(f3g.verdict, 'GAP'); assert.equal(f3g.brokers[0].state, 'GAP')

// F4 R1: the backend's expired-only GAP (protection.expired_stop, LQ-2412; stop_state is 'none') is UNKNOWN in the
// session and WARN after the close; never GAP-as-NO-STOP, never OK.
assert.equal(sessionOpenET(NOW), true); assert.equal(sessionOpenET(CLOSED), false)
assert.equal(sessionOpenET(Date.parse('2031-03-07T21:30:00Z')), false)   // Friday 16:30 ET
const r1 = rowProtection(gapRow({ stop_state: 'none' }, { expired_stop: true }), { nowMs: NOW })
assert.equal(r1.protection, 'UNKNOWN'); assert.equal(r1.chip, 'EXPIRED'); assert.equal(r1.cause, 'Expired Stop')
assert.equal(verdictOf([okRow('PPP'), gapRow({ stop_state: 'none' }, { expired_stop: true })]).verdict, 'UNKNOWN')
assert.equal(rowProtection(gapRow({ stop_state: 'none' }, { expired_stop: true }), { nowMs: CLOSED }).protection, 'WARN')
assert.equal(verdictOf([okRow('PPP'), gapRow({ stop_state: 'none' }, { expired_stop: true })], CLOSED).verdict, 'WARN')

// F4 R2: a 60 h old GAP read is UNKNOWN in session (limit 15 m); the last-known GAP stays listed as a P0 row.
const OLD = new Date(NOW - 60 * 3_600_000).toISOString()
const r2 = verdictOf([okRow('PPP'), gapRow({}, { as_of: OLD })])
assert.equal(r2.verdict, 'UNKNOWN'); assert.equal(r2.gap, 0); assert.equal(r2.unknown, 1)
assert.equal(r2.action[0].lastKnownGap, true); assert.equal(r2.action[0].cause, 'Stale Stop Read')
assert.deepEqual(p0Items(ok(wire([])), r2)!.map(x => x.category), ['Unprotected Position (stale read)'])
// 20 minutes old: stale in session, fresh after the close (72 h).
const MIN20 = (t: number) => new Date(t - 20 * 60_000).toISOString()
assert.equal(verdictOf([gapRow({}, { as_of: MIN20(NOW) })]).verdict, 'UNKNOWN')
assert.equal(verdictOf([gapRow({}, { as_of: MIN20(CLOSED) })], CLOSED).verdict, 'GAP')
// 73 h old after the close: stale.
assert.equal(verdictOf([gapRow({}, { as_of: new Date(CLOSED - 73 * 3_600_000).toISOString() })], CLOSED).verdict, 'UNKNOWN')
// A fresh GAP stays a GAP (R3 input: a NO from a fresh read).
assert.equal(verdictOf([okRow('PPP'), gapRow()]).verdict, 'GAP')

// 11. LQ-2483 (REVIEW-2479 M1/M2): exact limits. The limit itself is still fresh; one millisecond past it is stale.
// 2031-03-07 is before the 2031-03-09 DST change, so ET = UTC-5: 09:30 ET = 14:30Z, 16:00 ET = 21:00Z.
const agedGap = (nowMs: number, age: number) => gapRow({}, { as_of: new Date(nowMs - age).toISOString() })
assert.equal(verdictOf([agedGap(NOW, 900_000)]).verdict, 'GAP')
assert.equal(verdictOf([agedGap(NOW, 900_001)]).verdict, 'UNKNOWN')
assert.equal(verdictOf([agedGap(CLOSED, 72 * 3_600_000)], CLOSED).verdict, 'GAP')
assert.equal(verdictOf([agedGap(CLOSED, 72 * 3_600_000 + 1)], CLOSED).verdict, 'UNKNOWN')
// Session edges: 09:29:59 closed, 09:30:00 open, 15:59:59 open, 16:00:00 closed.
const OPEN_0930 = Date.parse('2031-03-07T14:30:00Z'), CLOSE_1600 = Date.parse('2031-03-07T21:00:00Z')
assert.equal(sessionOpenET(OPEN_0930 - 1_000), false); assert.equal(sessionOpenET(OPEN_0930), true)
assert.equal(sessionOpenET(CLOSE_1600 - 1_000), true); assert.equal(sessionOpenET(CLOSE_1600), false)
// At 16:00:00 ET R1 is WARN (closed) and R2 uses the 72 h limit: a 20 min old GAP read is still a GAP.
assert.equal(rowProtection(gapRow({ stop_state: 'none' }, { expired_stop: true }), { nowMs: CLOSE_1600 }).protection, 'WARN')
assert.equal(verdictOf([agedGap(CLOSE_1600, 20 * 60_000)], CLOSE_1600).verdict, 'GAP')
// At 09:30:00 ET R1 is UNKNOWN (open) and R2 uses the 900 s limit.
assert.equal(rowProtection(gapRow({ stop_state: 'none' }, { expired_stop: true }), { nowMs: OPEN_0930 }).protection, 'UNKNOWN')
assert.equal(verdictOf([agedGap(OPEN_0930, 900_001)], OPEN_0930).verdict, 'UNKNOWN')

// 12. LQ-2483: one verdict for one book. Same membership as stops_protection.summary over cio_truth after LQ-2431:
// a KNOWN value under $100 is listed, not counted, whatever its state, so a known $40 GAP next to a protected
// position reads OK on the page exactly as the served rollup does (no GAP-vs-served-OK split).
const oneBook = verdictOf([okRow('PPP'), row({ symbol: 'G40', market_value: 40, protection_state: 'GAP', stop_price: null,
  protection: { state: 'GAP', counted: false, as_of: AT } })])
assert.equal(oneBook.verdict, 'OK'); assert.equal(oneBook.counted, 1); assert.equal(oneBook.listedNotCounted, 1); assert.equal(oneBook.gap, 0)
// An unpriced GAP (after 2431: counted:true + price_missing; before it: counted:false) is counted and reads GAP.
for (const counted of [true, false]) {
  assert.equal(verdictOf([okRow('PPP'), gapRow({ market_value: null, price: null }, { counted, price_missing: counted })]).verdict, 'GAP')
}
// Cash only: UNKNOWN with its cause shown, never OK and never blank.
const cashCause = verdictOf(cashOnly)
assert.equal(cashCause.verdict, 'UNKNOWN'); assert.equal(cashCause.cause, 'No counted position, and the position count does not confirm zero')

// 13. PortfolioMeasures@v1 (LQ-20261113-3124R): the projection is the only source of the four measures.
// Absent block -> four UNKNOWN with the writer's reason, never a page-side computation.
const absent = measuresModel(ok(wire([row({})])))
assert.equal(absent.state, 'ABSENT'); assert.equal(absent.materialized, false)
assert.equal(absent.reason, MEASURES_ABSENT_REASON)
assert.deepEqual(absent.measures.map(m => m.key), [...MEASURE_KEYS])
for (const m of absent.measures) { assert.equal(m.status, 'UNKNOWN'); assert.equal(m.value, null); assert.equal(m.gap, MEASURES_ABSENT_REASON) }
// The read-path contract carries materialized:false with its own reason; that reason is quoted, not replaced.
const absentBlock: MeasuresBlockWire = { contract_version: 'PortfolioMeasures@v1', status: 'UNKNOWN', materialized: false,
  gap: { reason: 'writer has not run once yet' }, measures: {} }
const absent2 = measuresModel(ok(wire([row({})], { measures: absentBlock })))
assert.equal(absent2.state, 'ABSENT'); assert.equal(absent2.reason, 'writer has not run once yet')
// A failed holdings read is UNREADABLE: never a measure, never a 0.
const unread = measuresModel(failed)
assert.equal(unread.state, 'UNREADABLE')
for (const m of unread.measures) { assert.equal(m.status, 'UNKNOWN'); assert.equal(m.value, null) }

// 14. A materialized block is drawn exactly as published: no sum, no re-derivation, no default to zero.
const measured: MeasuresBlockWire = {
  contract_version: 'PortfolioMeasures@v1', as_of: AT, generated_at: AT, materialized: true,
  basis: { applied: 'broker_positions_store', why: 'broker values are the accounting anchor' },
  finviz_estimates_are_separate: true,
  labels: { account_value: 'Account value' },
  measures: {
    account_value: { measure: 'account_value', label: 'Account value', value: 1252980.85, status: 'MEASURED', as_of: AT, rows: 31,
      finviz_estimate: { label: 'Finviz mark estimate', value: 1255586.37, delta: -2605.52, marks_at: AT, note: 'a mark difference is not a move' } },
    price_move_estimate: { measure: 'price_move_estimate', value: -1836.58, status: 'PARTIAL', as_of: AT, definition: 'sum of row moves',
      coverage: { measured_rows: 28, unknown_rows: 1, row_count: 29 }, gap: { reason: 'one row has no prior-close baseline' },
      finviz_estimate: { value: null, total_with_broker_nav: -1836.58, delta_vs_broker: 0, marks_at: AT } },
    account_value_change_1d: { measure: 'account_value_change_1d', value: -5020.07, status: 'MEASURED', as_of: AT,
      start: { equity_usd: 1258000.92, as_of: AT, source: 'prior_snapshot' }, end: { equity_usd: 1252980.85, as_of: AT },
      drill_down: { price_move_estimate: -4467.14, closed_today_trade_effect: -552.93, fees_today: 0.47, income_today: 0,
        external_flows_today: 0, reconciles: true } },
    verified_daily_pnl: { measure: 'verified_daily_pnl', value: null, status: 'UNKNOWN', candidate: -5020.07,
      gap: { reason: 'no stored verified reconciliation exists', requires: 'stored signed per-account reconciliation' },
      known_components: { price_move_estimate: -4467.14, closed_today_trade_effect: -552.93, fees_today: 0.47, income_today: null,
        external_flows_today: null, note: 'a None component is UNKNOWN, never zero' } },
  },
}
const mm2 = measuresModel(ok(wire([row({})], { measures: measured })))
assert.equal(mm2.state, 'PRESENT'); assert.equal(mm2.materialized, true); assert.equal(mm2.dayUnverified, true)
const mv = (k: string) => mm2.measures.find(m => m.key === k)!
assert.equal(mv('account_value').value, 1252980.85); assert.equal(mv('account_value').status, 'MEASURED')
// The Finviz re-mark is published beside the anchor with its delta; it is never folded into the anchor.
assert.equal(mv('account_value').estimate!.value, 1255586.37); assert.equal(mv('account_value').estimate!.delta, -2605.52)
assert.equal(mv('account_value').estimate!.note, 'a mark difference is not a move')
assert.equal(mv('price_move_estimate').value, -1836.58); assert.equal(mv('price_move_estimate').status, 'PARTIAL')
// Measure 4 is UNKNOWN by design: the candidate is named and is never drawn as the verified figure.
assert.equal(mv('verified_daily_pnl').value, null); assert.equal(mv('verified_daily_pnl').status, 'UNKNOWN')
assert.equal(mv('verified_daily_pnl').candidate, -5020.07)
assert.match(mv('verified_daily_pnl').text, /candidate .*not verified/)
// Components are the wire's; a null component reads UNKNOWN, never zero.
const fee = mv('verified_daily_pnl').components.find(c => c.key === 'fees_today')!
const income = mv('verified_daily_pnl').components.find(c => c.key === 'income_today')!
assert.equal(fee.value, 0.47); assert.equal(fee.note, null)
assert.equal(income.value, null); assert.equal(income.note, 'UNKNOWN — not zero')
// The reconciliation verdict is the wire's own flag.
assert.equal(mv('account_value_change_1d').reconciles, true)
// A measure the projection did not publish is UNKNOWN; it is not taken from another measure.
const sparse = measuresModel(ok(wire([row({})], { measures: { ...measured, measures: { account_value: measured.measures!.account_value } } })))
assert.equal(sparse.state, 'PRESENT')
assert.equal(sparse.measures.find(m => m.key === 'price_move_estimate')!.status, 'UNKNOWN')
assert.match(sparse.measures.find(m => m.key === 'price_move_estimate')!.text, /carries no price_move_estimate/)
// C1 (REVIEW-CAMPAIGN8H-item1 F3): a value without a published status is NOT a figure. It is null — so it can
// never be drawn in its row or promoted to the header — and the row says why.
const noStatus = measuresModel(ok(wire([row({})], { measures: { materialized: true, measures: { account_value: { value: 5 } } } })))
assert.equal(noStatus.measures[0].value, null); assert.equal(noStatus.measures[0].status, 'UNKNOWN')
assert.match(noStatus.measures[0].text, /status not published — not a figure/); assert.doesNotMatch(noStatus.measures[0].text, /\$5/)
// The wire's own UNKNOWN status is not a figure either: a number beside UNKNOWN is not drawn.
const unkVal = measuresModel(ok(wire([row({})], { measures: { materialized: true, measures: { account_value: { status: 'UNKNOWN', value: 777777 } } } })))
assert.equal(unkVal.measures[0].value, null); assert.match(unkVal.measures[0].text, /marked UNKNOWN — the wire value is not drawn/)
assert.doesNotMatch(unkVal.measures[0].text, /777,777/)
// A MEASURED status with no value leaves the figure UNKNOWN, never 0.
const noValue = measuresModel(ok(wire([row({})], { measures: { materialized: true, measures: { account_value: { status: 'MEASURED' } } } })))
assert.equal(noValue.measures[0].value, null); assert.equal(noValue.measures[0].status, 'MEASURED')
// A6 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): the figure statuses are a closed allowlist, not "anything but
// UNKNOWN". A future status such as GAP cannot assert a number, and the row names the status instead of hiding it.
const oddStatus = measuresModel(ok(wire([row({})], { measures: { materialized: true, measures: { account_value: { status: 'GAP', value: 999999 } } } })))
assert.equal(oddStatus.measures[0].value, null)
assert.match(oddStatus.measures[0].text, /status GAP does not assert a figure — the wire value is not drawn/)
assert.doesNotMatch(oddStatus.measures[0].text, /999,999/)
// And the three figure statuses do assert one (PARTIAL included: the projection counted what it could).
const partVal = measuresModel(ok(wire([row({})], { measures: { materialized: true, measures: { account_value: { status: 'PARTIAL', value: 1234 } } } })))
assert.equal(partVal.measures[0].value, 1234)

// 15. Coverage categories (campaign 2026-11-14): six classes, resting vs held; the verdict is untouched.
const covRows = positionsFrom(wire([
  row({ symbol: 'FULL', shares: 300, stop_qty: 300 }),
  row({ symbol: 'HALF', shares: 300, stop_qty: 200 }),
  row({ symbol: 'PLAN', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_source: 'planned', stop_qty: null, stop_price: null }),
  row({ symbol: 'NONE', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null }),
  row({ symbol: 'CASHX', is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } }),
  row({ symbol: 'UNKX', protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null }),
  row({ symbol: 'EXPX', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_state: 'expired', stop_price: null }),
]), CLOSED)
const byCat = (s: string) => covRows.find(p => p.symbol === s)!
assert.equal(byCat('FULL').coverage.category, 'COVERED')
assert.equal(byCat('HALF').coverage.category, 'PARTIAL'); assert.equal(byCat('HALF').coverage.chip, 'PARTIAL 200/300')
assert.equal(byCat('HALF').coverage.restingShares, 200); assert.equal(byCat('HALF').coverage.heldShares, 300)
assert.equal(byCat('PLAN').coverage.category, 'PLANNED_ONLY'); assert.equal(byCat('PLAN').coverage.chip, 'PLANNED ONLY')
assert.equal(byCat('NONE').coverage.category, 'UNCOVERED'); assert.equal(byCat('NONE').coverage.chip, 'NO STOP')
assert.equal(byCat('CASHX').coverage.category, 'EXEMPT')
assert.equal(byCat('UNKX').coverage.category, 'UNVERIFIABLE'); assert.notEqual(byCat('UNKX').coverage.chip, 'NO STOP')
assert.equal(byCat('EXPX').coverage.category, 'UNCOVERED'); assert.equal(byCat('EXPX').coverage.chip, 'EXPIRED')
// Coverage is display-only: the backend verdict and the counted set do not move because a stop is short.
assert.equal(byCat('HALF').protection, 'PROTECTED'); assert.equal(byCat('HALF').counted, true)
assert.equal(byCat('HALF').lastKnownGap, false)
assert.equal(coverageOf(byCat('HALF')).category, 'PARTIAL')
const cc = coverageCounts(covRows)
assert.deepEqual([cc.covered, cc.partial, cc.uncovered, cc.planned, cc.exempt, cc.unverifiable], [1, 1, 2, 1, 1, 1])
assert.equal(cc.restingShares, 500); assert.equal(cc.heldShares, 630)
// F4 (REVIEW-CAMPAIGN8H-item1 advisory): PLAN/NONE/UNKX/EXPX publish no resting quantity, so the totals above are a
// PARTIAL sum; the model says so and every consumer must render "published", never "total".
assert.equal(cc.totalsComplete, false)
const completeCounts = coverageCounts(covRows.filter(p => p.symbol === 'FULL' || p.symbol === 'HALF'))
assert.equal(completeCounts.totalsComplete, true)
assert.equal(completeCounts.restingShares, 500); assert.equal(completeCounts.heldShares, 600)
assert.deepEqual(filterPositions(covRows, 'partial', 'all').map(p => p.symbol), ['HALF'])
assert.deepEqual(filterPositions(covRows, 'planned', 'all').map(p => p.symbol), ['PLAN'])
assert.deepEqual(filterPositions(covRows, 'exempt', 'all').map(p => p.symbol), ['CASHX'])
// A PROTECTED row with a stop quantity of 0 is drawn as partial, never as full coverage.
const zeroStop = positionsFrom(wire([row({ symbol: 'ZERO', shares: 100, stop_qty: 0 })]), NOW)[0]
assert.equal(zeroStop.coverage.category, 'PARTIAL'); assert.equal(zeroStop.coverage.restingShares, 0)

// 16. CSV export: served columns only; no computed P&L column; the coverage class is carried.
const csv = holdingsCsv(covRows)
const csvLines = csv.split('\r\n')
assert.equal(csvLines[0], CSV_COLUMNS.join(','))
assert.doesNotMatch(csvLines[0].toLowerCase(), /pnl|profit|gain/)
assert.equal(csvLines.length, covRows.length + 1)
const halfLine = csvLines.find(l => l.startsWith('HALF,'))!
assert.match(halfLine, /,300,200,PARTIAL,PROTECTED,/)
// Quoting: an account with a comma is quoted, never split into a second cell.
const com = positionsFrom(wire([row({ symbol: 'Q', account_label: 'Broker A, ··01' })]), NOW)[0]
assert.match(holdingsCsv([com]).split('\r\n')[1], /"Broker A, ··01"/)

// 17. The stop desk link carries account + broker + position identity.
const href = stopDeskHref(byCat('NONE'))
const q = new URLSearchParams(href.split('?')[1])
assert.equal(href.split('?')[0], '/portfolio-classic')
assert.equal(q.get('tab'), 'Stop Management'); assert.equal(q.get('symbol'), 'NONE')
assert.equal(q.get('account'), byCat('NONE').accountKey); assert.equal(q.get('acct'), byCat('NONE').accountKey)
assert.equal(q.get('broker'), 'broker_a'); assert.equal(q.get('position'), byCat('NONE').key); assert.equal(q.get('drawerTab'), 'stops')

// 18. Since your last visit: the anchor is read; a missing or unreadable record is never a silent 24 h claim.
assert.equal(sinceVisitModel({ state: 'LOADING', data: null, error: null, at: null, source: 'x' }).status, 'LOADING')
const rec: Read<LastSeenWire> = ok({ read: { status: 'RECORDED', window_basis: 'last_visit', seen_at: AT, previous_seen_at: null, age_sec: 3600, device: 'phone' } }, 'x')
const sv = sinceVisitModel(rec)
assert.equal(sv.status, 'RECORDED'); assert.match(sv.windowText, /Since your last visit/)
const notRec = sinceVisitModel(ok({ read: { status: 'NOT_RECORDED', window_basis: 'fallback_24h', fallback_text: 'last 24 h (your last visit is not recorded)' } }, 'x'))
assert.equal(notRec.status, 'NOT_RECORDED'); assert.match(notRec.windowText, /24 h/)
const badRec = sinceVisitModel(ok({ read: { status: 'UNKNOWN', reason: 'stored last-seen is unreadable' } }, 'x'))
assert.equal(badRec.status, 'UNKNOWN'); assert.match(badRec.windowText, /unreadable/)
assert.equal(sinceVisitModel({ state: 'UNKNOWN', data: null, error: 'HTTP 503', at: AT, source: '/api/v2/ui/prefs/get?key=portfolio.last_seen' }).status, 'UNKNOWN')
assert.equal(sinceVisitModel(ok({}, 'x')).status, 'UNKNOWN')
assert.equal(sv.changesNeedBackend, true)

// 19. Gate evidence: the four gates the design names, each with a threshold, none reported open or closed without
// the store — and no evidence string is ever the words a served verdict would use.
const gates = gateEvidence(mm, mm2, covRows)
assert.equal(gates.length, 4)
assert.deepEqual(gates.map(g => g.gate), ['Stop read covers every broker', 'Price check · 5 sessions clean',
  'Position count agrees', 'Value reconciles to the accounting anchor'])
for (const g of gates) {
  assert.equal(g.servedStatus, 'NOT AVAILABLE')
  assert.ok(g.threshold.length > 0, `gate has a threshold: ${g.gate}`)
  assert.doesNotMatch(`${g.gate} ${g.pageEvidence}`, /\b(PASS|FAIL|OPEN|CLOSED|OK)\b/)
}
assert.equal(gates.filter(g => g.blocksTrading).length, 1)
assert.equal(gates[0].blocksTrading, true)
assert.match(gates[0].pageEvidence, /counted positions/)
assert.match(gates[0].threshold, /900 s .*72 h/)
// A7 (REVIEW-CAMPAIGN8H-item1-fix): a broker whose only rows are EXEMPT carries no counted position and must not read
// as covered by the stop read; the evidence names counted brokers against brokers with non-cash rows.
const exRead = ok(wire([row({ symbol: 'CNT', broker: 'broker_a' }),
  row({ symbol: 'EXB', broker: 'broker_b', protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })]))
const exPos = positionsFrom(exRead.data, NOW)
const exGates = gateEvidence(protectionModel(exRead, exPos), measuresModel(exRead), exPos, exRead.data)
assert.match(exGates[0].pageEvidence, /1 counted position in 1 of 2 brokers with non-cash rows/)
assert.match(gates[1].pageEvidence, /one read cannot show a five-session window/)
// The count block IS in the holdings document, so the gate must read it, not claim it is invisible.
assert.match(gates[2].pageEvidence, /position count block is not in this read/)
// C5 (REVIEW-CAMPAIGN8H-item1-fix-cc-deepseek-2): the gate compares LIKE WITH LIKE — the block's holdings.all_rows
// scope against the rows this read drew — quotes the block's own summary, names the headline as a named scope, and
// never turns the cross-scope `agree` flag into "they disagree".
const evMatch = gateEvidence(mm, mm2, covRows, wire([], { position_counts: servedCounts({ all_rows: covRows.length, scopes: { 'holdings.all_rows': covRows.length } }) }))[2]
assert.doesNotMatch(evMatch.pageEvidence, /disagree/i)
assert.match(evMatch.pageEvidence, new RegExp(`this read drew ${covRows.length} rows`))
assert.match(evMatch.pageEvidence, /they match/)
assert.match(evMatch.pageEvidence, /headline 11 is its holdings\.non_cash_over_100 scope/)
assert.match(evMatch.pageEvidence, /its own summary: 11 positions at or above \$100/)
assert.doesNotMatch(evMatch.threshold, /summary count = row count/)
assert.match(evMatch.threshold, /holdings\.all_rows/)
// A genuine like-for-like difference IS said, in row terms — and still without the invented "disagree".
const evDiff = gateEvidence(mm, mm2, covRows, wire([], { position_counts: servedCounts() }))[2]
assert.match(evDiff.pageEvidence, /holdings\.all_rows scope counts 33; this read drew 7 rows/)
assert.match(evDiff.pageEvidence, /they differ/)
assert.doesNotMatch(evDiff.pageEvidence, /disagree/i)
// A block with no named all-rows scope is not compared at all, rather than compared against the wrong population.
const evNoScope = gateEvidence(mm, mm2, covRows, wire([], { position_counts: servedCounts({ all_rows: undefined, scopes: {} }) }))[2]
assert.match(evNoScope.pageEvidence, /names no all-rows scope/)
assert.doesNotMatch(evNoScope.pageEvidence, /disagree/i)
// The old invented shapes (no all_rows, agree carrying the comparison) produce no verdict either way.
const evInvented = gateEvidence(mm, mm2, covRows, wire([], { position_counts: { agree: false, summary: 'counts disagree' } }))[2]
assert.match(evInvented.pageEvidence, /names no all-rows scope/)
assert.doesNotMatch(evInvented.pageEvidence, /they disagree/)

// 20. Risk (G7): an isolated pending decision, never a score.
assert.equal(RISK_SCORE.status, 'PENDING DECISION')
assert.match(RISK_SCORE.text, /PROPOSED|proposed/); assert.match(RISK_SCORE.text, /no number|no score/)

// 21. C4 / mutant M3 (REVIEW-CAMPAIGN8H-item1): a book whose ONLY counted row is PROTECTED with a PARTIAL stop
// coverage still rolls up OK, counted 1. Coverage is a display class and never enters the verdict.
const partialOnly = verdictOf([row({ symbol: 'PAR', shares: 300, stop_qty: 200, market_value: 3000 })])
assert.equal(partialOnly.verdict, 'OK'); assert.equal(partialOnly.counted, 1); assert.equal(partialOnly.protectedN, 1)
const parPos = positionsFrom(wire([row({ symbol: 'PAR', shares: 300, stop_qty: 200, market_value: 3000 })]), NOW)
assert.equal(parPos[0].protection, 'PROTECTED'); assert.equal(parPos[0].coverage.category, 'PARTIAL')
assert.equal(partialOnly.action.length, 0)   // nothing to act on: coverage does not push a PROTECTED row into Action
// A PROTECTED row whose stop covers no resting quantity is still PROTECTED: coverage cannot demote the verdict either.
const zeroQty = verdictOf([row({ symbol: 'ZERO', shares: 300, stop_qty: 0, market_value: 3000 })])
assert.equal(zeroQty.verdict, 'OK'); assert.equal(zeroQty.counted, 1)

// 22. C4 / mutant M5: no status row is named Value or Today, and no status row text draws the store total or a
// "today" figure. The only place the store total may appear is the header fallback (a view test pins the markup).
const srows = statusRows(ok(wire([row({})], { total_value: 1234567.89 })), ok<IncidentsWire>({ counts: { P0: 0, P1: 0 }, served_at: AT }),
  positionsFrom(wire([row({})], { total_value: 1234567.89 }), NOW), NOW)
for (const r of srows) {
  assert.doesNotMatch(r.name, /^(value|today)\b/i, `status row named ${r.name}`)
  assert.doesNotMatch(`${r.name} ${r.text}`, /1,234,567/, `row ${r.id} draws the store total`)
  assert.doesNotMatch(`${r.name} ${r.text}`, /today/i, `row ${r.id} draws a today figure`)
}

console.log('portfolioV002.test.ts: ok')
