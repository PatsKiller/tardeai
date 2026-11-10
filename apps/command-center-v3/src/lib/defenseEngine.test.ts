// DefenseProjection@v1 display helpers (design defense/v001). Synthetic values only (public repo).
// Run: node --experimental-strip-types src/lib/defenseEngine.test.ts
// No node:assert / node:fs: CI's tsc has no @types/node (same local check as designTokens.test.ts).
import { clockET, defenseLines, GAP, isProjection, unwrapProjection, ladder, money, pct, readinessTone, scorePosition, signed, sourceSummaryText, tierPair, tierTone, unprotectedPair, type DefenseProjection } from './defenseEngine.ts'

function fail(msg: string): never { throw new Error(msg) }
const assert = {
  equal: (a: unknown, b: unknown, m = '') => { if (a !== b) fail(`${m}: expected ${String(b)} got ${String(a)}`) },
  ok: (c: unknown, m = 'assertion failed') => { if (!c) fail(m) },
}
let passed = 0
function test(name: string, fn: () => void) { fn(); passed += 1; void name }

test('money and pct never invent a number', () => {
  assert.equal(money(86400), '$86.4K', 'k')
  assert.equal(money(1_250_000), '$1.3M', 'm')
  assert.equal(money(211), '$211', 'small')
  assert.equal(money(null), GAP, 'null')
  assert.equal(money(Number.NaN), GAP, 'nan')
  assert.equal(pct(29.31, 1), '29.3%', 'pct')
  assert.equal(pct(undefined), GAP, 'pct gap')
  assert.equal(signed(7.54), '+7.5', 'signed +')
  assert.equal(signed(-5.5), '−5.5', 'signed −')
})

test('tier and readiness tones', () => {
  assert.equal(tierTone('RED'), 'bad', 'red')
  assert.equal(tierTone('orange'), 'bad', 'orange')
  assert.equal(tierTone('YELLOW'), 'warn', 'yellow')
  assert.equal(tierTone(null), 'muted', 'none')
  assert.equal(readinessTone('NOT NOW'), 'info', 'not now')
  assert.equal(readinessTone('CONDITIONS MET'), 'bad', 'met')
  assert.equal(readinessTone(undefined), 'warn', 'unknown')
})

test('ladder fills every tier and marks the current one', () => {
  const l = ladder({ tier: 'ORANGE', ladder: [{ tier: 'RED', min_score: 75, current: false }] })
  assert.equal(l.map(s => s.tier).join(','), 'GREEN,BLUE,YELLOW,ORANGE,RED', 'order')
  assert.equal(l.find(s => s.tier === 'ORANGE')?.current, true, 'current')
  assert.equal(l.find(s => s.tier === 'RED')?.min_score, 75, 'kept floor')
  assert.equal(scorePosition(140), 100, 'clamped')
  assert.equal(scorePosition(null), null, 'unmeasured')
})

test('clockET states a gap instead of a fake time', () => {
  const now = new Date('2030-01-07T21:00:00Z')
  assert.equal(clockET('2030-01-07T20:15:00+00:00', now), '15:15 ET', 'same day')
  assert.ok(clockET('2030-01-04T20:15:00+00:00', now).endsWith('15:15 ET'), 'weekday prefix')
  assert.equal(clockET('2030-01-07', now), '01-07 close', 'date only')
  assert.equal(clockET(null, now), GAP, 'null')
  assert.equal(clockET('garbage', now), GAP, 'garbage')
})

test('source summary leaves zero counts out', () => {
  assert.equal(sourceSummaryText({ fresh: 7, stale: 0, missing: 0, paused: 1, no_writer: 1 }), '7 fresh · 1 paused · 1 no writer', 'summary')
  assert.equal(sourceSummaryText(undefined, [{ id: 'a', label: 'A', state: 'fresh' }, { id: 'b', label: 'B', state: 'stale' }]), '1 fresh · 1 stale', 'derived')
})

