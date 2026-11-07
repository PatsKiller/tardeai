// /ops/jobs → Run history helpers (JobRunHistory@v1). Runs in the CC-v3 build:
//   node --experimental-strip-types src/lib/jobRunHistory.test.ts
import {
  STATUS_LABEL, ago, cadenceText, detailQuery, duration, etTime, fixLabel, fixTone, historyQuery, missedText, resultTone,
  slotTone, statusTone, type HistoryStatus,
} from './jobRunHistory.ts'
// No node:assert: CI's tsc has no @types/node (same local-assert pattern as opsControls.test.ts).
declare const process: { exit(code?: number): never }
function fail(m: string): never { console.log(`  [FAIL] ${m}`); process.exit(1) }
const eq = (a: unknown, b: unknown, m = '') => {
  const x = JSON.stringify(a), y = JSON.stringify(b); if (x !== y) fail(`${m} expected ${y} got ${x}`)
}
let n = 0
function t(name: string, fn: () => void) { fn(); n++; console.log(`  [PASS] ${name}`) }

t('times render in ET from the writer value; absent time says so', () => {
  eq(etTime('2026-11-04T15:07:00Z'), 'Nov 4, 10:07 AM ET')
  eq(etTime(null), 'Not recorded')
  eq(etTime('garbage', 'n/a'), 'n/a')
})
t('ago is relative to computed_at, never the browser clock', () => {
  eq(ago('2026-11-04T15:00:00Z', '2026-11-04T15:07:00Z'), '7 min ago')
  eq(ago('2026-11-04T10:00:00Z', '2026-11-04T15:07:00Z'), '5 h ago')
  eq(ago('2026-11-01T15:00:00Z', '2026-11-04T15:07:00Z'), '3 d ago')
  eq(ago('2026-11-04T15:08:00Z', '2026-11-04T15:07:00Z'), 'after this check')
  eq(ago(null, '2026-11-04T15:07:00Z'), null)
})
t('missed count is a number only when measured; otherwise the reason', () => {
  eq(missedText({ missed_count: 0, missed_gap: null }), 'None in the last 10 expected runs')
  eq(missedText({ missed_count: 3, missed_gap: null }), '3 of the last 10 expected runs')
  eq(missedText({ missed_count: null, missed_gap: 'systemd runs are not recorded' }), 'Not measured: systemd runs are not recorded')
})
t('cadence text: cron with zone, cadence-only, gap', () => {
  eq(cadenceText({ expressions: ['*/30 9-16 * * 1-5'], timezone: 'America/New_York', every_hours: 0.5, market_days_only: true }),
    '*/30 9-16 * * 1-5 (ET), market days only')
  eq(cadenceText({ expressions: [], timezone: 'UTC', every_hours: 4, market_days_only: false }), 'about every 4 h (no wall-clock schedule)')
  eq(cadenceText({ expressions: [], timezone: 'UTC', every_hours: 0.25, market_days_only: false }), 'about every 15 min (no wall-clock schedule)')
  eq(cadenceText({ expressions: [], timezone: 'UTC', every_hours: null, market_days_only: false, schedule_gap: 'Runs at boot only' }), 'Runs at boot only')
})
t('tones: failure is danger, not-measured is never success', () => {
  const all = Object.keys(STATUS_LABEL) as HistoryStatus[]
  eq(all.filter(s => statusTone(s) === 'success'), ['ok'])
  eq(statusTone('failed'), 'danger'); eq(statusTone('not_measured'), 'warning')
  eq(resultTone('timed_out'), 'danger'); eq(resultTone('skipped_lock'), 'warning')
  eq(slotTone('missed'), 'warning'); eq(slotTone('not_measured'), 'neutral')
  eq(fixTone({ at: '', kind: 'self_healed', by: '', outcome: 'resolved', detail: null, ref: null }), 'success')
  eq(fixTone({ at: '', kind: 'dead_letter', by: '', outcome: 'dead', detail: null, ref: null }), 'danger')
  eq(fixLabel('retry'), 'Retried'); eq(fixLabel('some_new_kind'), 'some new kind')
})
t('durations and queries', () => {
  eq(duration(39), '39 s'); eq(duration(600), '10 min'); eq(duration(5400), '1.5 h'); eq(duration(null), null)
  eq(historyQuery('fixed', 50, ' disk '), '/api/v2/jobs-history?filter=fixed&offset=50&limit=50&q=disk')
  eq(historyQuery('all', 0, ''), '/api/v2/jobs-history?filter=all&offset=0&limit=50')
  eq(detailQuery('a b'), '/api/v2/jobs-history?job=a%20b')
})
console.log(`jobRunHistory: ${n} passed`)
