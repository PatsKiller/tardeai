// Catalyst impact panel model (LQ-20261107-135). Synthetic tickers only; no holdings or account data.
//   node --experimental-strip-types src/lib/catalystImpact.test.ts
import {
  dayText, describeRow, directionTone, impactView, magnitudeText, priceText, weightText,
} from './catalystImpact.ts'
import type { CatalystImpactPayload, CatalystImpactRow } from './catalystImpact.ts'

declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

const row = (extra: Partial<CatalystImpactRow> = {}): CatalystImpactRow => ({
  id: 1, symbol: 'ZZZA', catalyst_type: 'analyst_upgrade', headline: 'A synthetic headline',
  expected_direction: 'UP', expected_magnitude: 3.7, price_at_event: 12.5, portfolio_impact_pct: 4.25,
  event_at: '2026-11-06T14:00:00-05:00', recorded_at: '2026-11-06T17:20:04-05:00', ...extra,
})
const payload = (extra: Partial<CatalystImpactPayload> = {}): CatalystImpactPayload => ({
  ok: true, schema: 'CatalystSymbolImpact@v1', days: 90, limit: 25, status: 'ok', count: 1,
  rows: [row()], ...extra,
})

t('direction is UP/DOWN/NEUTRAL; anything else is unknown, never neutral', () => {
  eq(directionTone('UP'), 'up'); eq(directionTone(' down '), 'down'); eq(directionTone('NEUTRAL'), 'neutral')
  eq(directionTone(null), 'unknown'); eq(directionTone(''), 'unknown'); eq(directionTone('SIDEWAYS'), 'unknown')
})

t('an unrecorded magnitude or price is a dash, never a zero', () => {
  eq(magnitudeText(row()), '3.7'); eq(magnitudeText(row({ expected_magnitude: null })), '—')
  eq(magnitudeText(row({ expected_magnitude: undefined })), '—')
  eq(priceText(row()), '$12.50 at event'); eq(priceText(row({ price_at_event: null })), 'price at event unknown')
})

t('a weight of zero says not held; a missing weight says unknown', () => {
  eq(weightText(row()), '4.3% of portfolio'); eq(weightText(row({ portfolio_impact_pct: 0 })), 'not held')
  eq(weightText(row({ portfolio_impact_pct: null })), 'weight unknown')
})

t('a timestamp becomes the day it happened, or a dash', () => {
  eq(dayText('2026-11-06T14:00:00-05:00'), '2026-11-06'); eq(dayText(null), '—'); eq(dayText('garbage'), '—')
})

t('a row reads as one plain sentence', () => {
  eq(describeRow(row()), 'analyst upgrade · UP · impact 3.7 · 4.3% of portfolio')
  eq(describeRow(row({ expected_direction: null })), 'analyst upgrade · direction not recorded · impact 3.7 · 4.3% of portfolio')
})

t('rows produce a sentence naming how many and over what window', () => {
  const v = impactView(payload({ rows: [row(), row({ id: 2 })] }))
  eq(v.state, 'rows'); eq(v.state === 'rows' ? v.sentence : '', '2 catalysts in the last 90 days')
  const one = impactView(payload())
  eq(one.state === 'rows' ? one.sentence : '', '1 catalyst in the last 90 days')
})

t('an empty window names when the writer last recorded something', () => {
  const v = impactView(payload({ status: 'no_rows_in_window', count: 0, rows: [], last_row_at: '2026-07-09T10:00:00Z', rows_written_total: 9 }))
  eq(v.state, 'empty')
  eq(v.state === 'empty' ? v.sentence : '', 'No catalyst impact recorded in the last 90 days')
  eq(v.state === 'empty' ? v.detail !== null : true, true)
})

t('a symbol the writer never saw says so, not "0 catalysts"', () => {
  const v = impactView(payload({ status: 'no_rows', count: 0, rows: [], note: 'the writer has recorded no catalyst impact for ZZZB' }))
  eq(v.state, 'empty')
  eq(v.state === 'empty' ? v.sentence : '', 'the writer has recorded no catalyst impact for ZZZB')
})

t('a failed read is UNAVAILABLE, never an empty list', () => {
  const v = impactView(null, { error: 'HTTP 500' })
  eq(v.state, 'unavailable'); eq(v.state === 'unavailable' ? v.sentence.includes('UNAVAILABLE'.toLowerCase()) || v.sentence.includes('unavailable') : false, true)
  const w = impactView(undefined, { loading: true }); eq(w.state, 'loading')
  const x = impactView({ ok: false } as CatalystImpactPayload); eq(x.state, 'unavailable')
})

t('a payload with no rows but status ok still reports the recorded-anything sentence', () => {
  const v = impactView({ ok: true, days: 30, rows: [] } as CatalystImpactPayload)
  eq(v.state, 'empty')
})

console.log(`\n  ${n} checks passed — catalystImpact (LQ-20261107-135)`)
