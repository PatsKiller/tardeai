// Runtime surface contract tests. These stay pure so the browser cannot turn
// adapter diagnostics or declared catalog posture into a live capability claim.
import { operatorRuntimeState } from './agentRuntimeReadAdapter.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, condition: boolean) {
  if (condition) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

check('SHADOW remains an explicit runtime state', operatorRuntimeState('SHADOW') === 'SHADOW')
check('FIXTURE remains an explicit runtime state', operatorRuntimeState('FIXTURE') === 'FIXTURE')
check('STALE remains an explicit runtime state', operatorRuntimeState('STALE') === 'STALE')
check('UNAVAILABLE remains an explicit runtime state', operatorRuntimeState('UNAVAILABLE') === 'UNAVAILABLE')
check('NOT_CONNECTED is disclosed as UNAVAILABLE', operatorRuntimeState('NOT_CONNECTED') === 'UNAVAILABLE')
check('adapter cannot promote NOT_CONNECTED to LIVE', operatorRuntimeState('NOT_CONNECTED') !== 'LIVE')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
