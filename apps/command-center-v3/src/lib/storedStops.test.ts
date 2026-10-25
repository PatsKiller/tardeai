// node --experimental-strip-types src/lib/storedStops.test.ts
// Stored broker stops for page views (page audit 2026-10-25): only an ACTIVE stored resting order counts.
import { storedStopFor, storedStopsAsOf } from './storedStops.ts'
declare const process: { exit(code?: number): never }

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}

const active = { symbol: 'fixa', account: 'fixture_account', stop_source: 'broker_resting', stop_state: 'active',
  stop_price: 41.5, stop_qty: 10, stop_order_id: 'fixture-order-1', stop_captured_at: '2026-10-24T20:00:00Z' }
const s = storedStopFor(active)
eq('active stored stop', [s?.symbol, s?.stop_price, s?.order_id, s?.source, s?.broker_verified, s?.fetched_at],
  ['FIXA', 41.5, 'fixture-order-1', 'stop_last_known', false, '2026-10-24T20:00:00Z'])
eq('pending is not protection', storedStopFor({ ...active, stop_state: 'pending_activation' }), undefined)
eq('filled is not protection', storedStopFor({ ...active, stop_state: 'filled' }), undefined)
eq('planned level is not a broker stop', storedStopFor({ ...active, stop_source: 'planned' }), undefined)
eq('no price is not protection', storedStopFor({ ...active, stop_price: null }), undefined)
eq('no row', storedStopFor(undefined), undefined)
eq('oldest capture', storedStopsAsOf([active, { ...active, stop_captured_at: '2026-10-23T20:00:00Z' }, { ...active, stop_state: 'filled', stop_captured_at: '2026-10-01T00:00:00Z' }]),
  '2026-10-23T20:00:00Z')
eq('no stored stops → null', storedStopsAsOf([{ symbol: 'X', stop_source: 'none' }]), null)

if (failed) { console.error(`${failed} failed`); process.exit(1) }
console.log('storedStops: all passed')
