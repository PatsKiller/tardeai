const assert = {
  equal(actual: unknown, expected: unknown, message = 'expected equality') { if (actual !== expected) throw new Error(`${message}: ${String(actual)} !== ${String(expected)}`) },
  ok(value: unknown, message = 'expected truthy value') { if (!value) throw new Error(message) },
  match(value: string, pattern: RegExp) { if (!pattern.test(value)) throw new Error(`expected ${value} to match ${pattern}`) },
}
import { ageText, ciLabel, ciTone, queueStoreText, kpiDisplay, lastRunText, prList, sectionView, shadowLine, verifyLabel, windowTone, type Kpi, type ReleasesSchedulesWire, type TimelineRow } from './releasesSchedules.ts'

const NOW = Date.parse('2026-10-22T19:00:00Z')
const wire: ReleasesSchedulesWire = {
  schema: 'ReleasesSchedules@v1', generated_at: '2026-10-22T19:00:00Z', status: 'DEGRADED',
  serving: { value: { sha: 'b'.repeat(40), short_sha: 'bbbbbbbbb', release_name: 'r', since: null, since_basis: null, pins_agree: true, pins: {}, deploy_receipt: null },
    as_of: '2026-10-22T18:58:00Z', freshness: 'OK', source: 'CURRENT', reason: null },
  queue: { value: null, as_of: null, freshness: 'UNAVAILABLE', source: 'postgres', reason: 'db_unavailable' },
  n8n_today: { value: { day: '2026-10-22', total: 0, by_mode: {}, by_state: {}, errors_total: 0, skips_total: 0, errors: [], lock_skips: [], busiest: [], dead_letters: { available: false, unreleased: null, recent: null } },
    as_of: '2026-10-22T18:59:00Z', freshness: 'OK', source: 'ledger', reason: null },
}

// OK section: value kept, freshness label carries age and source.
const sv = sectionView(wire, 'serving', { nowMs: NOW })
assert.equal(sv.state, 'OK'); assert.equal(sv.ageS, 120); assert.match(sv.label, /OK · 2m ago · CURRENT/)
// UNAVAILABLE section: null value, reason in the label, never zero.
const q = sectionView(wire, 'queue', { nowMs: NOW })
assert.equal(q.state, 'UNAVAILABLE'); assert.equal(q.value, null); assert.match(q.label, /UNAVAILABLE · db_unavailable/)
// A real zero from an OK source stays zero (it was measured).
const td = sectionView<{ total: number }>(wire, 'n8n_today', { nowMs: NOW })
assert.equal(td.value?.total, 0)
// Missing section, unknown schema, failed request: UNAVAILABLE.
assert.equal(sectionView(wire, 'timeline', { nowMs: NOW }).state, 'UNAVAILABLE')
assert.equal(sectionView({ ...wire, schema: 'ReleasesSchedules@v9' }, 'serving', { nowMs: NOW }).state, 'UNAVAILABLE')
assert.match(sectionView(null, 'serving', { nowMs: NOW, error: true }).label, /request failed/)
// Old response or failed refresh: STALE, value kept and labelled.
const old = sectionView(wire, 'serving', { nowMs: NOW + 10 * 60_000 })
assert.equal(old.state, 'STALE'); assert.ok(old.value); assert.match(old.reason ?? '', /older than 5 minutes/)
assert.equal(sectionView(wire, 'serving', { nowMs: NOW, error: true }).state, 'STALE')

// KPIs: null is UNAVAILABLE, never 0 / green; a stale response is labelled.
const k = (v: Kpi['value'], f: Kpi['freshness'] = 'OK'): Kpi => ({ key: 'x', label: 'X', value: v, detail: 'd', tone: 'success', freshness: f, as_of: null })
assert.equal(kpiDisplay(k(null), true).value, 'UNAVAILABLE'); assert.equal(kpiDisplay(k(null), true).tone, 'warning')
assert.equal(kpiDisplay(k(5, 'UNAVAILABLE'), true).value, 'UNAVAILABLE')
assert.equal(kpiDisplay(k(2883), true).value, '2,883'); assert.equal(kpiDisplay(k(2883), true).tone, 'success')
assert.equal(kpiDisplay(k(0), true).value, '0')
assert.match(kpiDisplay(k(1), false).detail, /^STALE/); assert.equal(kpiDisplay(undefined, true).value, 'UNAVAILABLE')

