// Home v010 — stop coverage (campaign item 3): the raw stop read and the coverage product are different readings.
//
// The approved producer is scripts/stop_coverage_incidents.py. Its verdict reaches this page as the `orders` gate
// ("Stop coverage (protection)") of /api/v2/home/status, graded on its OWN clock and its OWN freshness bar
// (900 s in session / 5400 s off-hours, as served in threshold_s). The raw stop read (since-close stop snapshot) is
// labelled RAW here, because a readable snapshot is not a coverage scan:
//   * a current raw read never makes a stale coverage product look current;
//   * a missing / unreadable coverage product is UNPROVEN (UNKNOWN), never a confirmed gap and never "no gaps";
//   * a confirmed gap (GAP) is never softened, and no field of the raw read can clear it.
// Synthetic fixtures only (no real accounts, symbols or values).
import assert from 'node:assert/strict'
import { API, buildModel, loadingRead, statusFrom, type HomeStatusWire, type HomeV010Inputs, type Read } from './homeV010.ts'

const NOW = Date.parse('2026-11-13T15:00:00Z')
const AT = '2026-11-13T14:59:00Z'
const read = <T,>(source: string, data: T): Read<T> => ({ state: 'OK', data, error: null, at: AT, source })
const gate = (id: string, extra: Record<string, unknown> = {}) => ({
  id, label: id, required: true, state: 'OK', source_id: `src_${id}`,
  as_of: '2026-11-13T14:59:00Z', age_s: 60, threshold_s: 900, reason: null, needs_backend: false, ...extra,
})
const statusWire = (gates: unknown[]): Read<HomeStatusWire> => read(API.status, {
  schema: 'HomeStatus@v1', verdict: 'YES',
  trade_ready: { verdict: 'YES', cause: 'every required input read OK', computed_at: AT },
  gates, blockers: [], unknown_inputs: [],
} as never)
/** A since-close payload whose raw stop read succeeded at `stopAsOf`. */
const sinceCloseRead = (stopAsOf: string | null, extra: Record<string, unknown> = {}) => read(API.sinceClose, {
  status: 'ok', freshness: { age_seconds: 30, stale: false, window_current: true },
  cio_brief: {
    status: 'available', stop_advice: [],
    ...(stopAsOf ? { stop_read: { status: 'read', as_of: stopAsOf } } : {}),
  },
  ...extra,
} as never)
const inputs = (gates: unknown[], stopAsOf: string | null = AT): HomeV010Inputs => ({
  sinceClose: sinceCloseRead(stopAsOf),
  approvals: read(API.approvals, { ok: true, data: { count: 0, urgent_count: 0, as_of: AT } } as never),
  incidents: read(API.incidents, { state: 'OK', items: [], counts: { P0: 0, P1: 0 }, data_integrity_24h: { state: 'OK', value: { events: 0 }, age_s: 0 } } as never),
  lastSeen: read(API.lastSeen, { ok: true, read: { status: 'NOT_RECORDED', seen_at: null } } as never),
  status: statusWire(gates),
})

