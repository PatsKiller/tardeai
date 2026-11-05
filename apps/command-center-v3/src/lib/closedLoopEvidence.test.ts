// Actual production formatter, runnable in Python-only CI without React/TypeScript npm packages.
import { closedLoopEvidenceText } from './closedLoopEvidence.ts'

function equal(actual: string, expected: string) {
  if (actual !== expected) throw new Error(`Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`)
}

let passed = 0
for (const absent of [null, undefined, '', ' ']) {
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
  'Based on 30 days of signals · confidence high · score up 0.042 · fired on 12% of those days')
passed++
equal(closedLoopEvidenceText({ score_delta: -0.5 }, {}), 'Based on the available signals · score down 0.500')
passed++
equal(closedLoopEvidenceText(null, null), 'Based on the available signals · score change not recorded')
passed++
console.log(`closedLoopEvidence: ${passed} passed`)
