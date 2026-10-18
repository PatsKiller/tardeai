import { projectOutbox, toneForOutboxState } from './outboxProjection.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const absent = projectOutbox(null)
check('no payload is UNAVAILABLE with a danger tone', absent.status === 'UNAVAILABLE' && absent.statusTone === 'danger' && absent.rows.length === 0)

const unavailable = projectOutbox({ status: 'UNAVAILABLE', note: 'no_db_env: DB_PASSWORD not in the environment', counts: {}, items: [] })
check('an unavailable projection keeps the server note', unavailable.status === 'UNAVAILABLE' && unavailable.note.startsWith('no_db_env'))

const ok = projectOutbox({
  status: 'OK', window_hours: 24, total: 3,
  counts: { communication_outbox: { suppressed: 2, sent: 1 }, telegram_outbox: { failed: 1 } },
  items: [
    { outbox: 'communication_outbox', id: '2', state: 'suppressed', reason: 'dedupe', channel: 'telegram', subject: 'evt-b', attempts: 0, created_at: '2026-10-08T00:50:00+00:00', age_min: 10 },
    { outbox: 'telegram_outbox', id: '8', state: 'failed', reason: 'ok=false char_len=5000', channel: 'operator', subject: 'alert', attempts: 1, created_at: '2026-10-08T00:57:00+00:00', age_min: 3 },
  ],
})
check('legacy response is labelled sample with unknown completeness', ok.status === 'PARTIAL' && ok.statusLabel.startsWith('LEGACY SAMPLE') && ok.windowLabel.includes('completeness unknown'))
check('counts flatten per outbox and state, largest first', ok.counts.map(c => `${c.outbox}:${c.state}=${c.n}`).join(',') === 'communication_outbox:suppressed=2,communication_outbox:sent=1,telegram_outbox:failed=1')
check('rows keep state, reason and age', ok.rows.length === 2 && ok.rows[1].tone === 'danger' && ok.rows[0].reason === 'dedupe' && ok.rows[0].ageMinutes === 10)
check('tones: sent success, suppressed neutral, withdrawn danger, recorded warning', toneForOutboxState('sent') === 'success' && toneForOutboxState('suppressed') === 'neutral' && toneForOutboxState('withdrawn') === 'danger' && toneForOutboxState('recorded') === 'warning')

console.log(`outboxProjection: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

const full = projectOutbox({ schema: 'NotificationOutboxProjection@v2', status: 'OK', as_of: '2026-10-18T16:00:00Z', total: 601,
  counts: { communication_outbox: { suppressed: 600, sent: 1 } }, items: [],
  coverage: { aggregation_complete: true, items_truncated: true, since: '2026-10-17T16:00:00Z', through: '2026-10-18T16:00:00Z' } }, { nowMs: Date.parse('2026-10-18T16:00:00Z') })
check('full window count is independent of sampled details', full.status === 'OK' && full.statusLabel.includes('601 recorded') && full.counts.some(c => c.state === 'sent' && c.n === 1))
check('retained error cannot expose current counts', projectOutbox({ schema: 'NotificationOutboxProjection@v2', status: 'OK', counts: { x: { sent: 5 } } }, { error: true }).counts.length === 0)
check('unknown major is unavailable', projectOutbox({ schema: 'NotificationOutboxProjection@v99', status: 'OK' }).status === 'UNAVAILABLE')
if (fail > 0) process.exit(1)