const P: DefenseProjection = {
  schema: 'DefenseProjection@v1', generated_at: '2030-01-07T20:00:00+00:00',
  narrative: { headline: 'Synthetic headline.', where_we_stand: [], what_to_do: [] },
  tier: { tier: 'ORANGE', score: 62 },
  exposure: { stressed_usd: 12000, stressed_pct_invested: 24, cash_pct_book: 40, cash_usd: 50000,
    rows: [{ symbol: 'ZZAA', usd_exposed: 8000 }, { symbol: 'ZZBB', usd_exposed: 4000 }, { symbol: 'ZZAA', usd_exposed: 100 }] },
  stops: { no_stop: { count: 2, value_usd: 3000 }, pending: { count: 1 } },
  hedge_readiness: { readiness: 'NOT NOW', met_count: 1, of: 2, shock_class: 'SECTOR' },
  playbook: {}, base_rates: { n: 30, further_drop_pct: 19, rows: [] }, cash_alternatives: { yields_on_file: false, stale_reason: 'no scheduled writer' },
  sector_posture: { stressed: ['Semis'], sectors_measured: 11, sectors_hit: 1 }, recommendations: {}, watch_next: { items: [{ text: 'CPI' }] },
  sources: [{ id: 'cash', label: 'Cash alternatives', state: 'no_writer' }, { id: 'market_risk', label: 'Market Risk', state: 'fresh' }],
  source_summary: { fresh: 1, no_writer: 1 },
}

test('defense lines carry one value per projection field', () => {
  assert.ok(isProjection(P), 'schema')
  assert.ok(!isProjection({ schema: 'Other' }), 'other schema')
  assert.equal(unwrapProjection({ ok: true, served_from: 'request_build', stale: false, data: P }), P, 'served envelope')
  assert.equal(unwrapProjection({ ok: true, data: { ok: true, data: P } }), P, 'double envelope')
  assert.equal(unwrapProjection(P), P, 'bare')
  assert.equal(unwrapProjection({ data: { schema: 'Other' } }), null, 'other schema in envelope')
  const lines = defenseLines(P, new Date('2030-01-07T21:00:00Z'))
  assert.equal(lines.map(l => l.sheet).join(','), 'exposure,stops,hedge,sector,cash,base,watch,sources', 'order')
  const by = Object.fromEntries(lines.map(l => [l.id, l]))
  assert.equal(by.book.value, '$12.0K', 'book value')
  assert.equal(by.book.sub, 'ZZAA · ZZBB', 'book names deduped')
  assert.equal(by.book.tone, 'warn', 'book tone')
  assert.equal(by.stops.sub, '2 without a broker stop · 1 pending', 'stops sub')
  assert.equal(by.hedge.value, 'NOT NOW', 'hedge')
  assert.equal(by.sector.valueSub, '10 of 11 holding', 'sector')
  assert.equal(by.cash.value, '40%', 'cash pct')
  assert.equal(by.base.value, '19%', 'base')
  assert.equal(by.sources.value, '1 fresh · 1 no writer', 'sources')
  assert.equal(by.sources.sub, 'Cash alternatives no writer', 'sources sub')
})

// LQ-20261107-1837 (C4): the projection's stops section is a FROZEN copy of a cio_truth count. When the live
// authority answered, the line prints its count and the value over the same rows — the number Home and Risk print.
test('the live cio_truth count replaces the projection\'s frozen stops copy', () => {
  const live = { unprotected: { count: 4, valueUsd: 49_089.02, asOf: '2026-11-10T20:54:00Z' } }
  const by = Object.fromEntries(defenseLines(P, new Date('2030-01-07T21:00:00Z'), live).map(l => [l.id, l]))
  assert.equal(by.stops.sub, '4 without a broker stop · 1 pending', 'live count, projection pending')
  assert.equal(by.stops.value, '$49.1K', 'live counted value')
  assert.equal(by.stops.asOf, '2026-11-10T20:54:00Z', 'live as_of')
  assert.equal(by.stops.tone, 'warn', 'a non-zero count warns')
  const zero = { unprotected: { count: 0, valueUsd: 0, asOf: null } }
  const z = Object.fromEntries(defenseLines(P, new Date('2030-01-07T21:00:00Z'), zero).map(l => [l.id, l]))
  assert.equal(z.stops.sub, '0 without a broker stop · 1 pending', 'zero is a measurement')
  assert.equal(z.stops.tone, 'good', 'zero unprotected is good, not a gap')
})

test('a live authority that did not answer leaves the projection copy, never a zero', () => {
  const by = Object.fromEntries(defenseLines(P, new Date('2030-01-07T21:00:00Z'), { unprotected: { count: null, valueUsd: null, asOf: null } }).map(l => [l.id, l]))
  assert.equal(by.stops.sub, '2 without a broker stop · 1 pending', 'projection fallback')
  assert.equal(by.stops.value, '$3.0K', 'projection value')
})

