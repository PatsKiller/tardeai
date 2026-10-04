import { ARTIFACT_LABELS, alertQualitySummary, artifactFields, artifactSummary } from './cioOperatorArtifacts.ts'

function eq(a: unknown, b: unknown, msg: string) {
  if (a !== b) throw new Error(`FAIL ${msg}: ${String(a)} !== ${String(b)}`)
}

eq(artifactSummary({ payload: { text: 'Cash 12% above band.' } }), 'Cash 12% above band.', 'advisory text shown verbatim')
eq(artifactSummary({ payload: { reply: 'Nothing material.' } }), 'Nothing material.', 'attention reply')
eq(artifactSummary({ payload: { sentences: [{ sentence: 'A.' }, { sentence: 'B.' }] } }), 'A. B.', 'narrative sentences joined')
eq(artifactSummary({ payload: { what_changed: [1, 2] } }), '2 changes recorded', 'what-changed count')
eq(artifactSummary({ payload: { _truncated: true, _original_bytes: 99000 } }).startsWith('Payload truncated (99000'), true, 'truncation is said, never hidden')
eq(artifactSummary({ payload: { nested: { a: 1 } } }), 'No readable text field; open details.', 'never dumps JSON')
eq(artifactSummary(null), 'No readable text field; open details.', 'missing row')
eq((artifactSummary({ payload: { text: 'x'.repeat(500) } })).length, 280, 'summary capped')
const f = artifactFields({ payload: { symbol: 'SCHD', n: 3, nested: { a: 1 }, none: null } })
eq(f.length, 2, 'only scalar fields listed')
eq(f[0][0], 'symbol', 'field order kept')
eq(ARTIFACT_LABELS['GrokCritique@v1'], 'Grok critique', 'labels')
const aq = artifactSummary({ payload: { schema: 'AlertQuality@v1', day: '2026-10-02',
  delivery: { attempts: 1667, delivered_confirmed: 79, delivered_unconfirmed: 32, suppressed: 1556 },
  editor: { held_duplicate: 30, held_cio_disagreement: 5, false_positive_cio_holds: 1 },
  outcomes: { status: 'UNMEASURED: no delivered alert carried a decision_id' } } })
eq(aq.startsWith('2026-10-02: 79 delivered (confirmed), 32 unconfirmed, 1556 suppressed of 1667 attempts.'), true, 'alert quality day line')
eq(aq.includes('UNMEASURED'), true, 'unmeasured outcome stays unmeasured')
eq(alertQualitySummary({ delivery: { attempts: 1 } }), null, 'partial alert quality payload falls back')
eq(alertQualitySummary({ delivery: {}, editor: {} })?.includes('— delivered'), true, 'missing numbers show a dash, never 0')
console.log('cioOperatorArtifacts.test.ts: ok')
