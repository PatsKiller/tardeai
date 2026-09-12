// Pure-logic tests for oscillatorDisplay.ts. Runnable with Node type-stripping:
//   node apps/command-center-v3/src/lib/oscillatorDisplay.test.ts
import { ageLabel, formatReading, readingSuffix } from './oscillatorDisplay.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// ---- readingSuffix: breadth is a percentage, rs_score is not ----
check('breadth_pct carries %', readingSuffix('breadth_pct') === '%')
check('breadth formats as 27%', formatReading(27, 'breadth_pct') === '27%')

// rs_score is rank-normalised 0-100 and the ladder is sorted descending, so
// sectors[0].rs_score is the maximum by construction. The live board read
// "Sector RS Ladder 100%" on every render: a constant, presented as a percent.
check('rs_score carries no %', readingSuffix('rs_score') === '')
check('rs_score formats as 100', formatReading(100, 'rs_score') === '100')

check('RS20 carries no unit', formatReading(1.22, 'RS20') === '1.22')
check('rel1m carries no unit', formatReading(-19.59, 'rel1m') === '-19.59')
check('null reading_name carries no unit', formatReading(4.06, null) === '4.06')
check('undefined reading_name carries no unit', formatReading(4.06, undefined) === '4.06')

// ---- ageLabel: absence is absence, not the word "never" ----
const NOW = Date.parse('2026-09-12T01:00:00Z')

// "never" asserts the producer has never run. For sector_comovement that is
// false — it has no reader wired to its registered store, which is different.
check('null → null, not "never"', ageLabel(null, NOW) === null)
check('undefined → null', ageLabel(undefined, NOW) === null)
check('empty string → null', ageLabel('', NOW) === null)
check('unparseable → null, not NaN', ageLabel('not-a-date', NOW) === null)

check('30 minutes', ageLabel('2026-09-12T00:30:00Z', NOW) === '30m')
check('5 hours', ageLabel('2026-09-11T20:00:00Z', NOW) === '5h')
// The served sector_momentum snapshot on 2026-09-12.
check('17 days', ageLabel('2026-08-26T02:04:48Z', NOW) === '17d')

console.log(`oscillatorDisplay: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