// LQ-20261107-1837 REWORK 2 (must-fix F1): cio_truth answers with a count and NO counted value whenever any
// counted row is unpriced (`_sum_known` returns None) or the book is empty (count 0, value None). A per-field
// `??` then printed the projection's no_stop value beside cio_truth's count — two populations, two build times,
// one label. The value must read as a gap, and the clock must be the answering record's.
test('a live count with no counted value is a gap, never the projection\'s value', () => {
  const live = { unprotected: { count: 4, valueUsd: null, asOf: '2026-11-10T20:54:00Z' } }
  const by = Object.fromEntries(defenseLines(P, new Date('2030-01-07T21:00:00Z'), live).map(l => [l.id, l]))
  assert.equal(by.stops.sub, '4 without a broker stop · 1 pending', 'the live count')
  assert.equal(by.stops.value, GAP, 'the projection\'s $3.0K must never sit beside cio_truth\'s 4')
  assert.equal(by.stops.asOf, '2026-11-10T20:54:00Z', 'the answering record\'s clock')
  assert.equal(by.stops.staleReason, null, 'the projection\'s stale reason does not date the live pair')
})

// REWORK 3 (N1): the mirror case — cio_truth publishes the counted VALUE but not the count. The pair rule makes
// that a legitimate answer, so the stop line shows its real dollar figure with a count gap; `(count ?? 0) > 0`
// then read the gap as zero and painted that figure GREEN. An unknown count is not a measurement of zero.
test('a live value with no count is never painted green', () => {
  const live = { unprotected: { count: null, valueUsd: 4_000, asOf: null } }
  const by = Object.fromEntries(defenseLines(P, new Date('2030-01-07T21:00:00Z'), live).map(l => [l.id, l]))
  assert.equal(by.stops.value, '$4.0K', 'the value it published is shown')
  assert.equal(by.stops.sub, `${GAP} without a broker stop · 1 pending`, 'the count is a gap, not 2')
  assert.ok(by.stops.tone !== 'good', 'an unknown count must not read as "nothing unprotected"')
  assert.equal(by.stops.tone, 'muted', 'no reading, no colour claim')
})

test('the unprotected pair never mixes sources, in either direction', () => {
  const onlyValue = unprotectedPair(P, { unprotected: { count: null, valueUsd: 4_000, asOf: null } })
  assert.equal(onlyValue.count, null, 'a count cio_truth did not publish is a gap, never the projection\'s 2')
  assert.equal(onlyValue.valueUsd, 4_000, 'the value it did publish is shown')
  assert.equal(onlyValue.source, 'cio_truth', 'named')
  const none = unprotectedPair(P, null)
  assert.equal(none.count, 2, 'projection count when nothing answered')
  assert.equal(none.valueUsd, 3_000, 'projection value, the SAME source')
  assert.equal(none.source, 'projection', 'named')
})

// REWORK 2 (F4): the tier, score and clock are one record. A snapshot with a tier and no score (state
// not_evaluated) used to print "NOT_EVALUATED · 62" — the live tier with the projection's frozen score — and
// the ladder dated it with the projection's as_of.
test('a snapshot with a tier and no score prints a gap, never the frozen score', () => {
  const tp = tierPair(P, { marketRisk: { tier: 'NOT_EVALUATED', score: null, asOf: '2026-11-10T20:55:00Z' } })
  assert.equal(tp.tier, 'NOT_EVALUATED', 'the live tier')
  assert.equal(tp.score, null, 'no frozen score beside the live tier')
  assert.equal(tp.asOf, '2026-11-10T20:55:00Z', 'the snapshot\'s clock')
  assert.equal(tp.source, 'snapshot', 'named')
  const proj = tierPair(P, null)
  assert.equal(proj.tier, 'ORANGE', 'projection tier when no snapshot')
  assert.equal(proj.score, 62, 'projection score, the same record')
  assert.equal(proj.source, 'projection', 'named')
})

test('a bare projection still renders every line with gaps, never a crash', () => {  const bare = { schema: 'DefenseProjection@v1', generated_at: '2030-01-07T20:00:00+00:00', narrative: {}, tier: {}, exposure: {}, stops: {},
    hedge_readiness: {}, playbook: {}, base_rates: {}, cash_alternatives: {}, sector_posture: {}, recommendations: {}, watch_next: {}, sources: [] } as unknown as DefenseProjection
  const lines = defenseLines(bare)
  assert.equal(lines.length, 8, 'eight lines')
  assert.equal(lines[0].value, GAP, 'book gap')
  assert.equal(lines[2].value, 'UNKNOWN', 'hedge unknown')
})

console.log(`defenseEngine.test.ts: ${passed} passed`)
