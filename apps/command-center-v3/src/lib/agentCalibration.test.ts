import { bucketText, countsText, hitRateText } from './agentCalibration.ts'

function eq(a: unknown, b: unknown, msg: string) {
  if (a !== b) throw new Error(`FAIL ${msg}: ${String(a)} !== ${String(b)}`)
}
eq(hitRateText({ agent: 'alex', scored_outcomes: 20, status: 'MEASURED', hit_rate: 0.75, brier: null }, 20), '75% hit · 20 scored', 'measured rate')
eq(hitRateText({ agent: 'steph', scored_outcomes: 3, status: 'INSUFFICIENT_SAMPLE', hit_rate: null, brier: null }, 20), 'insufficient sample (3 of 20 scored)', 'never a rate below the floor')
eq(hitRateText({ agent: 'x', scored_outcomes: 3, status: 'INSUFFICIENT_SAMPLE', hit_rate: 1, brier: null }, 20), 'insufficient sample (3 of 20 scored)', 'status wins over a stray rate')
eq(countsText({ DIRECTIONAL: 20, EXPECTATION: 0 }), 'directional 20', 'zero counts hidden')
eq(countsText(undefined), 'none', 'missing counts')
eq(bucketText({ bucket: '60-80%', n: 25, hit_rate: 0.6 }), 'stated 60-80%: 60% hit of 25', 'bucket rate')
eq(bucketText({ bucket: 'not_stated', n: 4, hit_rate: null }), 'confidence not stated: 4 scored (sample too small)', 'small bucket')
console.log('agentCalibration.test: ok')
