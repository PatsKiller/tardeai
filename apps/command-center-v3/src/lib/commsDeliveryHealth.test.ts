import { ageLabel, deliveryHealthFrom, telegramFailedDetail } from './commsDeliveryHealth.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const now = Date.parse('2026-10-18T12:00:00Z')
const ok = { status: 'OK', unsettled: 1234, failed: 7, total: 90000, oldest_unsettled_age_s: 10800, as_of: '2026-10-18T11:59:00Z' }

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
const old = deliveryHealthFrom({ ...ok, as_of: '2026-10-18T11:00:00Z' }, { nowMs: now })
check('an old answer is STALE but keeps the last counts', old.state === 'STALE' && old.unsettled === 1234)
const refreshFailed = deliveryHealthFrom(ok, { nowMs: now, error: 'timeout' })
check('a failed refresh over a kept payload is STALE', refreshFailed.state === 'STALE' && refreshFailed.reason === 'refresh failed: timeout')
check('age labels', ageLabel(45) === '45s' && ageLabel(720) === '12m' && ageLabel(10800) === '3h' && ageLabel(null) === '—')

const reaped = deliveryHealthFrom({ ...ok, failed: 0, reaped_unclaimed: 6, as_of: new Date(now).toISOString() }, { nowMs: now })
check('reaped unclaimed copies are their own count, not failed', reaped.state === 'OK' && reaped.failed === 0 && reaped.reapedUnclaimed === 6)
check('an older summary without the field is still OK, reaped unknown', good.state === 'OK' && good.reapedUnclaimed === null)

// 2026-10-21: telegram_outbox failures are their own figure, not merged into `failed`; archive holds are not failures.
const tg = deliveryHealthFrom({ ...ok, failed: 0, as_of: new Date(now).toISOString(), telegram_outbox_failed_24h: 3,
  telegram_outbox_failed_24h_by_channel: { telegram: 2, telegram_document: 1 }, telegram_outbox_held_24h: 149 }, { nowMs: now })
check('telegram send failures are a separate figure; delivery failed stays 0', tg.failed === 0 && tg.telegramFailed24h === 3)
check('archive holds are carried as held, not failed', tg.telegramHeld24h === 149)
check('by-channel detail sorted by count', telegramFailedDetail(tg) === 'telegram 2, telegram_document 1')
const tgUnknown = deliveryHealthFrom({ ...ok, as_of: new Date(now).toISOString(), telegram_outbox_failed_24h: null, telegram_outbox_error: 'UndefinedTable: x' }, { nowMs: now })
check('an unmeasured telegram ledger is null with its error, never zero', tgUnknown.telegramFailed24h === null && tgUnknown.telegramError === 'UndefinedTable: x')
check('no payload: telegram figures null', absent.telegramFailed24h === null && absent.telegramHeld24h === null)
console.log(`commsDeliveryHealth: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
