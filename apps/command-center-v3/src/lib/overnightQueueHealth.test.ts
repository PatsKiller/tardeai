import { queueHealthFrom, queueLevelTone } from './overnightQueueHealth.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
// live shape 2026-10-21
const live = { measured: true, pending: 1928, done_today: 0, failed: 268, cap_tonight: 100, estimated_completion_nights: 19.3, next_window_in_hours: 13.8 }
const h = queueHealthFrom(live)
check('live backlog is CRIT with every reason', h.level === 'CRIT' && h.reasons.length === 3 && h.drainNights === 19.3 && h.doneToday === 0)
check('CRIT tone is danger', queueLevelTone(h.level) === 'danger')
check('small queue is OK', queueHealthFrom({ pending: 40, failed: 0, cap_tonight: 100, estimated_completion_nights: 0.4 }).level === 'OK')
const w = queueHealthFrom({ pending: 600, failed: 3, cap_tonight: 100 })
check('WARN on backlog; drain computed when absent', w.level === 'WARN' && w.drainNights === 6)
check('measured=false is UNAVAILABLE, never zero', queueHealthFrom({ measured: false, pending: 0, failed: 0 }).level === 'UNAVAILABLE')
check('no payload is UNAVAILABLE; loading is LOADING', queueHealthFrom(null).level === 'UNAVAILABLE' && queueHealthFrom(null, { loading: true }).level === 'LOADING')
console.log(`overnightQueueHealth: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
