import { rotationAvailability } from './rotationPublication.ts'
import { observeRotationExpiry } from './rotationExpiry.ts'

const at = '2026-10-18T22:00:00Z'
let now = Date.parse(at)
const summary = { ok: true, publication: { schema: 'RotationPublication@v1', status: 'READY', reasons: [], checked_at: at,
  source_as_of: at, cache_generated_at: at, input_sha256: 'a'.repeat(64), producer_ok: true,
  source_as_of_basis: 'oldest_required_position_or_account_timestamp',
  coverage: { required_positions: 1, dated_positions: 1, accounts: 1, dated_accounts: 1 },
  accounts: [{ account_key: 'fixture', state: 'LIVE', source_as_of: at }],
} }
let displayed = rotationAvailability(summary, null, now)
let timer: (() => void) | null = null
let focus: (() => void) | null = null
let visibility: (() => void) | null = null
let delay = 0
let cleared = false
let updates = 0
const cleanup = observeRotationExpiry(displayed, () => { updates++; displayed = rotationAvailability(summary, null, now) }, {
  now: () => now,
  setTimer: (callback, ms) => { timer = callback; delay = ms; return 1 },
  clearTimer: () => { cleared = true },
  onFocus: callback => { focus = callback; return () => { focus = null } },
  onVisibility: callback => { visibility = callback; return () => { visibility = null } },
})
function check(value: unknown, message: string) { if (!value) throw new Error(message) }
check(displayed.ready && delay === 900_001 && timer, 'mounted advice must schedule its exact validation/engine deadline')
now += delay
;(timer as unknown as () => void)()
check(!displayed.ready && displayed.status === 'STALE', 'passive deadline must remove current advice without another fetch')
;(focus as unknown as () => void)()
;(visibility as unknown as () => void)()
check(updates === 3 && !displayed.ready, 'returning to a suspended tab must recheck the actual clock')
cleanup()
check(cleared && !focus && !visibility, 'unmount/replacement must remove the previous timer and listeners')

now = Date.parse(at)
displayed = rotationAvailability(summary, null, now)
const pending = new Map<number, { callback: () => void; delay: number }>()
let nextId = 0
const stopCorrectedClock = observeRotationExpiry(displayed, () => { displayed = rotationAvailability(summary, null, now) }, {
  now: () => now,
  setTimer: (callback, ms) => { const id = ++nextId; pending.set(id, { callback, delay: ms }); return id },
  clearTimer: id => { pending.delete(id) },
  onFocus: () => () => {},
  onVisibility: () => () => {},
})
const [firstId, first] = [...pending.entries()][0]
pending.delete(firstId)
now += first.delay - 500
first.callback()
check(displayed.ready && pending.size === 1, 'an early callback after a backward clock adjustment must rearm expiry')
const [secondId, second] = [...pending.entries()][0]
pending.delete(secondId)
now += second.delay
second.callback()
check(!displayed.ready && displayed.status === 'STALE', 'the rearmed callback must expire advice without a fetch')
stopCorrectedClock()
check(pending.size === 0, 'cleanup must cancel the most recently scheduled timer')

now = Date.parse(at)
displayed = rotationAvailability(summary, null, now)
const stopInvalidClock = observeRotationExpiry(displayed, () => { displayed = rotationAvailability(summary, null, now) }, {
  now: () => now,
  setTimer: (callback, ms) => { const id = ++nextId; pending.set(id, { callback, delay: ms }); return id },
  clearTimer: id => { pending.delete(id) },
  onFocus: () => () => {},
  onVisibility: () => () => {},
})
const [clockId, clockTimer] = [...pending.entries()][0]
pending.delete(clockId)
now -= 500
clockTimer.callback()
check(!displayed.ready && displayed.status === 'UNAVAILABLE', 'a clock moved before the proof time must refresh current validity')
stopInvalidClock()
check(pending.size === 0, 'invalid-clock cleanup must cancel a replacement timer')
console.log('rotation passive expiry and resume: passed')
