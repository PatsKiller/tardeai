// Pure-logic tests for forecastView.ts.
//   node --experimental-strip-types src/lib/forecastView.test.ts
import { longestHorizon, mergePayers, projectionValue } from './forecastView.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

// Shape the live API sends: scenario -> { label, years: { '1Y': {...}, '5Y': {...} } } (synthetic numbers).
const proj = {
  conservative: { label: 'Conservative (4% + divs)', years: { '1Y': { projected_value: 104 }, '5Y': { projected_value: 125 } } },
  moderate: { label: 'Moderate', years: { '1Y': { projected_value: 107 }, '3Y': { projected_value: 122 } } },
}
check('longest horizon is 5Y, not lexical order', longestHorizon(proj) === '5Y')
check('value read from years map (was $0)', projectionValue(proj.conservative, '5Y') === 125)
check('missing horizon is null, never 0', projectionValue(proj.moderate, '5Y') === null)
check('plain number passes through', projectionValue(42, null) === 42)
check('empty projections -> no horizon', longestHorizon({}) === null)
check('10Y beats 5Y', longestHorizon({ a: { years: { '5Y': {}, '10Y': {} } } }) === '10Y')

const first = { symbol: 'AAA', annual_income: 10, value: 100 }
const merged = mergePayers([
  first,
  { symbol: 'BBB', annual_income: 3, value: 50 },
  { symbol: 'BBB', annual_income: 2, value: 40 },
  { symbol: 'AAA', annual_income: 1, value: 5 },
])
check('one row per symbol', merged.length === 2)
check('income summed across accounts', merged[0].symbol === 'AAA' && merged[0].annual_income === 11)
check('sorted by income desc', merged[1].symbol === 'BBB' && merged[1].annual_income === 5)
check('input rows not mutated', first.annual_income === 10)

console.log(`forecastView: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
