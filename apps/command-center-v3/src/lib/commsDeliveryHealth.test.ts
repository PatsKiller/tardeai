import { ageLabel, deliveryHealthFrom } from './commsDeliveryHealth.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const now = Date.parse('2026-10-18T12:00:00Z')
const ok = { schema: 'CommunicationsDeliverySummary@v1', ok: true, coverage: { scope: 'all_retained_rows', complete: true, window_start: '2026-10-01T00:00:00Z', window_end: '2026-10-18T11:59:00Z' }, status: 'OK', unsettled: 1234, failed: 7, total: 90000, oldest_unsettled_age_s: 10800, as_of: '2026-10-18T11:59:00Z' }

const absent = deliveryHealthFrom(null, { nowMs: now })
check('no payload is UNAVAILABLE with null counts, never zero', absent.state === 'UNAVAILABLE' && absent.unsettled === null && absent.failed === null)
const errored = deliveryHealthFrom(null, { nowMs: now, error: 'HTTP 500' })
check('a failed first fetch is UNAVAILABLE with the error', errored.state === 'UNAVAILABLE' && errored.reason === 'HTTP 500')
check('first load is LOADING, not zero', deliveryHealthFrom(null, { nowMs: now, loading: true }).state === 'LOADING')
const unavailable = deliveryHealthFrom({ status: 'UNAVAILABLE', unsettled: null, failed: null, error: 'communications DB unavailable' }, { nowMs: now })
check('a server UNAVAILABLE keeps its reason and null counts', unavailable.state === 'UNAVAILABLE' && unavailable.unsettled === null && unavailable.reason === 'communications DB unavailable')
check('a malformed OK (missing counts) is UNAVAILABLE', deliveryHealthFrom({ status: 'OK' }, { nowMs: now }).state === 'UNAVAILABLE')
const good = deliveryHealthFrom(ok, { nowMs: now })
check('a fresh OK carries the server counts and backlog age', good.state === 'OK' && good.unsettled === 1234 && good.failed === 7 && good.oldestUnsettledAgeS === 10800)
const old = deliveryHealthFrom({ ...ok, as_of: '2026-10-18T11:00:00Z', coverage: { ...ok.coverage, window_end: '2026-10-18T11:00:00Z' } }, { nowMs: now })
check('an old answer is STALE but keeps the last counts', old.state === 'STALE' && old.unsettled === 1234)
const refreshFailed = deliveryHealthFrom(ok, { nowMs: now, error: 'timeout' })
check('a failed refresh over a kept payload is STALE', refreshFailed.state === 'STALE' && refreshFailed.reason === 'refresh failed; retained observation')
check('age labels', ageLabel(45) === '45s' && ageLabel(720) === '12m' && ageLabel(10800) === '3h' && ageLabel(null) === '—')

check('hook stale alone wins over retained OK', deliveryHealthFrom(ok, { nowMs: now, stale: true }).state === 'STALE')
check('last good age is source age', deliveryHealthFrom(ok, { nowMs: now, stale: true }).lastGoodAgeS === 60)
for (const [name, payload] of Object.entries({
  unversioned: { ...ok, schema: undefined }, future: { ...ok, as_of: '2026-10-19T00:00:00Z' },
  incomplete: { ...ok, coverage: { ...ok.coverage, complete: false } },
  fractional: { ...ok, total: 2.2 }, contradictory: { ...ok, total: 1 },
  unmeasured: { ...ok, total: null }, unbounded: { ...ok, total: Infinity },
  window: { ...ok, coverage: { ...ok.coverage, window_end: null } },
})) check(`${name} is unavailable`, deliveryHealthFrom(payload, { nowMs: now }).state === 'UNAVAILABLE')

console.log(`commsDeliveryHealth: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
