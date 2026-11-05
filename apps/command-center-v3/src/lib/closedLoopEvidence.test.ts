// Actual production formatter, runnable in Python-only CI without React/TypeScript npm packages.
import { closedLoopEvidenceText } from './closedLoopEvidence.ts'

function equal(actual: string, expected: string) {
  if (actual !== expected) throw new Error(`Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`)
}

let passed = 0
for (const absent of [null, undefined, '', ' ', 'n/a', '—', 'abc', 'NaN', 'Infinity', '-Infinity', NaN, Infinity, -Infinity, true, false, [], [0], {}, { value: 0 }]) {
  const text = closedLoopEvidenceText({ sample_days: 30, score_delta: absent }, {})
  equal(text, 'Based on 30 days of signals · score change not recorded')
  passed++
}
for (const zero of [0, '0']) {
  equal(closedLoopEvidenceText({ sample_days: 30, score_delta: zero }, {}),
    'Based on 30 days of signals · score unchanged')
  passed++
}
equal(closedLoopEvidenceText({ sample_days: 30, confidence: 'HIGH', score_delta: 0.042 }, { trigger_rate: 0.12 }),
  'Based on 30 days of signals · confidence high · score up 0.042 · candidate trigger rate 12% (scoring-window length not recorded)')
passed++
equal(closedLoopEvidenceText({ score_delta: -0.5 }, {}), 'Based on the available signals · score down 0.500')
passed++
equal(closedLoopEvidenceText(null, null), 'Based on the available signals · score change not recorded')
passed++
for (const holdout of [undefined, { passed: true }, { skipped: true }]) {
  const text = closedLoopEvidenceText({ sample_days: 30, score_delta: 0, holdout_validation: holdout }, { trigger_rate: 0.12 })
  equal(text, 'Based on 30 days of signals · score unchanged · candidate trigger rate 12% (scoring-window length not recorded)')
  passed++
}
for (const [delta, phrase] of [[' +0.042 ', 'score up 0.042'], ['-0.5', 'score down 0.500']]) {
  equal(closedLoopEvidenceText({ score_delta: delta }, {}), `Based on the available signals · ${phrase}`)
  passed++
}
console.log(`closedLoopEvidence: ${passed} passed`)
