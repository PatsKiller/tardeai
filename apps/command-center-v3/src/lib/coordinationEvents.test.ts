import { projectCoordination, toneForState, phaseForState } from './coordinationEvents.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const NOW = Date.parse('2026-10-07T15:00:00Z')
const noLedger = projectCoordination({ schema: 'N8nCoordinationProjection@v1', as_of: '2026-10-07T14:04:17+00:00', items: [], count: 0, status: 'NO_LEDGER', note: 'nothing is waiting' }, { nowMs: NOW })
check('NO_LEDGER is an explicit state, not an empty success', noLedger.status === 'NO_LEDGER' && noLedger.statusLabel === 'NO LEDGER')
check('NO_LEDGER carries a warning tone', noLedger.statusTone === 'warning')
check('NO_LEDGER keeps the server note', noLedger.note === 'nothing is waiting')
check('a dated projection is not UNDATED', noLedger.asOfLabel.startsWith('projected '))

const absent = projectCoordination(null, { transport: 'ERROR' })
check('no payload is UNAVAILABLE', absent.status === 'UNAVAILABLE' && absent.statusTone === 'danger')
check('no payload is UNDATED', absent.asOfLabel === 'UNDATED')
check('no payload renders no rows', absent.rows.length === 0)
check('transport ERROR is surfaced', absent.transportLabel === 'ERROR')

const ok = projectCoordination({
  status: 'OK', as_of: '2026-10-07T14:59:00+00:00', count: 4, items: [
    { state: 'CONSUMED', lane_id: 'approval-package-reminder', event_id: 'evt-a', idempotency_key: 'apr-1', recorded_at: NOW / 1000 - 600, consumer: 'approval-reminder-reconcile', consumer_receipt_id: 'run-1', origin_sha: '60863d207f4639819f04209f816f71e3056768a7', durable: true, artifact_ref: { store: 'data/runtime', ref: 'approval_package_reminder_last.json' } },
    { state: 'ARTIFACT_WRITTEN', lane_id: 'llm-spend-report-daily', event_id: 'evt-b', idempotency_key: 'llm-1', recorded_at: '2026-10-07T14:50:00+00:00', durable: true },
    { state: 'REFUSED', reason: 'typed_refusal:live_notifier_stays_in_code', lane_id: 'material-change-digest', event_id: 'evt-c', idempotency_key: 'mcd-1', recorded_at: null },
    { state: 'ACCEPTED', lane_id: 'incident-fanin', event_id: 'evt-d', idempotency_key: 'inc-1', recorded_at: NOW / 1000 - 60 },
  ],
}, { nowMs: NOW, transport: 'RETAINED', stale: true })
check('OK status', ok.status === 'OK' && ok.statusTone === 'success')
check('rows are projected', ok.rows.length === 4)
check('counts partition by phase', ok.counts.consumed === 1 && ok.counts.artifact === 1 && ok.counts.refused === 1 && ok.counts.waiting === 1)
check('epoch recorded_at becomes ISO and an age', ok.rows[0].recordedAt === '2026-10-07T14:50:00.000Z' && ok.rows[0].ageMinutes === 10)
check('ISO recorded_at parses', ok.rows[1].recordedAt === '2026-10-07T14:50:00.000Z')
check('missing recorded_at is null, never 0', ok.rows[2].recordedAt === null && ok.rows[2].ageMinutes === null)
check('consumer and receipt id are joined', ok.rows[0].consumer === 'approval-reminder-reconcile · run-1')
check('artifact ref renders store:ref', ok.rows[0].artifact === 'data/runtime:approval_package_reminder_last.json')
check('origin sha is shortened', ok.rows[0].originSha === '60863d207')
check('refusal reason is kept verbatim', ok.rows[2].reason === 'typed_refusal:live_notifier_stays_in_code')
check('stale retained transport is labelled', ok.transportLabel === 'STALE · RETAINED')

check('tone: CONSUMED success', toneForState('CONSUMED') === 'success')
check('tone: ARTIFACT_WRITTEN info', toneForState('ARTIFACT_WRITTEN') === 'info')
check('tone: STARTED warning', toneForState('STARTED') === 'warning')
check('tone: REFUSED danger', toneForState('REFUSED') === 'danger')
check('tone: unknown state is neutral, never success', toneForState('WHATEVER') === 'neutral')
check('phase: DEAD_LETTER is failed', phaseForState('DEAD_LETTER') === 'failed')
check('phase: unknown is other', phaseForState('???') === 'other')

console.log(`\ncoordinationEvents: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
