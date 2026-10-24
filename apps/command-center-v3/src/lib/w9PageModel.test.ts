import { pageTab, observedTime, recordedPercent, syncEvidenceState, verifiedEventLabel } from './w9PageModel.ts'

function equal(actual: unknown, expected: unknown) { if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`) }
function match(actual: string, pattern: RegExp) { if (!pattern.test(actual)) throw new Error(`Unexpected text: ${actual}`) }

equal(pageTab('HISTORY', ['overview', 'history'], 'overview'), 'history')
equal(pageTab('missing', ['overview', 'history'], 'overview'), 'overview')
equal(observedTime('2026-10-23'), '2026-10-23 · time not recorded')
equal(observedTime(undefined), 'Time unavailable')
equal(observedTime('bad timestamp'), 'Time unavailable')
match(observedTime('2026-10-24T22:10:00Z'), /18:10 ET$/)
equal(verifiedEventLabel({mode: 'dry_run', verified: true, success: true}), 'Preview')
equal(verifiedEventLabel({verified: true, exit_code: 1}), 'Failed')
equal(verifiedEventLabel({}), 'Unverified')
equal(verifiedEventLabel({verified: true}), 'Verified')
equal(recordedPercent('0%'), '0%')
equal(recordedPercent(87), '87%')
equal(recordedPercent('N/A'), 'Not recorded')
equal(recordedPercent(undefined), 'Not recorded')
equal(syncEvidenceState('OK', {rc: 1}, '2026-10-23', null), 'DEGRADED')
equal(syncEvidenceState('OK', {rc: 1}, '2026-10-24T22:10:00Z', '2026-10-24T22:00:00Z'), 'OK')
equal(syncEvidenceState('OK', {rc: 1}, '2026-10-24T21:00:00Z', '2026-10-24T22:00:00Z'), 'DEGRADED')
equal(syncEvidenceState('PAUSED', {rc: 1}, null, null), 'PAUSED')
equal(syncEvidenceState('OK', {rc: 0}, null, null), 'OK')
console.log('W9 recorded-evidence presentation checks passed')
