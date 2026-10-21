// Problems filter (audit 2026-10-21): only actionable states; NOT_MEASURED has its own filter.
import { filterSchedulerRows, schedulerProblems, SCHEDULER_FILTERS, NO_SIGNAL_UNDECLARED, type SchedulerRow } from './schedulerOperations.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

function row(lane_id: string, runtime_state: string, extra: Partial<SchedulerRow> = {}): SchedulerRow {
  return {
    lane_id, domain: null, owner: null, scheduler_type: 'cron', declared_state: 'ACTIVE', runtime_state,
    schedule: null, next_due: null, last_requested: null, last_started: null, last_completed: null, last_exit: null,
    duration: null, receipt: null, output_signal: null, output_age: null, freshness: 'NOT_MEASURED', lock_skips_24h: null,
    failures_24h: null, duplicate_scheduler: null, scheduler_drift: null, code_sha: null, code_root: null, consumer: null,
    evidence_class: 'SOURCE_ONLY', timeline: [], ...extra,
  }
}

const rows = [
  row('failed', 'RUN_FAILED'), row('silent', 'SILENT'), row('drift', 'DRIFT'), row('orphan', 'ORPHANED'), row('slow', 'SLOW'),
  row('live', 'LIVE'), row('expected', 'EXPECTED_SILENT', { scheduler_drift: true }),
  row('unmeasured', 'NOT_MEASURED', { scheduler_drift: true, duplicate_scheduler: true }),
  row('infra', 'INFRASTRUCTURE'),
  row('nosig-declared', 'NO_SIGNAL', { health_reason: 'NO_SIGNAL_WITH_REASON: monitor writes nothing durable' }),
  row('nosig-missing', 'NO_SIGNAL', { health_reason: `${NO_SIGNAL_UNDECLARED}; no output proof declared` }),
]
const problems = filterSchedulerRows(rows, 'Problems').map(r => r.lane_id)
check('Problems = actionable states only', problems.join(',') === 'failed,silent,drift,orphan,slow,nosig-missing')
check('NOT_MEASURED is never a problem, even with drift flags', !schedulerProblems(rows[7]))
check('EXPECTED_SILENT and INFRASTRUCTURE are never problems', !schedulerProblems(rows[6]) && !schedulerProblems(rows[8]))
check('NO_SIGNAL with a declared reason is not a problem', !schedulerProblems(rows[9]) && schedulerProblems(rows[10]))
check('a Not measured filter exists and shows only NOT_MEASURED', (SCHEDULER_FILTERS as readonly string[]).includes('Not measured')
  && filterSchedulerRows(rows, 'Not measured').map(r => r.lane_id).join(',') === 'unmeasured')
check('All is unchanged', filterSchedulerRows(rows, 'All').length === rows.length)

console.log(`\nschedulerOperations: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
