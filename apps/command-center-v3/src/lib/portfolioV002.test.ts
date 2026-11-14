// Portfolio v002 page model (design/pages/portfolio/v002, approved 2026-11-11). Unknown beats wrong:
// UNKNOWN is never drawn as NO STOP, a failed read is never OK or "0", a pending-activation GTC stop counts.
// Synthetic fixtures only (public repo): placeholder symbols, accounts and values.
import assert from 'node:assert/strict'
import {
  readOnce, positionsFrom, protectionModel, p0Items, statusRows, filterPositions, rowProtection, auditCategories, sessionOpenET,
  exclusiveCoverage,
  measuresModel, coverageCounts, coverageScopeRelation, coverageOf, holdingsCsv, CSV_COLUMNS, stopDeskHref, sinceVisitModel, gateEvidence, gateStore,
  changesModel, stopReadFreshness, STOP_READ_MAX_AGE_MS, snapshotFacts, sameSnapshot, pnlReceipt,
  basisCoverage, basisView, basisLine, moveToday, unrealizedLine, weightLine, priceClock, positionFields,
  GATES_SCHEMA, CHANGES_SCHEMA, RISK_SCORE, MEASURES_ABSENT_REASON, MEASURE_KEYS,
  type HoldingWire, type HoldingsWire, type Read, type IncidentsWire, type LastSeenWire, type MeasuresBlockWire,
  type PortfolioChangeWire, type PortfolioChangesWire, type PortfolioGateWire, type PortfolioGatesWire,
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
// The clock is always passed: a fixture dated in the future of the wall clock is an impossible read (PR-003).
const pend = positionsFrom(wire([row({ symbol: 'BBB', stop_state: 'pending_activation' }), row({ symbol: 'CCC', market_value: 2000 })]), NOW)
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

// 16. CSV export: served columns only (the page computes no P&L), the basis verdict travels WITH its reason, and every
// row carries the ONE snapshot identity the page read — an exported row cannot describe a different book.
const csv = holdingsCsv(covRows, { snapshotId: null, observedAt: AT })
const csvLines = csv.split('\r\n')
assert.equal(csvLines[0], CSV_COLUMNS.join(','))
assert.match(csvLines[0], /unrealized_pnl_usd/)
assert.equal(csvLines.length, covRows.length + 1)
const halfLine = csvLines.find(l => l.startsWith('HALF,'))!
assert.match(halfLine, /,300,200,PARTIAL,PROTECTED,/)
// The positions clock is repeated on every row (the header's snapshot line and the rows share it).
assert.ok(csvLines.slice(1).every(l => l.endsWith(`,${AT}`)))
const snapCsv = holdingsCsv(positionsFrom(wire([row({ symbol: 'S1' })]), NOW), { snapshotId: 'snap-20310307-1', observedAt: AT })
assert.match(snapCsv.split('\r\n')[1], /,snap-20310307-1,2031-03-07T14:59:00Z$/)
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

// 19. Gate evidence: the four gates the design names, each with a threshold, none reported open or closed without a
// served store row — and no page evidence string is ever the words a served verdict would use.
const gates = gateEvidence(mm, mm2, covRows)
assert.equal(gates.length, 4)
assert.deepEqual(gates.map(g => g.gate), ['Stop read covers every broker', 'Price check · 5 sessions clean',
  'Position count agrees', 'Value reconciles to the accounting anchor'])
for (const g of gates) {
  // PR-004: with no store read on the page, the honest state is UNAVAILABLE — not the old "NOT AVAILABLE" constant.
  assert.equal(g.served, 'UNAVAILABLE')
  assert.match(g.servedText, /the gate store could not be read/)
  assert.match(g.expectsGateId, /^VG-PORT-/)
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
assert.match(evMatch.pageEvidence, new RegExp(`this read parsed ${covRows.length} normalised rows`))
assert.match(evMatch.pageEvidence, /they match/)
assert.match(evMatch.pageEvidence, /headline 11 is its holdings\.non_cash_over_100 scope/)
assert.match(evMatch.pageEvidence, /its own summary: 11 positions at or above \$100/)
assert.doesNotMatch(evMatch.threshold, /summary count = row count/)
assert.match(evMatch.threshold, /holdings\.all_rows/)
// A genuine like-for-like difference IS said, in row terms — and still without the invented "disagree".
const evDiff = gateEvidence(mm, mm2, covRows, wire([], { position_counts: servedCounts() }))[2]
assert.match(evDiff.pageEvidence, /holdings\.all_rows scope counts 33; this read parsed 7 normalised rows/)
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

// 19b. PR-004 (sprint 8H-2): the served portfolio gate store. A failed read is UNAVAILABLE and says why; a payload
// under another schema is refused; an empty scope is not a pass; a NULL blocks_trading is unknown, not "no".
const gateRow = (o: Partial<PortfolioGateWire> = {}): PortfolioGateWire => ({ gate_id: 'VG-PORT-COUNT-AGREES',
  title: 'Position count agrees', category: 'Order protection', status: 'PASSED', blocks_trading: null,
  owner: 'position sync lane', label_text: 'FIXED · UNPROVEN OVER TIME',
  last_eval: { result: 'PASS', at: '2031-03-06T15:00:00Z', detail: '7 rows = 7 rows' },
  clock: { state: 'closed', at: '2031-03-06T15:00:00Z', age_s: 86400, threshold_s: 900, text: 'closed at its last evaluation (24.0 h ago)' },
  window: { end: '2031-03-09T15:00:00Z', days_remaining: 2, label_text: 'FIXED · UNPROVEN OVER TIME' },
  next_action: 'No action unless it regresses: proving over the window to 2031-03-09', decl_path: 'config/x.json', ...o })
const gatePayload = (o: Partial<PortfolioGatesWire> = {}): PortfolioGatesWire => ({ schema: GATES_SCHEMA,
  served_at: AT, state: 'OK', reason: null,
  scope: { categories: ['Order protection'], gates: 1 },
  snapshot: { computed_at: '2031-03-06T15:00:00Z', age_s: 86_400, threshold_s: 900, basis: 'closed_gates' },
  writer: { lane_id: 'validation-gates-sync', last_ok_at: '2031-03-07T14:57:00Z', receipt: 'data/runtime/validation-gates-sync_last.json' },
  counts: { rows: 1, failed: 0, overdue: 0, open: 0, closed: 1, blocks_trading: 0, blocks_trading_unknown: 1, never_evaluated: 0 },
  items: [gateRow()], ...o })

// F2 (REVIEW-S2-portfolio-risk-b5, cc-deepseek-4): a counts object that does not publish open/closed must not be drawn
// as "0 open · 0 closed" — a missing count is unavailable with its reason, and only a SERVED zero is drawn as zero.
const gateCountsPartial = gateStore(ok(gatePayload({ counts: { rows: 3 } })), NOW)
assert.doesNotMatch(gateCountsPartial.headline, /0 open/)
assert.doesNotMatch(gateCountsPartial.headline, /0 closed/)
assert.match(gateCountsPartial.headline, /open not published/)
assert.match(gateCountsPartial.headline, /closed not published/)
// A served zero is still a fact and is drawn as one.
assert.match(gateStore(ok(gatePayload({ counts: { rows: 0, open: 0, closed: 0 } })), NOW).headline, /0 open · 0 closed/)

// A read that never answered, an HTTP 404 (route not yet wired) and a foreign contract all refuse to draw a verdict.
const unavailable = gateStore({ state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source: '/api/v2/portfolio/gates' }, NOW)
assert.equal(unavailable.state, 'UNAVAILABLE'); assert.equal(unavailable.chip, 'UNKNOWN')
assert.equal(unavailable.headline, 'the gate store read failed (HTTP 404)')
assert.deepEqual(unavailable.rows, [])
assert.equal(gateStore({ state: 'LOADING', data: null, error: null, at: null, source: 'x' }, NOW).headline, 'the gate store read has not answered yet')
assert.match(gateStore(ok({ schema: 'SomethingElse@v9' } as unknown as PortfolioGatesWire), NOW).headline, /unexpected contract/)
assert.equal(gateStore(ok({ schema: 'SomethingElse@v9', state: 'OK' } as unknown as PortfolioGatesWire), NOW).state, 'UNAVAILABLE')

// The served closed-gate scope: OK with the closure clock named, never "fresh", and the NULL tri-state counted.
const served = gateStore(ok(gatePayload()), NOW)
assert.equal(served.state, 'OK'); assert.equal(served.chip, 'OK')
assert.equal(served.headline, '1 gate in scope · 0 open · 1 closed')
assert.match(served.scopeLine, /scope: Order protection/)
assert.equal(served.snapshotLine, 'closure clock · Thu 10:00 AM · 24 h old · limit 15 m')
assert.match(served.writerLine, /writer validation-gates-sync · last ok .*validation-gates-sync_last\.json/)
assert.equal(served.rows[0].blocksTrading, null)   // tri-state preserved, never coerced to false
assert.ok(served.caveats.some(c => /do not declare whether they block trading: that is unknown, not “does not block”/.test(c)))

// STALE and UNKNOWN both keep their own reason; an empty scope is not a pass.
assert.ok(gateStore(ok(gatePayload({ state: 'STALE', reason: 'oldest open-gate evaluation 7200s old > 900s' })), NOW)
  .caveats.some(c => /the projection is STALE: oldest open-gate evaluation/.test(c)))
const unknownStore = gateStore(ok(gatePayload({ state: 'UNKNOWN', reason: 'no portfolio gate is declared for scope [\'Order protection\']', items: [], counts: null })), NOW)
assert.equal(unknownStore.state, 'UNKNOWN'); assert.equal(unknownStore.chip, 'UNKNOWN')
assert.match(unknownStore.headline, /no gate verdict: no portfolio gate is declared/)
assert.deepEqual(unknownStore.rows, [])
assert.ok(gateStore(ok(gatePayload({ state: 'UNKNOWN', reason: 'an open gate has no recorded evaluation' })), NOW)
  .caveats.some(c => /no verdict is drawn from them/.test(c)))

// A served timestamp and its own age that disagree are named, never trusted silently.
assert.ok(gateStore(ok(gatePayload({ snapshot: { computed_at: '2031-03-07T14:00:00Z', age_s: 60, threshold_s: 900, basis: 'open_gates' } })), NOW)
  .caveats.some(c => /snapshot time and its own age disagree/.test(c)))

// A store row for the expectation turns it GATED, with the served facts in words; with no such row it says ungated.
const gated = gateEvidence(mm, mm2, covRows, null, served)
assert.equal(gated[2].served, 'GATED')
assert.equal(gated[2].servedRow?.gateId, 'VG-PORT-COUNT-AGREES')
assert.match(gated[2].servedText, /^PASSED · last result PASS at /)
assert.match(gated[2].servedText, /window to /); assert.match(gated[2].servedText, /owner position sync lane/)
assert.match(gated[2].servedText, /next: No action unless it regresses/)
assert.equal(gated[0].served, 'NOT_GATED_BY_STORE')
assert.match(gated[0].servedText, /declares no gate with id VG-PORT-STOP-READ-PER-BROKER; this expectation is ungated, which is not a pass/)
assert.equal(gateEvidence(mm, mm2, covRows, null, unavailable)[2].served, 'UNAVAILABLE')
assert.match(gateEvidence(mm, mm2, covRows, null, unknownStore)[2].servedText, /ungated, which is not a pass/)

// 19c. PR-005 (sprint 8H-2): the served change list. A failed read is UNAVAILABLE (never an empty list); a measured
// zero says so; each row keeps its own event time; another page's rows are counted, not shown.
const changeRow = (o: Partial<PortfolioChangeWire> = {}): PortfolioChangeWire => ({ event_id: 41, source_kind: 'gate',
  source_id: 'VG-R3-STOP-COVERAGE-HEARTBEAT', category: 'Order protection', transition: 'passed',
  label: 'FIXED_UNPROVEN', label_text: 'FIXED · UNPROVEN OVER TIME',
  occurred_at: '2031-03-07T13:04:54Z', detected_at: '2031-03-07T13:04:58Z',
  summary: 'Stop-coverage producer heartbeat is fresh: passed', owner: 'platform', ...o })
const changePayload = (o: Partial<PortfolioChangesWire> = {}): PortfolioChangesWire => ({ schema: CHANGES_SCHEMA,
  served_at: AT, state: 'OK', reason: null,
  window: { basis: 'last_visit', since: '2031-03-06T14:00:00Z', until: AT },
  count: 1, latest_at: '2031-03-07T13:04:54Z', may_be_truncated: false,
  outside_window: { before: 0, after: 0, unreadable: 0, out_of_scope: 8 },
  items: [changeRow()], ...o })

const chUnavailable = changesModel({ state: 'UNKNOWN', data: null, error: 'HTTP 404', at: AT, source: '/api/v2/portfolio/changes' })
assert.equal(chUnavailable.state, 'UNAVAILABLE'); assert.equal(chUnavailable.chip, 'UNKNOWN')
assert.equal(chUnavailable.headline, 'the change list read failed (HTTP 404)')
assert.deepEqual(chUnavailable.rows, [])   // a failed read is never "no changes"
assert.equal(changesModel({ state: 'LOADING', data: null, error: null, at: null, source: 'x' }).headline, 'the change list read has not answered yet')
assert.match(changesModel(ok({ schema: 'SomethingElse@v9' } as unknown as PortfolioChangesWire)).headline, /unexpected contract/)

const chServed = changesModel(ok(changePayload()))
assert.equal(chServed.state, 'OK'); assert.equal(chServed.chip, 'OK')
assert.equal(chServed.headline, '1 change since your last visit · newest Fri 8:04 AM ET')
assert.equal(chServed.windowLine, 'since your last visit · from Thu 9:00 AM → Fri 9:59 AM ET')
assert.equal(chServed.rows[0].occurredAt, '2031-03-07T13:04:54Z')   // the event's own time, not the read time
assert.equal(chServed.rows[0].detectedAt, '2031-03-07T13:04:58Z')
assert.equal(chServed.rows[0].labelText, 'FIXED · UNPROVEN OVER TIME')
assert.ok(chServed.caveats.some(c => /8 events on this store belong to another page's scope/.test(c)))

// A measured zero is not an absent store: the sentence says the window was read and held nothing.
const chZero = changesModel(ok(changePayload({ count: 0, items: [], latest_at: null,
  outside_window: { before: 6, after: 0, unreadable: 0, out_of_scope: 8 } })))
assert.equal(chZero.state, 'EMPTY'); assert.equal(chZero.chip, 'OK')
assert.match(chZero.headline, /measured zero/)
assert.ok(chZero.caveats.some(c => /6 rows fell outside the window/.test(c)))

// The 24 h fallback names itself, and a truncation or a missing event time is stated rather than hidden.
const chFallback = changesModel(ok(changePayload({ window: { basis: 'fallback_24h', since: '2031-03-06T14:59:00Z', until: AT },
  may_be_truncated: true, items: [changeRow({ occurred_at: null })] })))
assert.match(chFallback.windowLine, /the last 24 h \(no visit cursor was recorded\)/)
// F1 (REVIEW-S2-portfolio-risk-b5, cc-deepseek-4): the fallback window must name WHY there was no cursor. A FAILED
// last-visit read is not "no visit cursor was recorded" — only a successful NOT_RECORDED read may say that.
const cursorFailed = sinceVisitModel({ state: 'UNKNOWN', data: null, error: 'HTTP 503', at: AT, source: '/api/v2/ui/prefs/get' })
assert.equal(cursorFailed.status, 'UNKNOWN')
const chFallbackFailed = changesModel(ok(changePayload({ window: { basis: 'fallback_24h', since: '2031-03-06T14:59:00Z', until: AT } })), cursorFailed)
assert.match(chFallbackFailed.windowLine, /the last-visit read gave no usable cursor: .*HTTP 503/)
assert.doesNotMatch(chFallbackFailed.windowLine, /no visit cursor was recorded/)
// An unreadable prefs record (the read answered, the record is not usable) is named by its own reason too.
const cursorUnreadable = sinceVisitModel(ok({ read: { status: 'UNKNOWN', reason: 'no valid seen_at in the record' } }))
const chFallbackUnreadable = changesModel(ok(changePayload({ window: { basis: 'fallback_24h' } })), cursorUnreadable)
assert.match(chFallbackUnreadable.windowLine, /no valid seen_at in the record/)
assert.doesNotMatch(chFallbackUnreadable.windowLine, /no visit cursor was recorded/)
// A successful NOT_RECORDED read is the only state that may say no cursor was recorded.
const cursorNone = sinceVisitModel(ok({ read: { status: 'NOT_RECORDED' } }))
assert.match(changesModel(ok(changePayload({ window: { basis: 'fallback_24h' } })), cursorNone).windowLine,
  /no visit cursor was recorded/)
assert.ok(chFallback.caveats.some(c => /may hold more than the 1 shown/.test(c)))
assert.ok(chFallback.caveats.some(c => /without a readable event time/.test(c)))
// A future cursor / unreadable store: the projection's own reason is quoted, not replaced.
const chUnknown = changesModel(ok(changePayload({ state: 'UNKNOWN', reason: 'the visit cursor is in the future (clock fault)', count: null, items: [] })))
assert.equal(chUnknown.state, 'UNKNOWN'); assert.match(chUnknown.headline, /no change list: the visit cursor is in the future/)

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

// 23. C1 (REVIEW-S2-portfolio-risk-b1 §5): a GAP row whose stop-read time is LATER than the capture clock is an
// impossible observation. It reads UNKNOWN with cause Invalid Stop Read Time (never NO STOP, whose own sentence would
// then call the read untrustworthy), keeps the last-known GAP visible, and leaves the NO STOP population. The clock is
// carried by the wire in two places — protection.as_of and stop_captured_at — so both are exercised.
for (const carrier of ['protection.as_of', 'stop_captured_at'] as const) {
  const FUT = '2031-03-07T20:00:00Z'   // NOW is 15:00Z that day: a read five hours after the capture clock
  const h = carrier === 'protection.as_of'
    ? row({ symbol: 'FUTG', protection_state: 'GAP', protection: { state: 'GAP', as_of: FUT, counted: true }, stop_captured_at: null, stop_price: null })
    : row({ symbol: 'FUTG', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_captured_at: FUT, stop_price: null })
  const [m] = positionsFrom(wire([h]), NOW)
  assert.equal(m.protection, 'UNKNOWN', `${carrier}: a future read is not a successful negative read`)
  assert.equal(m.chip, 'UNKNOWN', `${carrier}: the chip is UNKNOWN`)
  assert.equal(m.cause, 'Invalid Stop Read Time', `${carrier}: cause names the impossible read`)
  assert.match(m.reason, /later than the capture clock/)
  assert.equal(m.verifiedAtInvalid, true, `${carrier}: the row records the invalid read time`)
  assert.equal(m.coverage.category, 'UNVERIFIABLE', `${carrier}: coverage is unverifiable, never uncovered`)
  // and it is not counted as a no-stop row in the rollup the page's tiles use
  const ex = exclusiveCoverage([m])
  assert.equal(ex.noStop, 0, `${carrier}: the future-read GAP is not in No broker stop`)
  assert.equal(ex.unknown, 1, `${carrier}: it is in Unknown`)
  assert.equal(ex.complete, true)
  // nor in the unprotected filter population
  assert.equal(filterPositions([m], 'unprotected', 'all').length, 0, `${carrier}: it is not an unprotected row`)
}
// The stale direction still works, and keeps its own cause: a read older than the limit is Stale Stop Read.
{
  const OLD = '2031-03-05T15:00:00Z'
  const [stale] = positionsFrom(wire([row({ protection_state: 'GAP', protection: { state: 'GAP', as_of: OLD, counted: true }, stop_price: null })]), NOW)
  assert.equal(stale.protection, 'UNKNOWN'); assert.equal(stale.cause, 'Stale Stop Read')
}
// A GAP row whose success is ordinary still reads NO STOP (the fix must not swallow the honest case).
{
  const [gap] = positionsFrom(wire([row({ protection_state: 'GAP', protection: { state: 'GAP', as_of: AT, counted: true }, stop_price: null })]), NOW)
  assert.equal(gap.protection, 'GAP'); assert.equal(gap.chip, 'NO STOP'); assert.equal(gap.coverage.category, 'UNCOVERED')
  assert.equal(exclusiveCoverage([gap]).noStop, 1)
}

// 17. R5b #1 (2026-11-14, SEV-3): ONE stop-read freshness rule. Risk › Exposure's stop sheet consumes this function;
// it must apply the same clock and the same limit Portfolio's R2 applies, and never invent a second copy.
const OLD_READ = '2031-03-01T00:00:00Z'      // 6.6 d before NOW — stale in session (15 m) and usable off-hours
const FRESH_OFF = '2031-03-07T02:00:00Z'     // 37 h before CLOSED, 11 h before NOW — inside the 72 h off-hours limit
{
  // The live shape of a /api/v2/cio/pages row (AMANX, 2026-11-14): no protection verdict, a planned level, the
  // stop-read clock, and the projection's own stop_evidence mark.
  const amanx = { protection: null, protection_state: null, stop_state: 'none', stop_source: 'planned',
    stop_captured_at: OLD_READ, stop_price: 63.66, stop_evidence: { stale: true, as_of: OLD_READ } }
  const stale = stopReadFreshness(amanx, NOW)
  assert.equal(stale.kind, 'stale')
  assert.equal(stale.sessionOpen, true, 'NOW is inside the ET session, so the strict 15 m limit applies')
  assert.equal(stale.limitMs, STOP_READ_MAX_AGE_MS.session)
  assert.equal(stale.servedStale, true); assert.equal(stale.agreesWithServed, true)
  assert.match(stale.line, /UNKNOWN · the stop read is \d+ d old \(session limit 15 m\); the served state is last known, not a current read/)
  assert.match(stale.line, /R2, the rule Portfolio applies/)
  // ...and the row rule reaches the same verdict from the same clock: one implementation, no drift.
  const gapped = rowProtection({ protection: { state: 'GAP', counted: true, as_of: OLD_READ }, protection_state: 'GAP', stop_captured_at: OLD_READ }, { nowMs: NOW })
  assert.equal(gapped.protection, 'UNKNOWN'); assert.equal(gapped.cause, 'Stale Stop Read')

  // Off-hours: a 37 h-old read is fresh under the 72 h limit, and the served mark agrees.
  const fresh = stopReadFreshness({ ...amanx, stop_captured_at: FRESH_OFF, stop_evidence: { stale: false, as_of: FRESH_OFF } }, CLOSED)
  assert.equal(fresh.kind, 'fresh'); assert.equal(fresh.sessionOpen, false)
  assert.equal(fresh.limitMs, STOP_READ_MAX_AGE_MS.offHours)
  assert.equal(fresh.line, 'fresh · read 37 h ago · off-hours limit 3 d')

  // A read time later than the clock is an impossible observation, never fresh.
  const future = stopReadFreshness({ stop_captured_at: '2031-03-07T15:10:00Z' }, NOW)
  assert.equal(future.kind, 'invalid'); assert.match(future.line, /later than the clock; the read cannot be trusted/)

  // No published read clock: freshness is not measured — and the served mark is still said out loud.
  const none = stopReadFreshness({ stop_captured_at: null, stop_evidence: { stale: true } }, NOW)
  assert.equal(none.kind, 'unpublished'); assert.match(none.line, /no stop-read time is published/)
  assert.match(none.line, /served stop evidence marks it stale/)
  assert.equal(none.agreesWithServed, null)

  // The rule and the served mark disagree on a fresh off-hours read: both are shown, neither is chosen silently.
  const drift = stopReadFreshness({ stop_captured_at: FRESH_OFF, stop_evidence: { stale: true } }, CLOSED)
  assert.equal(drift.kind, 'fresh'); assert.equal(drift.agreesWithServed, false)
  assert.match(drift.line, /the served stop evidence marks it stale — the two marks disagree/)
}

// 18. R5b #2 (2026-11-14): the six coverage categories count EVERY drawn row; the tiles count the `counted` rows.
// Both numbers were right and the page printed them as one sentence. The relation is computed once, from one loop.
{
  const six = positionsFrom(wire([
    row({ symbol: 'BIG1', shares: 300, stop_qty: 300 }),
    row({ symbol: 'BIG2', protection_state: 'GAP', protection: { state: 'GAP', counted: true }, stop_price: null }),
    row({ symbol: 'BIG3', protection_state: 'UNKNOWN', protection: { state: 'UNKNOWN', cause: 'No Stop Read', counted: true }, stop_price: null }),
    row({ symbol: 'SML1', market_value: 50, protection_state: 'GAP', protection: { state: 'GAP', counted: false }, stop_price: null }),
    row({ symbol: 'SML2', market_value: 40, protection_state: 'GAP', protection: { state: 'GAP', counted: false }, stop_price: null }),
    row({ symbol: 'CASHX', is_cash: true, market_value: 900, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } }),
  ]), NOW)
  const c = coverageCounts(six)
  assert.equal(c.rows, 6); assert.equal(c.counted, 3)
  assert.equal(c.uncountedUnderFloor, 2); assert.equal(c.uncountedExempt, 1); assert.equal(c.uncountedReconciles, true)
  assert.equal(coverageScopeRelation(c), 'all 6 rows drawn · 3 counted (the tiles) · 3 not counted: 2 under $100, listed only · 1 exempt')
  // The categories still count all six rows (that is what the line's six figures are).
  assert.deepEqual([c.covered, c.partial, c.uncovered, c.planned, c.exempt, c.unverifiable], [1, 0, 3, 0, 1, 1])
  // A book where every drawn row is counted has no relation to explain.
  assert.equal(coverageScopeRelation(coverageCounts(positionsFrom(wire([row({})]), NOW))), 'all 1 row drawn · 1 counted (the tiles)')
  // An uncounted row that is neither under the floor nor exempt breaks the split: the page states the total and
  // does NOT assert a decomposition it cannot prove.
  const broken = coverageCounts([...six, { ...six[0], counted: false, underFloor: false, coverage: { ...six[0].coverage, category: 'UNCOVERED' as const } }])
  assert.equal(broken.uncountedReconciles, false)
  assert.equal(coverageScopeRelation(broken), 'all 7 rows drawn · 3 counted (the tiles) · 4 not counted (the under-$100 / exempt split does not reconcile)')
}

// 19. R5c one snapshot (b6, operator 11:06 ET): Portfolio reads /api/v2/portfolio/holdings and Risk reads
// /api/v2/cio/pages — two payload shapes from ONE broker snapshot. Both pages must name the same snapshot clock
// through the same accessor (not two equal computations), and the page must say so when the clocks differ.
{
  const SNAP = '2031-03-07T15:00:00Z'                       // Fri 10:00 AM ET
  const rows = [{ account_id: 'acct_1' }, { account_id: 'acct_2' }]
  const h = snapshotFacts(wire([], { positions_as_of: SNAP }), rows.map(r => ({ account: r.account_id })))
  // The Risk shape: positions.as_of carries the same field on the cio/pages projection.
  const p = snapshotFacts({ positions: { as_of: SNAP } }, rows)
  assert.equal(h.observedAt, SNAP); assert.equal(p.observedAt, SNAP)
  assert.equal(h.accountCount, 2); assert.equal(h.accounts, 'all accounts (2)')
  // ONE sentence from two shapes: this equality is the pin, not two strings that happen to match.
  assert.equal(h.line, p.line)
  assert.equal(h.line, 'snapshot id not published · positions read Fri 10:00 AM ET · all accounts (2)')
  assert.deepEqual(h.missing, ['snapshot id'])
  assert.deepEqual(p.missing, ['snapshot id'])
  // A published id leads the same sentence, whichever payload carries it.
  assert.equal(snapshotFacts(wire([], { snapshot_id: 'snap-20310307-1' }), []).line,
    'snapshot snap-20310307-1 · positions read Fri 9:59 AM ET · all accounts (0)')
  assert.deepEqual(snapshotFacts(wire([], { snapshot_id: 'snap-20310307-1' }), []).missing, [])
  // No clock is named as missing, never filled with a plausible instant.
  const none = snapshotFacts({}, [])
  assert.equal(none.observedAt, null)
  assert.match(none.line, /positions read clock not published/)
  assert.ok(none.missing.includes('positions read clock'))
  // Same clock = same snapshot. A different clock is stated with both times, never silently compared.
  assert.deepEqual(sameSnapshot(h, p), { same: true, line: 'the same snapshot clock on both pages: Fri 10:00 AM ET' })
  const later = snapshotFacts({ positions_as_of: '2031-03-07T15:05:00Z' }, [])
  assert.deepEqual(sameSnapshot(h, later),
    { same: false, line: 'different snapshot clocks: Fri 10:00 AM ET here, Fri 10:05 AM ET there' })
  assert.equal(sameSnapshot(h, none).same, null)
  assert.equal(sameSnapshot(h, none).line, 'the two reads cannot be compared: one of them publishes no position clock')
}

// 19b. The verified daily P&L is drawn ONLY under a signed reconciliation receipt. Today the wire marks it
// UNKNOWN, so this is dormant — the test pins the contract before a producer ever sends VERIFIED.
{
  const block = (extra: Partial<MeasuresBlockWire> = {}): MeasuresBlockWire => ({ ...measured, ...extra,
    measures: { ...measured.measures,
      verified_daily_pnl: { measure: 'verified_daily_pnl', value: -1841.22, status: 'VERIFIED', as_of: AT } } })
  const pnlOf = (w: HoldingsWire) => measuresModel(ok(w))
  const vOf = (m: ReturnType<typeof pnlOf>) => m.measures.find(x => x.key === 'verified_daily_pnl')!
  // No receipt: the VERIFIED label is not evidence, and the figure is not drawn.
  const unsigned = pnlOf(wire([row({})], { measures: block() }))
  assert.equal(vOf(unsigned).value, null)
  assert.match(vOf(unsigned).text, /no signed reconciliation receipt is on file/)
  assert.equal(unsigned.dayUnverified, true)
  // An explicit verified:false is the same as absent.
  const denied = pnlOf(wire([row({})], { measures: block({ broker_contract: { pnl: { verified: false } } }) }))
  assert.equal(vOf(denied).value, null); assert.equal(denied.dayUnverified, true)
  // A signed receipt on the contract lets the wire's own VERIFIED figure through, unchanged.
  const signed = pnlOf(wire([row({})], { measures: block({ broker_contract: { pnl: { verified: true } } }) }))
  assert.equal(vOf(signed).value, -1841.22)
  assert.equal(vOf(signed).status, 'VERIFIED')
  assert.equal(signed.dayUnverified, false)
  // The receipt name the page prints is the one it read.
  assert.equal(pnlReceipt({ broker_contract: { pnl: { verified: true } } }).signed, true)
  assert.equal(pnlReceipt({}).signed, false)
}

// 23. OBS-P1 (operator 2026-11-14 11:15 ET): the row's mark carries its source and clock, the session move is drawn
// as a PRICE MOVE and never as P&L, weight is drawn only when published, and unrealized P&L is drawn only on a
// recorded basis — a row without one prints the read's precise reason, never a zero and never a blank.
{
  const px = (o: Partial<HoldingWire> = {}) => row({ symbol: 'PX1', shares: 100, price: 186.64, market_value: 18664,
    price_source: 'finviz', price_as_of: AT, prior_close: 188.98, day_change: -234, day_change_pct: -1.24, ...o })
  const [p1] = positionsFrom(wire([px()]), NOW)
  assert.equal(p1.priceSource, 'finviz'); assert.equal(p1.priceAt, AT)
  assert.equal(priceClock(p1.raw, wire([])).line, 'quote read Fri 9:59 AM ET')
  // A row that publishes no per-row clock inherits the BATCH clock, labelled as the batch.
  const batch = priceClock(px({ price_as_of: null }), wire([]))
  assert.equal(batch.perRow, false); assert.match(batch.line, /book quote clock .* · no per-row quote time published/)
  assert.equal(priceClock(px({ price_as_of: null }), wire([], { quote_as_of: null })).line, 'no quote clock published in this read')

  // The session move is a price move: both figures, one label, and the word P&L never appears on it.
  const mv = moveToday(p1)
  assert.equal(mv.text, 'price move today −1.2% · −$234')
  assert.doesNotMatch(mv.text, /P&L|profit|gain/i)
  assert.equal(mv.cls, 'dn')
  // A row that publishes only one of the two figures names the other as missing rather than half-drawing a move.
  const half = moveToday({ isCash: false, dayUsd: null, dayPct: -1.24 })
  assert.match(half.text, /price move today −1.2% · \$ move not published/)
  const noMove = moveToday({ isCash: false, dayUsd: null, dayPct: null })
  assert.equal(noMove.known, false); assert.equal(noMove.text, 'price move today not published in this read')

  // No basis in the read: the reason is printed, the P&L is null, and no zero is ever drawn.
  assert.equal(p1.basis.status, 'UNKNOWN')
  assert.equal(p1.basis.reason, 'cost basis not reported by the broker read')
  assert.equal(p1.basis.pnlUsd, null)
  const pnlNone = unrealizedLine(p1.basis)
  assert.equal(pnlNone.known, false)
  assert.equal(pnlNone.text, 'unrealized P&L not shown — cost basis not reported by the broker read')
  assert.doesNotMatch(pnlNone.text, /\$0/)

  // A partial lot history: the producer's own gap sentence is the reason printed, never a computed P&L.
  const partialBasis = positionsFrom(wire([px({ symbol: 'PBL', basis_partial: true, cost_basis: 5000,
    basis_truth: { cost_basis_usd: null, unrealized_pl_usd: null, unrealized_pl_pct: null, source: null, status: 'unknown',
      gap: { reason: 'basis unknown — incomplete or pre-window lot history' } } })]), NOW)[0]
  assert.equal(partialBasis.basis.status, 'UNKNOWN')
  assert.match(unrealizedLine(partialBasis.basis).text, /incomplete or pre-window lot history/)

  // A recorded basis: the figure is the READ's, with its pct and source named.
  const recorded = positionsFrom(wire([px({ symbol: 'REC', cost_basis: 15000,
    basis_truth: { cost_basis_usd: 15000, unrealized_pl_usd: 1234.56, unrealized_pl_pct: 8.23, source: 'broker_api', status: 'recorded', gap: null } })]), NOW)[0]
  assert.equal(recorded.basis.status, 'RECORDED'); assert.equal(recorded.basis.usd, 15000)
  const pnlRec = unrealizedLine(recorded.basis)
  assert.equal(pnlRec.known, true); assert.equal(pnlRec.text, '+$1,235 (+8.2%) on recorded basis · broker_api')
  assert.equal(pnlRec.cls, 'up')

  // REVIEW F1 (cc-deepseek-4, blocking): a RECORDED basis whose P&L figure is not published must never be worded
  // as if the basis were missing. cio_truth.basis_for keeps status 'recorded' when the row has no mark AND no
  // market_value (value=None -> pnl=None), so the basis is present and only the FIGURE is absent — the exact
  // contradiction the operator flagged: the page says it has no basis in the one place it has one.
  const recNoPnlTruth = { cost_basis_usd: 1500, unrealized_pl_usd: null, unrealized_pl_pct: null, source: 'broker_api',
    status: 'recorded', gap: null }
  const recNoPnl = positionsFrom(wire([px({ symbol: 'RECX', price: null, market_value: null, price_as_of: null,
    prior_close: null, day_change: null, day_change_pct: null, cost_basis: 1500, basis_truth: recNoPnlTruth })]), NOW)[0]
  assert.equal(recNoPnl.basis.status, 'RECORDED'); assert.equal(recNoPnl.basis.usd, 1500)
  const pnlMissing = unrealizedLine(recNoPnl.basis)
  assert.equal(pnlMissing.known, false)
  assert.doesNotMatch(pnlMissing.text, /no recorded cost basis/i)
  assert.match(pnlMissing.text, /unrealized P&L not published in this read/)
  assert.match(pnlMissing.text, /\((\$1,500)\)/)                      // names the basis the row DOES have, unsigned
  assert.doesNotMatch(pnlMissing.text, /\+\$1,500/)                   // a stock is not a delta
  assert.match(pnlMissing.text, /no published mark or market value/)  // and the real cause of the missing figure
  // A recorded basis with a mark but no published figure: still never "no recorded cost basis".
  const recMarkNoPnl = basisView({ ...px({ symbol: 'RECY' }), basis_truth: recNoPnlTruth })
  assert.doesNotMatch(unrealizedLine(recMarkNoPnl).text, /no recorded cost basis/i)
  assert.match(unrealizedLine(recMarkNoPnl).text, /publishes no unrealized figure/)

  // REVIEW F2: a verdict is drawn from a verdict. A numeric cost_basis with NO published basis status is not a
  // recorded basis — the read never said "recorded", so the page may not manufacture the verdict (nor a P&L).
  const noVerdict = positionsFrom(wire([px({ symbol: 'NVX', cost_basis: 900, basis_truth: undefined })]), NOW)[0]
  assert.equal(noVerdict.basis.status, 'UNKNOWN')
  assert.equal(noVerdict.basis.usd, null)
  assert.match(String(noVerdict.basis.reason), /no basis status is published/i)

  // Weight is drawn only when the read publishes it; the page never divides two served numbers itself.
  assert.equal(weightLine({ isCash: false, weightPct: null, weightBasis: null }).text, 'weight not published in this read')
  assert.equal(weightLine({ isCash: false, weightPct: 3.24, weightBasis: 'the book total' }).text, '3.2% of the book total')
  assert.equal(weightLine({ isCash: true, weightPct: null, weightBasis: null }).text, 'cash row · no position weight')

  // Header coverage: N of M NON-CASH rows, and an empty population is named, never "0 of 0".
  const cov1 = basisCoverage([p1, recorded])
  assert.equal(cov1.recorded, 1); assert.equal(cov1.total, 2)
  assert.equal(cov1.line, 'cost basis recorded for 1 of 2 non-cash positions (1 without a usable basis — their unrealized P&L is not drawn)')
  assert.match(basisCoverage([]).line, /no non-cash rows in this read/)
  const cashRow = positionsFrom(wire([row({ symbol: 'CASHR', is_cash: true, price: null, market_value: 1000,
    protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })]), NOW)[0]
  assert.equal(moveToday(cashRow).text, 'cash row · no price move')
  assert.equal(basisCoverage([cashRow]).total, 0)

  // ONE snapshot, four surfaces: the CSV carries the same id and positions clock the header line names, and the
  // drawer names the same identity in its Book snapshot field.
  const wWithId = wire([row({ symbol: 'AAA' })], { snapshot_id: 'snap-20310307-1' })
  const snap = snapshotFacts(wWithId, [{ account: p1.account }])
  assert.equal(snap.snapshotId, 'snap-20310307-1')
  const csv2 = holdingsCsv(positionsFrom(wWithId, NOW), snap).split('\r\n')
  assert.match(csv2[0], /snapshot_id,positions_as_of$/)
  assert.match(csv2[1], /,snap-20310307-1,2031-03-07T14:59:00Z$/)
  const book = positionFields(p1, wWithId, NOW).find(f => f.field === 'Book snapshot')!
  assert.equal(book.value, 'snap-20310307-1')
  // The unrealized-P&L cell is the served value (or empty + reason) — never a page-computed number.
  const recCsv = holdingsCsv([recorded]).split('\r\n')[1].split(',')
  assert.equal(recCsv[CSV_COLUMNS.indexOf('unrealized_pnl_usd')], '1234.56')
  const p1Csv = holdingsCsv([p1]).split('\r\n')[1]
  assert.match(p1Csv, /,UNKNOWN,,,/)  // basis_status UNKNOWN, no cost basis, no P&L — a reason column carries the words
  assert.match(p1Csv, /cost basis not reported by the broker read/)
}

// OP-026 D2: the primary row carries the WEIGHTED REMAINING BASIS and its per-share average from the same row the
// drawer reads, and a row without a usable basis says "basis not recorded" WITHOUT losing its mark, value or move.
// Synthetic fixtures only. Fail-before: the v002 row model had no avgEntry and no basis line at all, so the table
// could only show a basis indirectly (inside the unrealized sentence, and only when a P&L figure existed).
const op26Wire = wire([
  row({ symbol: 'WK1', account_id: 'acct-a', shares: 600, price: 139.11, market_value: 83466,
    day_change: -495.36, day_change_pct: -0.59, cost_basis: 79620,
    basis_truth: { cost_basis_usd: 79620, unrealized_pl_usd: 3846, unrealized_pl_pct: 4.83, source: 'broker_api', status: 'recorded', gap: null, conflicts: [] } }),
  row({ symbol: 'WK1', account_id: 'acct-b', shares: 200, price: 139.11, market_value: 27822,
    day_change: -165.12, day_change_pct: -0.59, cost_basis: 35239.48,
    basis_truth: { cost_basis_usd: 35239.48, unrealized_pl_usd: -7417.48, unrealized_pl_pct: -21.05, source: 'broker_api', status: 'recorded', gap: null, conflicts: [] } }),
  row({ symbol: 'NOPX', account_id: 'acct-c', shares: 0.133, price: 162.85, market_value: 21.66,
    day_change: -0.44, day_change_pct: -2.01, cost_basis: null,
    basis_truth: { cost_basis_usd: null, unrealized_pl_usd: null, unrealized_pl_pct: null, source: null, status: 'unknown',
      gap: { reason: 'basis unknown — no recorded acquisition cost' }, conflicts: [] } }),
  row({ symbol: 'PARTL', account_id: 'acct-d', shares: 100, price: 50, market_value: 5000,
    day_change: 10, day_change_pct: 0.2, cost_basis: 1000, basis_partial: true,
    basis_truth: { cost_basis_usd: 1000, unrealized_pl_usd: null, unrealized_pl_pct: null, source: 'broker_api', status: 'partial',
      gap: { reason: 'cost basis is partial — the broker lot history starts after some acquisitions' }, conflicts: [] } }),
])
const op26 = positionsFrom(op26Wire, NOW)
const wA = op26.find(p => p.key === 'acct-a:WK1')!
const wB = op26.find(p => p.key === 'acct-b:WK1')!
const nop = op26.find(p => p.symbol === 'NOPX')!
const partl = op26.find(p => p.symbol === 'PARTL')!

// The per-share weighted remaining basis is basis ÷ held shares, computed, not the wire avg_cost field.
assert.equal(Math.round(wA.avgEntry! * 100) / 100, 132.70)
assert.match(basisLine(wA).text, /^basis \$79,620 · avg entry \$132\.70$/)
assert.match(basisLine(wB).text, /^basis \$35,239 · avg entry \$176\.20$/)

// The same ticker in two accounts stays two rows with two different bases — the key carries the account.
assert.notEqual(wA.key, wB.key)
assert.match(wB.key, /^acct-b:WK1$/)
assert.notEqual(wA.avgEntry, wB.avgEntry)

// Missing basis: named as "basis not recorded" with the read's reason — and the price facts survive untouched.
assert.equal(nop.basis.status, 'UNKNOWN')
assert.equal(nop.avgEntry, null)
assert.match(basisLine(nop).text, /^basis not recorded — basis unknown — no recorded acquisition cost$/)
assert.equal(nop.price, 162.85)
assert.equal(nop.value, 21.66)
assert.equal(nop.dayUsd, -0.44)
assert.equal(moveToday(nop).known, true)
assert.match(moveToday(nop).text, /−2\.0% · −\$0/)

// Partial basis is not a recorded basis either: it never licenses a P&L percent, but it keeps the mark.
assert.equal(partl.basis.status, 'UNKNOWN')
assert.match(basisLine(partl).text, /^basis not recorded — cost basis is partial/)
assert.equal(partl.price, 50)
assert.equal(partl.dayUsd, 10)

// Table == drawer: the drawer's Cost basis + Avg entry are the row's two numbers.
const drawerA = positionFields(wA, op26Wire, NOW)
assert.equal(drawerA.find(f => f.field === 'Cost basis')!.value, '$79,620')
assert.equal(drawerA.find(f => f.field === 'Avg entry')!.value, '$132.70')
const drawerNop = positionFields(nop, op26Wire, NOW)
assert.equal(drawerNop.find(f => f.field === 'Cost basis')!.value, 'basis not recorded')
assert.equal(drawerNop.find(f => f.field === 'Avg entry')!.value, 'not recorded (no usable basis)')

// Table == CSV: the exported row carries the same basis and per-share average, blank (never 0) when unknown.
const op26Csv = holdingsCsv(op26).split('\r\n')
const hdr = op26Csv[0].split(',')
assert.ok(hdr.includes('avg_entry_usd'), 'the CSV publishes avg_entry_usd')
const avgI = hdr.indexOf('avg_entry_usd')
const wRows = op26Csv.slice(1).filter(l => l.startsWith('WK1,'))
const rowA = wRows[0].split(',')  // value-desc: acct-a (83,466) before acct-b (27,822)
const rowN = op26Csv.slice(1).find(l => l.startsWith('NOPX,'))!.split(',')
assert.equal(rowA[avgI], '132.7')
assert.equal(rowN[avgI], '')

console.log('portfolioV002.test.ts: ok')