assert.equal(ageText(null), 'age unknown'); assert.equal(ageText(30), '30s ago'); assert.equal(ageText(7200), '2h ago')
assert.equal(prList(null, 'git failed'), 'UNAVAILABLE · git failed'); assert.equal(prList([], null), 'no PRs')
assert.equal(prList([1, 2, 3], null, 2), '#1, #2 +1 more')
assert.equal(verifyLabel({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: true, readback_errors: [] }, verify_reason: null, serving: true }).text, 'LIVE · VERIFIED')
assert.equal(verifyLabel({ receipt: 'r', mode: 'apply', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: [], prs_reason: null, verify: { ok: false }, verify_reason: null }).tone, 'danger')
assert.equal(verifyLabel({ receipt: 'r', mode: 'rollback', at: null, sha: 's', sha_basis: 'BUILD_SHA', prs: null, prs_reason: null, verify: null, verify_reason: null }).text, 'ROLLBACK')
assert.equal(windowTone('STOPPED'), 'danger'); assert.equal(windowTone('nonsense'), 'warning')
const row = (o: Partial<TimelineRow>): TimelineRow => ({ at: '2026-10-22T20:33:00Z', lane: 'l', lane_id: 'l', runner: 'cron', schedule: '', stage: 'LIVE', n8n_stage: null, fires_in_horizon: 1, cadence_label: null, paused_since: null, paused_note: null, last_run: null, ...o })
assert.match(lastRunText(row({ stage: 'PAUSED', paused_since: '2026-10-14', paused_note: 'schwab' })), /paused since 2026-10-14 · schwab/)
assert.match(lastRunText(row({ runner: 'n8n' })), /no ledger run today/)
console.log('releasesSchedules: OK/STALE/UNAVAILABLE sections, KPI never-zero, PR/verify/stage labels passed')

// Main-HEAD CI: state + age from the main-ci-watch receipt; tone never green unless SUCCESS/OK.
assert.equal(ciLabel({ state: 'PENDING', reason: null, age_s: 720 }), 'PENDING · 12m ago')
assert.equal(ciLabel({ state: 'SUCCESS', reason: null, age_s: 9000, stale: true }), 'SUCCESS · 3h ago (stale)')
assert.equal(ciLabel({ state: 'UNAVAILABLE', reason: 'no receipt' }), 'UNAVAILABLE')
assert.equal(ciTone('FAILURE'), 'danger'); assert.equal(ciTone('PENDING'), 'info'); assert.equal(ciTone('UNAVAILABLE'), 'warning')
assert.equal(ciTone('SUCCESS'), 'success')
// Queue store chip: a missing census turns "0 queued" into an explicit UNKNOWN for open PRs.
const qMissing = { store: { freshness: 'OK', total: 0 }, census: { freshness: 'UNAVAILABLE', reason: 'no_receipt', alert: 'PR census MISSING' }, open_prs: [] }
assert.match(queueStoreText(qMissing), /0 queued \(explicit train queue only\) · open PRs UNKNOWN/)
assert.equal(queueStoreText({ ...qMissing, census: { freshness: 'OK' } }), 'queue store 0 queued')
// Shadow tick line (Phase 5): outcome, reason, queue seen, riding, candidate; unknown counts are "?" never 0.
const shadowFull = { request_id: 'rtw-20261023-1800-f2fb974', outcome: 'NO_OP', reason: 'DRY_RUN_COMPLETE', queue_open: 49, queue_complete: true,
  riding: 3, candidate_sha: 'abcdef1234567890', train_id: 'rt-20261023-1800-316c4b', has_report: true }
assert.equal(shadowLine(shadowFull), 'shadow: NO_OP · DRY_RUN_COMPLETE · queue 49 open · 3 riding · candidate abcdef123')
assert.equal(shadowLine({ ...shadowFull, queue_open: null, riding: null, queue_complete: false, candidate_sha: null }),
  'shadow: NO_OP · DRY_RUN_COMPLETE · queue ? open (INCOMPLETE) · ? riding')
assert.equal(shadowLine({ ...shadowFull, has_report: false, reason: null, outcome: null, candidate_sha: null }), 'shadow: no receipt')
