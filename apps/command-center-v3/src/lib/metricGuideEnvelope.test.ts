// node src/lib/metricGuideEnvelope.test.ts (no node:assert: CI tsc has no @types/node)
import { unwrapGuideResponse } from './metricGuideEnvelope.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}

const served = { ok: true, data: { ok: true, schema: 'UiMetricGuide@v1', version: '1', count: 1, entries: { 'cio.decision': { label: 'CIO decision' } } } }
eq('api_v2 envelope', unwrapGuideResponse(served), { entries: { 'cio.decision': { label: 'CIO decision' } }, version: '1' })
eq('bare body', unwrapGuideResponse({ version: 2, entries: { a: 1 } }), { entries: { a: 1 }, version: '2' })
eq('legacy guide key', unwrapGuideResponse({ guide: { a: 1 } }), { entries: { a: 1 }, version: 'server' })
eq('error envelope', unwrapGuideResponse({ ok: false, data: { ok: false, error: 'x', entries: {} } }), { entries: {}, version: 'server' })
eq('null', unwrapGuideResponse(null), null)
eq('array entries', unwrapGuideResponse({ entries: [1] }), null)
eq('string', unwrapGuideResponse('nope'), null)

if (failed) throw new Error(`metricGuideEnvelope: ${failed} failed`)
console.log('[metricGuideEnvelope] ok')
