// LQ-20261107-2708: one verdict per book. The page side of the shared protection-books contract.
// tests/fixtures/portfolio_protection_books_lq2708.json is also read by
// tests/test_portfolio_protection_books_lq2708_20261112.py, which runs each book's positions through
// cio_truth.protection_for (the wire stored here) and stops_protection.summary. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  positionsFrom, protectionModel, p0Items, priceMissing, STOP_READ_MAX_AGE_MS, R1_EXPIRED_OPEN_SESSION,
  type HoldingWire, type HoldingsWire, type Read,
} from './portfolioV002.ts'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..')
const doc = JSON.parse(readFileSync(join(REPO, 'tests', 'fixtures', 'portfolio_protection_books_lq2708.json'), 'utf8')) as {
  now: string; stop_read_max_age_s: { session: number; off_hours: number }; r1_expired_open_session: string
  books: { name: string; wire: HoldingWire[]; position_counts?: HoldingsWire['position_counts']; expect: { page: string; summary: string }; split?: string }[]
}
const NOW = Date.parse(doc.now)
const ok = (data: HoldingsWire): Read<HoldingsWire> => ({ state: 'OK', data, error: null, at: doc.now, source: '/api/v2/portfolio/holdings' })
const verdictOf = (w: HoldingsWire) => protectionModel(ok(w), positionsFrom(w, NOW))

// 1. Every book: the page verdict is the fixture's, and the page/summary pair obeys the one-book invariants.
assert.ok(doc.books.length >= 9, 'the shared fixture lost books')
for (const b of doc.books) {
  const w: HoldingsWire = { holdings: b.wire, position_counts: b.position_counts ?? { agree: true } }
  const m = verdictOf(w)
  assert.equal(m.verdict, b.expect.page, `${b.name}: page verdict`)
  assert.ok(!(m.verdict === 'GAP' && b.expect.summary === 'OK'), `${b.name}: page GAP while the backend reads OK`)
  assert.ok(!(m.verdict === 'OK' && b.expect.summary !== 'OK'), `${b.name}: page OK while the backend reads ${b.expect.summary}`)
  if (m.verdict !== b.expect.summary) {
    assert.ok(b.split, `${b.name}: page ${m.verdict} vs backend ${b.expect.summary} is not a declared split`)
    assert.equal(m.verdict, 'UNKNOWN', `${b.name}: a declared split may only be the page reading UNKNOWN`)
  }
  // R2/R1: a split that hides a backend GAP keeps that GAP visible as a P0 row (stale) or an action row (expired).
  if (b.expect.summary === 'GAP' && m.verdict !== 'GAP') {
    const gapSyms = b.wire.filter(r => r.protection_state === 'GAP' && r.protection?.counted).map(r => String(r.symbol))
    const shown = new Set(m.action.map(p => p.symbol))
    for (const s of gapSyms) assert.ok(shown.has(s), `${b.name}: backend GAP ${s} vanished from the page`)
  }
}
// The stale-read book keeps its last-known GAP as a P0 row.
{
  const b = doc.books.find(x => x.name === 'stale_gap_read_in_session')!
  const w: HoldingsWire = { holdings: b.wire, position_counts: { agree: true } }
  const p0 = p0Items(ok(w), verdictOf(w))!
  assert.ok(p0.some(i => i.category === 'Unprotected Position (stale read)'), 'stale GAP lost its P0 row')
}

// 2. One number for the stop-read limits and R1: the fixture, the registry and the page constants agree.
assert.equal(STOP_READ_MAX_AGE_MS.session, doc.stop_read_max_age_s.session * 1000)
assert.equal(STOP_READ_MAX_AGE_MS.offHours, doc.stop_read_max_age_s.off_hours * 1000)
const reg = JSON.parse(readFileSync(join(REPO, 'config', 'data_source_authority.json'), 'utf8')) as Record<string, unknown>
const stopsDom = ['domains', 'proposed_domains'].flatMap(g => (reg[g] as { domain?: string }[] | undefined) || [])
  .find(d => d && d.domain === 'broker_stops') as { stale_after_hours: number; stale_after_hours_closed: number } | undefined
assert.ok(stopsDom, 'config/data_source_authority.json has no broker_stops domain')
assert.equal(STOP_READ_MAX_AGE_MS.session, stopsDom.stale_after_hours * 3_600_000, 'session limit differs from the registry')
assert.equal(STOP_READ_MAX_AGE_MS.offHours, stopsDom.stale_after_hours_closed * 3_600_000, 'closed limit differs from the registry')
assert.equal(R1_EXPIRED_OPEN_SESSION, doc.r1_expired_open_session)
const pvPath = join(REPO, 'config', 'protection_verdict.json')
if (existsSync(pvPath)) {
  const pv = JSON.parse(readFileSync(pvPath, 'utf8')) as { protection_verdict?: { expired_day_stop_open_session?: string } }
  assert.equal(R1_EXPIRED_OPEN_SESSION, pv.protection_verdict?.expired_day_stop_open_session, 'R1 differs from config/protection_verdict.json')
} else {
  // Before LQ-2412 folds, the owner's fallback for a missing config is the safe side: UNKNOWN.
  assert.equal(R1_EXPIRED_OPEN_SESSION, 'UNKNOWN')
}

// 3. A value <= 0 is a missing price on any wire (owner rule, LQ-2436 F3), even a pre-2436 wire that says counted:false.
const gapRow = (o: Partial<HoldingWire>): HoldingWire => ({ symbol: 'SYNZ', account_id: 'acct-1', broker: 'broker_a', market_value: 0,
  protection_state: 'GAP', protection: { state: 'GAP', counted: false, as_of: doc.now }, ...o })
const protRow: HoldingWire = { symbol: 'SYNA', account_id: 'acct-1', broker: 'broker_a', market_value: 5000, stop_price: 90,
  protection_state: 'PROTECTED', protection: { state: 'PROTECTED', counted: true, as_of: doc.now } }
for (const mv of [0, -5]) {
  const w: HoldingsWire = { holdings: [protRow, gapRow({ market_value: mv })], position_counts: { agree: true } }
  assert.equal(verdictOf(w).verdict, 'GAP', `market_value ${mv} hid a GAP`)
  assert.equal(priceMissing(gapRow({ market_value: mv })), true)
}
// Guard: a KNOWN positive value under the floor is still listed, not counted (DECISIONS-20261111 line 21).
{
  const w: HoldingsWire = { holdings: [protRow, gapRow({ market_value: 40 })], position_counts: { agree: true } }
  const m = verdictOf(w)
  assert.equal(m.verdict, 'OK'); assert.equal(m.listedNotCounted, 1)
  assert.equal(priceMissing(gapRow({ market_value: 40 })), false)
}
// A known positive value with a stale price_missing flag (repriced after the protection read) is listed, as the owner
// (price_missing_of reads the value) and stops_protection.summary (reads counted:false) both list it: no page-only GAP.
{
  const stale = gapRow({ market_value: 40, protection: { state: 'GAP', counted: false, price_missing: true, as_of: doc.now } })
  const m = verdictOf({ holdings: [protRow, stale], position_counts: { agree: true } })
  assert.equal(m.verdict, 'OK'); assert.equal(m.listedNotCounted, 1); assert.equal(priceMissing(stale), false)
}

console.log('portfolioV002.contract.test.ts: ok')
