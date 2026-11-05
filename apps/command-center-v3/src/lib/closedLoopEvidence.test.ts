// Actual production formatter, runnable in Python-only CI without React/TypeScript npm packages.
import assert from 'node:assert/strict'
import { closedLoopEvidenceText } from './closedLoopEvidence.ts'

let passed = 0
for (const absent of [null, undefined, '', ' ']) {
  const text = closedLoopEvidenceText({ sample_days: 30, score_delta: absent }, {})
  assert.equal(text, 'Based on 30 days of signals · score change not recorded')
  passed++
}
for (const zero of [0, '0']) {
  assert.equal(closedLoopEvidenceText({ sample_days: 30, score_delta: zero }, {}),
    'Based on 30 days of signals · score unchanged')
  passed++
}
assert.equal(closedLoopEvidenceText({ sample_days: 30, confidence: 'HIGH', score_delta: 0.042 }, { trigger_rate: 0.12 }),
  'Based on 30 days of signals · confidence high · score up 0.042 · fired on 12% of those days')
passed++
assert.equal(closedLoopEvidenceText({ score_delta: -0.5 }, {}), 'Based on the available signals · score down 0.500')
passed++
assert.equal(closedLoopEvidenceText(null, null), 'Based on the available signals · score change not recorded')
passed++
console.log(`closedLoopEvidence: ${passed} passed`)
