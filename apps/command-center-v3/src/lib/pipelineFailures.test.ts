import { pipelineFailuresFrom } from './pipelineFailures.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const m = pipelineFailuresFrom({ status: 'OK', window_hours: 24, pipelines: [
  { pipeline: 'b', failed: 1, last_failed_at: '2026-10-21T10:00:00Z', last_error: '' },
  { pipeline: 'a', failed: 3, last_failed_at: '2026-10-21T09:00:00Z', last_error: 'HTTP 429', zombie_cleared: 2 }] })
check('sorted by count, totals', m.state === 'OK' && m.rows[0].pipeline === 'a' && m.failedRuns === 4)
check('empty error text is null', m.rows[1].lastError === null)
check('zombie-cleared count carried; absent is null', m.rows[0].zombieCleared === 2 && m.rows[1].zombieCleared === null)
check('UNAVAILABLE is not an empty OK list', pipelineFailuresFrom({ status: 'UNAVAILABLE', pipelines: null, note: 'pipeline_runs could not be read' }).state === 'UNAVAILABLE')
check('empty OK list is OK with 0', pipelineFailuresFrom({ status: 'OK', pipelines: [] }).failedRuns === 0)
check('loading', pipelineFailuresFrom(null, { loading: true }).state === 'LOADING')
console.log(`pipelineFailures: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
