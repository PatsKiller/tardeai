// Scheduler checks (Coordination › Automation merged into Jobs & n8n, 2026-11-06). Synthetic rows only.
import assert from 'node:assert/strict'
import {
  ageWords, checkKinds, driftText, filterChecks, freshnessText, isUnregistered, kindCounts, observationExpired, outputText, schedulerLaneApi,
} from './schedulerChecks.ts'

let n = 0
const t = (name, fn) => { fn(); n++; console.log('ok', name) }
const row = (o = {}) => ({ lane_id: 'job-a', domain: null, owner: 'platform', scheduler_type: 'cron', runtime_state: 'LIVE', slo_verdict: 'NOT_MEASURED',
  duplicate_scheduler: false, scheduler_drift: false, health_reason: null, freshness: 'NOT_MEASURED', output_age: null, output_signal: null, declared_in_registry: true, ...o })

t('state, duplicate, drift and SLO each become a check', () => {
  assert.deepEqual(checkKinds(row({ runtime_state: 'SILENT', duplicate_scheduler: true })), ['silent', 'duplicate'])
  assert.deepEqual(checkKinds(row({ runtime_state: 'DRIFT', scheduler_drift: true })), ['drift'])
  assert.deepEqual(checkKinds(row({ slo_verdict: 'CADENCE_LT_P95' })), ['slo'])
  assert.deepEqual(checkKinds(row()), [])
  assert.deepEqual(checkKinds(row({ runtime_state: 'NOT_MEASURED' })), [])
})
t('kind counts follow CHECK_KINDS order and skip empty kinds', () => {
  const rows = [row({ runtime_state: 'ORPHANED' }), row({ runtime_state: 'RUN_FAILED' }), row({ runtime_state: 'ORPHANED', duplicate_scheduler: true })]
  assert.deepEqual(kindCounts(rows).map(c => [c.kind, c.count]), [['failed', 1], ['orphaned', 2], ['duplicate', 1]])
})
t('filters by kind, scheduler and text', () => {
  const rows = [row({ lane_id: 'x', runtime_state: 'SLOW', scheduler_type: 'systemd' }), row({ lane_id: 'y', runtime_state: 'SLOW', health_reason: 'p95 over cadence' }), row({ lane_id: 'z', runtime_state: 'DRIFT' })]
  assert.deepEqual(filterChecks(rows, { kind: 'slow' }).map(r => r.lane_id), ['x', 'y'])
  assert.deepEqual(filterChecks(rows, { kind: 'slow', scheduler: 'cron' }).map(r => r.lane_id), ['y'])
  assert.deepEqual(filterChecks(rows, { q: 'CADENCE' }).map(r => r.lane_id), ['y'])
  assert.equal(filterChecks(rows, { scheduler: 'all' }).length, 3)
})
t('unregistered entries are recognised by flag or id', () => {
  assert.equal(isUnregistered(row({ declared_in_registry: false })), true)
  assert.equal(isUnregistered(row({ lane_id: 'unregistered-cron-abc-12', declared_in_registry: undefined })), true)
  assert.equal(isUnregistered(row()), false)
})
t('ages, output and freshness read in words; unknown stays null', () => {
  assert.equal(ageWords(600), '10 m'); assert.equal(ageWords(3 * 3600 + 300), '3 h 5 m'); assert.equal(ageWords(3 * 86400), '3 d')
  assert.equal(ageWords(null), null); assert.equal(ageWords(-5), null)
  assert.equal(outputText({ kind: 'json_key', path: 'data/runtime/x.json' }), 'data/runtime/x.json')
  assert.equal(outputText({ kind: 'db', table: 'quotes' }), 'table quotes')
  assert.equal(outputText({ kind: 'none' }), 'No output declared'); assert.equal(outputText(null), null)
  assert.equal(freshnessText(row({ freshness: 'STALE', output_age: 7200 })), 'stale · written 2 h ago')
  assert.equal(freshnessText(row({ freshness: 'ABSENT' })), 'missing')
  assert.equal(freshnessText(row()), null)
})
t('drift text: aligned, drift, scheduled twice, or unknown', () => {
  assert.equal(driftText(row()), 'aligned')
  assert.equal(driftText(row({ scheduler_drift: true, duplicate_scheduler: true })), 'drift · scheduled twice')
  assert.equal(driftText(row({ scheduler_drift: null })), null)
})
t('observation older than 5 minutes or future-dated is expired', () => {
  const now = Date.parse('2026-11-06T12:00:00Z')
  assert.equal(observationExpired('2026-11-06T11:58:00Z', now), false)
  assert.equal(observationExpired('2026-11-06T11:50:00Z', now), true)
  assert.equal(observationExpired('2026-11-06T12:01:00Z', now), true)
  assert.equal(observationExpired(null, now), true)
})
t('lane URL is encoded', () => { assert.equal(schedulerLaneApi('unregistered-unit-a.timer'), '/api/v2/scheduler-operations?lane=unregistered-unit-a.timer'); assert.ok(schedulerLaneApi('a b&c').endsWith('a%20b%26c')) })
console.log(`${n}/8 passed`)
