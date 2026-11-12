// Portfolio v002 page model (design/pages/portfolio/v002, approved 2026-11-11). Unknown beats wrong:
// UNKNOWN is never drawn as NO STOP, a failed read is never OK or "0", a pending-activation GTC stop counts.
// Synthetic fixtures only (public repo): placeholder symbols, accounts and values.
import assert from 'node:assert/strict'
import {
  readOnce, positionsFrom, protectionModel, p0Items, statusRows, filterPositions, rowProtection, auditCategories, sessionOpenET,
  type HoldingWire, type HoldingsWire, type Read, type IncidentsWire,
} from './portfolioV002.ts'

const AT = '2031-03-07T14:59:00Z'
const NOW = Date.parse('2031-03-07T15:00:00Z')
const ok = <T,>(data: T, source = '/api/v2/portfolio/holdings'): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })
const row = (o: Partial<HoldingWire>): HoldingWire => ({ symbol: 'AAA', account_id: 'acct-1', account_label: 'Broker A ··01', broker: 'broker_a',
  shares: 10, market_value: 1000, price: 100, price_as_of: AT, protection_state: 'PROTECTED',
  protection: { state: 'PROTECTED', reason: 'Resting stop', source: 'stop store', as_of: AT, counted: true }, stop_price: 90, ...o })
const wire = (rows: HoldingWire[], o: Partial<HoldingsWire> = {}): HoldingsWire => ({ holdings: rows, total_value: 5000, today_change: 12,
  positions_as_of: AT, valuation_as_of: AT, quote_as_of: AT, position_counts: { agree: true }, ...o })

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
// GAP (by value), then UNKNOWN, then WARN — not by value. TINY is a GAP under $100: it counts (F1).
assert.deepEqual(mm.action.map(p => p.symbol), ['GGG', 'TINY', 'UUU', 'EEE'])
assert.equal(mm.counted, 5); assert.equal(mm.listedNotCounted, 1); assert.equal(mm.exempt, 1)
assert.equal(mm.gap, 2); assert.equal(mm.warn, 1); assert.equal(mm.unknown, 1)
const onlyUnk = protectionModel(ok(wire([])), mixed.filter(p => p.symbol === 'UUU' || p.symbol === 'PPP'))
assert.equal(onlyUnk.verdict, 'UNKNOWN')   // an unread stop never rolls up to OK
assert.equal(onlyUnk.brokers[0].state, 'UNKNOWN')

// 4. P0 counts GAP rows and a position-count mismatch; it is null (never 0) when the read failed.
const p0 = p0Items(ok(wire([], { position_counts: { agree: false, summary: 'counts disagree' } })), mm)!
assert.deepEqual(p0.map(x => x.category), ['Unprotected Position', 'Position Count Mismatch'])
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

// 8. Filters: unprotected = GAP + WARN; unknown = UNKNOWN; under $100 = a PROTECTED row listed, not counted.
assert.deepEqual(filterPositions(mixed, 'unprotected', 'all').map(p => p.symbol).sort(), ['EEE', 'GGG', 'TINY'])
assert.deepEqual(filterPositions(mixed, 'unknown', 'all').map(p => p.symbol), ['UUU'])
assert.deepEqual(filterPositions(mixed, 'under100', 'all').map(p => p.symbol), ['SMOL'])

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
// The floor still drops a small PROTECTED row from the count (display only).
const small = positionsFrom(wire([row({ symbol: 'SML', market_value: 50, protection: { state: 'PROTECTED', as_of: AT, counted: false } })]), NOW)[0]
assert.equal(small.counted, false); assert.equal(small.underFloor, true)

// F2: zero counted positions is UNKNOWN unless the position count confirms zero.
const cashOnly = [row({ symbol: 'CASH', is_cash: true, protection_state: 'EXEMPT', protection: { state: 'EXEMPT', counted: false } })]
const f2 = verdictOf(cashOnly)
assert.equal(f2.verdict, 'UNKNOWN'); assert.equal(f2.counted, 0); assert.ok(f2.cause)
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

console.log('portfolioV002.test.ts: ok')
