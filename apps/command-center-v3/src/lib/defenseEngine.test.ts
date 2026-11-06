// DefenseProjection@v1 display helpers (design defense/v001). Synthetic values only (public repo).
// Run: node --experimental-strip-types src/lib/defenseEngine.test.ts
// No node:assert / node:fs: CI's tsc has no @types/node (same local check as designTokens.test.ts).
import { clockET, defenseLines, GAP, isProjection, ladder, money, pct, readinessTone, scorePosition, signed, sourceSummaryText, tierTone, type DefenseProjection } from './defenseEngine.ts'

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

test('a bare projection still renders every line with gaps, never a crash', () => {
  const bare = { schema: 'DefenseProjection@v1', generated_at: '2030-01-07T20:00:00+00:00', narrative: {}, tier: {}, exposure: {}, stops: {},
    hedge_readiness: {}, playbook: {}, base_rates: {}, cash_alternatives: {}, sector_posture: {}, recommendations: {}, watch_next: {}, sources: [] } as unknown as DefenseProjection
  const lines = defenseLines(bare)
  assert.equal(lines.length, 8, 'eight lines')
  assert.equal(lines[0].value, GAP, 'book gap')
  assert.equal(lines[2].value, 'UNKNOWN', 'hedge unknown')
})

console.log(`defenseEngine.test.ts: ${passed} passed`)