// 1. The snapshot row is the RAW read, named as such, and the model itself never claims coverage from it: with no
//    `orders` gate there is no coverage row and no coverage wording on the raw row.
{
  const m = buildModel(inputs([gate('p0')], AT), NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  assert.equal(raw.name, 'Stop read (raw)')
  assert.equal(raw.state, 'OK')
  assert.equal(m.status.find(r => r.id === 'row-coverage'), undefined, 'the v010 model derives no coverage row')
  assert.doesNotMatch(`${raw.name} ${raw.value}`, /coverage (fresh|ok|clear)/i)
}

// 2. A CURRENT raw read does not upgrade a STALE coverage product: the gate keeps STALE, ages from its own as_of, and
//    carries the producer's bar.
{
  const m = buildModel(inputs([gate('orders', { state: 'STALE', as_of: '2026-11-13T11:00:00Z', reason: 'age 14400 s > 900 s' })], AT), NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  const cov = m.gates!.find(g => g.id === 'orders')!
  assert.equal(raw.state, 'OK', 'the raw read is current')
  assert.equal(cov.state, 'STALE', 'coverage is not current and is never shown current')
  assert.equal(cov.age, '4 h 0 m', 'aged at render from the coverage clock, not from the raw read')
  assert.equal(cov.thresholdS, 900)
  assert.match(cov.reason || '', /14400 s > 900 s/)
}

// 3. A missing coverage product is UNPROVEN (UNKNOWN), not a gap and not a clearance — even beside a fresh raw read.
{
  const m = buildModel(inputs([gate('orders', { state: 'UNKNOWN', as_of: null, age_s: null, needs_backend: true, reason: 'no stop-coverage-incidents heartbeat' })], AT), NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  const cov = m.gates!.find(g => g.id === 'orders')!
  assert.equal(raw.state, 'OK')
  assert.equal(cov.state, 'UNKNOWN')
  assert.equal(cov.asOf, null)
  assert.equal(cov.needsBackend, true, 'an absent producer is flagged, not silently OK')
  assert.match(cov.reason || '', /no .* heartbeat/)
}

// 4. A confirmed GAP is preserved exactly: never softened to UNKNOWN/WARN and never cleared by the raw read. The
//    gate's `value` is a counts object on the wire, so the page carries no count from it — it shows the reason.
{
  const m = buildModel(inputs([gate('orders', { state: 'GAP', reason: '2 position(s) confirmed unprotected' })], AT), NOW)
  const cov = m.gates!.find(g => g.id === 'orders')!
  assert.equal(cov.state, 'GAP')
  assert.equal(cov.count, null, 'a counts object is not a count; nothing is invented')
  assert.match(cov.reason || '', /confirmed unprotected/)
}

// 5. The freshness bar is the producer's, carried as served: session and off-hours bars both survive, and a gate that
//    ships no usable bar gets null rather than an invented limit.
{
  assert.equal(statusFrom(inputs([gate('orders', { threshold_s: 5400 })]).status, NOW).gates![0].thresholdS, 5400)
  assert.equal(statusFrom(inputs([gate('orders', { threshold_s: null })]).status, NOW).gates![0].thresholdS, null)
  assert.equal(statusFrom(inputs([gate('orders', { threshold_s: 0 })]).status, NOW).gates![0].thresholdS, null)
  assert.equal(statusFrom(inputs([gate('orders', { threshold_s: '900' })]).status, NOW).gates![0].thresholdS, null)
}

// 6. `read_status` (no stop read on record) keeps the raw row UNKNOWN and opens no coverage claim.
{
  const m = buildModel(inputs([gate('orders', { state: 'UNKNOWN', as_of: null, needs_backend: true, reason: 'no heartbeat' })], null), NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  assert.equal(raw.name, 'Stop read (raw)')
  assert.equal(raw.state, 'UNKNOWN')
  assert.match(raw.cause || '', /no stop read on record/)
  assert.equal(m.gates!.find(g => g.id === 'orders')!.state, 'UNKNOWN')
}

// 7. A STALE since-close snapshot is never drawn OK, however readable its stop read: the raw row keeps its identity
//    and its state carries the staleness (review item-3 C1; kills the "stale drawn OK" mutant).
{
  const staleSnap = read(API.sinceClose, {
    status: 'ok', freshness: { age_seconds: 4000, stale: true, window_current: true },
    cio_brief: { status: 'available', stop_advice: [], stop_read: { status: 'read', as_of: AT } },
  } as never)
  const m = buildModel({ ...inputs([gate('p0')], AT), sinceClose: staleSnap }, NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  assert.equal(raw.name, 'Stop read (raw)')
  assert.equal(raw.state, 'STALE', 'a stale snapshot is not a current stop read')
  assert.match(raw.cause || '', /raw read; coverage is the orders gate/)
  assert.equal(raw.source, API.sinceClose)
}

// 8. The row keeps that identity while the read is still in flight (review item-3 C1; kills the loading-path name
//    mutant). A LOADING read is not a stop read at all, so nothing about coverage is claimed either.
{
  const m = buildModel({ ...inputs([gate('p0')], AT), sinceClose: loadingRead(API.sinceClose) }, NOW)
  const raw = m.status.find(r => r.id === 'row-orders')!
  assert.equal(raw.name, 'Stop read (raw)')
  assert.equal(raw.state, 'LOADING')
}

console.log('homeV010.coverage: ok')
