// Pure-logic tests for sectorMonitorSource.ts (LQ-20261107-312).
//   node --experimental-strip-types src/lib/sectorMonitorSource.test.ts
import { shouldFetchSectorMonitor, sectorMonitorPayload } from './sectorMonitorSource.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

const payload = { sectors: [{ etf: 'XLK', sector: 'Technology' }], as_of: '2026-11-07' }

// Nobody supplied a payload: the board is on its own and must fetch.
check('undefined supplied -> fetch', shouldFetchSectorMonitor(undefined) === true)

// The hub supplied anything at all (including "still loading"): never fetch a second time.
check('hub payload supplied -> no fetch', shouldFetchSectorMonitor(payload) === false)
check('hub still loading (null) -> no fetch', shouldFetchSectorMonitor(null) === false)
check('empty-but-present payload -> no fetch', shouldFetchSectorMonitor({}) === false)

// Rendering picks the supplied payload and ignores a stale own fetch.
check('supplied payload wins over the own fetch', sectorMonitorPayload(payload, { sectors: [] }) === payload)
check('null supplied is rendered as null, not replaced by the own fetch',
  sectorMonitorPayload(null, payload) === null)
check('no supplied payload -> own fetch is used', sectorMonitorPayload(undefined, payload) === payload)
check('no supplied payload and nothing fetched yet -> null', sectorMonitorPayload(undefined, null) === null)

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
