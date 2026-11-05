const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  ok(value: unknown, message = 'expected truthy value') { if (!value) throw new Error(message) },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import {
  FAIL_RATE_BANNER_PCT, STALE_AFTER_MS, displayCount, fmtEt, matchesFilter, projectAutomations, rowFailure,
  searchRows, topCause, type AutomationsPayload, type WorkflowRow,
} from './automationsProjection.ts'

const NOW = Date.parse('2026-11-05T12:00:00Z')
const at = (offsetMs: number) => new Date(NOW - offsetMs).toISOString()
const row = (over: Partial<WorkflowRow> = {}): WorkflowRow => ({
  name: 'tradeai-fabric-run-lane', state: 'live', runs: 42, ok: 42, fail: 0, folder: 'fabric', steps: 6, ...over,
})
const payload = (over: Partial<AutomationsPayload> = {}): AutomationsPayload => ({
  schema: 'Automations@v1', as_of: at(30_000), window_days: 7,
  kpi: { runs: 100, ok: 85, failed: 15, running: 0, fail_rate_pct: 15, avg_run_s: 4.2, cron_left: 368, cron_left_has_draft: 140, deltas: null, deltas_unavailable_reason: 'no prior 7-day snapshot' },
  workflows: [row(), row({ name: 'tradeai-event-router', fail: 15, ok: 0, runs: 15, last_error: 'ETIMEDOUT calling relay', state: 'off' })],
  counts: { workflows: 2, live: 1, shadow: 0, off: 1, failing: 1 },
  ...over,
})

// The banner comes only from a MEASURED rate over 10%, and it names the top cause.
const v = projectAutomations(payload(), { nowMs: NOW })
assert.equal(v.status, 'OK')
assert.equal(v.banner.show, true)
assert.equal(v.banner.cause?.name, 'tradeai-event-router')
assert.equal(v.banner.cause?.reason, 'ETIMEDOUT calling relay')

// At exactly the threshold it is quiet, and an unreadable rate never reads as "fine".
assert.equal(projectAutomations(payload({ kpi: { ...payload().kpi, fail_rate_pct: FAIL_RATE_BANNER_PCT } }), { nowMs: NOW }).banner.show, false)
assert.equal(projectAutomations(payload({ kpi: { ...payload().kpi, fail_rate_pct: null } }), { nowMs: NOW }).banner.show, false)

// Stale after three missed one-minute refreshes; an unknown schema is UNAVAILABLE with no rows.
assert.equal(projectAutomations(payload({ as_of: at(STALE_AFTER_MS + 1) }), { nowMs: NOW }).status, 'STALE')
assert.equal(projectAutomations(payload({ schema: 'Something@v2' }), { nowMs: NOW }).status, 'UNAVAILABLE')
assert.equal(projectAutomations(null, { nowMs: NOW }).status, 'UNAVAILABLE')
assert.equal(projectAutomations(null, { nowMs: NOW }).rows.length, 0, 'an unavailable payload renders no rows rather than an empty healthy table')

// An absent week-over-week delta stays unknown WITH its reason, never a zero.
assert.equal(v.kpi.deltas, null)
assert.equal(v.kpi.deltasUnavailable, 'no prior 7-day snapshot')
assert.equal(displayCount(null), '—')

// Filters.
const rows = [
  row(),
  row({ name: 'tradeai-event-router', fail: 3, state: 'off', last_error: 'relay refused', folder: 'routing' }),
  row({ name: 'shadow-lane', state: 'shadow', folder: 'research' }),
]
assert.equal(rows.filter(r => matchesFilter(r, 'failing')).map(r => r.name).join(','), 'tradeai-event-router')
assert.equal(rows.filter(r => matchesFilter(r, 'live')).map(r => r.name).join(','), 'tradeai-fabric-run-lane')
assert.equal(rows.filter(r => matchesFilter(r, 'off')).map(r => r.name).join(','), 'tradeai-event-router')
assert.equal(rows.filter(r => matchesFilter(r, 'all')).length, 3)

// Search over name, area and error text, case-insensitively; blank query keeps everything.
assert.equal(searchRows(rows, 'ROUTER').map(r => r.name).join(','), 'tradeai-event-router')
assert.equal(searchRows(rows, 'fabric').map(r => r.name).join(','), 'tradeai-fabric-run-lane')
assert.equal(searchRows(rows, 'relay refused').map(r => r.name).join(','), 'tradeai-event-router')
assert.equal(searchRows(rows, '   ').length, 3)

// A failing row with no error text says so instead of inventing a cause.
assert.equal(rowFailure(row()).failing, false)
assert.equal(rowFailure(row()).reason, null)
assert.equal(rowFailure(row({ fail: 1, last_error: null })).reason, 'no error text recorded for the last failure')

// The banner's top cause is the failing row with the most failures, never the first seen.
const cause = topCause([row({ name: 'a', fail: 2, last_error: 'x' }), row({ name: 'b', fail: 9, last_error: 'y' })])
assert.equal(cause?.name, 'b'); assert.equal(cause?.fail, 9)
assert.equal(topCause([row()]), null)

// ET formatting returns null on junk rather than a fake date.
assert.match(String(fmtEt('2026-11-05T16:30:00Z')), /ET/)
assert.equal(fmtEt('not-a-date'), null)
assert.equal(fmtEt(null), null)

console.log('automationsProjection: banner threshold and cause, stale/unavailable, delta honesty, filters, search, row failure text and ET fallback passed')
